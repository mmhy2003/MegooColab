package jobs

import (
	"sync"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// outboxLimit bounds the messages an outbox keeps (run_finished messages aside).
const outboxLimit = 2000

// outbox keeps a run's messages (run_update, run_finished, run_steer_result) that could not reach the server
// while the connection is down, in order, for the next connection (MC-214).
type outbox struct {
	mu      sync.Mutex
	limit   int
	holding bool  // between a disconnect with a grace period and the next runs_held: everything waits here
	msgs    []any // protocol.RunUpdate, protocol.RunFinished, protocol.RunSteerResult values
}

func newOutbox(limit int) *outbox {
	return &outbox{limit: limit}
}

// send sends msg, or keeps it: while holding, while older messages wait, or when keep is set and the send fails.
// The send happens under the lock, so a later message never overtakes one that is being kept.
func (o *outbox) send(send func(any) error, msg any, keep bool) {
	o.mu.Lock()
	defer o.mu.Unlock()
	if o.holding || len(o.msgs) > 0 {
		o.addLocked(msg)
		return
	}
	if err := send(msg); err != nil && keep {
		o.addLocked(msg)
	}
}

// hold makes every message wait in the outbox until a flush sends them all.
func (o *outbox) hold() {
	o.mu.Lock()
	o.holding = true
	o.mu.Unlock()
}

// drop forgets every message and stops holding.
func (o *outbox) drop() {
	o.mu.Lock()
	o.msgs = nil
	o.holding = false
	o.mu.Unlock()
}

// holds reports whether messages wait here, or will.
func (o *outbox) holds() bool {
	o.mu.Lock()
	defer o.mu.Unlock()
	return o.holding || len(o.msgs) > 0
}

// finishedRuns is the run ids of the queued run_finished messages, in order.
func (o *outbox) finishedRuns() []string {
	o.mu.Lock()
	defer o.mu.Unlock()
	var ids []string
	for _, msg := range o.msgs {
		if rf, ok := msg.(protocol.RunFinished); ok {
			ids = append(ids, rf.RunID)
		}
	}
	return ids
}

// flush sends the queued messages in order under the lock (new ones queue behind). On a failure it keeps the rest
// and stays holding; once all are sent it stops holding.
func (o *outbox) flush(send func(any) error) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	for len(o.msgs) > 0 {
		if err := send(o.msgs[0]); err != nil {
			o.holding = true
			return err
		}
		o.msgs[0] = nil
		o.msgs = o.msgs[1:]
	}
	o.msgs = nil
	o.holding = false
	return nil
}

// addLocked queues msg. At the limit it drops the oldest RunUpdate first, then the oldest RunSteerResult; never a
// RunFinished (the outbox may then grow past the limit by run_finished messages only). o.mu is held.
func (o *outbox) addLocked(msg any) {
	if len(o.msgs) >= o.limit {
		if i := o.oldestLocked(func(m any) bool { _, ok := m.(protocol.RunUpdate); return ok }); i >= 0 {
			o.msgs = append(o.msgs[:i], o.msgs[i+1:]...)
		} else if i := o.oldestLocked(func(m any) bool { _, ok := m.(protocol.RunSteerResult); return ok }); i >= 0 {
			o.msgs = append(o.msgs[:i], o.msgs[i+1:]...)
		}
	}
	o.msgs = append(o.msgs, msg)
}

// oldestLocked is the index of the first queued message that matches, or -1.
func (o *outbox) oldestLocked(match func(any) bool) int {
	for i, m := range o.msgs {
		if match(m) {
			return i
		}
	}
	return -1
}
