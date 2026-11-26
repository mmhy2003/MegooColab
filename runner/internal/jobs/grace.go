package jobs

import (
	"slices"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// reconnectCapWhileHolding is the longest reconnect delay while runs are held, so a 60 s grace period is not missed.
const reconnectCapWhileHolding = 5 * time.Second

// disconnected is conn.Client.OnDisconnect. Without a grace period every run stops, as before. With one, the runs
// keep going and their messages wait in the outbox; the timer stops them if no welcome comes in time. It is called
// again for each failed reconnect: a running timer is left alone.
func (m *Manager) disconnected(lost int) {
	m.mu.Lock()
	grace, timing := m.grace, m.holdTimer != nil
	if grace <= 0 {
		m.mu.Unlock()
		m.out.drop()
		m.StopAllUpTo(lost)
		return
	}
	m.out.hold()
	if !timing {
		m.holdID++
		id := m.holdID
		m.holdTimer = time.AfterFunc(grace, func() { m.graceExpired(id, lost) })
	}
	m.mu.Unlock()
}

// graceExpired: the server has given the runs up; stop them as a disconnect without a grace period does.
// m.ended is not moved at the disconnect itself, so a run_start still queued from the lost connection starts and
// is listed in runs_held; it moves here.
func (m *Manager) graceExpired(id, lost int) {
	m.mu.Lock()
	if id != m.holdID || m.holdTimer == nil {
		m.mu.Unlock()
		return
	}
	m.holdTimer = nil
	m.mu.Unlock()
	m.out.drop()
	m.out.hold() // until the next runs_held: the runs are stale and send nothing anyway
	m.StopAllUpTo(lost)
}

// resume handles a welcome on connection conn (0: unknown, nothing to do). It is called after HandleWelcome.
func (m *Manager) resume(conn int, w protocol.Welcome) {
	m.mu.Lock()
	m.grace = time.Duration(w.GraceSeconds) * m.GraceUnit
	if conn == 0 || (w.GraceSeconds > 0 && conn <= m.heldSent) {
		m.mu.Unlock()
		return
	}
	stopped := m.stopHoldLocked()
	if w.GraceSeconds <= 0 {
		m.mu.Unlock()
		if stopped || m.out.holds() { // an older server: no grace any more
			m.out.drop()
			m.StopAllUpTo(conn - 1)
		}
		return
	}
	m.heldSent = conn
	m.mu.Unlock()
	if err := m.send(protocol.NewRunsHeld(append(m.heldRuns(), m.out.finishedRuns()...))); err != nil {
		return // this connection died too; its OnDisconnect starts a new timer
	}
	_ = m.out.flush(m.send)
}

// stopHoldLocked stops and clears the grace timer, and reports whether one was running. m.mu is held.
func (m *Manager) stopHoldLocked() bool {
	if m.holdTimer == nil {
		return false
	}
	m.holdTimer.Stop()
	m.holdTimer = nil
	return true
}

// heldRuns are the runs in flight on the current generation, oldest id first (sorted).
func (m *Manager) heldRuns() []string {
	m.mu.Lock()
	defer m.mu.Unlock()
	var ids []string
	for id, r := range m.runs {
		if r.gen == m.gen {
			ids = append(ids, id)
		}
	}
	slices.Sort(ids)
	return ids
}

// ReconnectCap is conn.Client.ReconnectCap: 5 s while runs are held, so a 60 s grace period is not missed.
func (m *Manager) ReconnectCap() time.Duration {
	m.mu.Lock()
	timing := m.holdTimer != nil
	m.mu.Unlock()
	if timing || m.out.holds() {
		return reconnectCapWhileHolding
	}
	return 0
}
