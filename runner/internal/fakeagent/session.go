package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
)

// histMsg is one stored message chunk of a session ("user" or "agent").
type histMsg struct {
	Role string `json:"role"`
	Text string `json:"text"`
}

var safeSessionID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)

// sessionPath is where a session's history lives, or "" when
// FAKEAGENT_SESSIONS_DIR is unset.
func sessionPath(id string) string {
	dir := os.Getenv("FAKEAGENT_SESSIONS_DIR")
	if dir == "" || !safeSessionID.MatchString(id) {
		return ""
	}
	return filepath.Join(dir, id+".json")
}

// newSessionID is fake-session-1 without a sessions dir; with one, the next free number.
func newSessionID() string {
	dir := os.Getenv("FAKEAGENT_SESSIONS_DIR")
	if dir == "" {
		return "fake-session-1"
	}
	for n := 1; ; n++ {
		id := fmt.Sprintf("fake-session-%d", n)
		if _, err := os.Stat(sessionPath(id)); os.IsNotExist(err) {
			return id
		}
	}
}

func loadHistory(id string) ([]histMsg, error) {
	p := sessionPath(id)
	if p == "" {
		return nil, fmt.Errorf("session %q not found", id)
	}
	b, err := os.ReadFile(p)
	if err != nil {
		return nil, fmt.Errorf("session %q not found", id)
	}
	var h []histMsg
	if err := json.Unmarshal(b, &h); err != nil {
		return nil, err
	}
	return h, nil
}

func saveHistory(id string, h []histMsg) {
	p := sessionPath(id)
	if p == "" {
		return
	}
	if h == nil {
		h = []histMsg{}
	}
	b, _ := json.Marshal(h)
	_ = os.MkdirAll(filepath.Dir(p), 0o755)
	_ = os.WriteFile(p, b, 0o644)
}
