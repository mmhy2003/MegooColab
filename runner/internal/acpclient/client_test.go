package acpclient_test

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/coder/acp-go-sdk"
	"github.com/mmhy2003/megoocolab/runner/internal/acpclient"
	"github.com/mmhy2003/megoocolab/runner/internal/policy"
	"github.com/mmhy2003/megoocolab/runner/internal/testutil"
)

// The server's allow-list (backend sanitize_update): the only keys a runner may emit.
var allowedFields = map[string][]string{
	"message":     {"text"},
	"plan":        {"entries"},
	"tool":        {"tool_kind", "title", "status"},
	"file_change": {"path", "lines_added", "lines_removed"},
	"command":     {"command", "exit_code"},
	"permission":  {"tool_kind", "title", "decision", "reason"},
}

type emitted struct {
	Kind string
	Data map[string]any
}

type recorder struct {
	mu  sync.Mutex
	all []emitted
}

func (r *recorder) emit(kind string, data map[string]any) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.all = append(r.all, emitted{kind, data})
}

func (r *recorder) list() []emitted {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]emitted(nil), r.all...)
}

func (r *recorder) ofKind(kind string) []map[string]any {
	var out []map[string]any
	for _, e := range r.list() {
		if e.Kind == kind {
			out = append(out, e.Data)
		}
	}
	return out
}

// checkShape fails if anything emitted has a kind or key outside the allow-list.
func (r *recorder) checkShape(t *testing.T) {
	t.Helper()
	for _, e := range r.list() {
		allowed, ok := allowedFields[e.Kind]
		if !ok {
			t.Errorf("unknown kind %q", e.Kind)
			continue
		}
		for k := range e.Data {
			found := false
			for _, a := range allowed {
				found = found || a == k
			}
			if !found {
				t.Errorf("%s update carries disallowed field %q", e.Kind, k)
			}
		}
	}
}

func (r *recorder) json(t *testing.T) string {
	t.Helper()
	b, err := json.Marshal(r.list())
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

type harness struct {
	conn   *acp.ClientSideConnection
	client *acpclient.Client
	rec    *recorder
	sid    acp.SessionId
	report string
	cmd    *exec.Cmd
	stdin  interface{ Close() error }
	root   string
}

// startAt runs the fake agent against the given worktree root (resolved, so tests
// can compare paths exactly). Scenarios name absolute paths, so the root is chosen first.
func startAt(t *testing.T, root string, kind policy.Kind, scenario any, opts ...acpclient.Option) *harness {
	t.Helper()
	root, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}
	pol, err := policy.New(kind, root)
	if err != nil {
		t.Fatal(err)
	}
	sc, _ := json.Marshal(scenario)
	report := filepath.Join(t.TempDir(), "report.json")
	cmd := exec.Command(testutil.BuildFakeAgent(t))
	cmd.Env = append(os.Environ(), "FAKEAGENT_SCENARIO="+string(sc), "FAKEAGENT_REPORT="+report)
	cmd.Stderr = os.Stderr
	in, _ := cmd.StdinPipe()
	out, _ := cmd.StdoutPipe()
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = cmd.Process.Kill(); _ = cmd.Wait() })
	rec := &recorder{}
	cl := acpclient.New(pol, root, rec.emit, opts...)
	conn := acp.NewClientSideConnection(cl, in, out)
	conn.SetLogger(slog.New(slog.NewTextHandler(io.Discard, nil)))
	ctx := context.Background()
	if _, err := conn.Initialize(ctx, acp.InitializeRequest{
		ProtocolVersion:    acp.ProtocolVersionNumber,
		ClientCapabilities: acp.ClientCapabilities{Fs: acp.FileSystemCapabilities{ReadTextFile: true, WriteTextFile: true}},
	}); err != nil {
		t.Fatal(err)
	}
	ns, err := conn.NewSession(ctx, acp.NewSessionRequest{Cwd: root, McpServers: []acp.McpServer{}})
	if err != nil {
		t.Fatal(err)
	}
	return &harness{conn: conn, client: cl, rec: rec, sid: ns.SessionId, report: report, cmd: cmd, stdin: in, root: root}
}

func (h *harness) prompt(t *testing.T) {
	t.Helper()
	if _, err := h.conn.Prompt(context.Background(), acp.PromptRequest{SessionId: h.sid, Prompt: []acp.ContentBlock{acp.TextBlock("go")}}); err != nil {
		t.Fatal(err)
	}
	h.client.Flush()
}

// steps closes the agent and returns the "steps" of its report.
func (h *harness) steps(t *testing.T) []map[string]any {
	t.Helper()
	_ = h.stdin.Close()
	done := make(chan struct{})
	go func() { _ = h.cmd.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatal("agent did not exit")
	}
	b, err := os.ReadFile(h.report)
	if err != nil {
		t.Fatal(err)
	}
	var r struct{ Steps []map[string]any }
	if err := json.Unmarshal(b, &r); err != nil {
		t.Fatal(err)
	}
	return r.Steps
}

func (h *harness) path(rel string) string { return filepath.Join(h.root, filepath.FromSlash(rel)) }

func write(path, content string) map[string]any {
	return map[string]any{"write": map[string]any{"path": path, "content": content}}
}

func TestDeniedWriteLeavesFileUntouchedAndEmitsPermission(t *testing.T) {
	root := t.TempDir()
	existing := filepath.Join(root, "keep.txt")
	if err := os.WriteFile(existing, []byte("original"), 0o644); err != nil {
		t.Fatal(err)
	}
	h := startAt(t, root, policy.ReadOnly, []any{
		write(existing, "overwritten"),
		write(filepath.Join(root, "new.txt"), "fresh"),
		write(filepath.Join(root, "..", "escape.txt"), "out"),
	})
	h.prompt(t)

	if b, _ := os.ReadFile(existing); string(b) != "original" {
		t.Fatalf("file was modified: %q", b)
	}
	for _, p := range []string{filepath.Join(root, "new.txt"), filepath.Join(root, "..", "escape.txt")} {
		if _, err := os.Stat(p); err == nil {
			t.Fatalf("%s must not exist", p)
		}
	}
	for i, s := range h.steps(t) {
		if s["ok"] != false || s["error"] == "" {
			t.Errorf("step %d must fail: %v", i, s)
		}
	}
	perms := h.rec.ofKind("permission")
	if len(perms) != 3 {
		t.Fatalf("want 3 permission updates, got %v", h.rec.list())
	}
	for _, p := range perms {
		if p["decision"] != "denied" || p["tool_kind"] != "edit" || p["reason"] == "" {
			t.Errorf("permission = %v", p)
		}
	}
	if n := len(h.rec.ofKind("file_change")); n != 0 {
		t.Errorf("denied writes must not emit file_change, got %d", n)
	}
	h.rec.checkShape(t)
	if strings.Contains(h.rec.json(t), root) {
		t.Error("emitted metadata leaks the absolute root")
	}
}

func TestWorkspaceWritesInsideAndCountsLines(t *testing.T) {
	root, _ := filepath.EvalSymlinks(t.TempDir())
	old := filepath.Join(root, "src", "old.go")
	if err := os.MkdirAll(filepath.Dir(old), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(old, []byte("a\nb\nc\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	outside := filepath.Join(root, "..", "evil-"+filepath.Base(root)+".txt")
	h := startAt(t, root, policy.Workspace, []any{
		write(filepath.Join(root, "src", "new", "n.txt"), "one\ntwo\n"),
		write(old, "a\nB\nc\nd\n"),
		write(outside, "x"),
		write("rel.txt", "relative"),
	})
	h.prompt(t)

	if b, _ := os.ReadFile(filepath.Join(root, "src", "new", "n.txt")); string(b) != "one\ntwo\n" {
		t.Fatalf("new file = %q", b)
	}
	if b, _ := os.ReadFile(old); string(b) != "a\nB\nc\nd\n" {
		t.Fatalf("old file = %q", b)
	}
	if _, err := os.Stat(outside); err == nil {
		t.Fatal("write outside the worktree happened")
	}
	if b, _ := os.ReadFile(filepath.Join(root, "rel.txt")); string(b) != "relative" {
		t.Fatalf("relative write = %q", b)
	}
	want := []map[string]any{
		{"path": "src/new/n.txt", "lines_added": 2, "lines_removed": 0},
		{"path": "src/old.go", "lines_added": 2, "lines_removed": 1},
		{"path": "rel.txt", "lines_added": 1, "lines_removed": 0},
	}
	got := h.rec.ofKind("file_change")
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("file_change = %v\nwant %v", got, want)
	}
	perms := h.rec.ofKind("permission")
	if len(perms) != 1 || perms[0]["decision"] != "denied" {
		t.Fatalf("permission = %v", perms)
	}
	h.rec.checkShape(t)
	if strings.Contains(h.rec.json(t), root) {
		t.Error("emitted metadata leaks the absolute root")
	}
}

func TestWorkspaceDeniesWriteThroughEscapingSymlink(t *testing.T) {
	root, _ := filepath.EvalSymlinks(t.TempDir())
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(root, "link")); err != nil {
		t.Skipf("cannot create symlinks here: %v", err)
	}
	h := startAt(t, root, policy.Workspace, []any{write(filepath.Join(root, "link", "pwn.txt"), "x")})
	h.prompt(t)
	if _, err := os.Stat(filepath.Join(outside, "pwn.txt")); err == nil {
		t.Fatal("write escaped through the symlink")
	}
	if p := h.rec.ofKind("permission"); len(p) != 1 || p[0]["decision"] != "denied" {
		t.Fatalf("permission = %v", p)
	}
}

func TestMetadataNeverContainsContent(t *testing.T) {
	root, _ := filepath.EvalSymlinks(t.TempDir())
	secret := "secret-content"
	h := startAt(t, root, policy.Workspace, []any{
		map[string]any{"say": "working on it"},
		map[string]any{"plan": [][]string{{"step one", "pending"}}},
		map[string]any{"tool": map[string]any{"kind": "edit", "title": "edit file", "path": filepath.Join(root, "s.txt")}},
		write(filepath.Join(root, "s.txt"), secret+"\nmore "+secret),
		map[string]any{"exec": map[string]any{"command": filepath.Join(root, "bin", "tool.exe") + " --token=" + secret}},
		map[string]any{"read": map[string]any{"path": filepath.Join(root, "s.txt")}},
	})
	h.prompt(t)

	// the fake agent's tool steps carry the path as rawInput; a hostile agent also sends content
	ctx := context.Background()
	for _, u := range []acp.SessionUpdate{
		{ToolCall: &acp.SessionUpdateToolCall{
			ToolCallId: "x1", Title: "write", Kind: acp.ToolKindEdit, Status: acp.ToolCallStatusInProgress,
			Content:   []acp.ToolCallContent{acp.ToolDiffContent(filepath.Join(root, "s.txt"), secret)},
			RawInput:  map[string]any{"content": secret},
			RawOutput: map[string]any{"stdout": secret},
			Locations: []acp.ToolCallLocation{{Path: filepath.Join(root, "s.txt")}},
		}},
		{ToolCallUpdate: &acp.SessionToolCallUpdate{
			ToolCallId: "x1", Status: ptr(acp.ToolCallStatusCompleted),
			Content:   []acp.ToolCallContent{acp.ToolContent(acp.TextBlock(secret))},
			RawOutput: secret,
		}},
		{AgentThoughtChunk: &acp.SessionUpdateAgentThoughtChunk{Content: acp.TextBlock(secret)}},
		{UserMessageChunk: &acp.SessionUpdateUserMessageChunk{Content: acp.TextBlock(secret)}},
	} {
		if err := h.client.SessionUpdate(ctx, acp.SessionNotification{SessionId: h.sid, Update: u}); err != nil {
			t.Fatal(err)
		}
	}
	h.client.Flush()

	if strings.Contains(h.rec.json(t), secret) {
		t.Fatalf("emitted metadata contains file content: %s", h.rec.json(t))
	}
	if strings.Contains(h.rec.json(t), root) {
		t.Fatalf("emitted metadata contains the absolute root: %s", h.rec.json(t))
	}
	h.rec.checkShape(t)
	if n := len(h.rec.ofKind("file_change")); n != 1 {
		t.Fatalf("file_change count = %d", n)
	}
	// commands: first token, basename only
	cmds := h.rec.ofKind("command")
	if len(cmds) != 1 || cmds[0]["command"] != "tool" {
		t.Fatalf("command updates = %v", cmds)
	}
	for _, e := range h.rec.list() {
		if e.Kind == "tool" && e.Data["tool_kind"] == nil {
			t.Errorf("tool update without tool_kind: %v", e.Data)
		}
	}
	_ = h.steps(t)
}

func TestPermissionFollowsPolicy(t *testing.T) {
	h := startAt(t, t.TempDir(), policy.ReadOnly, []any{
		map[string]any{"exec": map[string]any{"command": "git status"}},
		map[string]any{"exec": map[string]any{"command": "rm -rf x"}},
		map[string]any{"exec": map[string]any{"command": "cat a.txt; rm -rf x"}},
		map[string]any{"tool": map[string]any{"kind": "edit", "title": "edit", "path": "a.go"}},
		map[string]any{"tool": map[string]any{"kind": "read", "title": "read", "path": "a.go"}},
	})
	h.prompt(t)
	var outcomes []any
	for _, s := range h.steps(t) {
		outcomes = append(outcomes, s["outcome"])
	}
	want := []any{"allowed", "rejected", "rejected", "rejected", "allowed"}
	if !reflect.DeepEqual(outcomes, want) {
		t.Fatalf("outcomes = %v, want %v", outcomes, want)
	}
	var decisions []any
	for _, p := range h.rec.ofKind("permission") {
		decisions = append(decisions, p["decision"])
	}
	if !reflect.DeepEqual(decisions, []any{"allowed", "denied", "denied", "denied", "allowed"}) {
		t.Fatalf("decisions = %v", decisions)
	}
	// only the allowed command was announced, as its program name only
	if cmds := h.rec.ofKind("command"); len(cmds) != 1 || cmds[0]["command"] != "git" {
		t.Fatalf("commands = %v", cmds)
	}
	// execute titles never carry arguments
	for _, e := range h.rec.list() {
		if (e.Kind == "permission" || e.Kind == "tool") && e.Data["tool_kind"] == "execute" && strings.Count(asString(e.Data["title"]), " ") != 1 {
			t.Errorf("execute title carries arguments: %v", e.Data)
		}
	}
	h.rec.checkShape(t)
}

func TestRequestPermissionWithoutSuitableOptionIsCancelled(t *testing.T) {
	pol, _ := policy.New(policy.Workspace, t.TempDir())
	c := acpclient.New(pol, t.TempDir(), func(string, map[string]any) {})
	req := func(kind acp.ToolKind, opts ...acp.PermissionOption) acp.RequestPermissionRequest {
		return acp.RequestPermissionRequest{
			SessionId: "s", Options: opts,
			ToolCall: acp.ToolCallUpdate{ToolCallId: "t", Kind: &kind, Title: ptr("do it")},
		}
	}
	allowAlways := acp.PermissionOption{Kind: acp.PermissionOptionKindAllowAlways, OptionId: "aa", Name: "always"}
	rejectAlways := acp.PermissionOption{Kind: acp.PermissionOptionKindRejectAlways, OptionId: "ra", Name: "never"}
	allowOnce := acp.PermissionOption{Kind: acp.PermissionOptionKindAllowOnce, OptionId: "ao", Name: "once"}
	rejectOnce := acp.PermissionOption{Kind: acp.PermissionOptionKindRejectOnce, OptionId: "ro", Name: "no"}

	// allowed by policy, but only allow_always is offered: never grant a standing approval
	r, err := c.RequestPermission(context.Background(), req(acp.ToolKindThink, allowAlways, rejectOnce))
	if err != nil || r.Outcome.Cancelled == nil || r.Outcome.Selected != nil {
		t.Fatalf("allow with no allow_once = %+v %v", r, err)
	}
	// denied by policy with only reject_always: cancelled as well
	loc := req(acp.ToolKindEdit, allowOnce, rejectAlways)
	loc.ToolCall.Locations = []acp.ToolCallLocation{{Path: "/etc/passwd"}}
	r, err = c.RequestPermission(context.Background(), loc)
	if err != nil || r.Outcome.Cancelled == nil {
		t.Fatalf("deny with no reject_once = %+v %v", r, err)
	}
	// the normal case
	r, err = c.RequestPermission(context.Background(), req(acp.ToolKindThink, allowAlways, allowOnce, rejectOnce))
	if err != nil || r.Outcome.Selected == nil || r.Outcome.Selected.OptionId != "ao" {
		t.Fatalf("allow = %+v %v", r, err)
	}
	loc = req(acp.ToolKindEdit, allowAlways, allowOnce, rejectOnce)
	loc.ToolCall.Locations = []acp.ToolCallLocation{{Path: "/etc/passwd"}}
	r, err = c.RequestPermission(context.Background(), loc)
	if err != nil || r.Outcome.Selected == nil || r.Outcome.Selected.OptionId != "ro" {
		t.Fatalf("deny = %+v %v", r, err)
	}
}

func TestMessageCoalescing(t *testing.T) {
	h := startAt(t, t.TempDir(), policy.Workspace, []any{
		map[string]any{"say": "one "}, map[string]any{"say": "two "}, map[string]any{"say": "three"},
		map[string]any{"sleep_ms": 600},
		map[string]any{"say": "four"},
	}, acpclient.WithFlushInterval(150*time.Millisecond))
	h.prompt(t)
	var texts []any
	for _, m := range h.rec.ofKind("message") {
		texts = append(texts, m["text"])
	}
	if !reflect.DeepEqual(texts, []any{"one two three", "four"}) {
		t.Fatalf("messages = %v", texts)
	}
	h.rec.checkShape(t)
}

func TestMessageFlushedAtEndOfTurnAndBeforeOtherUpdates(t *testing.T) {
	h := startAt(t, t.TempDir(), policy.Workspace, []any{
		map[string]any{"say": "before the plan"},
		map[string]any{"plan": [][]string{{"a", "pending"}}},
		map[string]any{"say": "after"},
	}) // default 1.5 s: nothing flushes by timer
	h.prompt(t)
	var kinds []string
	for _, e := range h.rec.list() {
		kinds = append(kinds, e.Kind)
	}
	if !reflect.DeepEqual(kinds, []string{"message", "plan", "message"}) {
		t.Fatalf("order = %v", kinds)
	}
}

func TestLongMessageIsSplitNotTruncated(t *testing.T) {
	pol, _ := policy.New(policy.Workspace, t.TempDir())
	rec := &recorder{}
	c := acpclient.New(pol, t.TempDir(), rec.emit)
	long := strings.Repeat("é", 4000) + strings.Repeat("x", 10)
	_ = c.SessionUpdate(context.Background(), acp.SessionNotification{Update: acp.UpdateAgentMessageText(long)})
	c.Flush()
	msgs := rec.ofKind("message")
	if len(msgs) != 2 || len([]rune(msgs[0]["text"].(string))) != 4000 || msgs[1]["text"] != strings.Repeat("x", 10) {
		t.Fatalf("messages = %v", msgs)
	}
	c.Flush() // idempotent: nothing buffered
	if len(rec.ofKind("message")) != 2 {
		t.Fatal("second Flush emitted again")
	}
}

func TestPlanAndToolMapping(t *testing.T) {
	pol, _ := policy.New(policy.Workspace, t.TempDir())
	rec := &recorder{}
	c := acpclient.New(pol, t.TempDir(), rec.emit)
	ctx := context.Background()
	entries := make([]acp.PlanEntry, 0, 60)
	for i := 0; i < 60; i++ {
		entries = append(entries, acp.PlanEntry{Content: strings.Repeat("p", 300), Status: acp.PlanEntryStatusPending, Priority: acp.PlanEntryPriorityHigh})
	}
	_ = c.SessionUpdate(ctx, acp.SessionNotification{Update: acp.UpdatePlan(entries...)})
	_ = c.SessionUpdate(ctx, acp.SessionNotification{Update: acp.StartToolCall("c1", "Run tests", acp.WithStartKind(acp.ToolKindExecute), acp.WithStartStatus(acp.ToolCallStatusPending))})
	// the update omits kind and title: they are remembered from the start
	_ = c.SessionUpdate(ctx, acp.SessionNotification{Update: acp.UpdateToolCall("c1", acp.WithUpdateStatus(acp.ToolCallStatusCompleted))})
	// content-only updates carry nothing worth reporting
	_ = c.SessionUpdate(ctx, acp.SessionNotification{Update: acp.UpdateToolCall("c1", acp.WithUpdateContent([]acp.ToolCallContent{acp.ToolContent(acp.TextBlock("x"))}))})
	_ = c.SessionUpdate(ctx, acp.SessionNotification{Update: acp.StartToolCall("c2", "Think", acp.WithStartKind(acp.ToolKindSwitchMode))})

	plans := rec.ofKind("plan")
	if len(plans) != 1 {
		t.Fatalf("plans = %v", plans)
	}
	es := plans[0]["entries"].([]map[string]any)
	if len(es) != 50 || len([]rune(es[0]["title"].(string))) != 200 || es[0]["status"] != "pending" {
		t.Fatalf("plan entries = %d first=%v", len(es), es[0])
	}
	tools := rec.ofKind("tool")
	if len(tools) != 3 {
		t.Fatalf("tools = %v", tools)
	}
	if tools[0]["tool_kind"] != "execute" || tools[0]["status"] != "pending" || tools[1]["status"] != "completed" || tools[1]["tool_kind"] != "execute" {
		t.Fatalf("tools = %v", tools)
	}
	if tools[2]["tool_kind"] != "other" {
		t.Fatalf("unknown kinds map to other: %v", tools[2])
	}
	rec.checkShape(t)
}

func TestReadTextFile(t *testing.T) {
	root, _ := filepath.EvalSymlinks(t.TempDir())
	if err := os.WriteFile(filepath.Join(root, "a.txt"), []byte("l1\nl2\nl3\nl4\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	for _, kind := range []policy.Kind{policy.ReadOnly, policy.Workspace} {
		pol, _ := policy.New(kind, root)
		rec := &recorder{}
		c := acpclient.New(pol, root, rec.emit)
		ctx := context.Background()
		r, err := c.ReadTextFile(ctx, acp.ReadTextFileRequest{Path: filepath.Join(root, "a.txt")})
		if err != nil || r.Content != "l1\nl2\nl3\nl4\n" {
			t.Fatalf("%s full read = %q %v", kind, r.Content, err)
		}
		r, err = c.ReadTextFile(ctx, acp.ReadTextFileRequest{Path: "a.txt", Line: ptr(2), Limit: ptr(2)})
		if err != nil || r.Content != "l2\nl3\n" {
			t.Fatalf("%s ranged read = %q %v", kind, r.Content, err)
		}
		if _, err := c.ReadTextFile(ctx, acp.ReadTextFileRequest{Path: filepath.Join(root, "..", "x")}); err == nil {
			t.Fatalf("%s: read outside the root must fail", kind)
		}
		if _, err := c.ReadTextFile(ctx, acp.ReadTextFileRequest{Path: filepath.Join(root, "missing.txt")}); err == nil {
			t.Fatalf("%s: missing file must fail", kind)
		}
		if len(rec.list()) != 0 {
			t.Fatalf("reads emit nothing, got %v", rec.list())
		}
	}
}

func TestTerminalNotSupported(t *testing.T) {
	pol, _ := policy.New(policy.Workspace, t.TempDir())
	c := acpclient.New(pol, t.TempDir(), func(string, map[string]any) {})
	ctx := context.Background()
	if _, err := c.CreateTerminal(ctx, acp.CreateTerminalRequest{Command: "ls"}); err == nil {
		t.Error("CreateTerminal must fail")
	}
	if _, err := c.KillTerminal(ctx, acp.KillTerminalRequest{}); err == nil {
		t.Error("KillTerminal must fail")
	}
	if _, err := c.TerminalOutput(ctx, acp.TerminalOutputRequest{}); err == nil {
		t.Error("TerminalOutput must fail")
	}
	if _, err := c.ReleaseTerminal(ctx, acp.ReleaseTerminalRequest{}); err == nil {
		t.Error("ReleaseTerminal must fail")
	}
	if _, err := c.WaitForTerminalExit(ctx, acp.WaitForTerminalExitRequest{}); err == nil {
		t.Error("WaitForTerminalExit must fail")
	}
}

func ptr[T any](v T) *T { return &v }

func asString(v any) string {
	s, _ := v.(string)
	return s
}
