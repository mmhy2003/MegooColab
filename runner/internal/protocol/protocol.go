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
	TypeHello          = "hello"
	TypeHeartbeat      = "heartbeat"
	TypeAgentStatus    = "agent_status"
	TypeRunUpdate      = "run_update"
	TypeRunFinished    = "run_finished"
	TypeWelcome        = "welcome"
	TypeRunStart       = "run_start"
	TypeRunCancel      = "run_cancel"
	TypeDraftDone      = "draft_done"
	TypeConfigChanged  = "config_changed"
	TypeRunSteer       = "run_steer"
	TypeRunSteerResult = "run_steer_result"
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

// CapabilityModel is advertised in every hello: the runner starts a session on
// the agent's chosen model and effort, or fails the run (model_unavailable,
// effort_unavailable) rather than use others, and reports the models the agent
// offers with their effort levels.
const CapabilityModel = "model/1"

// CapabilitySteer is advertised in every hello: the runner takes run_steer, a
// person's message for a running agent, hands it into the running turn (ACP
// _session/steering) and answers with run_steer_result.
const CapabilitySteer = "steer/1"

// CapabilityImages is advertised in every hello: the runner takes run_start.images and run_steer.images,
// downloads each with its token, and shows them to the agent (image blocks in the prompt, or files it may read).
const CapabilityImages = "images/1"

// CapabilityDrafts is advertised in every hello: the runner takes run_start.draft, a Knowledge Base draft's run, works
// in a folder kept for the draft (a detached worktree of the project's repository, or an empty folder), and removes
// it on draft_done.
const CapabilityDrafts = "drafts/1"

// CapabilitySecrets is advertised in every hello: the runner takes run_start.secrets, sets them on the agent's
// process, and blanks their values out of everything it reports.
const CapabilitySecrets = "secrets/1"

// CapabilityCrons is advertised in every hello: the runner takes run_start.cron, a project's scheduled job, and runs it
// in the cron's own worktree, reset to the project's default branch before and after the run.
const CapabilityCrons = "crons/1"

// CapabilityStageModel is advertised in every hello: the runner takes run_start.model_choice, a run's own model and
// effort (its workflow stage's), and puts even a resumed session on them.
const CapabilityStageModel = "stagemodel/1"

// Outcomes of a run_steer.
const (
	SteerInjected    = "injected"    // the agent has it, in its running turn
	SteerNotRunning  = "not_running" // no turn to hand it into: the server gives it to the next run
	SteerUnsupported = "unsupported" // the adapter cannot take messages mid-turn
	SteerFailed      = "failed"
)

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
	// Uncommitted, in a git_after only and only when the run_start asked (report_uncommitted): whether `git status`
	// shows changes nobody committed when the run ends, .megoocolab/ aside. Dirty is broader: anything the run
	// changed, ignored files included. A server that doesn't ask would refuse the field.
	Uncommitted *bool `json:"uncommitted,omitempty"`
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
	// Model is the model its sessions start on, as its owner named it; "" is
	// the program's own default.
	Model string `json:"model,omitempty"`
	// Effort is its thinking effort ("high"); "" is the model's own default.
	Effort string `json:"effort,omitempty"`
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

// RunImage is an image for the agent (capability images/1): the runner downloads it from
// /api/runner/images/{id} with its token.
type RunImage struct {
	ID          string `json:"id"`
	Filename    string `json:"filename"`
	ContentType string `json:"content_type"`
	Size        int64  `json:"size"`
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
	Images          []RunImage `json:"images,omitempty"` // in the order the prompt names them

	// Every task run (capability branch/1); nil for answering runs.
	Branch *RunBranch `json:"branch,omitempty"`

	// Only a Knowledge Base draft's run (capability drafts/1).
	Draft *RunDraft `json:"draft,omitempty"`

	// The agent owner's and the project's secrets (capability secrets/1): never logged or written to disk.
	Secrets []RunSecret `json:"secrets,omitempty"`

	// Only a cron's run (capability crons/1).
	Cron *RunCron `json:"cron,omitempty"`

	// ReportUncommitted asks for git_after.uncommitted. Sent by a server that takes the field; an older one leaves
	// it out and is never sent the field.
	ReportUncommitted bool `json:"report_uncommitted,omitempty"`

	// ModelChoice is the model and effort of this run's workflow stage (capability stagemodel/1), in place of the
	// agent's. nil: the agent's, as before.
	ModelChoice *RunModelChoice `json:"model_choice,omitempty"`
}

// RunModelChoice is the model and effort a run starts on, applied also to a resumed session. Model "" is the
// program's starting model (what a new session starts on); Effort "" is the chosen model's default effort.
type RunModelChoice struct {
	Model  string `json:"model"`
	Effort string `json:"effort"`
}

// RunCron names the cron a run belongs to and the branch its worktree is reset to.
type RunCron struct {
	ID     string `json:"id"`
	Branch string `json:"branch"`
}

// RunSecret is one environment variable for the agent.
type RunSecret struct {
	Name  string `json:"name"`
	Value string `json:"value"`
}

// RunDraft names the Knowledge Base draft a run writes.
type RunDraft struct {
	ID string `json:"id"`
}

// DraftDone tells the runner a draft was saved or discarded: its folder goes.
type DraftDone struct {
	Type    string `json:"type"`
	AgentID string `json:"agent_id"`
	DraftID string `json:"draft_id"`
}

// RunCancel asks the runner to stop a run.
type RunCancel struct {
	Type  string `json:"type"`
	RunID string `json:"run_id"`
}

// RunSteer is a person's message for a running agent.
type RunSteer struct {
	Type      string     `json:"type"`
	RunID     string     `json:"run_id"`
	MessageID string     `json:"message_id"`
	Text      string     `json:"text"`
	Images    []RunImage `json:"images,omitempty"`
}

// RunSteerResult answers a RunSteer with one of the Steer* outcomes.
type RunSteerResult struct {
	Type      string `json:"type"`
	RunID     string `json:"run_id"`
	MessageID string `json:"message_id"`
	Outcome   string `json:"outcome"`
	Error     string `json:"error,omitempty"`
}

// NewRunSteerResult builds a run_steer_result; errMsg is sent only when set.
func NewRunSteerResult(runID, messageID, outcome, errMsg string) RunSteerResult {
	return RunSteerResult{Type: TypeRunSteerResult, RunID: runID, MessageID: messageID, Outcome: outcome, Error: errMsg}
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
	return Hello{Type: TypeHello, RunnerVersion: version, OS: os, Arch: arch, Agents: out, Capabilities: []string{CapabilityWorkflow, CapabilityBranch, CapabilityModel, CapabilitySteer, CapabilityTools, CapabilityOmp, CapabilityImages, CapabilityDrafts, CapabilitySecrets, CapabilityCrons, CapabilityStageModel}}
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
