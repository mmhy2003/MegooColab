package services

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"
)

// startAttempts is how many times start picks new ports when one it picked
// was taken before the containers bound it.
const startAttempts = 3

// removeTimeout bounds the removal after a failed start.
const removeTimeout = 2 * time.Minute

// portTakenMessages are what docker prints when a published port is taken.
var portTakenMessages = []string{
	"port is already allocated",
	"address already in use",
	"Only one usage of each socket address",
}

// start brings set up for f's worktree. On success it returns the saved
// record and the vars for the command. On failure everything it started is
// removed, the logs are saved when containers were started, and the error
// says why.
func start(ctx context.Context, dir string, f *File, set Set, stderr io.Writer) (Record, []string, error) {
	project := ProjectName(f.Dir, set.Name)
	rec := Record{
		Project:  project,
		Worktree: f.Dir,
		Set:      set.Name,
		Compose:  set.Compose,
		EnvFile:  filepath.Join(dir, project+".env"),
		PID:      os.Getpid(),
		Started:  time.Now(),
	}
	for attempt := 1; ; attempt++ {
		if err := Claim(dir, rec); err != nil {
			return Record{}, nil, err
		}
		var err error
		var vars []string
		rec, vars, err = prepare(ctx, dir, rec, set)
		if err != nil {
			return Record{}, nil, errors.Join(err, release(dir, rec))
		}

		var upErr bytes.Buffer
		err = docker(ctx, dir, vars, stderr, io.MultiWriter(stderr, &upErr), composeArgs(rec, "up", "-d", "--build", "--wait", "--wait-timeout", "300")...)
		if err == nil {
			return rec, vars, nil
		}
		err = fmt.Errorf("docker compose up of %s: %w", set.Name, err)

		cleanup, cancel := context.WithTimeout(context.WithoutCancel(ctx), removeTimeout)
		if attempt < startAttempts && portTaken(upErr.String()) {
			rerr := Remove(cleanup, dir, rec)
			cancel()
			if rerr != nil {
				return Record{}, nil, errors.Join(err, rerr)
			}
			continue
		}
		if path, lerr := saveLogs(cleanup, dir, rec, vars); lerr == nil {
			fmt.Fprintf(stderr, "megoocolab-runner services: logs saved to %s\n", path)
		} else {
			fmt.Fprintf(stderr, "megoocolab-runner services: could not save the logs: %v\n", lerr)
		}
		rerr := Remove(cleanup, dir, rec)
		cancel()
		return Record{}, nil, errors.Join(err, rerr)
	}
}

// prepare picks the ports, writes the env file, finds the images the Compose
// files build and saves them in the record. It starts no container.
func prepare(ctx context.Context, dir string, rec Record, set Set) (Record, []string, error) {
	picked, err := PickPorts(len(set.Ports))
	if err != nil {
		return rec, nil, err
	}
	ports := make(map[string]int, len(set.Ports))
	for i, name := range set.Ports {
		ports[name] = picked[i]
	}
	vars, err := Vars(set, ports, rec.Project, os.LookupEnv)
	if err != nil {
		return rec, nil, err
	}
	if err := writeEnvFile(rec.EnvFile, set.Name, vars); err != nil {
		return rec, nil, err
	}
	rec.Built, err = builtImages(ctx, dir, rec, vars)
	if err != nil {
		return rec, nil, err
	}
	return rec, vars, Save(dir, rec)
}

// release deletes the record and env file of a start that never ran up.
func release(dir string, rec Record) error {
	var errs []error
	for _, path := range []string{recordPath(dir, rec.Project), rec.EnvFile} {
		if err := os.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
			errs = append(errs, err)
		}
	}
	return errors.Join(errs...)
}

// writeEnvFile writes vars (sorted NAME=VALUE) as NAME='value' lines, readable
// only by the owner since values can hold secrets.
func writeEnvFile(path, set string, vars []string) error {
	var b strings.Builder
	for _, v := range vars {
		name, value, _ := strings.Cut(v, "=")
		if strings.Contains(value, "'") {
			return fmt.Errorf("services.%s.env.%s: a value cannot contain a single quote", set, name)
		}
		b.WriteString(name + "='" + value + "'\n")
	}
	return os.WriteFile(path, []byte(b.String()), 0o600)
}

// builtImages returns the images the Compose files build: for each service
// with a build key its image, else <project>-<service>; deduplicated, sorted.
func builtImages(ctx context.Context, dir string, rec Record, vars []string) ([]string, error) {
	args := composeArgs(rec, "config", "--format", "json")
	var stdout, stderr bytes.Buffer
	if err := docker(ctx, dir, vars, &stdout, &stderr, args...); err != nil {
		return nil, callError(args, err, stderr.String())
	}
	var cfg struct {
		Services map[string]struct {
			Build json.RawMessage `json:"build"`
			Image string          `json:"image"`
		} `json:"services"`
	}
	if err := json.Unmarshal(stdout.Bytes(), &cfg); err != nil {
		return nil, fmt.Errorf("docker compose config: %w", err)
	}
	var built []string
	for name, svc := range cfg.Services {
		if svc.Build == nil {
			continue
		}
		image := svc.Image
		if image == "" {
			image = rec.Project + "-" + name
		}
		built = append(built, image)
	}
	slices.Sort(built)
	return slices.Compact(built), nil
}

// saveLogs writes the containers' logs to <dir>/logs/<project>.log and
// returns its path.
func saveLogs(ctx context.Context, dir string, rec Record, vars []string) (string, error) {
	logs := filepath.Join(dir, "logs")
	if err := os.MkdirAll(logs, 0o700); err != nil {
		return "", err
	}
	path := filepath.Join(logs, rec.Project+".log")
	f, err := os.OpenFile(path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return "", err
	}
	err = docker(ctx, dir, vars, f, f, composeArgs(rec, "logs", "--no-color", "--timestamps")...)
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	if err != nil {
		return "", fmt.Errorf("docker compose logs: %w", err)
	}
	return path, nil
}

// composeArgs returns `compose -p <project> --env-file <file> -f <each>`
// followed by args.
func composeArgs(rec Record, args ...string) []string {
	out := []string{"compose", "-p", rec.Project, "--env-file", rec.EnvFile}
	for _, f := range rec.Compose {
		out = append(out, "-f", f)
	}
	return append(out, args...)
}

// portTaken reports whether up failed because a published port was taken.
func portTaken(stderr string) bool {
	for _, m := range portTakenMessages {
		if strings.Contains(stderr, m) {
			return true
		}
	}
	return false
}
