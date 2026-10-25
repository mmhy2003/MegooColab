// Package protocol mirrors backend/app/runner/protocol.py: JSON text frames,
// each {"type": ..., ...}. Field names must match the pydantic models exactly;
// the server rejects unknown fields on runner->server messages.
package protocol

import (
	"encoding/json"
	"fmt"
)

// WebSocket close codes sent by the server.
const (
	CloseProtocolError = 4400
	CloseUnauthorized  = 4401
	CloseIdle          = 4408
	CloseReplaced      = 4409
)

// Message type names.
const (
	TypeHello         = "hello"
	TypeHeartbeat     = "heartbeat"
	TypeAgentStatus   = "agent_status"
	TypeRunUpdate     = "run_update"
	TypeRunFinished   = "run_finished"
	TypeWelcome       = "welcome"
	TypeRunStart      = "run_start"
	TypeRunCancel     = "run_cancel"
	TypeConfigChanged = "config_changed"
)

// AgentAvailability is the server's AgentReport.
type AgentAvailability struct {
	AgentID   string   `json:"agent_id"`
	Available bool     `json:"available"`
	Problems  []string `json:"problems"`
}

// Hello is sent first after connecting.
type Hello struct {
	Type          string              `json:"type"`
	RunnerVersion string              `json:"runner_version"`
	OS            string              `json:"os"`
	Arch          string              `json:"arch"`
	Agents        []AgentAvailability `json:"agents"`
}

// Heartbeat is sent every 15 s.
type Heartbeat struct {
	Type string `json:"type"`
}

// AgentStatus reports a change in one agent's availability.
type AgentStatus struct {
	Type      string   `json:"type"`
	AgentID   string   `json:"agent_id"`
	Available bool     `json:"available"`
	Problems  []string `json:"problems"`
}

// RunUpdate carries one metadata-only progress event.
type RunUpdate struct {
	Type  string         `json:"type"`
	RunID string         `json:"run_id"`
	Seq   int            `json:"seq"`
	Kind  string         `json:"kind"`
	Data  map[string]any `json:"data"`
}

// RunFinished ends a run. Outcome is completed, failed or cancelled.
type RunFinished struct {
	Type    string  `json:"type"`
	RunID   string  `json:"run_id"`
	Outcome string  `json:"outcome"`
	Summary string  `json:"summary"`
	Error   *string `json:"error,omitempty"`
}

// WelcomeBinding is a project bound to an agent.
type WelcomeBinding struct {
	ProjectKey string `json:"project_key"`
	LocalPath  string `json:"local_path"`
}

// WelcomeAgent is one of the user's agents.
type WelcomeAgent struct {
	AgentID           string           `json:"agent_id"`
	Name              string           `json:"name"`
	Program           string           `json:"program"`
	MaxConcurrentRuns int              `json:"max_concurrent_runs"`
	Bindings          []WelcomeBinding `json:"bindings"`
}

// Welcome is the server's reply to hello.
type Welcome struct {
	Type   string         `json:"type"`
	UserID string         `json:"user_id"`
	Agents []WelcomeAgent `json:"agents"`
}

// RunTask describes the task a run works on.
type RunTask struct {
	Key           string `json:"key"`
	Title         string `json:"title"`
	DescriptionMD string `json:"description_md"`
	ProjectKey    string `json:"project_key"`
}

// RunStart tells the runner to start a run. Policy is read_only or workspace.
type RunStart struct {
	Type      string  `json:"type"`
	RunID     string  `json:"run_id"`
	AgentID   string  `json:"agent_id"`
	Task      RunTask `json:"task"`
	LocalPath string  `json:"local_path"`
	Policy    string  `json:"policy"`
	Prompt    string  `json:"prompt"`
}

// RunCancel asks the runner to stop a run.
type RunCancel struct {
	Type  string `json:"type"`
	RunID string `json:"run_id"`
}

// ConfigChanged tells the runner its agent configuration changed on the server.
type ConfigChanged struct {
	Type string `json:"type"`
}

// NewHello builds a hello with non-nil lists (the server rejects null).
func NewHello(version, os, arch string, agents []AgentAvailability) Hello {
	out := make([]AgentAvailability, len(agents))
	for i, a := range agents {
		if a.Problems == nil {
			a.Problems = []string{}
		}
		out[i] = a
	}
	return Hello{Type: TypeHello, RunnerVersion: version, OS: os, Arch: arch, Agents: out}
}

// NewHeartbeat builds a heartbeat.
func NewHeartbeat() Heartbeat { return Heartbeat{Type: TypeHeartbeat} }

// NewAgentStatus builds an agent_status with a non-nil problems list.
func NewAgentStatus(agentID string, available bool, problems []string) AgentStatus {
	if problems == nil {
		problems = []string{}
	}
	return AgentStatus{Type: TypeAgentStatus, AgentID: agentID, Available: available, Problems: problems}
}

// Envelope is a received frame: its type plus the full raw JSON.
type Envelope struct {
	Type string
	Raw  json.RawMessage
	// Conn is the number of the connection the frame arrived on (1, 2, ...),
	// set by the connection client; 0 when unknown.
	Conn int
}

// Decode parses a frame's type and keeps the raw bytes for Into.
func Decode(data []byte) (Envelope, error) {
	var head struct {
		Type string `json:"type"`
	}
	if err := json.Unmarshal(data, &head); err != nil {
		return Envelope{}, fmt.Errorf("decode frame: %w", err)
	}
	if head.Type == "" {
		return Envelope{}, fmt.Errorf("decode frame: missing type")
	}
	return Envelope{Type: head.Type, Raw: append(json.RawMessage(nil), data...)}, nil
}

// Into unmarshals the envelope into v (e.g. *RunStart).
func (e Envelope) Into(v any) error { return json.Unmarshal(e.Raw, v) }

// NewRunUpdate builds a run_update whose data is never null (the server
// rejects null).
func NewRunUpdate(runID string, seq int, kind string, data map[string]any) RunUpdate {
	if data == nil {
		data = map[string]any{}
	}
	return RunUpdate{Type: TypeRunUpdate, RunID: runID, Seq: seq, Kind: kind, Data: data}
}
