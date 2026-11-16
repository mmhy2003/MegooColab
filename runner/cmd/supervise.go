package cmd

// On Windows nothing restarts a per-user process, so `run --background`
// supervises the worker: it runs the runner and restarts it with backoff when
// it exits. Linux (systemd) and macOS (launchd) restart the runner themselves
// and don't need it. Exit 0 is a deliberate stop and 78 needs `login`, so
// neither is restarted.

import (
	"fmt"
	"io"
	"time"
)

const (
	restartMin   = 5 * time.Second   // first delay before a restart
	restartMax   = 120 * time.Second // the delay doubles up to this
	restartReset = 5 * time.Minute   // a worker up this long resets the delay
)

// supervisor restarts the runner worker. Its dependencies are injected so the
// loop can be tested with a fake worker and clock.
type supervisor struct {
	log           io.Writer
	otherRunning  func() (int, bool)
	claim         func() (func(), error)
	runWorker     func() (int, error)
	stopRequested func() bool
	now           func() time.Time
	sleep         func(time.Duration)
}

func (s supervisor) run() error {
	if pid, ok := s.otherRunning(); ok {
		fmt.Fprintf(s.log, "another runner is already running (pid %d); exiting\n", pid)
		return nil
	}
	release, err := s.claim()
	if err != nil {
		return fmt.Errorf("cannot write the pid file: %w", err)
	}
	defer release()
	delay := restartMin
	for {
		if s.stopRequested() {
			fmt.Fprintln(s.log, "stop requested; not starting the runner")
			return nil
		}
		started := s.now()
		code, err := s.runWorker()
		if err != nil {
			return fmt.Errorf("cannot start the runner: %w", err)
		}
		switch code {
		case 0:
			fmt.Fprintln(s.log, "runner stopped")
			return nil
		case exitStoppedByServer:
			fmt.Fprintf(s.log, "runner exited with status %d (run `megoocolab-runner login`, then `service start`); not restarting\n", code)
			return nil
		}
		if s.now().Sub(started) >= restartReset {
			delay = restartMin
		}
		fmt.Fprintf(s.log, "runner exited with status %d; restarting in %s\n", code, delay)
		if !s.wait(delay) {
			fmt.Fprintln(s.log, "stop requested; not restarting the runner")
			return nil
		}
		delay = min(delay*2, restartMax)
	}
}

// wait sleeps d in steps of at most one second and returns false as soon as a stop is requested.
func (s supervisor) wait(d time.Duration) bool {
	for left := d; left > 0; left -= time.Second {
		if s.stopRequested() {
			return false
		}
		s.sleep(min(time.Second, left))
	}
	return true
}
