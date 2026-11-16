package cmd

import (
	"bytes"
	"errors"
	"slices"
	"strings"
	"testing"
	"time"
)

type fakeClock struct {
	t       time.Time
	slept   []time.Duration
	onSleep func(n int) // called after each sleep with the number of sleeps so far
}

func (c *fakeClock) now() time.Time { return c.t }

func (c *fakeClock) sleep(d time.Duration) {
	c.t = c.t.Add(d)
	c.slept = append(c.slept, d)
	if c.onSleep != nil {
		c.onSleep(len(c.slept))
	}
}

type workerRun struct {
	code int
	up   time.Duration
}

// harness drives a supervisor with a fake clock and a scripted worker.
type harness struct {
	clock    *fakeClock
	log      bytes.Buffer
	script   []workerRun
	runs     int
	runStart []int // len(clock.slept) at the start of each run
	stop     bool
	claimed  int
	released int
	other    int
	workErr  error
}

func newHarness(script ...workerRun) *harness {
	return &harness{clock: &fakeClock{t: time.Date(2026, 11, 16, 8, 0, 0, 0, time.UTC)}, script: script}
}

func codes(cs ...int) []workerRun {
	out := make([]workerRun, len(cs))
	for i, c := range cs {
		out[i] = workerRun{code: c}
	}
	return out
}

func (h *harness) supervisor() supervisor {
	return supervisor{
		log: &h.log,
		otherRunning: func() (int, bool) {
			return h.other, h.other != 0
		},
		claim: func() (func(), error) {
			h.claimed++
			return func() { h.released++ }, nil
		},
		runWorker: func() (int, error) {
			h.runStart = append(h.runStart, len(h.clock.slept))
			if h.workErr != nil {
				return 0, h.workErr
			}
			if h.runs >= len(h.script) {
				panic("worker script exhausted")
			}
			r := h.script[h.runs]
			h.runs++
			h.clock.t = h.clock.t.Add(r.up)
			return r.code, nil
		},
		stopRequested: func() bool { return h.stop },
		now:           h.clock.now,
		sleep:         h.clock.sleep,
	}
}

// waits sums the slept chunks between consecutive worker runs.
func (h *harness) waits() []time.Duration {
	var out []time.Duration
	for i := 1; i < len(h.runStart); i++ {
		var sum time.Duration
		for _, d := range h.clock.slept[h.runStart[i-1]:h.runStart[i]] {
			sum += d
		}
		out = append(out, sum)
	}
	return out
}

func TestSuperviseStopsOnZeroAnd78(t *testing.T) {
	cases := []struct {
		code int
		want string
	}{
		{0, "runner stopped"},
		{78, "not restarting"},
	}
	for _, tc := range cases {
		h := newHarness(codes(tc.code)...)
		if err := h.supervisor().run(); err != nil {
			t.Fatalf("code %d: run() = %v", tc.code, err)
		}
		if h.runs != 1 {
			t.Errorf("code %d: worker ran %d times, want 1", tc.code, h.runs)
		}
		if !strings.Contains(h.log.String(), tc.want) {
			t.Errorf("code %d: log %q does not contain %q", tc.code, h.log.String(), tc.want)
		}
	}
}

func TestSuperviseRestartsWithBackoff(t *testing.T) {
	h := newHarness(codes(1, 1, 1, 1, 1, 1, 1, 0)...)
	if err := h.supervisor().run(); err != nil {
		t.Fatalf("run() = %v", err)
	}
	if h.runs != 8 {
		t.Errorf("worker ran %d times, want 8", h.runs)
	}
	s := time.Second
	want := []time.Duration{5 * s, 10 * s, 20 * s, 40 * s, 80 * s, 120 * s, 120 * s}
	if got := h.waits(); !slices.Equal(got, want) {
		t.Errorf("waits = %v, want %v", got, want)
	}
	for _, line := range []string{"runner exited with status 1; restarting in 5s", "restarting in 2m0s"} {
		if !strings.Contains(h.log.String(), line) {
			t.Errorf("log %q does not contain %q", h.log.String(), line)
		}
	}
}

func TestSuperviseResetsAfterLongUptime(t *testing.T) {
	h := newHarness(workerRun{1, 0}, workerRun{1, 0}, workerRun{1, 6 * time.Minute}, workerRun{0, 0})
	if err := h.supervisor().run(); err != nil {
		t.Fatalf("run() = %v", err)
	}
	want := []time.Duration{5 * time.Second, 10 * time.Second, 5 * time.Second}
	if got := h.waits(); !slices.Equal(got, want) {
		t.Errorf("waits = %v, want %v", got, want)
	}
}

func TestSuperviseSleepsInSecondSteps(t *testing.T) {
	h := newHarness(codes(1, 1, 1, 0)...)
	if err := h.supervisor().run(); err != nil {
		t.Fatalf("run() = %v", err)
	}
	if len(h.clock.slept) == 0 {
		t.Fatal("never slept")
	}
	for i, d := range h.clock.slept {
		if d > time.Second {
			t.Errorf("sleep %d = %s, want <= 1s", i, d)
		}
	}
}

func TestSuperviseStopDuringBackoff(t *testing.T) {
	h := newHarness(codes(1, 1)...)
	h.clock.onSleep = func(n int) {
		if n == 3 {
			h.stop = true
		}
	}
	if err := h.supervisor().run(); err != nil {
		t.Fatalf("run() = %v", err)
	}
	if h.runs != 1 {
		t.Errorf("worker ran %d times, want 1", h.runs)
	}
	if !strings.Contains(h.log.String(), "stop requested") {
		t.Errorf("log %q does not contain %q", h.log.String(), "stop requested")
	}
}

func TestSuperviseStopBeforeFirstStart(t *testing.T) {
	h := newHarness(codes(0)...)
	h.stop = true
	if err := h.supervisor().run(); err != nil {
		t.Fatalf("run() = %v", err)
	}
	if len(h.runStart) != 0 {
		t.Errorf("worker ran %d times, want 0", len(h.runStart))
	}
}

func TestSuperviseRefusesSecondRunner(t *testing.T) {
	h := newHarness(codes(0)...)
	h.other = 4242
	if err := h.supervisor().run(); err != nil {
		t.Fatalf("run() = %v", err)
	}
	if h.claimed != 0 || len(h.runStart) != 0 {
		t.Errorf("claimed %d times, worker ran %d times, want 0 and 0", h.claimed, len(h.runStart))
	}
	if !strings.Contains(h.log.String(), "already running (pid 4242)") {
		t.Errorf("log %q does not contain %q", h.log.String(), "already running (pid 4242)")
	}
}

func TestSuperviseReleasesClaim(t *testing.T) {
	h := newHarness(codes(1, 0)...)
	if err := h.supervisor().run(); err != nil {
		t.Fatalf("run() = %v", err)
	}
	if h.claimed != 1 || h.released != 1 {
		t.Errorf("claimed %d, released %d, want 1 and 1", h.claimed, h.released)
	}
}

func TestSuperviseWorkerStartError(t *testing.T) {
	h := newHarness()
	h.workErr = errors.New("no exe")
	err := h.supervisor().run()
	if err == nil || !strings.Contains(err.Error(), "cannot start the runner") {
		t.Fatalf("run() = %v, want an error containing %q", err, "cannot start the runner")
	}
	if h.released != 1 {
		t.Errorf("released %d, want 1", h.released)
	}
}
