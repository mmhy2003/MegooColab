package jobs

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/config"
	"github.com/mmhy2003/megoocolab/runner/internal/conn"
	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
	"github.com/mmhy2003/megoocolab/runner/internal/testserver"
	"github.com/mmhy2003/megoocolab/runner/internal/testutil"
)

const token = "mgc_test"

// TestMain lets the test binary double as a "silent" adapter: a process that
// never speaks ACP and just sleeps, for the kill-on-cancel test.
func TestMain(m *testing.M) {
	if os.Getenv("JOBS_TEST_HANG") == "1" {
		time.Sleep(time.Minute)
		os.Exit(0)
	}
	os.Exit(m.Run())
}

func gitRepo(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	run := func(args ...string) {
		cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	run("init", "-q")
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte("hello\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	run("add", ".")
	run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
	return dir
}

type env struct {
	t        *testing.T
	srv      *testserver.Server
	mgr      *Manager
	repo     string
	cache    string
	report   string
	serveErr chan error
	cancel   context.CancelFunc
}

// newEnvWithCache starts a manager served over a fake server, with the fake
// agent as the claude_code adapter running the given scenario. The welcome has
// one agent ("agent-1") bound to project MEG. tweak runs before Serve starts.
func newEnvWithCache(t *testing.T, scenario string, maxRuns int, cache string, tweak ...func(*Manager)) *env {
	t.Helper()
	e := &env{t: t, repo: gitRepo(t), cache: cache, serveErr: make(chan error, 1)}
	e.report = filepath.Join(t.TempDir(), "report.json")
	t.Setenv("MEGOO_ADAPTER_CLAUDE_CODE", `"`+testutil.BuildFakeAgent(t)+`"`)
	t.Setenv("FAKEAGENT_SCENARIO", scenario)
	t.Setenv("FAKEAGENT_REPORT", e.report)
	e.srv = testserver.New(t, token)
	e.srv.AutoWelcome = false

	var client *conn.Client
	e.mgr = New(func(v any) error { return client.Send(v) }, cache)
	e.mgr.LookPath = func(s string) (string, error) { return s, nil }
	for _, f := range tweak {
		f(e.mgr)
	}
	client = conn.New(config.Config{URL: e.srv.URL(), Token: token}, "test", e.mgr.Probe)
	client.HeartbeatInterval = time.Hour
	client.BackoffBase, client.BackoffMax = 10*time.Millisecond, 50*time.Millisecond
	ctx, cancel := context.WithCancel(context.Background())
	e.cancel = cancel
	go func() { e.serveErr <- e.mgr.Serve(ctx, client) }()
	t.Cleanup(func() {
		cancel()
		select {
		case <-e.serveErr:
		case <-time.After(15 * time.Second):
			t.Error("Serve did not return")
		}
	})
	e.srv.WaitFrame(t, "hello")
	e.welcome(maxRuns)
	return e
}

func (e *env) welcome(maxRuns int) {
	if err := e.srv.Send(protocol.Welcome{
		Type: protocol.TypeWelcome, UserID: "u1",
		Agents: []protocol.WelcomeAgent{{
			AgentID: "agent-1", Name: "A", Program: "claude_code", MaxConcurrentRuns: maxRuns,
			Bindings: []protocol.WelcomeBinding{{ProjectKey: "MEG", LocalPath: e.repo}},
		}},
	}); err != nil {
		e.t.Fatal(err)
	}
}

func (e *env) worktree(key string) string { return filepath.Join(e.cache, "worktrees", "agent-1", key) }

func (e *env) startRun(runID, key, policy string) {
	e.t.Helper()
	if err := e.srv.Send(protocol.RunStart{
		Type: protocol.TypeRunStart, RunID: runID, AgentID: "agent-1",
		Task:      protocol.RunTask{Key: key, Title: "Do the thing", ProjectKey: "MEG"},
		LocalPath: e.repo, Policy: policy, Prompt: "please",
	}); err != nil {
		e.t.Fatal(err)
	}
}

func (e *env) finished(runID string) protocol.RunFinished {
	e.t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		for _, f := range e.srv.Frames() {
			if f.Type != protocol.TypeRunFinished {
				continue
			}
			var rf protocol.RunFinished
			if err := json.Unmarshal(f.Raw, &rf); err != nil {
				e.t.Fatal(err)
			}
			if rf.RunID == runID {
				return rf
			}
		}
		time.Sleep(20 * time.Millisecond)
	}
	e.t.Fatalf("no run_finished for %s", runID)
	return protocol.RunFinished{}
}

func (e *env) updates(runID string) []protocol.RunUpdate {
	var out []protocol.RunUpdate
	for _, f := range e.srv.Frames() {
		if f.Type != protocol.TypeRunUpdate {
			continue
		}
		var u protocol.RunUpdate
		if err := json.Unmarshal(f.Raw, &u); err != nil {
			e.t.Fatal(err)
		}
		if u.RunID == runID {
			out = append(out, u)
		}
	}
	return out
}

func (e *env) waitUpdate(runID string) {
	e.t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		if len(e.updates(runID)) > 0 {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	e.t.Fatal("no run_update arrived")
}

type agentReport struct {
	Initialize struct {
		FSRead   bool `json:"fs_read"`
		FSWrite  bool `json:"fs_write"`
		Terminal bool `json:"terminal"`
	} `json:"initialize"`
	Cwd       string          `json:"cwd"`
	Meta      json.RawMessage `json:"meta"`
	ModesSet  []string        `json:"modes_set"`
	Cancelled bool            `json:"cancelled"`
}

func (e *env) readReport() agentReport {
	e.t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		if b, err := os.ReadFile(e.report); err == nil {
			var r agentReport
			if err := json.Unmarshal(b, &r); err != nil {
				e.t.Fatal(err)
			}
			var compact bytes.Buffer
			if err := json.Compact(&compact, r.Meta); err == nil {
				r.Meta = compact.Bytes()
			}
			return r
		}
		time.Sleep(20 * time.Millisecond)
	}
	e.t.Fatal("fake agent wrote no report")
	return agentReport{}
}

func jsonStr(v any) string { b, _ := json.Marshal(v); return string(b) }

func TestRunCompletesAndStreamsMetadata(t *testing.T) {
	cache := t.TempDir() // the scenario needs the worktree path, which depends on it
	wtFile := filepath.Join(cache, "worktrees", "agent-1", "MEG-1", "out.txt")
	scenario := "[" + strings.Join([]string{
		`{"plan":[["step one","in_progress"]]}`,
		`{"tool":{"kind":"read","title":"Read README","path":` + jsonStr(wtFile) + `}}`,
		`{"write":{"path":` + jsonStr(wtFile) + `,"content":"a\nb\n"}}`,
		`{"say":"all done"}`,
	}, ",") + "]"
	e := newEnvWithCache(t, scenario, 1, cache)
	e.startRun("run-1", "MEG-1", "workspace")

	rf := e.finished("run-1")
	if rf.Outcome != "completed" || rf.Summary != "all done" || rf.Error != nil {
		t.Fatalf("finished = %+v", rf)
	}
	ups := e.updates("run-1")
	kinds := map[string]bool{}
	for i, u := range ups {
		if u.Seq != i+1 {
			t.Fatalf("update %d has seq %d, want %d", i, u.Seq, i+1)
		}
		kinds[u.Kind] = true
		if u.Data == nil {
			t.Fatalf("update %d has null data", i)
		}
	}
	for _, k := range []string{"message", "plan", "tool", "file_change"} {
		if !kinds[k] {
			t.Errorf("no %s update; got %v", k, ups)
		}
	}
	if b, err := os.ReadFile(wtFile); err != nil || string(b) != "a\nb\n" {
		t.Fatalf("worktree file = %q, %v", b, err)
	}
	if _, err := os.Stat(filepath.Join(e.repo, "out.txt")); err == nil {
		t.Fatal("the developer's checkout was written to")
	}

	r := e.readReport()
	if !r.Initialize.FSRead || !r.Initialize.FSWrite || r.Initialize.Terminal {
		t.Errorf("client capabilities = %+v", r.Initialize)
	}
	if r.Cwd != e.worktree("MEG-1") {
		t.Errorf("cwd = %q, want the task worktree %q", r.Cwd, e.worktree("MEG-1"))
	}
	if !strings.Contains(string(r.Meta), `"settingSources":[]`) || !strings.Contains(string(r.Meta), `"allowDangerouslySkipPermissions":false`) {
		t.Errorf("session meta = %s", r.Meta)
	}
	if strings.Join(r.ModesSet, ",") != "default" {
		t.Errorf("modes set = %v, want [default]", r.ModesSet)
	}
	if _, err := os.Stat(filepath.Join(e.cache, "logs", "run-1.log")); err != nil {
		t.Errorf("no adapter log: %v", err)
	}
}

func TestReadOnlyRunCannotWrite(t *testing.T) {
	cache := t.TempDir()
	target := filepath.Join(cache, "worktrees", "agent-1", "MEG-2", "evil.txt")
	e := newEnvWithCache(t, `[{"write":{"path":`+jsonStr(target)+`,"content":"x"}}]`, 1, cache)
	e.startRun("run-ro", "MEG-2", "read_only")

	rf := e.finished("run-ro")
	if rf.Outcome != "completed" {
		t.Fatalf("finished = %+v", rf)
	}
	if _, err := os.Stat(target); err == nil {
		t.Fatal("read-only run wrote a file")
	}
	denied := false
	for _, u := range e.updates("run-ro") {
		if u.Kind == "permission" && u.Data["decision"] == "denied" {
			denied = true
		}
	}
	if !denied {
		t.Fatalf("no permission denied update: %+v", e.updates("run-ro"))
	}
	r := e.readReport()
	if r.Cwd != e.worktree("MEG-2") {
		t.Errorf("read-only cwd = %q, want the worktree", r.Cwd)
	}
	if !strings.Contains(string(r.Meta), `"disallowedTools":["Edit","Write","MultiEdit","NotebookEdit"]`) {
		t.Errorf("session meta = %s", r.Meta)
	}
	if strings.Join(r.ModesSet, ",") != "plan" {
		t.Errorf("modes set = %v, want [plan]", r.ModesSet)
	}
}

const sleeping = `[{"plan":[["working","in_progress"]]},{"sleep_ms":60000}]`

func TestCancelStopsAgent(t *testing.T) {
	e := newEnvWithCache(t, sleeping, 1, t.TempDir())
	e.startRun("run-c", "MEG-3", "workspace")
	e.waitUpdate("run-c")
	if err := e.srv.Send(protocol.RunCancel{Type: protocol.TypeRunCancel, RunID: "run-c"}); err != nil {
		t.Fatal(err)
	}
	rf := e.finished("run-c")
	if rf.Outcome != "cancelled" {
		t.Fatalf("finished = %+v", rf)
	}
	if !e.readReport().Cancelled {
		t.Error("the agent never received session/cancel")
	}
	if n := e.mgr.Active(); n != 0 {
		t.Errorf("%d runs still active", n)
	}
}

func TestCancelKillsAgentThatNeverAnswers(t *testing.T) {
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	var killed []*exec.Cmd
	e := newEnvWithCache(t, "[]", 1, t.TempDir(), func(m *Manager) {
		m.Kill = func(c *exec.Cmd) {
			mu.Lock()
			killed = append(killed, c)
			mu.Unlock()
			killTree(c)
		}
	})
	t.Setenv("MEGOO_ADAPTER_CLAUDE_CODE", `"`+exe+`"`)
	t.Setenv("JOBS_TEST_HANG", "1")
	e.startRun("run-h", "MEG-4", "workspace")
	deadline := time.Now().Add(10 * time.Second)
	for e.mgr.Active() == 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	time.Sleep(300 * time.Millisecond) // let the process start and Initialize block
	if err := e.srv.Send(protocol.RunCancel{Type: protocol.TypeRunCancel, RunID: "run-h"}); err != nil {
		t.Fatal(err)
	}
	if rf := e.finished("run-h"); rf.Outcome != "cancelled" {
		t.Fatalf("finished = %+v", rf)
	}
	mu.Lock()
	defer mu.Unlock()
	if len(killed) == 0 {
		t.Fatal("the unresponsive adapter process was not killed")
	}
}

func TestUnauthorizedCloseStopsRuns(t *testing.T) {
	e := newEnvWithCache(t, sleeping, 1, t.TempDir())
	e.startRun("run-u", "MEG-5", "workspace")
	e.waitUpdate("run-u")

	e.srv.Close(protocol.CloseUnauthorized, "revoked")
	select {
	case err := <-e.serveErr:
		if !errors.Is(err, conn.ErrUnauthorized) {
			t.Fatalf("Serve returned %v, want ErrUnauthorized", err)
		}
		e.serveErr <- err // for the cleanup
	case <-time.After(15 * time.Second):
		t.Fatal("Serve did not stop after 4401")
	}
	if n := e.mgr.Active(); n != 0 {
		t.Fatalf("%d runs still active after 4401", n)
	}
	if !e.readReport().Cancelled {
		t.Error("the agent was not told to cancel")
	}
}

func TestConcurrencyLimitReportsBusy(t *testing.T) {
	e := newEnvWithCache(t, sleeping, 1, t.TempDir())
	e.startRun("run-a", "MEG-6", "workspace")
	e.waitUpdate("run-a")
	e.startRun("run-b", "MEG-7", "workspace")

	rf := e.finished("run-b")
	if rf.Outcome != "failed" || rf.Error == nil || *rf.Error != "busy" {
		t.Fatalf("finished = %+v", rf)
	}
	if _, err := os.Stat(e.worktree("MEG-7")); err == nil {
		t.Error("a busy run created a worktree")
	}
}

func TestUnknownAgentFails(t *testing.T) {
	e := newEnvWithCache(t, "[]", 1, t.TempDir())
	if err := e.srv.Send(protocol.RunStart{Type: protocol.TypeRunStart, RunID: "run-x", AgentID: "nope",
		Task: protocol.RunTask{Key: "MEG-1", Title: "t", ProjectKey: "MEG"}, Policy: "workspace", Prompt: "p"}); err != nil {
		t.Fatal(err)
	}
	rf := e.finished("run-x")
	if rf.Outcome != "failed" || rf.Error == nil || *rf.Error != "unknown_agent" {
		t.Fatalf("finished = %+v", rf)
	}
}

func TestCancelBeforeStartAnswersCancelled(t *testing.T) {
	e := newEnvWithCache(t, sleeping, 1, t.TempDir())
	if err := e.srv.Send(protocol.RunCancel{Type: protocol.TypeRunCancel, RunID: "run-early"}); err != nil {
		t.Fatal(err)
	}
	e.startRun("run-early", "MEG-8", "workspace")
	rf := e.finished("run-early")
	if rf.Outcome != "cancelled" {
		t.Fatalf("finished = %+v", rf)
	}
	if len(e.updates("run-early")) != 0 {
		t.Error("a pre-cancelled run produced updates")
	}
	if _, err := os.Stat(e.worktree("MEG-8")); err == nil {
		t.Error("a pre-cancelled run created a worktree")
	}
	if e.mgr.Active() != 0 {
		t.Error("a pre-cancelled run was launched")
	}
}

func TestEarlyCancelSetIsBounded(t *testing.T) {
	m := New(func(any) error { return nil }, t.TempDir())
	for i := 0; i < earlyCancelLimit+10; i++ {
		m.HandleRunCancel(fmt.Sprintf("r%d", i))
	}
	if m.takeEarlyCancel("r0") {
		t.Error("the oldest remembered cancel should have been dropped")
	}
	if !m.takeEarlyCancel(fmt.Sprintf("r%d", earlyCancelLimit+9)) {
		t.Error("the newest cancel was forgotten")
	}
	if m.takeEarlyCancel(fmt.Sprintf("r%d", earlyCancelLimit+9)) {
		t.Error("a cancel must be consumed once")
	}
}

func TestProbeFlagsMissingRepo(t *testing.T) {
	good := gitRepo(t)
	bad := filepath.Join(t.TempDir(), "pay")
	m := New(func(any) error { return nil }, t.TempDir())
	m.LookPath = func(string) (string, error) { return "x", nil }
	m.HandleWelcome(protocol.Welcome{Agents: []protocol.WelcomeAgent{
		{AgentID: "ok", Program: "claude_code", MaxConcurrentRuns: 1, Bindings: []protocol.WelcomeBinding{{ProjectKey: "A", LocalPath: good}}},
		{AgentID: "bad", Program: "codex", MaxConcurrentRuns: 1, Bindings: []protocol.WelcomeBinding{{ProjectKey: "B", LocalPath: bad}}},
	}})
	got := map[string]protocol.AgentAvailability{}
	for _, a := range m.Probe() {
		got[a.AgentID] = a
	}
	if a := got["ok"]; !a.Available || len(a.Problems) != 0 {
		t.Errorf("ok agent = %+v", a)
	}
	want := bad + " is not a git repository"
	if a := got["bad"]; a.Available || len(a.Problems) != 1 || a.Problems[0] != want {
		t.Errorf("bad agent = %+v, want problem %q", a, want)
	}

	m.LookPath = func(s string) (string, error) {
		if s == "node" {
			return "", errors.New("missing")
		}
		return s, nil
	}
	for _, a := range m.Probe() {
		if a.AgentID == "ok" && (a.Available || len(a.Problems) != 1 || a.Problems[0] != "node not found") {
			t.Errorf("without node: %+v", a)
		}
	}
}

func TestWelcomeReportsAvailabilityChanges(t *testing.T) {
	e := newEnvWithCache(t, "[]", 1, t.TempDir())
	st := e.srv.WaitFrame(t, "agent_status")
	var s protocol.AgentStatus
	if err := json.Unmarshal(st.Raw, &s); err != nil {
		t.Fatal(err)
	}
	if s.AgentID != "agent-1" || !s.Available || s.Problems == nil {
		t.Fatalf("agent_status = %+v", s)
	}
	// Same bindings again: nothing changed, nothing is sent.
	e.welcome(1)
	// A binding that is not a repo: availability changes.
	if err := e.srv.Send(protocol.Welcome{Type: protocol.TypeWelcome, Agents: []protocol.WelcomeAgent{{
		AgentID: "agent-1", Program: "claude_code", MaxConcurrentRuns: 1,
		Bindings: []protocol.WelcomeBinding{{ProjectKey: "MEG", LocalPath: filepath.Join(e.cache, "nope")}},
	}}}); err != nil {
		t.Fatal(err)
	}
	second := e.srv.WaitNthFrame(t, "agent_status", 2)
	if err := json.Unmarshal(second.Raw, &s); err != nil || s.Available || len(s.Problems) != 1 {
		t.Fatalf("second agent_status = %+v, %v", s, err)
	}
}

func TestDisconnectStopsRuns(t *testing.T) {
	var mu sync.Mutex
	var killed int
	e := newEnvWithCache(t, sleeping, 1, t.TempDir(), func(m *Manager) {
		m.CancelGrace = time.Second
		m.Kill = func(c *exec.Cmd) { mu.Lock(); killed++; mu.Unlock(); killTree(c) }
	})
	t.Setenv("FAKEAGENT_IGNORE_CANCEL", "1") // the old run lingers until the kill
	e.startRun("run-d", "MEG-9", "workspace")
	e.waitUpdate("run-d")

	e.srv.Close(1011, "network blip") // not terminal: the client reconnects
	e.srv.WaitNthFrame(t, "hello", 2)
	select {
	case err := <-e.serveErr:
		t.Fatalf("Serve returned after a reconnectable loss: %v", err)
	default:
	}
	if !e.readReport().Cancelled {
		t.Error("the agent was not told to cancel after the disconnect")
	}

	t.Setenv("FAKEAGENT_SCENARIO", `[{"say":"again"}]`)
	e.welcome(1)
	// The stopped run still occupies its id: the same id is refused, not dropped.
	e.startRun("run-d", "MEG-9", "workspace")
	if rf := e.finished("run-d"); rf.Outcome != "failed" || rf.Error == nil || *rf.Error != "busy" {
		t.Fatalf("re-sent id = %+v", rf)
	}
	// A different run is not blocked by the stopped one (no busy while it winds down).
	e.startRun("run-e", "MEG-10", "workspace")
	if rf := e.finished("run-e"); rf.Outcome != "completed" || rf.Summary != "again" {
		t.Fatalf("run after reconnect = %+v", rf)
	}

	deadline := time.Now().Add(10 * time.Second)
	for e.mgr.Active() != 0 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if n := e.mgr.Active(); n != 0 {
		t.Fatalf("%d runs still active", n)
	}
	mu.Lock()
	if killed == 0 {
		t.Error("the lingering adapter was never killed")
	}
	mu.Unlock()
	time.Sleep(100 * time.Millisecond)
	for _, f := range e.srv.Frames() {
		if f.Conn != 2 || (f.Type != protocol.TypeRunUpdate && f.Type != protocol.TypeRunFinished) {
			continue
		}
		var h struct {
			RunID string  `json:"run_id"`
			Error *string `json:"error"`
		}
		_ = json.Unmarshal(f.Raw, &h)
		if h.RunID == "run-d" && !(f.Type == protocol.TypeRunFinished && h.Error != nil && *h.Error == "busy") {
			t.Errorf("stale run sent %s on the new connection", f.Type)
		}
	}
}

func TestCancelKillsAgentThatIgnoresCancel(t *testing.T) {
	var mu sync.Mutex
	var killed int
	e := newEnvWithCache(t, sleeping, 1, t.TempDir(), func(m *Manager) {
		m.CancelGrace = 200 * time.Millisecond
		m.Kill = func(c *exec.Cmd) { mu.Lock(); killed++; mu.Unlock(); killTree(c) }
	})
	t.Setenv("FAKEAGENT_IGNORE_CANCEL", "1")
	e.startRun("run-i", "MEG-11", "workspace")
	e.waitUpdate("run-i")
	if err := e.srv.Send(protocol.RunCancel{Type: protocol.TypeRunCancel, RunID: "run-i"}); err != nil {
		t.Fatal(err)
	}
	if rf := e.finished("run-i"); rf.Outcome != "cancelled" {
		t.Fatalf("finished = %+v", rf)
	}
	mu.Lock()
	defer mu.Unlock()
	if killed == 0 {
		t.Fatal("the adapter that ignored session/cancel was not killed")
	}
}

func TestRunFailuresReportStableCodesOnly(t *testing.T) {
	e := newEnvWithCache(t, "[]", 1, t.TempDir())
	// A binding exists for another project only.
	if err := e.srv.Send(protocol.RunStart{Type: protocol.TypeRunStart, RunID: "run-n", AgentID: "agent-1",
		Task: protocol.RunTask{Key: "MEG-1", Title: "t", ProjectKey: "OTHER"}, LocalPath: e.repo, Policy: "workspace", Prompt: "p"}); err != nil {
		t.Fatal(err)
	}
	if rf := e.finished("run-n"); rf.Error == nil || *rf.Error != "not_bound" {
		t.Fatalf("finished = %+v", rf)
	}
	// Bad policy: stable code, and no worktree or branch is left behind.
	e.startRun("run-p", "MEG-2", "bogus")
	if rf := e.finished("run-p"); rf.Error == nil || *rf.Error != "unknown_policy" {
		t.Fatalf("finished = %+v", rf)
	}
	if _, err := os.Stat(e.worktree("MEG-2")); err == nil {
		t.Error("a run with an unknown policy created a worktree")
	}
	// A worktree failure (unsafe task key) reports a code with no git or path text.
	e.startRun("run-w", "../evil", "workspace")
	rf := e.finished("run-w")
	if rf.Error == nil || *rf.Error != "worktree_failed" {
		t.Fatalf("finished = %+v", rf)
	}
	b, err := os.ReadFile(filepath.Join(e.cache, "logs", "run-w.log"))
	if err != nil || !strings.Contains(string(b), "worktree") {
		t.Errorf("the full error should be in the run log: %q, %v", b, err)
	}
}

func TestNoUpdateAfterFinish(t *testing.T) {
	var mu sync.Mutex
	var sent []any
	m := New(func(v any) error { mu.Lock(); sent = append(sent, v); mu.Unlock(); return nil }, t.TempDir())
	r := &run{m: m, id: "r"}
	r.emit("message", map[string]any{"text": "a"})
	r.closeEmit()
	r.emit("message", map[string]any{"text": "late"})
	mu.Lock()
	defer mu.Unlock()
	if len(sent) != 1 {
		t.Fatalf("sent %d messages, want 1 (nothing after close)", len(sent))
	}
}

func TestProbeRejectsEmptyOrRelativeBindingPath(t *testing.T) {
	m := New(func(any) error { return nil }, t.TempDir())
	m.LookPath = func(string) (string, error) { return "x", nil }
	m.HandleWelcome(protocol.Welcome{Agents: []protocol.WelcomeAgent{
		{AgentID: "e", Bindings: []protocol.WelcomeBinding{{ProjectKey: "A", LocalPath: ""}}},
		{AgentID: "r", Bindings: []protocol.WelcomeBinding{{ProjectKey: "A", LocalPath: "."}}},
	}})
	for _, a := range m.Probe() {
		if a.Available || len(a.Problems) != 1 || !strings.Contains(a.Problems[0], "not an absolute path") {
			t.Errorf("agent %s = %+v", a.AgentID, a)
		}
	}
}
