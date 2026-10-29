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
	Capabilities  []string            `json:"capabilities"`
}

// CapabilityWorkflow is advertised in every hello: the runner understands the
// protocol v2 run_start fields and reports git state and session id.
const CapabilityWorkflow = "workflow/1"

// CapabilityBranch is advertised in every hello: the runner starts a task's
// branch from run_start.branch and reports where it started (kind "branch").
const CapabilityBranch = "branch/1"

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

// GitState is the repository state of a run's worktree. Head is nil when the
// repository has no commits yet.
type GitState struct {
	Head   *string `json:"head"`
	Branch *string `json:"branch"`
	Dirty  bool    `json:"dirty"`
}

// RunFinished ends a run. Outcome is completed, failed or cancelled.
// GitBefore is omitted when git could not be read before the run; GitAfter when
// it could not be read after it and there was no GitBefore either (with one, a
// failed read is sent as dirty); SessionID when the agent session never started.
type RunFinished struct {
	Type      string    `json:"type"`
	RunID     string    `json:"run_id"`
	Outcome   string    `json:"outcome"`
	Summary   string    `json:"summary"`
	Error     *string   `json:"error,omitempty"`
	SessionID *string   `json:"session_id,omitempty"`
	GitBefore *GitState `json:"git_before,omitempty"`
	GitAfter  *GitState `json:"git_after,omitempty"`
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

// File is a path (relative, slash-separated) and its text content.
type File struct {
	Path    string `json:"path"`
	Content string `json:"content"`
}

// McpAccess is where and how the agent reaches MegooColab's MCP server.
type McpAccess struct {
	URL   string `json:"url"`
	Token string `json:"token"`
}

// RunBranchRepo is one of the project's repositories and its default branch.
type RunBranchRepo struct {
	URL           string `json:"url"`
	DefaultBranch string `json:"default_branch"`
}

// RunBranch says where a task's branch starts: the task's Branch from (empty:
// the matched repository's default branch), or the start branch the server
// recorded when the branch was first created.
type RunBranch struct {
	BranchFrom   string          `json:"branch_from"`
	StartBranch  string          `json:"start_branch"`
	Repositories []RunBranchRepo `json:"repositories"`
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

	// Protocol v2: only sent for workflow runs.
	Role            string     `json:"role,omitempty"`
	Stage           string     `json:"stage,omitempty"`
	Step            *int       `json:"step,omitempty"`
	ResumeSessionID string     `json:"resume_session_id,omitempty"`
	ResumePrompt    string     `json:"resume_prompt,omitempty"`
	Mcp             *McpAccess `json:"mcp,omitempty"`
	Files           []File     `json:"files,omitempty"`
	RepoFiles       []File     `json:"repo_files,omitempty"`
	CommitMessage   string     `json:"commit_message,omitempty"`

	// Every task run (capability branch/1); nil for answering runs.
	Branch *RunBranch `json:"branch,omitempty"`
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
	return Hello{Type: TypeHello, RunnerVersion: version, OS: os, Arch: arch, Agents: out, Capabilities: []string{CapabilityWorkflow, CapabilityBranch}}
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
