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
		// the adapter that never answers: it says it is running (for a test to wait on), then hangs
		if started := os.Getenv("JOBS_TEST_HANG_STARTED"); started != "" {
			_ = os.WriteFile(started, nil, 0o644)
		}
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

// startRunWith is startRun for a workflow run: tweak adds the v2 fields.
func (e *env) startRunWith(runID, key string, tweak func(*protocol.RunStart)) {
	e.t.Helper()
	rs := protocol.RunStart{
		Type: protocol.TypeRunStart, RunID: runID, AgentID: "agent-1",
		Task:      protocol.RunTask{Key: key, Title: "Do the thing", ProjectKey: "MEG"},
		LocalPath: e.repo, Policy: "workspace", Prompt: "please",
	}
	tweak(&rs)
	if err := e.srv.Send(rs); err != nil {
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
	ModelsSet []string        `json:"models_set"`
	Prompts   []string        `json:"prompts"`
	Cancelled bool            `json:"cancelled"`
	Steps     []struct {
		Type    string `json:"type"`
		Exists  *bool  `json:"exists"`
		Content string `json:"content"`
	} `json:"steps"`
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
	if !strings.Contains(string(r.Meta), `"allowedTools":["mcp__megoocolab"]`) {
		t.Errorf("session meta = %s", r.Meta)
	}
	// not plan mode, which blocks MegooColab's MCP tools; the denied write above is the policy at work
	if strings.Join(r.ModesSet, ",") != "default" {
		t.Errorf("modes set = %v, want [default]", r.ModesSet)
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
	started := filepath.Join(t.TempDir(), "started")
	t.Setenv("JOBS_TEST_HANG_STARTED", started)
	e.startRun("run-h", "MEG-4", "workspace")
	// cancel only once the adapter process runs (Initialize then blocks on it): a fixed wait was too short on
	// slow CI machines, where the cancel came before there was a process to kill
	deadline := time.Now().Add(30 * time.Second)
	for {
		if _, err := os.Stat(started); err == nil {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("the adapter process never started")
		}
		time.Sleep(10 * time.Millisecond)
	}
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
	take := func(id string) bool {
		m.mu.Lock()
		defer m.mu.Unlock()
		return m.takeEarlyCancelLocked(id)
	}
	if take("r0") {
		t.Error("the oldest remembered cancel should have been dropped")
	}
	if !take(fmt.Sprintf("r%d", earlyCancelLimit+9)) {
		t.Error("the newest cancel was forgotten")
	}
	if take(fmt.Sprintf("r%d", earlyCancelLimit+9)) {
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
	// The kill blocks until the test has made its assertions, so the stopped run
	// is certain to still be alive while they run.
	release := make(chan struct{})
	var releaseOnce sync.Once
	open := func() { releaseOnce.Do(func() { close(release) }) }
	e := newEnvWithCache(t, sleeping, 1, t.TempDir(), func(m *Manager) {
		m.CancelGrace = 100 * time.Millisecond
		m.Kill = func(c *exec.Cmd) {
			<-release
			mu.Lock()
			killed++
			mu.Unlock()
			killTree(c)
		}
	})
	t.Cleanup(open)
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

	open() // assertions done: let the lingering adapter be killed
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

func TestRunStartFromLostConnectionIsNotLaunched(t *testing.T) {
	var mu sync.Mutex
	var sent []any
	m := New(func(v any) error { mu.Lock(); sent = append(sent, v); mu.Unlock(); return nil }, t.TempDir())
	m.HandleWelcome(protocol.Welcome{Agents: []protocol.WelcomeAgent{{AgentID: "agent-1", MaxConcurrentRuns: 1}}})
	mu.Lock()
	sent = nil
	mu.Unlock()

	raw, _ := json.Marshal(protocol.RunStart{Type: protocol.TypeRunStart, RunID: "run-old", AgentID: "agent-1",
		Task: protocol.RunTask{Key: "MEG-1", Title: "t", ProjectKey: "MEG"}, Policy: "workspace", Prompt: "p"})
	buffered := protocol.Envelope{Type: protocol.TypeRunStart, Raw: raw, Conn: 1}

	m.StopAllUpTo(1) // connection 1 was lost before the buffered run_start was dispatched
	m.Dispatch(context.Background(), buffered)
	if m.Active() != 0 {
		t.Fatal("a run_start from the lost connection was launched")
	}
	mu.Lock()
	defer mu.Unlock()
	if len(sent) != 0 {
		t.Fatalf("sent %v for a run the server already failed", sent)
	}
	// A run_start from the next connection is still accepted.
	buffered.Conn = 2
	m.mu.Lock()
	ok := buffered.Conn > m.ended
	m.mu.Unlock()
	if !ok {
		t.Fatal("the new connection must not count as lost")
	}
}

func TestStopCodesAreLogged(t *testing.T) {
	e := newEnvWithCache(t, `[{"stop":"refusal"}]`, 1, t.TempDir())
	e.startRun("run-s", "MEG-12", "workspace")
	rf := e.finished("run-s")
	if rf.Error == nil || *rf.Error != "stopped:refusal" {
		t.Fatalf("finished = %+v", rf)
	}
	e.startRun("run-q", "MEG-13", "bogus")
	e.finished("run-q")
	for id, want := range map[string]string{"run-s": "stopped:refusal", "run-q": "unknown_policy"} {
		b, err := os.ReadFile(filepath.Join(e.cache, "logs", id+".log"))
		if err != nil || !strings.Contains(string(b), want) {
			t.Errorf("log of %s = %q, %v; want it to name %q", id, b, err, want)
		}
	}
}

// A read-only Claude turn in plan mode ends "cancelled" on its own when the
// denied switch_mode ("Approve Plan") stops it: the runner did not ask for
// that, so the analysis counts as completed. Under workspace nothing changes.
func TestReadOnlyTurnCancelledByTheAgentCompletes(t *testing.T) {
	const selfCancelled = `[{"say":"Here is my analysis"},{"stop":"cancelled"}]`
	e := newEnvWithCache(t, selfCancelled, 1, t.TempDir())
	e.startRun("run-ro", "MEG-20", "read_only")
	if rf := e.finished("run-ro"); rf.Outcome != "completed" || rf.Summary != "Here is my analysis" || rf.Error != nil {
		t.Fatalf("read-only finished = %+v", rf)
	}
	e.startRun("run-ws", "MEG-21", "workspace")
	if rf := e.finished("run-ws"); rf.Outcome != "cancelled" {
		t.Fatalf("workspace finished = %+v", rf)
	}
}

// A cancel the runner asked for stays "cancelled" under read-only too.
func TestReadOnlyRequestedCancelStaysCancelled(t *testing.T) {
	e := newEnvWithCache(t, sleeping, 1, t.TempDir())
	e.startRun("run-c", "MEG-22", "read_only")
	e.waitUpdate("run-c")
	if err := e.srv.Send(protocol.RunCancel{Type: protocol.TypeRunCancel, RunID: "run-c"}); err != nil {
		t.Fatal(err)
	}
	if rf := e.finished("run-c"); rf.Outcome != "cancelled" {
		t.Fatalf("finished = %+v", rf)
	}
}

func TestRunFinishedCarriesGitStates(t *testing.T) {
	e := newEnvWithCache(t, `[{"commit":{"message":"agent work"}},{"say":"done"}]`, 1, t.TempDir())
	e.startRun("run-git", "MEG-10", "workspace")

	rf := e.finished("run-git")
	if rf.Outcome != "completed" || rf.SessionID == nil || *rf.SessionID != "fake-session-1" {
		t.Fatalf("finished = %+v", rf)
	}
	b, a := rf.GitBefore, rf.GitAfter
	if b == nil || a == nil || b.Head == nil || a.Head == nil || *a.Head == *b.Head || a.Dirty || b.Dirty {
		t.Fatalf("git_before = %+v, git_after = %+v", b, a)
	}
	if b.Branch == nil || *b.Branch != "megoo/MEG-10-do-the-thing" {
		t.Fatalf("branch = %q", *b.Branch)
	}
}

func TestWorkflowRunMaterializesFilesAndCommitsDocsBeforeGitBefore(t *testing.T) {
	scenario := `[{"report_file":{"path":".megoocolab/plan.md"}},{"commit":{"message":"agent work"}}]`
	e := newEnvWithCache(t, scenario, 1, t.TempDir())
	e.startRunWith("run-wf", "MEG-11", func(rs *protocol.RunStart) {
		rs.Files = []protocol.File{{Path: ".megoocolab/plan.md", Content: "the plan"}}
		rs.RepoFiles = []protocol.File{{Path: "docs/superpowers/specs/d.md", Content: "# design"}}
		rs.CommitMessage = "docs: design"
	})
	rf := e.finished("run-wf")
	if rf.Outcome != "completed" || rf.GitBefore == nil || rf.GitAfter == nil {
		t.Fatalf("finished = %+v", rf)
	}
	r := e.readReport()
	if len(r.Steps) < 1 || r.Steps[0].Exists == nil || !*r.Steps[0].Exists || r.Steps[0].Content != "the plan" {
		t.Fatalf("agent saw %+v", r.Steps)
	}
	wt := e.worktree("MEG-11")
	log, err := exec.Command("git", "-C", wt, "log", "--format=%s", "-3").Output()
	if err != nil || !strings.HasPrefix(string(log), "agent work\ndocs: design\n") {
		t.Fatalf("log = %q, %v", log, err)
	}
	// the docs commit is the starting point (git_before), not part of the agent's change
	head, _ := exec.Command("git", "-C", wt, "rev-parse", "HEAD~1").Output()
	if strings.TrimSpace(string(head)) != *rf.GitBefore.Head {
		t.Fatalf("git_before head %s is not the docs commit %s", *rf.GitBefore.Head, head)
	}
	if rf.GitBefore.Dirty || rf.GitAfter.Dirty {
		t.Fatal(".megoocolab must not make the tree dirty")
	}
}

func TestBadFilesFailTheRunWithStableCode(t *testing.T) {
	for code, tweak := range map[string]func(*protocol.RunStart){
		"files_failed": func(rs *protocol.RunStart) {
			rs.Files = []protocol.File{{Path: "../escape", Content: "x"}}
		},
		"commit_failed": func(rs *protocol.RunStart) {
			rs.RepoFiles = []protocol.File{{Path: "outside/x.md", Content: "x"}}
			rs.CommitMessage = "m"
		},
	} {
		t.Run(code, func(t *testing.T) {
			e := newEnvWithCache(t, `[{"say":"never"}]`, 1, t.TempDir())
			e.startRunWith("run-bad", "MEG-12", tweak)
			rf := e.finished("run-bad")
			if rf.Outcome != "failed" || rf.Error == nil || *rf.Error != code {
				t.Fatalf("finished = %+v", rf)
			}
			if rf.GitBefore == nil || rf.GitAfter == nil {
				t.Fatal("git states are still reported for a failed run")
			}
			if _, err := os.Stat(filepath.Join(e.cache, "worktrees", "agent-1", "MEG-12", "escape")); err == nil {
				t.Fatal("escaped file written")
			}
		})
	}
}

func TestRunWithoutFilesPrunesStaleMegoocolabFiles(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	e.startRunWith("run-a", "MEG-13", func(rs *protocol.RunStart) {
		rs.Files = []protocol.File{{Path: ".megoocolab/plan.md", Content: "old"}}
	})
	e.finished("run-a")
	stale := filepath.Join(e.worktree("MEG-13"), ".megoocolab", "plan.md")
	if _, err := os.Stat(stale); err != nil {
		t.Fatal(err)
	}
	e.startRunWith("run-b", "MEG-13", func(rs *protocol.RunStart) {})
	e.finished("run-b")
	if _, err := os.Stat(stale); err == nil {
		t.Fatal("stale file survived a run without files")
	}
}

func TestStashMadeBeforeTheRunIsNotTheRunsDoing(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	// a stash made between two runs of the same worktree is part of both snapshots
	e.startRun("run-s1", "MEG-14", "workspace")
	e.finished("run-s1")
	wt := e.worktree("MEG-14")
	if err := os.WriteFile(filepath.Join(wt, "README.md"), []byte("edited"), 0o644); err != nil {
		t.Fatal(err)
	}
	if out, err := exec.Command("git", "-C", wt, "stash").CombinedOutput(); err != nil {
		t.Fatalf("%v %s", err, out)
	}
	e.startRun("run-s2", "MEG-14", "workspace")
	rf := e.finished("run-s2")
	if rf.GitAfter == nil || rf.GitAfter.Dirty {
		t.Fatalf("a stash made before the run is not the run's doing: %+v", rf.GitAfter)
	}
}

// I5: after a dropped connection the server retries the task's run under a new
// id. That run must not share the worktree with the stopped one still winding
// down: its adapter starts only once the old run has fully ended, and it is
// never answered busy.
func TestRetriedRunWaitsForTheStoppedRunOfTheSameTask(t *testing.T) {
	var mu sync.Mutex
	var killedAt time.Time
	release := make(chan struct{})
	var releaseOnce sync.Once
	open := func() { releaseOnce.Do(func() { close(release) }) }
	e := newEnvWithCache(t, sleeping, 1, t.TempDir(), func(m *Manager) {
		m.CancelGrace = 100 * time.Millisecond
		m.Kill = func(c *exec.Cmd) {
			<-release
			killTree(c)
			mu.Lock()
			if killedAt.IsZero() {
				killedAt = time.Now()
			}
			mu.Unlock()
		}
	})
	t.Cleanup(open)
	t.Setenv("FAKEAGENT_IGNORE_CANCEL", "1") // the old run lingers until the kill
	e.startRun("run-old", "MEG-9", "workspace")
	e.waitUpdate("run-old")

	e.srv.Close(1011, "network blip")
	e.srv.WaitNthFrame(t, "hello", 2)
	t.Setenv("FAKEAGENT_SCENARIO", `[{"say":"again"}]`)
	e.welcome(1)
	e.startRun("run-new", "MEG-9", "workspace") // the same task, retried

	time.Sleep(700 * time.Millisecond)
	if n := len(e.updates("run-new")); n != 0 {
		t.Fatalf("the retried run started its adapter while the old one was still alive (%d updates)", n)
	}
	for _, f := range e.srv.Frames() {
		if f.Type == protocol.TypeRunFinished && strings.Contains(string(f.Raw), `"run-new"`) {
			t.Fatalf("the retried run was answered early: %s", f.Raw)
		}
	}

	open()
	rf := e.finished("run-new")
	if rf.Outcome != "completed" || rf.Summary != "again" {
		t.Fatalf("retried run = %+v", rf)
	}
	mu.Lock()
	defer mu.Unlock()
	if killedAt.IsZero() {
		t.Fatal("the old run's adapter was never killed")
	}
}

func TestRunStartsFromBranchAndReports(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	if out, err := exec.Command("git", "-C", e.repo, "branch", "develop").CombinedOutput(); err != nil {
		t.Fatalf("%v: %s", err, out)
	}
	branch := &protocol.RunBranch{Repositories: []protocol.RunBranchRepo{{URL: "https://example.com/acme/meg", DefaultBranch: "develop"}}}
	e.startRunWith("run-b1", "MEG-1", func(rs *protocol.RunStart) { rs.Branch = branch })
	if rf := e.finished("run-b1"); rf.Outcome != "completed" {
		t.Fatalf("finished = %+v", rf)
	}
	ups := e.updates("run-b1")
	if len(ups) == 0 || ups[0].Kind != "branch" || ups[0].Data["start_branch"] != "develop" ||
		ups[0].Data["default_branch"] != "develop" || ups[0].Data["repository_url"] != "https://example.com/acme/meg" {
		t.Fatalf("first update = %+v", ups)
	}
	// the server recorded it: a reused worktree says nothing more
	recorded := *branch
	recorded.StartBranch = "develop"
	e.startRunWith("run-b2", "MEG-1", func(rs *protocol.RunStart) { rs.Branch = &recorded })
	e.finished("run-b2")
	for _, u := range e.updates("run-b2") {
		if u.Kind == "branch" {
			t.Fatal("a reused worktree reported a branch the server already has")
		}
	}
	// the first report was lost (nothing recorded): the next run sends it again
	e.startRunWith("run-b3", "MEG-1", func(rs *protocol.RunStart) { rs.Branch = branch })
	e.finished("run-b3")
	ups = e.updates("run-b3")
	if len(ups) == 0 || ups[0].Kind != "branch" || ups[0].Data["start_branch"] != "develop" {
		t.Fatalf("run-b3 updates = %+v", ups)
	}
}

func TestRunFailsWithStartBranchMissing(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"ok"}]`, 1, t.TempDir())
	e.startRunWith("run-m", "MEG-3", func(rs *protocol.RunStart) {
		rs.Branch = &protocol.RunBranch{BranchFrom: "hotfix-base",
			Repositories: []protocol.RunBranchRepo{{URL: "https://example.com/acme/meg", DefaultBranch: "main"}}}
	})
	if rf := e.finished("run-m"); rf.Error == nil || *rf.Error != "start_branch_missing" {
		t.Fatalf("finished = %+v", rf)
	}
	if _, err := os.Stat(e.worktree("MEG-3")); err == nil {
		t.Error("a worktree was left behind")
	}
}
