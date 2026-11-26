package jobs

import (
	"errors"
	"reflect"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// fakeSend records what was sent; it fails while fail is set, or on the failAt-th call (1-based).
type fakeSend struct {
	sent   []any
	calls  int
	fail   bool
	failAt int
}

func (f *fakeSend) send(msg any) error {
	f.calls++
	if f.fail || f.calls == f.failAt {
		return errors.New("socket closed")
	}
	f.sent = append(f.sent, msg)
	return nil
}

func upd(runID string, seq int) protocol.RunUpdate {
	return protocol.NewRunUpdate(runID, seq, "message", map[string]any{"text": "x"})
}

func fin(runID string) protocol.RunFinished {
	return protocol.RunFinished{Type: protocol.TypeRunFinished, RunID: runID, Outcome: "completed"}
}

func TestOutboxSendsDirectlyWhenNotHolding(t *testing.T) {
	o := newOutbox(10)
	f := &fakeSend{}
	o.send(f.send, upd("r", 1), true)
	o.send(f.send, fin("r"), false)
	if want := []any{upd("r", 1), fin("r")}; !reflect.DeepEqual(f.sent, want) {
		t.Fatalf("sent %v, want %v", f.sent, want)
	}
	if o.holds() {
		t.Fatal("holds() is true after direct sends")
	}
}

func TestOutboxKeepsFailedSendsOnlyWhenAsked(t *testing.T) {
	o := newOutbox(10)
	f := &fakeSend{fail: true}
	o.send(f.send, upd("r", 1), false)
	if o.holds() {
		t.Fatal("a failed send with keep=false was kept")
	}
	o.send(f.send, upd("r", 2), true)
	if !o.holds() {
		t.Fatal("a failed send with keep=true was dropped")
	}
	f.fail = false
	o.send(f.send, upd("r", 3), false) // older messages wait: this one queues behind them
	if len(f.sent) != 0 {
		t.Fatalf("sent %v while older messages wait", f.sent)
	}
	if err := o.flush(f.send); err != nil {
		t.Fatal(err)
	}
	if want := []any{upd("r", 2), upd("r", 3)}; !reflect.DeepEqual(f.sent, want) {
		t.Fatalf("sent %v, want %v", f.sent, want)
	}
}

func TestOutboxHoldsInOrderAndFlushes(t *testing.T) {
	o := newOutbox(10)
	f := &fakeSend{}
	o.hold()
	o.send(f.send, upd("r", 1), true)
	o.send(f.send, protocol.NewRunSteerResult("r", "m1", protocol.SteerNotRunning, ""), true)
	o.send(f.send, fin("r"), true)
	if len(f.sent) != 0 {
		t.Fatalf("sent %v while holding", f.sent)
	}
	if err := o.flush(f.send); err != nil {
		t.Fatal(err)
	}
	want := []any{upd("r", 1), protocol.NewRunSteerResult("r", "m1", protocol.SteerNotRunning, ""), fin("r")}
	if !reflect.DeepEqual(f.sent, want) {
		t.Fatalf("sent %v, want %v", f.sent, want)
	}
	if o.holds() {
		t.Fatal("holds() is true after a full flush")
	}
}

func TestOutboxFlushFailureKeepsTheRest(t *testing.T) {
	o := newOutbox(10)
	o.hold()
	o.send(nil, upd("r", 1), true)
	o.send(nil, upd("r", 2), true)
	o.send(nil, upd("r", 3), true)
	f := &fakeSend{failAt: 2}
	if err := o.flush(f.send); err == nil {
		t.Fatal("flush returned no error")
	}
	if want := []any{upd("r", 1)}; !reflect.DeepEqual(f.sent, want) {
		t.Fatalf("sent %v, want %v", f.sent, want)
	}
	if !o.holds() {
		t.Fatal("holds() is false after a failed flush")
	}
	if err := o.flush(f.send); err != nil {
		t.Fatal(err)
	}
	if want := []any{upd("r", 1), upd("r", 2), upd("r", 3)}; !reflect.DeepEqual(f.sent, want) {
		t.Fatalf("sent %v, want %v", f.sent, want)
	}
}

func TestOutboxIsBoundedAndNeverDropsRunFinished(t *testing.T) {
	o := newOutbox(3)
	o.hold()
	for _, m := range []any{upd("r", 1), fin("f"), upd("r", 2), upd("r", 3), upd("r", 4)} {
		o.send(nil, m, true)
	}
	o.mu.Lock()
	got := append([]any(nil), o.msgs...)
	o.mu.Unlock()
	if want := []any{fin("f"), upd("r", 3), upd("r", 4)}; !reflect.DeepEqual(got, want) {
		t.Fatalf("kept %v, want %v", got, want)
	}

	o = newOutbox(3)
	o.hold()
	o.send(nil, upd("r", 1), true)
	o.send(nil, protocol.NewRunSteerResult("r", "m1", protocol.SteerNotRunning, ""), true)
	o.send(nil, fin("a"), true)
	o.send(nil, fin("b"), true) // drops the update
	o.send(nil, fin("c"), true) // drops the steer result
	o.send(nil, fin("d"), true) // only run_finished left: grows past the limit
	if want := []string{"a", "b", "c", "d"}; !reflect.DeepEqual(o.finishedRuns(), want) {
		t.Fatalf("finished %v, want %v", o.finishedRuns(), want)
	}
	o.mu.Lock()
	n := len(o.msgs)
	o.mu.Unlock()
	if n != 4 {
		t.Fatalf("kept %d messages, want 4", n)
	}
}

func TestOutboxFinishedRuns(t *testing.T) {
	o := newOutbox(10)
	if got := o.finishedRuns(); len(got) != 0 {
		t.Fatalf("finished %v on an empty outbox", got)
	}
	o.hold()
	o.send(nil, fin("b"), true)
	o.send(nil, upd("a", 1), true)
	o.send(nil, fin("a"), true)
	if want := []string{"b", "a"}; !reflect.DeepEqual(o.finishedRuns(), want) {
		t.Fatalf("finished %v, want %v", o.finishedRuns(), want)
	}
	o.drop()
	if o.holds() || len(o.finishedRuns()) != 0 {
		t.Fatal("drop left messages or holding")
	}
}
