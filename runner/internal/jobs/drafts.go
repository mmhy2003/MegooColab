package jobs

import (
	"context"
	"strings"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/drafts"
	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// sweepEvery is how often the runner looks for draft folders whose draft_done it missed.
const sweepEvery = 24 * time.Hour

// draftKey is the task key the server gives a draft's runs (KBD- and the draft id's first 12 hex digits).
func draftKey(draftID string) string {
	hex := strings.ReplaceAll(draftID, "-", "")
	if len(hex) > 12 {
		hex = hex[:12]
	}
	return "KBD-" + hex
}

// handleDraftDone removes a saved or discarded draft's folder, once its last run (just cancelled, maybe) is gone.
func (m *Manager) handleDraftDone(d protocol.DraftDone) {
	key := draftKey(d.DraftID)
	m.mu.Lock()
	var running []*run
	for _, r := range m.runs {
		if r.agent == d.AgentID && r.task == key {
			running = append(running, r)
		}
	}
	m.mu.Unlock()
	go func() {
		deadline := time.NewTimer(m.CancelGrace + reapWait)
		defer deadline.Stop()
		for _, r := range running {
			select {
			case <-r.done:
			case <-deadline.C:
				return // still running: the sweep removes the folder later
			}
		}
		_ = drafts.Remove(m.cacheRoot, d.AgentID, d.DraftID) // what is left, the sweep removes later
	}()
}

// sweepDrafts removes draft folders unused for drafts.SweepAge, now and then every sweepEvery until ctx ends.
func (m *Manager) sweepDrafts(ctx context.Context) {
	ticker := time.NewTicker(sweepEvery)
	defer ticker.Stop()
	for {
		drafts.Sweep(m.cacheRoot, drafts.SweepAge, time.Now())
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
