package jobs

import (
	"encoding/json"
	"reflect"
	"testing"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
	"github.com/mmhy2003/megoocolab/runner/internal/testserver"
)

// welcomeGrace is welcomeAs for claude_code with a grace period of grace (grace seconds, see Manager.GraceUnit).
func (e *env) welcomeGrace(maxRuns, grace int) {
	if err := e.srv.Send(protocol.Welcome{
		Type: protocol.TypeWelcome, UserID: "u1", GraceSeconds: grace,
		Agents: []protocol.WelcomeAgent{{
			AgentID: "agent-1", Name: "A", Program: "claude_code", MaxConcurrentRuns: maxRuns,
			Bindings: []protocol.WelcomeBinding{{ProjectKey: "MEG", LocalPath: e.repo}},
		}},
	}); err != nil {
		e.t.Fatal(err)
	}
}

func graceTweak(m *Manager) {
	m.GraceUnit = 100 * time.Millisecond
	m.FlushInterval = 50 * time.Millisecond
	m.CancelGrace = 100 * time.Millisecond
}

func runsHeld(t *testing.T, f testserver.Frame) []string {
	t.Helper()
	var h protocol.RunsHeld
	if err := json.Unmarshal(f.Raw, &h); err != nil {
		t.Fatal(err)
	}
	return h.Runs
}

// runFrames are the runs_held, run_update and run_finished frames that arrived on connection conn, in order.
func runFrames(srv *testserver.Server, conn int) []testserver.Frame {
	var out []testserver.Frame
	for _, f := range srv.Frames() {
		if f.Conn != conn {
			continue
		}
		switch f.Type {
		case protocol.TypeRunsHeld, protocol.TypeRunUpdate, protocol.TypeRunFinished:
			out = append(out, f)
		}
	}
	return out
}

// drop closes the live connection and makes every reconnect fail until accept.
func drop(e *env) {
	e.srv.RejectWith(1011)
	e.srv.Close(1011, "blip")
}

func accept(e *env) testserver.Frame {
	e.srv.RejectWith(0)
	return e.srv.WaitNthFrame(e.t, "hello", 2)
}

func TestDropWithGraceKeepsTheRunAndResumes(t *testing.T) {
	scenario := `[{"say":"before"},{"sleep_ms":1500},{"plan":[["after","in_progress"]]},{"say":"done"}]`
	e := newEnvWithCache(t, scenario, 1, t.TempDir(), graceTweak)
	e.welcomeGrace(1, 50)
	if held := e.srv.WaitFrame(t, protocol.TypeRunsHeld); held.Conn != 1 || len(runsHeld(t, held)) != 0 {
		t.Fatalf("first runs_held = %s on connection %d, want [] on 1", held.Raw, held.Conn)
	}
	e.startRun("run-g", "MEG-1", "workspace")
	e.waitUpdate("run-g")

	drop(e)
	time.Sleep(time.Second)
	hello := accept(e)
	e.welcomeGrace(1, 50)
	rf := e.finished("run-g")
	if rf.Outcome != "completed" {
		t.Fatalf("run_finished = %+v", rf)
	}

	frames := runFrames(e.srv, hello.Conn)
	if len(frames) == 0 || frames[0].Type != protocol.TypeRunsHeld {
		t.Fatalf("the first run frame on the new connection is not runs_held: %v", frames)
	}
	if got := runsHeld(t, frames[0]); !reflect.DeepEqual(got, []string{"run-g"}) {
		t.Fatalf("runs_held = %v, want [run-g]", got)
	}
	resumed := 0
	for _, f := range frames[1:] {
		if f.Type == protocol.TypeRunUpdate {
			resumed++
		}
	}
	if resumed == 0 {
		t.Fatal("no buffered update reached the new connection")
	}
	if last := frames[len(frames)-1]; last.Type != protocol.TypeRunFinished {
		t.Fatalf("the last run frame is %s, want run_finished", last.Type)
	}
	seq := 0
	for _, u := range e.updates("run-g") {
		if u.Seq <= seq {
			t.Fatalf("seq %d after %d: updates were lost or reordered", u.Seq, seq)
		}
		seq = u.Seq
	}
	if e.readReport().Cancelled {
		t.Error("the agent was cancelled by a drop inside the grace period")
	}
}

func TestGraceTimerStopsTheRuns(t *testing.T) {
	e := newEnvWithCache(t, sleeping, 1, t.TempDir(), graceTweak)
	e.welcomeGrace(1, 2) // 200 ms
	e.srv.WaitFrame(t, protocol.TypeRunsHeld)
	e.startRun("run-g", "MEG-1", "workspace")
	e.waitUpdate("run-g")

	drop(e)
	deadline := time.Now().Add(10 * time.Second)
	for !e.readReport().Cancelled {
		if time.Now().After(deadline) {
			t.Fatal("the grace timer did not stop the run")
		}
		time.Sleep(20 * time.Millisecond)
	}
	hello := accept(e)
	e.welcomeGrace(1, 2)
	held := e.srv.WaitNthFrame(t, protocol.TypeRunsHeld, 2)
	if got := runsHeld(t, held); len(got) != 0 {
		t.Fatalf("runs_held = %v after the grace period, want []", got)
	}
	time.Sleep(300 * time.Millisecond)
	for _, f := range runFrames(e.srv, hello.Conn) {
		if f.Type != protocol.TypeRunsHeld {
			t.Errorf("the stopped run sent %s on the new connection: %s", f.Type, f.Raw)
		}
	}
}

func TestWelcomeWithoutGraceSendsNoRunsHeld(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"hi"}]`, 1, t.TempDir(), graceTweak)
	e.startRun("run-a", "MEG-1", "workspace")
	e.finished("run-a")
	e.srv.Close(1011, "blip")
	e.srv.WaitNthFrame(t, "hello", 2)
	e.welcome(1)
	e.startRun("run-b", "MEG-2", "workspace")
	e.finished("run-b")
	for _, f := range e.srv.Frames() {
		if f.Type == protocol.TypeRunsHeld {
			t.Fatalf("runs_held sent without a grace period: %s", f.Raw)
		}
	}
}

func TestReconnectCapWhileHolding(t *testing.T) {
	m := New(func(any) error { return nil }, t.TempDir())
	m.GraceUnit = 100 * time.Millisecond
	t.Cleanup(func() { m.Shutdown(t.Context()) })
	if got := m.ReconnectCap(); got != 0 {
		t.Fatalf("cap before any drop = %v, want 0", got)
	}
	w := protocol.Welcome{Type: protocol.TypeWelcome, GraceSeconds: 50}
	m.resume(1, w)
	m.disconnected(1)
	if got := m.ReconnectCap(); got != 5*time.Second {
		t.Fatalf("cap while holding = %v, want 5s", got)
	}
	m.resume(2, w)
	if got := m.ReconnectCap(); got != 0 {
		t.Fatalf("cap after the resume = %v, want 0", got)
	}
}
