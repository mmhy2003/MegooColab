package main_test

import (
	"context"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/coder/acp-go-sdk"
	"github.com/mmhy2003/megoocolab/runner/internal/testutil"
)

// testClient is a bare ACP client: it rejects tools titled "deny*", fails
// writes under /forbidden and serves reads from a map.
type testClient struct {
	mu       sync.Mutex
	updates  []acp.SessionUpdate
	writes   map[string]string
	files    map[string]string
	permReqs []acp.RequestPermissionRequest
}

func (c *testClient) ReadTextFile(_ context.Context, p acp.ReadTextFileRequest) (acp.ReadTextFileResponse, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	s, ok := c.files[p.Path]
	if !ok {
		return acp.ReadTextFileResponse{}, os.ErrNotExist
	}
	return acp.ReadTextFileResponse{Content: s}, nil
}

func (c *testClient) WriteTextFile(_ context.Context, p acp.WriteTextFileRequest) (acp.WriteTextFileResponse, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if strings.HasPrefix(p.Path, "/forbidden") {
		return acp.WriteTextFileResponse{}, os.ErrPermission
	}
	c.writes[p.Path] = p.Content
	return acp.WriteTextFileResponse{}, nil
}

func (c *testClient) RequestPermission(_ context.Context, p acp.RequestPermissionRequest) (acp.RequestPermissionResponse, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.permReqs = append(c.permReqs, p)
	want := acp.PermissionOptionKindAllowOnce
	if p.ToolCall.Title != nil && strings.HasPrefix(*p.ToolCall.Title, "deny") {
		want = acp.PermissionOptionKindRejectOnce
	}
	for _, o := range p.Options {
		if o.Kind == want {
			return acp.RequestPermissionResponse{Outcome: acp.RequestPermissionOutcome{
				Selected: &acp.RequestPermissionOutcomeSelected{OptionId: o.OptionId, Outcome: "selected"},
			}}, nil
		}
	}
	return acp.RequestPermissionResponse{}, os.ErrInvalid
}

func (c *testClient) SessionUpdate(_ context.Context, n acp.SessionNotification) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.updates = append(c.updates, n.Update)
	return nil
}

func (c *testClient) CreateTerminal(context.Context, acp.CreateTerminalRequest) (acp.CreateTerminalResponse, error) {
	return acp.CreateTerminalResponse{}, os.ErrInvalid
}
func (c *testClient) KillTerminal(context.Context, acp.KillTerminalRequest) (acp.KillTerminalResponse, error) {
	return acp.KillTerminalResponse{}, os.ErrInvalid
}
func (c *testClient) TerminalOutput(context.Context, acp.TerminalOutputRequest) (acp.TerminalOutputResponse, error) {
	return acp.TerminalOutputResponse{}, os.ErrInvalid
}
func (c *testClient) ReleaseTerminal(context.Context, acp.ReleaseTerminalRequest) (acp.ReleaseTerminalResponse, error) {
	return acp.ReleaseTerminalResponse{}, os.ErrInvalid
}
func (c *testClient) WaitForTerminalExit(context.Context, acp.WaitForTerminalExitRequest) (acp.WaitForTerminalExitResponse, error) {
	return acp.WaitForTerminalExitResponse{}, os.ErrInvalid
}

type session struct {
	cmd    *exec.Cmd
	conn   *acp.ClientSideConnection
	client *testClient
	stdin  io.Closer
	sid    acp.SessionId
	report string
	modes  *acp.SessionModeState
}

func start(t *testing.T, scenario any, meta map[string]any) *session {
	t.Helper()
	return startIn(t, "", scenario, meta)
}

// startIn starts the fake agent with its working directory set to dir ("" for the test's own).
func startIn(t *testing.T, dir string, scenario any, meta map[string]any) *session {
	t.Helper()
	bin := testutil.BuildFakeAgent(t)
	sc, err := json.Marshal(scenario)
	if err != nil {
		t.Fatal(err)
	}
	report := filepath.Join(t.TempDir(), "report.json")
	cmd := exec.Command(bin)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), "FAKEAGENT_SCENARIO="+string(sc), "FAKEAGENT_REPORT="+report)
	cmd.Stderr = os.Stderr
	in, _ := cmd.StdinPipe()
	out, _ := cmd.StdoutPipe()
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = cmd.Process.Kill(); _ = cmd.Wait() })
	cl := &testClient{writes: map[string]string{}, files: map[string]string{"/ws/a.txt": "hello"}}
	conn := acp.NewClientSideConnection(cl, in, out)
	ctx := context.Background()
	if _, err := conn.Initialize(ctx, acp.InitializeRequest{
		ProtocolVersion: acp.ProtocolVersionNumber,
		ClientInfo:      &acp.Implementation{Name: "testclient", Version: "9.9"},
		ClientCapabilities: acp.ClientCapabilities{
			Fs: acp.FileSystemCapabilities{ReadTextFile: true, WriteTextFile: true},
		},
	}); err != nil {
		t.Fatal(err)
	}
	ns, err := conn.NewSession(ctx, acp.NewSessionRequest{Cwd: "/ws", McpServers: []acp.McpServer{}, Meta: meta})
	if err != nil {
		t.Fatal(err)
	}
	return &session{cmd: cmd, conn: conn, client: cl, stdin: in, sid: ns.SessionId, report: report, modes: ns.Modes}
}

// finish closes stdin, waits for exit and returns the parsed report.
func (s *session) finish(t *testing.T) map[string]any {
	t.Helper()
	_ = s.stdin.Close()
	done := make(chan error, 1)
	go func() { done <- s.cmd.Wait() }()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatal("fake agent did not exit")
	}
	b, err := os.ReadFile(s.report)
	if err != nil {
		t.Fatalf("report: %v", err)
	}
	var r map[string]any
	if err := json.Unmarshal(b, &r); err != nil {
		t.Fatal(err)
	}
	return r
}

func TestFakeAgentScenario(t *testing.T) {
	direct := filepath.Join(t.TempDir(), "direct.txt")
	s := start(t, []any{
		map[string]any{"say": "hi there"},
		map[string]any{"plan": [][]string{{"a", "pending"}, {"b", "in_progress"}}},
		map[string]any{"tool": map[string]any{"kind": "edit", "title": "allow edit", "path": "/ws/x.go"}},
		map[string]any{"tool": map[string]any{"kind": "edit", "title": "deny edit", "path": "/ws/y.go"}},
		map[string]any{"exec": map[string]any{"command": "git status"}},
		map[string]any{"write": map[string]any{"path": "/ws/w.txt", "content": "data"}},
		map[string]any{"write": map[string]any{"path": "/forbidden/w.txt", "content": "data"}},
		map[string]any{"read": map[string]any{"path": "/ws/a.txt"}},
		map[string]any{"sleep_ms": 5},
		map[string]any{"direct_write": map[string]any{"path": direct, "content": "sneaky"}},
		map[string]any{"stop": "max_tokens"},
		map[string]any{"say": "never reached"},
	}, map[string]any{"systemPrompt": map[string]any{"append": "be nice"}})

	if s.modes == nil || len(s.modes.AvailableModes) < 4 || s.modes.CurrentModeId != "default" {
		t.Fatalf("modes = %+v", s.modes)
	}
	if _, err := s.conn.SetSessionMode(context.Background(), acp.SetSessionModeRequest{SessionId: s.sid, ModeId: "plan"}); err != nil {
		t.Fatal(err)
	}
	resp, err := s.conn.Prompt(context.Background(), acp.PromptRequest{SessionId: s.sid, Prompt: []acp.ContentBlock{acp.TextBlock("go")}})
	if err != nil {
		t.Fatal(err)
	}
	if resp.StopReason != acp.StopReasonMaxTokens {
		t.Fatalf("stop = %q", resp.StopReason)
	}
	r := s.finish(t)

	if got := r["cwd"]; got != "/ws" {
		t.Errorf("cwd = %v", got)
	}
	meta, _ := r["meta"].(map[string]any)
	sp, _ := meta["systemPrompt"].(map[string]any)
	if sp["append"] != "be nice" {
		t.Errorf("meta = %v", r["meta"])
	}
	init, _ := r["initialize"].(map[string]any)
	if init["client_name"] != "testclient" || init["fs_read"] != true || init["fs_write"] != true {
		t.Errorf("initialize = %v", init)
	}
	if modes, _ := r["modes_set"].([]any); len(modes) != 1 || modes[0] != "plan" {
		t.Errorf("modes_set = %v", r["modes_set"])
	}
	if r["cancelled"] != false {
		t.Errorf("cancelled = %v", r["cancelled"])
	}
	steps, _ := r["steps"].([]any)
	if len(steps) != 10 { // stop ends the turn, the trailing say never runs
		t.Fatalf("steps = %d: %v", len(steps), steps)
	}
	field := func(i int, k string) any { return steps[i].(map[string]any)[k] }
	for i, want := range []string{"say", "plan", "tool", "tool", "exec", "write", "write", "read", "sleep", "direct_write"} {
		if field(i, "type") != want {
			t.Errorf("step %d type = %v want %s", i, field(i, "type"), want)
		}
	}
	if field(2, "outcome") != "allowed" || field(3, "outcome") != "rejected" || field(4, "outcome") != "allowed" {
		t.Errorf("permission outcomes: %v %v %v", field(2, "outcome"), field(3, "outcome"), field(4, "outcome"))
	}
	if field(5, "ok") != true || field(6, "ok") != false || field(6, "error") == "" {
		t.Errorf("write results: %v / %v %v", steps[5], field(6, "ok"), field(6, "error"))
	}
	if field(7, "length") != float64(5) {
		t.Errorf("read length = %v", field(7, "length"))
	}
	if s.client.writes["/ws/w.txt"] != "data" {
		t.Errorf("client writes = %v", s.client.writes)
	}
	if b, err := os.ReadFile(direct); err != nil || string(b) != "sneaky" {
		t.Errorf("direct write: %q %v", b, err)
	}

	// Wire-level checks on what the client saw.
	var kinds []string
	for _, u := range s.client.updates {
		switch {
		case u.AgentMessageChunk != nil:
			kinds = append(kinds, "msg")
		case u.Plan != nil:
			kinds = append(kinds, "plan")
		case u.ToolCall != nil:
			kinds = append(kinds, "tool_call")
		case u.ToolCallUpdate != nil:
			kinds = append(kinds, "tool_call_update:"+string(*u.ToolCallUpdate.Status))
		}
	}
	want := "msg plan tool_call tool_call_update:completed tool_call tool_call_update:failed tool_call tool_call_update:completed"
	if strings.Join(kinds, " ") != want {
		t.Errorf("updates = %s", strings.Join(kinds, " "))
	}
	if n := len(s.client.permReqs); n != 3 {
		t.Fatalf("perm requests = %d", n)
	}
	last := s.client.permReqs[2]
	if last.ToolCall.Kind == nil || *last.ToolCall.Kind != acp.ToolKindExecute || !strings.Contains(*last.ToolCall.Title, "git status") {
		t.Errorf("exec perm = %+v", last.ToolCall)
	}
}

func TestFakeAgentCancel(t *testing.T) {
	s := start(t, []any{map[string]any{"sleep_ms": 60000}, map[string]any{"say": "x"}}, nil)
	type res struct {
		r   acp.PromptResponse
		err error
	}
	ch := make(chan res, 1)
	go func() {
		r, err := s.conn.Prompt(context.Background(), acp.PromptRequest{SessionId: s.sid, Prompt: []acp.ContentBlock{acp.TextBlock("go")}})
		ch <- res{r, err}
	}()
	time.Sleep(300 * time.Millisecond)
	if err := s.conn.Cancel(context.Background(), acp.CancelNotification{SessionId: s.sid}); err != nil {
		t.Fatal(err)
	}
	select {
	case got := <-ch:
		if got.err != nil || got.r.StopReason != acp.StopReasonCancelled {
			t.Fatalf("prompt = %+v %v", got.r, got.err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("prompt did not return after cancel")
	}
	if r := s.finish(t); r["cancelled"] != true {
		t.Errorf("cancelled = %v", r["cancelled"])
	}
}

// FAKEAGENT_REPORT_DIR: every process writes its own report there, so a test
// that drives several runs (one agent process each) keeps every report.
func TestFakeAgentReportDirKeepsOneReportPerProcess(t *testing.T) {
	bin := testutil.BuildFakeAgent(t)
	dir := filepath.Join(t.TempDir(), "reports")
	for i := 0; i < 2; i++ {
		cmd := exec.Command(bin)
		cmd.Env = append(os.Environ(), "FAKEAGENT_REPORT_DIR="+dir)
		cmd.Stdin = strings.NewReader("") // EOF at once: the agent exits and writes its report
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("run %d: %v %s", i, err, out)
		}
	}
	files, err := filepath.Glob(filepath.Join(dir, "report-*.json"))
	if err != nil || len(files) != 2 {
		t.Fatalf("reports = %v %v", files, err)
	}
	for _, f := range files {
		b, err := os.ReadFile(f)
		var r map[string]any
		if err != nil || json.Unmarshal(b, &r) != nil {
			t.Fatalf("%s: %v %q", f, err, b)
		}
	}
}

// commit {all: true} stages every change first, like an agent committing its work; without it the commit
// takes only what is already staged.
func TestFakeAgentCommitAllStagesChanges(t *testing.T) {
	repo := t.TempDir()
	git := func(args ...string) string {
		t.Helper()
		out, err := exec.Command("git", append([]string{"-C", repo, "-c", "user.name=t", "-c", "user.email=t@t"}, args...)...).CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	git("init", "-q")
	git("commit", "-q", "--allow-empty", "-m", "init")
	s := startIn(t, repo, []any{
		map[string]any{"direct_write": map[string]any{"path": "a.txt", "content": "a"}},
		map[string]any{"commit": map[string]any{"message": "only staged"}},
		map[string]any{"commit": map[string]any{"message": "everything", "all": true}},
	}, nil)
	if _, err := s.conn.Prompt(context.Background(), acp.PromptRequest{SessionId: s.sid, Prompt: []acp.ContentBlock{acp.TextBlock("go")}}); err != nil {
		t.Fatal(err)
	}
	s.finish(t)
	if got := git("log", "--format=%s", "--name-only", "-2"); got != "everything\n\na.txt\nonly staged" {
		t.Fatalf("log = %q", got)
	}
	if st := git("status", "--porcelain"); st != "" {
		t.Fatalf("status = %q", st)
	}
}
