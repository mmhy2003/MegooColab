// Command fakeagent is a scripted ACP agent for tests. The scenario comes from
// $FAKEAGENT_SCENARIO (JSON array of steps, run on session/prompt) and a JSON
// report of what the agent observed is written to $FAKEAGENT_REPORT on exit
// (or, with $FAKEAGENT_REPORT_DIR, to a file of its own in that directory).
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/coder/acp-go-sdk"
)

type fakeAgent struct {
	conn       *acp.AgentSideConnection
	steps      []Step
	reportPath string // where the report goes; "" for nowhere

	mu         sync.Mutex
	report     Report
	sessionID  acp.SessionId
	cancelTurn context.CancelFunc
	cancelled  bool
	toolSeq    int
	history    []histMsg
	mcp        []acp.McpServer
	mode       string   // the session mode set by the client ("default" until then)
	model      string   // the session's model, with $FAKEAGENT_MODELS ("default" until set)
	effort     string   // the model's effort, with $FAKEAGENT_EFFORTS ("default" until set, and on a model change)
	allowed    []string // Claude Code allowedTools from the session _meta
}

var _ acp.Agent = (*fakeAgent)(nil)

func (a *fakeAgent) SetAgentConnection(c *acp.AgentSideConnection) { a.conn = c }

func (a *fakeAgent) Initialize(_ context.Context, p acp.InitializeRequest) (acp.InitializeResponse, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	s := InitSummary{
		ProtocolVersion: int(p.ProtocolVersion),
		FSRead:          p.ClientCapabilities.Fs.ReadTextFile,
		FSWrite:         p.ClientCapabilities.Fs.WriteTextFile,
		Terminal:        p.ClientCapabilities.Terminal,
	}
	if p.ClientInfo != nil {
		s.ClientName, s.ClientVersion = p.ClientInfo.Name, p.ClientInfo.Version
	}
	a.report.Initialize = s
	caps := acp.AgentCapabilities{
		McpCapabilities: acp.McpCapabilities{Http: os.Getenv("FAKEAGENT_NO_MCP_HTTP") != "1"},
		LoadSession:     os.Getenv("FAKEAGENT_NO_LOAD") != "1",
	}
	if os.Getenv("FAKEAGENT_RESUME") == "1" && os.Getenv("FAKEAGENT_NO_LOAD") != "1" {
		caps.SessionCapabilities.Resume = &acp.SessionResumeCapabilities{}
	}
	return acp.InitializeResponse{ProtocolVersion: acp.ProtocolVersionNumber, AgentCapabilities: caps}, nil
}

// begin records a session request (new, load or resume) and makes it current.
func (a *fakeAgent) begin(event string, id acp.SessionId, cwd string, meta map[string]any, servers []acp.McpServer, history []histMsg) {
	a.sessionID = id
	a.history = history
	a.mcp = servers
	a.mode = "default"
	a.model = "default"
	a.effort = "default"
	a.allowed = allowedTools(meta)
	a.report.Cwd = cwd
	if meta != nil {
		a.report.Meta, _ = json.Marshal(meta)
	}
	a.report.SessionEvents = append(a.report.SessionEvents, event+":"+string(id))
	a.report.McpServers, _ = json.Marshal(servers)
	if os.Getenv("FAKEAGENT_ECHO_MCP") == "1" {
		fmt.Fprintf(os.Stderr, "fakeagent: mcpServers: %s\n", a.report.McpServers)
	}
}

func fakeModes() *acp.SessionModeState {
	desc := func(s string) *string { return &s }
	return &acp.SessionModeState{
		CurrentModeId: "default",
		AvailableModes: []acp.SessionMode{
			{Id: "default", Name: "Default", Description: desc("Ask before acting")},
			{Id: "plan", Name: "Plan", Description: desc("Plan only")},
			{Id: "read-only", Name: "Read only", Description: desc("No edits")},
			{Id: "workspace-write", Name: "Workspace access", Description: desc("Edit workspace files")},
		},
	}
}

func (a *fakeAgent) NewSession(_ context.Context, p acp.NewSessionRequest) (acp.NewSessionResponse, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	id := acp.SessionId(newSessionID())
	a.begin("new", id, p.Cwd, p.Meta, p.McpServers, nil)
	saveHistory(string(id), nil)
	return acp.NewSessionResponse{SessionId: id, Modes: fakeModes(), ConfigOptions: a.configOptions()}, nil
}

// LoadSession replays the stored history as session/update before returning,
// like a real agent does.
func (a *fakeAgent) LoadSession(ctx context.Context, p acp.LoadSessionRequest) (acp.LoadSessionResponse, error) {
	h, err := loadHistory(string(p.SessionId))
	if err != nil {
		return acp.LoadSessionResponse{}, err
	}
	a.mu.Lock()
	a.begin("load", p.SessionId, p.Cwd, p.Meta, p.McpServers, h)
	a.mu.Unlock()
	for _, m := range h {
		u := acp.UpdateAgentMessageText(m.Text)
		if m.Role == "user" {
			u = acp.UpdateUserMessageText(m.Text)
		}
		if err := a.update(ctx, p.SessionId, u); err != nil {
			return acp.LoadSessionResponse{}, err
		}
		a.mu.Lock()
		a.report.Replayed++
		a.mu.Unlock()
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	return acp.LoadSessionResponse{Modes: fakeModes(), ConfigOptions: a.configOptions()}, nil
}

// ResumeSession continues a stored session without replaying it.
func (a *fakeAgent) ResumeSession(_ context.Context, p acp.ResumeSessionRequest) (acp.ResumeSessionResponse, error) {
	h, err := loadHistory(string(p.SessionId))
	if err != nil {
		return acp.ResumeSessionResponse{}, err
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	a.begin("resume", p.SessionId, p.Cwd, p.Meta, p.McpServers, h)
	return acp.ResumeSessionResponse{Modes: fakeModes(), ConfigOptions: a.configOptions()}, nil
}

func (a *fakeAgent) SetSessionMode(_ context.Context, p acp.SetSessionModeRequest) (acp.SetSessionModeResponse, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.report.ModesSet = append(a.report.ModesSet, string(p.ModeId))
	a.mode = string(p.ModeId)
	return acp.SetSessionModeResponse{}, nil
}

func (a *fakeAgent) Cancel(_ context.Context, _ acp.CancelNotification) error {
	a.mu.Lock()
	a.cancelled = true
	a.report.Cancelled = true
	// FAKEAGENT_IGNORE_CANCEL=1: keep working, like a stuck adapter.
	if a.cancelTurn != nil && os.Getenv("FAKEAGENT_IGNORE_CANCEL") != "1" {
		a.cancelTurn()
	}
	a.mu.Unlock()
	a.flush() // so tests can see the cancel even if the process is killed afterwards
	return nil
}

func (a *fakeAgent) Prompt(_ context.Context, p acp.PromptRequest) (acp.PromptResponse, error) {
	ctx, cancel := context.WithCancel(context.Background())
	a.mu.Lock()
	a.cancelTurn = cancel
	a.mu.Unlock()
	defer cancel()

	var text strings.Builder
	for _, b := range p.Prompt {
		if b.Text != nil {
			text.WriteString(b.Text.Text)
		}
	}
	a.mu.Lock()
	if len(a.report.Prompts) == 0 {
		a.report.PromptModel, a.report.PromptEffort = a.model, a.effort
	}
	a.report.Prompts = append(a.report.Prompts, text.String())
	a.history = append(a.history, histMsg{Role: "user", Text: text.String()})
	a.mu.Unlock()
	defer a.saveCurrent()

	stop := acp.StopReasonEndTurn
	for _, st := range expand(a.steps, text.String()) {
		if ctx.Err() != nil {
			stop = acp.StopReasonCancelled
			break
		}
		if st.Stop != nil {
			stop = acp.StopReason(*st.Stop)
			break
		}
		if err := a.run(ctx, p.SessionId, st); err != nil {
			if ctx.Err() != nil {
				stop = acp.StopReasonCancelled
				break
			}
			a.flush()
			return acp.PromptResponse{}, err
		}
	}
	if ctx.Err() != nil {
		stop = acp.StopReasonCancelled
	}
	a.flush()
	return acp.PromptResponse{StopReason: stop}, nil
}

func (a *fakeAgent) saveCurrent() {
	a.mu.Lock()
	defer a.mu.Unlock()
	saveHistory(string(a.sessionID), a.history)
}

func (a *fakeAgent) record(r StepResult) {
	a.mu.Lock()
	a.report.Steps = append(a.report.Steps, r)
	a.mu.Unlock()
}

func (a *fakeAgent) update(ctx context.Context, sid acp.SessionId, u acp.SessionUpdate) error {
	return a.conn.SessionUpdate(ctx, acp.SessionNotification{SessionId: sid, Update: u})
}

func (a *fakeAgent) run(ctx context.Context, sid acp.SessionId, st Step) error {
	res := StepResult{Type: st.typeName()}
	switch {
	case st.Say != nil:
		if err := a.update(ctx, sid, acp.UpdateAgentMessageText(*st.Say)); err != nil {
			return err
		}
		a.mu.Lock()
		a.history = append(a.history, histMsg{Role: "agent", Text: *st.Say})
		a.mu.Unlock()
	case st.Plan != nil:
		entries := make([]acp.PlanEntry, 0, len(st.Plan))
		for _, e := range st.Plan {
			if len(e) != 2 {
				return fmt.Errorf("plan entry needs [title, status]: %v", e)
			}
			entries = append(entries, acp.PlanEntry{
				Content:  e[0],
				Status:   acp.PlanEntryStatus(e[1]),
				Priority: acp.PlanEntryPriorityMedium,
			})
		}
		if err := a.update(ctx, sid, acp.UpdatePlan(entries...)); err != nil {
			return err
		}
	case st.Tool != nil:
		var locs []acp.ToolCallLocation
		input := map[string]any{}
		if st.Tool.Path != "" {
			locs = []acp.ToolCallLocation{{Path: st.Tool.Path}}
			input["path"] = st.Tool.Path
		}
		out, err := a.permissioned(ctx, sid, acp.ToolKind(st.Tool.Kind), st.Tool.Title, locs, input)
		if err != nil {
			return err
		}
		res.Outcome = out
	case st.Exec != nil:
		out, err := a.permissioned(ctx, sid, acp.ToolKindExecute, st.Exec.Command, nil, map[string]any{"command": st.Exec.Command})
		if err != nil {
			return err
		}
		res.Outcome = out
	case st.Write != nil:
		_, err := a.conn.WriteTextFile(ctx, acp.WriteTextFileRequest{SessionId: sid, Path: st.Write.Path, Content: st.Write.Content})
		ok := err == nil
		res.OK = &ok
		if err != nil {
			if ctx.Err() != nil {
				return err
			}
			res.Error = err.Error()
		}
	case st.Read != nil:
		r, err := a.conn.ReadTextFile(ctx, acp.ReadTextFileRequest{SessionId: sid, Path: st.Read.Path})
		ok := err == nil
		res.OK = &ok
		if err != nil {
			if ctx.Err() != nil {
				return err
			}
			res.Error = err.Error()
		} else {
			n := len(r.Content)
			res.Length = &n
		}
	case st.DirectWrite != nil:
		// Deliberately bypasses the client: lets tests prove checks inspect the disk.
		err := os.WriteFile(st.DirectWrite.Path, []byte(st.DirectWrite.Content), 0o644)
		ok := err == nil
		res.OK = &ok
		if err != nil {
			res.Error = err.Error()
		}
	case st.Commit != nil:
		var out []byte
		var err error
		if st.Commit.All {
			out, err = exec.CommandContext(ctx, "git", "add", "-A").CombinedOutput()
		}
		if err == nil {
			out, err = exec.CommandContext(ctx, "git", "-c", "user.name=fakeagent", "-c", "user.email=fakeagent@localhost", "commit", "--allow-empty", "-q", "-m", st.Commit.Message).CombinedOutput()
		}
		ok := err == nil
		res.OK = &ok
		if err != nil {
			res.Error = strings.TrimSpace(string(out))
		}
	case st.ReportFile != nil:
		b, err := os.ReadFile(st.ReportFile.Path)
		exists := err == nil
		res.Exists = &exists
		res.Content = string(b)
	case st.McpCall != nil:
		a.mu.Lock()
		srv := firstHTTPMcp(a.mcp)
		a.mu.Unlock()
		res.Tool = st.McpCall.Tool
		if srv != nil {
			stopped, err := a.mcpGate(ctx, sid, srv.Name, st.McpCall.Tool, st.McpCall.Args)
			if err != nil {
				return err
			}
			if stopped != "" {
				ok := false
				res.OK, res.Outcome = &ok, stopped
				res.Error = map[string]string{"blocked": "plan mode: MCP tools are not available"}[stopped]
				if res.Error == "" {
					res.Error = "permission " + stopped
				}
				break
			}
			if !a.preApproved(srv.Name, st.McpCall.Tool) {
				res.Outcome = "allowed"
			}
		}
		out, ok, err := callMcpTool(ctx, srv, st.McpCall.Tool, st.McpCall.Args)
		if err != nil && ctx.Err() != nil {
			return err
		}
		res.OK, res.Result = &ok, out
		if err != nil {
			res.Error = err.Error()
		}
	case st.SleepMS != nil:
		select {
		case <-time.After(time.Duration(*st.SleepMS) * time.Millisecond):
		case <-ctx.Done():
			return ctx.Err()
		}
	default:
		return fmt.Errorf("unknown scenario step")
	}
	a.record(res)
	return nil
}

// allowedTools reads Claude Code's options.allowedTools from a session's _meta.
func allowedTools(meta map[string]any) []string {
	cc, _ := meta["claudeCode"].(map[string]any)
	opts, _ := cc["options"].(map[string]any)
	list, _ := opts["allowedTools"].([]any)
	out := make([]string, 0, len(list))
	for _, v := range list {
		if s, ok := v.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

// preApproved: an allowedTools rule names the MCP server ("mcp__<server>") or the tool ("mcp__<server>__<tool>").
func (a *fakeAgent) preApproved(server, tool string) bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	for _, rule := range a.allowed {
		if rule == "mcp__"+server || rule == "mcp__"+server+"__"+tool {
			return true
		}
	}
	return false
}

// mcpGate gates an MCP tool call the way Claude Code (which the fake agent stands in for) does: refused in plan
// mode, run at once when allowedTools pre-approve it, otherwise asked for as a tool of kind "other" titled with
// the tool's full name. It returns "" to go ahead, else what stopped the call (blocked, rejected, cancelled).
func (a *fakeAgent) mcpGate(ctx context.Context, sid acp.SessionId, server, tool string, args map[string]any) (string, error) {
	a.mu.Lock()
	plan := a.mode == "plan"
	a.mu.Unlock()
	if plan {
		return "blocked", nil
	}
	if a.preApproved(server, tool) {
		return "", nil
	}
	input := map[string]any{}
	for k, v := range args {
		input[k] = v
	}
	out, err := a.permissioned(ctx, sid, acp.ToolKindOther, "mcp__"+server+"__"+tool, nil, input)
	if err != nil || out == "allowed" {
		return "", err
	}
	return out, nil
}

// permissioned sends tool_call(pending), asks for permission, records the
// outcome and sends tool_call_update completed (allowed) or failed (rejected).
func (a *fakeAgent) permissioned(ctx context.Context, sid acp.SessionId, kind acp.ToolKind, title string, locs []acp.ToolCallLocation, input map[string]any) (string, error) {
	a.mu.Lock()
	a.toolSeq++
	id := acp.ToolCallId(fmt.Sprintf("call_%d", a.toolSeq))
	a.mu.Unlock()

	start := []acp.ToolCallStartOpt{acp.WithStartKind(kind), acp.WithStartStatus(acp.ToolCallStatusPending), acp.WithStartRawInput(input)}
	if locs != nil {
		start = append(start, acp.WithStartLocations(locs))
	}
	if err := a.update(ctx, sid, acp.StartToolCall(id, title, start...)); err != nil {
		return "", err
	}
	resp, err := a.conn.RequestPermission(ctx, acp.RequestPermissionRequest{
		SessionId: sid,
		ToolCall: acp.ToolCallUpdate{
			ToolCallId: id,
			Title:      acp.Ptr(title),
			Kind:       acp.Ptr(kind),
			Status:     acp.Ptr(acp.ToolCallStatusPending),
			Locations:  locs,
			RawInput:   input,
		},
		Options: []acp.PermissionOption{
			{Kind: acp.PermissionOptionKindAllowOnce, Name: "Allow", OptionId: "allow"},
			{Kind: acp.PermissionOptionKindRejectOnce, Name: "Reject", OptionId: "reject"},
		},
	})
	if err != nil {
		return "", err
	}
	outcome, status := "cancelled", acp.ToolCallStatusFailed
	if sel := resp.Outcome.Selected; sel != nil {
		if sel.OptionId == "allow" {
			outcome, status = "allowed", acp.ToolCallStatusCompleted
		} else {
			outcome = "rejected"
		}
	}
	if err := a.update(ctx, sid, acp.UpdateToolCall(id, acp.WithUpdateStatus(status))); err != nil {
		return "", err
	}
	return outcome, nil
}

// flush writes the report atomically (temp file + rename).
func (a *fakeAgent) flush() {
	path := a.reportPath
	if path == "" {
		return
	}
	a.mu.Lock()
	r := a.report
	if r.Steps == nil {
		r.Steps = []StepResult{}
	}
	if r.ModesSet == nil {
		r.ModesSet = []string{}
	}
	b, err := json.MarshalIndent(r, "", "  ")
	a.mu.Unlock()
	if err != nil {
		fmt.Fprintln(os.Stderr, "fakeagent: report:", err)
		return
	}
	_ = os.MkdirAll(filepath.Dir(path), 0o755)
	tmp, err := os.CreateTemp(filepath.Dir(path), ".fakeagent-report-*")
	if err != nil {
		fmt.Fprintln(os.Stderr, "fakeagent: report:", err)
		return
	}
	_, werr := tmp.Write(b)
	cerr := tmp.Close()
	if werr != nil || cerr != nil || os.Rename(tmp.Name(), path) != nil {
		_ = os.Remove(tmp.Name())
		fmt.Fprintln(os.Stderr, "fakeagent: report: write failed")
	}
}

// reportFile is $FAKEAGENT_REPORT, else a file of this process's own in
// $FAKEAGENT_REPORT_DIR (one agent process per run, so every run keeps its
// report), else "".
func reportFile() string {
	if p := os.Getenv("FAKEAGENT_REPORT"); p != "" {
		return p
	}
	if dir := os.Getenv("FAKEAGENT_REPORT_DIR"); dir != "" {
		return filepath.Join(dir, fmt.Sprintf("report-%d-%d.json", time.Now().UnixNano(), os.Getpid()))
	}
	return ""
}

// Unused protocol surface.

func (a *fakeAgent) Authenticate(context.Context, acp.AuthenticateRequest) (acp.AuthenticateResponse, error) {
	return acp.AuthenticateResponse{}, nil
}
func (a *fakeAgent) Logout(context.Context, acp.LogoutRequest) (acp.LogoutResponse, error) {
	return acp.LogoutResponse{}, acp.NewMethodNotFound(acp.AgentMethodLogout)
}
func (a *fakeAgent) CloseSession(context.Context, acp.CloseSessionRequest) (acp.CloseSessionResponse, error) {
	return acp.CloseSessionResponse{}, acp.NewMethodNotFound(acp.AgentMethodSessionClose)
}
func (a *fakeAgent) ListSessions(context.Context, acp.ListSessionsRequest) (acp.ListSessionsResponse, error) {
	return acp.ListSessionsResponse{}, acp.NewMethodNotFound(acp.AgentMethodSessionList)
}

// SetSessionConfigOption sets the model, with $FAKEAGENT_MODELS: a value the
// agent offers, or one of their names in any case (as real adapters resolve
// aliases); anything else is refused.
func (a *fakeAgent) SetSessionConfigOption(_ context.Context, p acp.SetSessionConfigOptionRequest) (acp.SetSessionConfigOptionResponse, error) {
	models := fakeModels()
	if models == nil || p.ValueId == nil {
		return acp.SetSessionConfigOptionResponse{}, acp.NewMethodNotFound(acp.AgentMethodSessionSetConfigOption)
	}
	want := string(p.ValueId.Value)
	if p.ValueId.ConfigId == "effort" {
		a.mu.Lock()
		defer a.mu.Unlock()
		for _, e := range fakeEfforts(a.model) {
			if string(e.Value) == want {
				a.effort = want
				a.report.EffortsSet = append(a.report.EffortsSet, want)
				return acp.SetSessionConfigOptionResponse{ConfigOptions: a.configOptions()}, nil
			}
		}
		return acp.SetSessionConfigOptionResponse{}, acp.NewInvalidParams(map[string]any{"error": "unknown effort " + want})
	}
	if p.ValueId.ConfigId != "model" {
		return acp.SetSessionConfigOptionResponse{}, acp.NewMethodNotFound(acp.AgentMethodSessionSetConfigOption)
	}
	for _, m := range models {
		if string(m.Value) == want || strings.EqualFold(m.Name, want) {
			a.mu.Lock()
			defer a.mu.Unlock()
			a.model, a.effort = string(m.Value), "default"
			a.report.ModelsSet = append(a.report.ModelsSet, a.model)
			return acp.SetSessionConfigOptionResponse{ConfigOptions: a.configOptions()}, nil
		}
	}
	if os.Getenv("FAKEAGENT_MODELS_ANY") == "1" { // as Codex does: an unknown name is a model of its own
		a.mu.Lock()
		defer a.mu.Unlock()
		a.model = want
		a.report.ModelsSet = append(a.report.ModelsSet, want)
		return acp.SetSessionConfigOptionResponse{ConfigOptions: a.configOptions()}, nil
	}
	return acp.SetSessionConfigOptionResponse{}, acp.NewInvalidParams(map[string]any{"error": "unknown model " + want})
}

// fakeModels is $FAKEAGENT_MODELS ("value=Name,..."), or nil when unset: then
// the agent offers no model choice.
func fakeModels() []acp.SessionConfigSelectOption {
	spec := os.Getenv("FAKEAGENT_MODELS")
	if spec == "" {
		return nil
	}
	var out []acp.SessionConfigSelectOption
	for _, item := range strings.Split(spec, ",") {
		value, name, _ := strings.Cut(item, "=")
		out = append(out, acp.SessionConfigSelectOption{Value: acp.SessionConfigValueId(value), Name: name})
	}
	return out
}

// fakeEfforts are the effort levels of a model, with $FAKEAGENT_EFFORTS
// ("model=low|high;..."), "default" first as real adapters list it; nil: the
// model has no effort setting.
func fakeEfforts(model string) []acp.SessionConfigSelectOption {
	for _, item := range strings.Split(os.Getenv("FAKEAGENT_EFFORTS"), ";") {
		m, levels, ok := strings.Cut(item, "=")
		if !ok || m != model {
			continue
		}
		out := []acp.SessionConfigSelectOption{{Value: "default", Name: "Default"}}
		for _, l := range strings.Split(levels, "|") {
			out = append(out, acp.SessionConfigSelectOption{Value: acp.SessionConfigValueId(l), Name: strings.ToUpper(l[:1]) + l[1:]})
		}
		return out
	}
	return nil
}

// configOptions is the session's model selector, at its current model, and
// that model's effort selector if it has one; mu is held.
func (a *fakeAgent) configOptions() []acp.SessionConfigOption {
	models := fakeModels()
	if models == nil {
		return nil
	}
	cat := acp.SessionConfigOptionCategoryModel
	listed := false
	for _, m := range models {
		listed = listed || string(m.Value) == a.model
	}
	if !listed { // as Codex does: the current model leads the list
		models = append([]acp.SessionConfigSelectOption{{Value: acp.SessionConfigValueId(a.model), Name: a.model}}, models...)
	}
	list := acp.SessionConfigSelectOptionsUngrouped(models)
	out := []acp.SessionConfigOption{{Select: &acp.SessionConfigOptionSelect{
		Id: "model", Name: "Model", Category: &cat, Type: "select", CurrentValue: acp.SessionConfigValueId(a.model),
		Options: acp.SessionConfigSelectOptions{Ungrouped: &list},
	}}}
	if efforts := fakeEfforts(a.model); efforts != nil {
		thought := acp.SessionConfigOptionCategoryThoughtLevel
		levels := acp.SessionConfigSelectOptionsUngrouped(efforts)
		out = append(out, acp.SessionConfigOption{Select: &acp.SessionConfigOptionSelect{
			Id: "effort", Name: "Effort", Category: &thought, Type: "select", CurrentValue: acp.SessionConfigValueId(a.effort),
			Options: acp.SessionConfigSelectOptions{Ungrouped: &levels},
		}})
	}
	return out
}

func main() {
	steps, err := loadScenario()
	if err != nil {
		fmt.Fprintln(os.Stderr, "fakeagent:", err)
		os.Exit(2)
	}
	a := &fakeAgent{steps: steps, reportPath: reportFile()}
	conn := acp.NewAgentSideConnection(a, os.Stdout, os.Stdin)
	a.conn = conn
	<-conn.Done()
	a.flush()
}
