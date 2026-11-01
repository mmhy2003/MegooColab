package jobs

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// steerScenario says something (so a test can wait for the turn), then waits for steers.
const steerScenario = `[{"say":"thinking"},{"await_steer_ms":5000},{"say":"done"}]`

const steerText = "MegooColab: a person sent you an instruction.\n\nInstruction from Mo, sent 2026-11-01 14:02 UTC:\n> Use RetryPolicy"

func (e *env) steer(runID, messageID, text string) {
	e.t.Helper()
	if err := e.srv.Send(protocol.RunSteer{Type: protocol.TypeRunSteer, RunID: runID, MessageID: messageID, Text: text}); err != nil {
		e.t.Fatal(err)
	}
}

func (e *env) steerResult(messageID string) protocol.RunSteerResult {
	e.t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		for _, f := range e.srv.Frames() {
			if f.Type != protocol.TypeRunSteerResult {
				continue
			}
			var r protocol.RunSteerResult
			if err := json.Unmarshal(f.Raw, &r); err != nil {
				e.t.Fatal(err)
			}
			if r.MessageID == messageID {
				return r
			}
		}
		time.Sleep(20 * time.Millisecond)
	}
	e.t.Fatalf("no run_steer_result for %s", messageID)
	return protocol.RunSteerResult{}
}

func (e *env) said(runID, text string) bool {
	for _, u := range e.updates(runID) {
		if u.Kind == "message" && strings.Contains(jsonStr(u.Data), text) {
			return true
		}
	}
	return false
}

func TestSteerDuringTurnIsInjected(t *testing.T) {
	e := newEnvWithCache(t, steerScenario, 1, t.TempDir())
	e.startRun("run-s", "MEG-1", "workspace")
	e.waitUpdate("run-s")
	e.steer("run-s", "m1", steerText)
	if r := e.steerResult("m1"); r.Outcome != protocol.SteerInjected || r.RunID != "run-s" {
		t.Fatalf("result = %+v", r)
	}
	if rf := e.finished("run-s"); rf.Outcome != "completed" {
		t.Fatalf("finished = %+v", rf)
	}
	if !e.said("run-s", "steered: Use RetryPolicy") {
		t.Error("the agent never said it got the instruction")
	}
	if got := e.readReport().Steers; len(got) != 1 || got[0] != steerText {
		t.Errorf("steers = %q", got)
	}
}

func TestSteerBeforeTurnIsHeldThenInjected(t *testing.T) {
	e := newEnvWithCache(t, steerScenario, 1, t.TempDir())
	e.startRun("run-h", "MEG-1", "workspace")
	e.steer("run-h", "m1", steerText) // the adapter is still starting: the runner holds it
	if r := e.steerResult("m1"); r.Outcome != protocol.SteerInjected {
		t.Fatalf("result = %+v", r)
	}
	e.finished("run-h")
}

func TestSteerForUnknownRunIsNotRunning(t *testing.T) {
	e := newEnvWithCache(t, steerScenario, 1, t.TempDir())
	e.steer("nope", "m1", steerText)
	if r := e.steerResult("m1"); r.Outcome != protocol.SteerNotRunning || r.RunID != "nope" {
		t.Fatalf("result = %+v", r)
	}
}

func TestSteerAfterTurnEndsReportsNotRunningAndCancelsStrayTurn(t *testing.T) {
	t.Setenv("FAKEAGENT_STEER_OUTCOME", "startedNewTurn") // like Codex when the turn ended under the steer
	e := newEnvWithCache(t, steerScenario, 1, t.TempDir())
	e.startRun("run-x", "MEG-1", "workspace")
	e.waitUpdate("run-x")
	e.steer("run-x", "m1", steerText)
	if r := e.steerResult("m1"); r.Outcome != protocol.SteerNotRunning {
		t.Fatalf("result = %+v", r)
	}
	e.finished("run-x")
	if !e.readReport().Cancelled {
		t.Error("the stray turn the steer started was never cancelled")
	}
}

func TestSteerWithoutAdapterSupportIsUnsupported(t *testing.T) {
	t.Setenv("FAKEAGENT_STEERING", "off")
	e := newEnvWithCache(t, steerScenario, 1, t.TempDir())
	e.startRun("run-u", "MEG-1", "workspace")
	e.waitUpdate("run-u")
	e.steer("run-u", "m1", steerText)
	if r := e.steerResult("m1"); r.Outcome != protocol.SteerUnsupported {
		t.Fatalf("result = %+v", r)
	}
	e.finished("run-u")
}

func TestSteersAreDeliveredInOrder(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"thinking"},{"await_steer_ms":5000},{"await_steer_ms":5000},{"say":"done"}]`, 1, t.TempDir())
	e.startRun("run-o", "MEG-1", "workspace")
	e.waitUpdate("run-o")
	e.steer("run-o", "m1", "> first")
	e.steer("run-o", "m2", "> second")
	for _, id := range []string{"m1", "m2"} {
		if r := e.steerResult(id); r.Outcome != protocol.SteerInjected {
			t.Fatalf("%s: result = %+v", id, r)
		}
	}
	e.finished("run-o")
	if got := e.readReport().Steers; len(got) != 2 || got[0] != "> first" || got[1] != "> second" {
		t.Errorf("steers = %q", got)
	}
}
