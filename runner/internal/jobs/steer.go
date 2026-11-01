package jobs

import (
	"context"
	"encoding/json"
	"sync"
	"time"

	"github.com/coder/acp-go-sdk"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// steeringMethod is the ACP extension that hands a message into the running
// turn (claude-agent-acp and codex-acp both implement it).
const steeringMethod = "_session/steering"

// steerTimeout bounds one steering call.
const steerTimeout = 30 * time.Second

type turnState int

const (
	turnPending turnState = iota // the session is still being set up: steers are held
	turnLive                     // session/prompt is running: steers are handed in, one at a time
	turnOver                     // the turn ended: steers go back to the server for the next run
)

// steering is a run's queue of steers. Guarded by its own mutex: delivery
// waits on the adapter, and must not hold up the run's other state.
type steering struct {
	mu        sync.Mutex
	turn      turnState
	queue     []protocol.RunSteer
	ac        *acp.ClientSideConnection
	session   acp.SessionId
	supported bool          // the adapter announced _meta.steering.supported
	busy      chan struct{} // set while a goroutine delivers; closed when it stops
	stray     bool          // a steer started a turn of its own (the run's turn had just ended)
}

// steeringSupported reads the adapter's initialize _meta.steering.supported.
func steeringSupported(meta map[string]any) bool {
	s, ok := meta["steering"].(map[string]any)
	return ok && s["supported"] == true
}

// HandleRunSteer queues a person's message for a running run. A run this
// runner does not have gets not_running at once.
func (m *Manager) HandleRunSteer(s protocol.RunSteer) {
	m.mu.Lock()
	r := m.runs[s.RunID]
	m.mu.Unlock()
	if r == nil || r.stale() {
		_ = m.send(protocol.NewRunSteerResult(s.RunID, s.MessageID, protocol.SteerNotRunning, ""))
		return
	}
	r.queueSteer(s)
}

func (r *run) answerSteer(s protocol.RunSteer, outcome, errMsg string) {
	if r.stale() {
		return
	}
	_ = r.m.send(protocol.NewRunSteerResult(r.id, s.MessageID, outcome, truncate(errMsg, 200)))
}

func (r *run) queueSteer(s protocol.RunSteer) {
	st := &r.steer
	st.mu.Lock()
	switch {
	case st.turn == turnOver:
		st.mu.Unlock()
		r.answerSteer(s, protocol.SteerNotRunning, "")
		return
	case st.turn == turnLive && !st.supported:
		st.mu.Unlock()
		r.answerSteer(s, protocol.SteerUnsupported, "")
		return
	}
	st.queue = append(st.queue, s)
	start := st.turn == turnLive && st.busy == nil
	if start {
		st.busy = make(chan struct{})
	}
	st.mu.Unlock()
	if start {
		go r.deliverSteers()
	}
}

// beginTurn is called right before session/prompt: held steers go in now.
func (r *run) beginTurn(ac *acp.ClientSideConnection, session acp.SessionId, supported bool) {
	st := &r.steer
	st.mu.Lock()
	st.turn, st.ac, st.session, st.supported = turnLive, ac, session, supported
	var refused []protocol.RunSteer
	if !supported {
		refused, st.queue = st.queue, nil
	}
	start := len(st.queue) > 0 && st.busy == nil
	if start {
		st.busy = make(chan struct{})
	}
	st.mu.Unlock()
	for _, s := range refused {
		r.answerSteer(s, protocol.SteerUnsupported, "")
	}
	if start {
		go r.deliverSteers()
	}
}

// deliverSteers hands the queued steers in, strictly one at a time, in order.
func (r *run) deliverSteers() {
	st := &r.steer
	for {
		st.mu.Lock()
		if len(st.queue) == 0 || st.turn != turnLive {
			left := st.queue
			st.queue = nil
			close(st.busy)
			st.busy = nil
			st.mu.Unlock()
			for _, s := range left {
				r.answerSteer(s, protocol.SteerNotRunning, "")
			}
			return
		}
		s := st.queue[0]
		st.queue = st.queue[1:]
		ac, session := st.ac, st.session
		st.mu.Unlock()

		outcome, errMsg, stray := steerTurn(r.ctx, ac, session, s.Text)
		if stray {
			st.mu.Lock()
			st.stray = true
			st.mu.Unlock()
		}
		r.answerSteer(s, outcome, errMsg)
	}
}

// endTurn is called once session/prompt has returned (and again when the run
// ends, for a run that never reached its turn). Whatever is still queued goes
// back to the server; a delivery in flight is waited for. It reports whether a
// steer started a turn of its own, which the caller cancels.
func (r *run) endTurn() (stray bool) {
	st := &r.steer
	st.mu.Lock()
	st.turn = turnOver
	left := st.queue
	st.queue = nil
	busy := st.busy
	st.mu.Unlock()
	for _, s := range left {
		r.answerSteer(s, protocol.SteerNotRunning, "")
	}
	if busy != nil {
		<-busy
	}
	st.mu.Lock()
	defer st.mu.Unlock()
	stray, st.stray = st.stray, false
	return stray
}

// steerTurn makes one _session/steering call. promptRequired (no running turn)
// and startedNewTurn (Codex, when the turn ended under the steer) both mean the
// agent did not get the message in this run.
func steerTurn(ctx context.Context, ac *acp.ClientSideConnection, session acp.SessionId, text string) (outcome, errMsg string, stray bool) {
	cctx, cancel := context.WithTimeout(ctx, steerTimeout)
	defer cancel()
	raw, err := ac.CallExtension(cctx, steeringMethod, map[string]any{
		"sessionId": session,
		"prompt":    []acp.ContentBlock{acp.TextBlock(text)},
		"_meta":     map[string]any{"steering": map[string]any{"idleBehavior": "promptRequired"}},
	})
	if err != nil {
		return protocol.SteerFailed, err.Error(), false
	}
	var resp struct {
		Outcome string `json:"outcome"`
	}
	if err := json.Unmarshal(raw, &resp); err != nil {
		return protocol.SteerFailed, "unreadable steering answer", false
	}
	switch resp.Outcome {
	case "injected":
		return protocol.SteerInjected, "", false
	case "promptRequired":
		return protocol.SteerNotRunning, "", false
	case "startedNewTurn":
		return protocol.SteerNotRunning, "", true
	}
	return protocol.SteerFailed, "unknown steering outcome " + resp.Outcome, false
}
