// Command fakeagent is a scripted ACP agent for tests. The scenario comes from
// $FAKEAGENT_SCENARIO (JSON array of steps, run on session/prompt) and a JSON
// report of what the agent observed is written to $FAKEAGENT_REPORT on exit.
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
	conn  *acp.AgentSideConnection
	steps []Step

	mu         sync.Mutex
	report     Report
	sessionID  acp.SessionId
	cancelTurn context.CancelFunc
	cancelled  bool
	toolSeq    int
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
	return acp.InitializeResponse{ProtocolVersion: acp.ProtocolVersionNumber}, nil
}

func (a *fakeAgent) NewSession(_ context.Context, p acp.NewSessionRequest) (acp.NewSessionResponse, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.sessionID = "fake-session-1"
	a.report.Cwd = p.Cwd
	if p.Meta != nil {
		a.report.Meta, _ = json.Marshal(p.Meta)
	}
	desc := func(s string) *string { return &s }
	return acp.NewSessionResponse{
		SessionId: a.sessionID,
		Modes: &acp.SessionModeState{
			CurrentModeId: "default",
			AvailableModes: []acp.SessionMode{
				{Id: "default", Name: "Default", Description: desc("Ask before acting")},
				{Id: "plan", Name: "Plan", Description: desc("Plan only")},
				{Id: "read-only", Name: "Read only", Description: desc("No edits")},
				{Id: "auto", Name: "Auto", Description: desc("Act without asking")},
			},
		},
	}, nil
}

func (a *fakeAgent) SetSessionMode(_ context.Context, p acp.SetSessionModeRequest) (acp.SetSessionModeResponse, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.report.ModesSet = append(a.report.ModesSet, string(p.ModeId))
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

	stop := acp.StopReasonEndTurn
	for _, st := range a.steps {
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
		out, err := exec.CommandContext(ctx, "git", "-c", "user.name=fakeagent", "-c", "user.email=fakeagent@localhost", "commit", "--allow-empty", "-q", "-m", st.Commit.Message).CombinedOutput()
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
	path := os.Getenv("FAKEAGENT_REPORT")
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
func (a *fakeAgent) ResumeSession(context.Context, acp.ResumeSessionRequest) (acp.ResumeSessionResponse, error) {
	return acp.ResumeSessionResponse{}, acp.NewMethodNotFound(acp.AgentMethodSessionResume)
}
func (a *fakeAgent) SetSessionConfigOption(context.Context, acp.SetSessionConfigOptionRequest) (acp.SetSessionConfigOptionResponse, error) {
	return acp.SetSessionConfigOptionResponse{}, acp.NewMethodNotFound(acp.AgentMethodSessionSetConfigOption)
}

func main() {
	steps, err := loadScenario()
	if err != nil {
		fmt.Fprintln(os.Stderr, "fakeagent:", err)
		os.Exit(2)
	}
	a := &fakeAgent{steps: steps}
	conn := acp.NewAgentSideConnection(a, os.Stdout, os.Stdin)
	a.conn = conn
	<-conn.Done()
	a.flush()
}
