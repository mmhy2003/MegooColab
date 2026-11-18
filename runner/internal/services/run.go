package services

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"syscall"
	"time"
)

// ExitServices is the exit code when the runner could not start or remove
// the services, or the set is already running.
const ExitServices = 125

// exitNotFound is the exit code when the command cannot be found, as shells
// use.
const exitNotFound = 127

// Options says which set Run starts and which command it wraps.
type Options struct {
	Dir     string // records folder (Dir())
	Cwd     string // where megoocolab.toml is searched from and the command runs
	Set     string
	Command []string // program and arguments
	Stdin   io.Reader
	Stdout  io.Writer
	Stderr  io.Writer
	Signals <-chan os.Signal // forwarded to the command; may be nil
}

// Run starts o.Set for the worktree holding o.Cwd, runs o.Command with the
// set's variables, removes the set and returns the command's exit code, or
// ExitServices when the services could not be started or removed.
func Run(ctx context.Context, o Options) int {
	say := func(format string, args ...any) {
		fmt.Fprintf(o.Stderr, "megoocolab-runner services: "+format+"\n", args...)
	}

	f, set, err := lookUp(o.Cwd, o.Set)
	if err != nil {
		say("%v", err)
		return ExitServices
	}
	if len(o.Command) == 0 {
		say("no command to run")
		return ExitServices
	}
	if err := Check(ctx); err != nil {
		say("%v", err)
		return ExitServices
	}
	if err := Sweep(ctx, o.Dir, time.Now()); err != nil {
		say("removing the services of ended checks: %v", err)
	}

	rec, vars, err := start(ctx, o.Dir, f, set, o.Stderr)
	if errors.Is(err, ErrBusy) {
		say("%s is already running in this worktree", set.Name)
		return ExitServices
	}
	if err != nil {
		say("%v", err)
		return ExitServices
	}

	code := runCommand(o, vars, say)

	cleanup, cancel := context.WithTimeout(context.WithoutCancel(ctx), removeTimeout)
	defer cancel()
	if code != 0 {
		if path, err := saveLogs(cleanup, o.Dir, rec, vars); err == nil {
			say("logs saved to %s", path)
		} else {
			say("could not save the logs: %v", err)
		}
	}
	if err := Remove(cleanup, o.Dir, rec); err != nil {
		say("%v", err)
		say("the services stay recorded; megoocolab-runner services clean retries")
		return ExitServices
	}
	return code
}

// lookUp finds and loads megoocolab.toml from cwd and returns the named set.
func lookUp(cwd, name string) (*File, Set, error) {
	path, err := Find(cwd)
	if err != nil {
		return nil, Set{}, err
	}
	f, err := Load(path)
	if err != nil {
		return nil, Set{}, err
	}
	set, ok := f.Sets[name]
	if !ok {
		return nil, Set{}, fmt.Errorf("%s: no service set %q (sets: %s)", f.Path, name, strings.Join(f.Names(), ", "))
	}
	return f, set, nil
}

// runCommand runs o.Command in o.Cwd with vars added to the environment,
// forwarding o.Signals to it, and returns its exit code: 128 + the signal
// number when a signal ended it on Unix.
func runCommand(o Options, vars []string, say func(string, ...any)) int {
	path, err := exec.LookPath(o.Command[0])
	if err != nil {
		say("%v", err)
		return exitNotFound
	}
	cmd := exec.Command(path, o.Command[1:]...)
	cmd.Dir = o.Cwd
	cmd.Env = append(os.Environ(), vars...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = o.Stdin, o.Stdout, o.Stderr
	if err := cmd.Start(); err != nil {
		say("%v", err)
		return exitNotFound
	}

	done := make(chan struct{})
	forwarded := make(chan struct{})
	go func() {
		defer close(forwarded)
		for {
			select {
			case <-done:
				return
			case sig := <-o.Signals:
				forward(cmd.Process, sig)
			}
		}
	}()
	err = cmd.Wait()
	close(done)
	<-forwarded

	var exit *exec.ExitError
	if err != nil && !errors.As(err, &exit) {
		say("%v", err)
		return 1
	}
	if ws, ok := cmd.ProcessState.Sys().(syscall.WaitStatus); ok && ws.Signaled() {
		return 128 + int(ws.Signal())
	}
	return cmd.ProcessState.ExitCode()
}

// forward passes sig to p. Windows cannot send signals: Ctrl+C already reached
// the command through the console, and anything else kills it.
func forward(p *os.Process, sig os.Signal) {
	if runtime.GOOS != "windows" {
		_ = p.Signal(sig)
		return
	}
	if sig != os.Interrupt {
		_ = p.Kill()
	}
}
