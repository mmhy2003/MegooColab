package cmd

import (
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/mmhy2003/megoocolab/runner/internal/config"
)

const nodeHint = "Install Node.js 20+ from https://nodejs.org — the Claude Code and Codex adapters run on it"

type checkResult struct {
	Name string
	OK   bool
	Hint string
}

// Line renders the result as "[OK] name: hint" or "[FAIL] name: hint".
func (r checkResult) Line() string {
	tag := "[FAIL]"
	if r.OK {
		tag = "[OK]"
	}
	return fmt.Sprintf("%s %s: %s", tag, r.Name, r.Hint)
}

// doctor holds the injectable dependencies of the checks.
type doctor struct {
	lookPath func(string) (string, error)
	run      func(name string, args ...string) (string, error)
	http     *http.Client
	load     func() (config.Config, error)
}

func newDoctor() doctor {
	return doctor{
		lookPath: exec.LookPath,
		run: func(name string, args ...string) (string, error) {
			out, err := exec.Command(name, args...).Output()
			return string(out), err
		},
		http: &http.Client{Timeout: 10 * time.Second},
		load: config.Load,
	}
}

func newDoctorCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "doctor",
		Short: "Check configuration, server access and prerequisites",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return newDoctor().report(cmd.OutOrStdout())
		},
	}
}

// report prints every check and returns an error if any failed.
func (d doctor) report(w io.Writer) error {
	cfg, cfgRes := d.checkConfig()
	results := []checkResult{cfgRes}
	if cfgRes.OK {
		results = append(results, d.checkServer(cfg))
	} else {
		results = append(results, checkResult{Name: "server", Hint: "skipped: no usable config"})
	}
	results = append(results, d.checkGit(), d.checkNode())
	failed := 0
	for _, r := range results {
		fmt.Fprintln(w, r.Line())
		if !r.OK {
			failed++
		}
	}
	if failed > 0 {
		return fmt.Errorf("%d check(s) failed", failed)
	}
	return nil
}

func (d doctor) checkConfig() (config.Config, checkResult) {
	const login = "run: megoocolab-runner login --url URL --token TOKEN"
	cfg, err := d.load()
	if err != nil {
		hint := "cannot read the config (" + err.Error() + "); " + login
		if errors.Is(err, os.ErrNotExist) {
			hint = "no config found; " + login
		}
		return cfg, checkResult{Name: "config", Hint: hint}
	}
	return cfg, checkResult{Name: "config", OK: true, Hint: "server " + cfg.URL}
}

func (d doctor) checkServer(cfg config.Config) checkResult {
	const name = "server"
	scopes, err := tokenScopes(d.http, cfg.URL, cfg.Token)
	if err != nil {
		hint := err.Error()
		if strings.Contains(hint, "rejected") {
			hint += "; run: megoocolab-runner login with a fresh token"
		} else {
			hint += "; check the URL and your network"
		}
		return checkResult{Name: name, Hint: hint}
	}
	if !hasScope(scopes, "runner") {
		return checkResult{Name: name, Hint: "the token has no runner scope; create one with the runner scope and run login again"}
	}
	return checkResult{Name: name, OK: true, Hint: "reachable, token valid with runner scope"}
}

func (d doctor) checkGit() checkResult {
	if _, err := d.lookPath("git"); err != nil {
		return checkResult{Name: "git", Hint: "git was not found on PATH; install it from https://git-scm.com"}
	}
	return checkResult{Name: "git", OK: true, Hint: "found on PATH"}
}

func (d doctor) checkNode() checkResult {
	const name = "node"
	if _, err := d.lookPath("node"); err != nil {
		return checkResult{Name: name, Hint: "node was not found on PATH. " + nodeHint}
	}
	out, err := d.run("node", "--version")
	if err != nil {
		return checkResult{Name: name, Hint: "could not run node --version (" + err.Error() + "). " + nodeHint}
	}
	ver := strings.TrimSpace(out)
	major, err := strconv.Atoi(strings.SplitN(strings.TrimPrefix(ver, "v"), ".", 2)[0])
	if err != nil {
		return checkResult{Name: name, Hint: fmt.Sprintf("unrecognized node version %q. %s", ver, nodeHint)}
	}
	if major < 20 {
		return checkResult{Name: name, Hint: fmt.Sprintf("found %s, need 20 or newer. %s", ver, nodeHint)}
	}
	if _, err := d.lookPath("npx"); err != nil {
		return checkResult{Name: name, Hint: "npx was not found on PATH (it ships with Node.js). " + nodeHint}
	}
	return checkResult{Name: name, OK: true, Hint: ver + " with npx"}
}
