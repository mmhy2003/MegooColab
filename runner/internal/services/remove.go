package services

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// logsMaxAge is how long the containers' logs of a failed check are kept.
const logsMaxAge = 7 * 24 * time.Hour

// Remove removes everything of rec's Compose project: its containers, volumes,
// networks and the images it built. It goes on after a failed call and
// returns every error; the record and env file are deleted only when all
// calls succeeded, so a later sweep tries again. A project the runner would
// not have named is refused before any docker call.
func Remove(ctx context.Context, dir string, rec Record) error {
	if !IsOurs(rec.Project) {
		return fmt.Errorf("%q is not a project the runner starts; not removing it", rec.Project)
	}
	var errs []error
	call := func(args ...string) string {
		out, err := dockerOutput(ctx, dir, args...)
		if err != nil {
			errs = append(errs, err)
		}
		return out
	}

	down := []string{"compose", "-p", rec.Project}
	if filesIntact(rec) {
		down = append(down, "--env-file", rec.EnvFile)
		for _, f := range rec.Compose {
			down = append(down, "-f", f)
		}
	}
	call(append(down, "down", "--volumes", "--remove-orphans", "--timeout", "10")...)

	label := "label=com.docker.compose.project=" + rec.Project
	for _, kind := range []struct{ list, rm []string }{
		{[]string{"ps", "-aq"}, []string{"rm", "-f", "-v"}},
		{[]string{"volume", "ls", "-q"}, []string{"volume", "rm", "-f"}},
		{[]string{"network", "ls", "-q"}, []string{"network", "rm"}},
	} {
		if ids := strings.Fields(call(append(kind.list, "--filter", label)...)); len(ids) > 0 {
			call(append(kind.rm, ids...)...)
		}
	}

	if len(rec.Built) > 0 {
		var stderr bytes.Buffer
		err := docker(ctx, dir, nil, nil, &stderr, append([]string{"image", "rm"}, rec.Built...)...)
		if err != nil && !isNoSuchImage(stderr.String()) {
			errs = append(errs, callError([]string{"image", "rm"}, err, stderr.String()))
		}
	}

	if len(errs) > 0 {
		return fmt.Errorf("remove %s: %w", rec.Project, errors.Join(errs...))
	}
	for _, path := range []string{recordPath(dir, rec.Project), filepath.Join(dir, rec.Project+".env")} {
		if err := os.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
			errs = append(errs, err)
		}
	}
	return errors.Join(errs...)
}

// CleanWorktree removes every recorded set of worktree, whether or not the
// process that started it still runs.
func CleanWorktree(ctx context.Context, dir, worktree string) error {
	recs, err := List(dir)
	if err != nil {
		return err
	}
	want := Canonical(worktree)
	var errs []error
	for _, rec := range recs {
		if Canonical(rec.Worktree) == want {
			errs = append(errs, Remove(ctx, dir, rec))
		}
	}
	return errors.Join(errs...)
}

// Sweep removes the sets whose starting process is gone and deletes logs
// older than seven days. It goes on after a failure and returns every error.
func Sweep(ctx context.Context, dir string, now time.Time) error {
	recs, err := List(dir)
	if err != nil {
		return err
	}
	var errs []error
	for _, rec := range recs {
		if !processAlive(rec.PID) {
			errs = append(errs, Remove(ctx, dir, rec))
		}
	}
	logs := filepath.Join(dir, "logs")
	entries, err := os.ReadDir(logs)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		errs = append(errs, err)
	}
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".log") {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		if now.Sub(info.ModTime()) > logsMaxAge {
			if err := os.Remove(filepath.Join(logs, e.Name())); err != nil && !errors.Is(err, fs.ErrNotExist) {
				errs = append(errs, err)
			}
		}
	}
	return errors.Join(errs...)
}

// filesIntact reports whether the Compose files and env file of rec still
// exist, so down can be given them.
func filesIntact(rec Record) bool {
	if len(rec.Compose) == 0 || rec.EnvFile == "" {
		return false
	}
	for _, path := range append([]string{rec.EnvFile}, rec.Compose...) {
		if _, err := os.Stat(path); err != nil {
			return false
		}
	}
	return true
}

// dockerOutput runs docker and returns its stdout; a failure names the call
// and carries docker's stderr.
func dockerOutput(ctx context.Context, dir string, args ...string) (string, error) {
	var stdout, stderr bytes.Buffer
	if err := docker(ctx, dir, nil, &stdout, &stderr, args...); err != nil {
		return "", callError(args, err, stderr.String())
	}
	return stdout.String(), nil
}

func callError(args []string, err error, stderr string) error {
	if s := strings.TrimSpace(stderr); s != "" {
		return fmt.Errorf("docker %s: %w: %s", strings.Join(args, " "), err, s)
	}
	return fmt.Errorf("docker %s: %w", strings.Join(args, " "), err)
}

// isNoSuchImage reports whether every error docker image rm printed is about
// an image that is already gone.
func isNoSuchImage(stderr string) bool {
	found := false
	for _, line := range strings.Split(stderr, "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		if !strings.Contains(line, "No such image") {
			return false
		}
		found = true
	}
	return found
}
