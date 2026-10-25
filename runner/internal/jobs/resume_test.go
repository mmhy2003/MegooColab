package jobs

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

const runToken = "mgr_SECRET-run-token-0123456789"

// mcpEndpoint is an HTTP MCP server that records what it is asked.
type mcpEndpoint struct {
	*httptest.Server
	mu    sync.Mutex
	calls []mcpCall
}

type mcpCall struct {
	Auth   string
	Method string
	Tool   string
}

func newMcpEndpoint(t *testing.T) *mcpEndpoint {
	t.Helper()
	m := &mcpEndpoint{}
	m.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			ID     json.RawMessage `json:"id"`
			Method string          `json:"method"`
			Params struct {
				Name string `json:"name"`
			} `json:"params"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		m.mu.Lock()
		m.calls = append(m.calls, mcpCall{Auth: r.Header.Get("Authorization"), Method: req.Method, Tool: req.Params.Name})
		m.mu.Unlock()
		result := `{"content":[{"type":"text","text":"done"}],"isError":false}`
		if req.Method == "initialize" {
			result = `{"protocolVersion":"2025-03-26","capabilities":{},"serverInfo":{"name":"t","version":"0"}}`
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"jsonrpc":"2.0","id":` + string(req.ID) + `,"result":` + result + `}`))
	}))
	t.Cleanup(m.Close)
	return m
}

func (m *mcpEndpoint) recorded() []mcpCall {
	m.mu.Lock()
	defer m.mu.Unlock()
	return append([]mcpCall(nil), m.calls...)
}

type fullReport struct {
	Prompts       []string        `json:"prompts"`
	SessionEvents []string        `json:"session_events"`
	Replayed      int             `json:"replayed"`
	McpServers    json.RawMessage `json:"mcp_servers"`
	Meta          json.RawMessage `json:"meta"`
	ModesSet      []string        `json:"modes_set"`
	Steps         []struct {
		Type   string `json:"type"`
		Tool   string `json:"tool"`
		OK     *bool  `json:"ok"`
		Result string `json:"result"`
		Error  string `json:"error"`
	} `json:"steps"`
}

// finalReport reads the fake agent's report once the run is over.
func (e *env) finalReport() fullReport {
	e.t.Helper()
	b, err := os.ReadFile(e.report)
	if err != nil {
		e.t.Fatal(err)
	}
	var r fullReport
	if err := json.Unmarshal(b, &r); err != nil {
		e.t.Fatal(err)
	}
	return r
}

func (e *env) runLog(runID string) string {
	e.t.Helper()
	b, err := os.ReadFile(filepath.Join(e.cache, "logs", runID+".log"))
	if err != nil {
		e.t.Fatal(err)
	}
	return string(b)
}

func withMcp(url string) func(*protocol.RunStart) {
	return func(rs *protocol.RunStart) { rs.Mcp = &protocol.McpAccess{URL: url, Token: runToken} }
}

func TestMcpServerPassedWithBearerHeader(t *testing.T) {
	ep := newMcpEndpoint(t)
	e := newEnvWithCache(t, `[{"mcp_call":{"tool":"submit_plan","args":{"n":1}}}]`, 1, t.TempDir())
	e.startRunWith("run-mcp", "MEG-1", withMcp(ep.URL+"/api/mcp"))
	if rf := e.finished("run-mcp"); rf.Outcome != "completed" {
		t.Fatalf("finished = %+v", rf)
	}
	r := e.finalReport()
	var servers []struct {
		Type    string `json:"type"`
		Name    string `json:"name"`
		URL     string `json:"url"`
		Headers []struct{ Name, Value string }
	}
	if err := json.Unmarshal(r.McpServers, &servers); err != nil || len(servers) != 1 {
		t.Fatalf("mcp servers = %s, %v", r.McpServers, err)
	}
	s := servers[0]
	if s.Type != "http" || s.Name != "megoocolab" || s.URL != ep.URL+"/api/mcp" ||
		len(s.Headers) != 1 || s.Headers[0].Name != "Authorization" || s.Headers[0].Value != "Bearer "+runToken {
		t.Fatalf("server = %+v", s)
	}
	if len(r.Steps) != 1 || r.Steps[0].Type != "mcp_call" || r.Steps[0].OK == nil || !*r.Steps[0].OK {
		t.Fatalf("steps = %+v", r.Steps)
	}
	calls := ep.recorded()
	if len(calls) != 2 || calls[0].Method != "initialize" || calls[1].Method != "tools/call" || calls[1].Tool != "submit_plan" {
		t.Fatalf("calls = %+v", calls)
	}
	for _, c := range calls {
		if c.Auth != "Bearer "+runToken {
			t.Fatalf("call %+v lacks the bearer header", c)
		}
	}
}

func TestRunWithoutMcpPassesNoServers(t *testing.T) {
	e := newEnvWithCache(t, `[{"say":"hi"}]`, 1, t.TempDir())
	e.startRun("run-v1", "MEG-2", "workspace")
	e.finished("run-v1")
	if got := strings.TrimSpace(string(e.finalReport().McpServers)); got != "[]" {
		t.Fatalf("mcp servers = %s, want none", got)
	}
}

func TestMcpHttpUnsupportedFailsRun(t *testing.T) {
	t.Setenv("FAKEAGENT_NO_MCP_HTTP", "1")
	e := newEnvWithCache(t, `[{"say":"never"}]`, 1, t.TempDir())
	e.startRunWith("run-nohttp", "MEG-3", withMcp("http://127.0.0.1:1/api/mcp"))
	rf := e.finished("run-nohttp")
	if rf.Outcome != "failed" || rf.Error == nil || *rf.Error != "mcp_http_unsupported" {
		t.Fatalf("finished = %+v", rf)
	}
	if rf.SessionID != nil {
		t.Fatalf("no session should have been created, got %q", *rf.SessionID)
	}
	if got := e.runLog("run-nohttp"); !strings.Contains(got, "mcp_http_unsupported") {
		t.Fatalf("log = %q", got)
	}
}

const twoTurns = `[
 {"if_prompt_contains":"first turn","then":[{"say":"REPLAYED-HISTORY"}]},
 {"if_prompt_contains":"continue please","then":[{"say":"fresh answer"}]},
 {"if_prompt_contains":"full prompt","then":[{"say":"started over"}]}
]`

func messages(e *env, runID string) string {
	var sb strings.Builder
	for _, u := range e.updates(runID) {
		if u.Kind == "message" {
			sb.WriteString(u.Data["text"].(string))
		}
	}
	return sb.String()
}

func TestResumeUsesLoadSessionAndDropsReplay(t *testing.T) {
	t.Setenv("FAKEAGENT_SESSIONS_DIR", t.TempDir())
	e := newEnvWithCache(t, twoTurns, 1, t.TempDir())
	e.startRunWith("run-a", "MEG-4", func(rs *protocol.RunStart) { rs.Prompt = "first turn" })
	first := e.finished("run-a")
	if first.SessionID == nil {
		t.Fatalf("finished = %+v", first)
	}

	e.startRunWith("run-b", "MEG-4", func(rs *protocol.RunStart) {
		rs.Prompt = "full prompt"
		rs.ResumeSessionID = *first.SessionID
		rs.ResumePrompt = "continue please"
		withMcp("http://127.0.0.1:1/api/mcp")(rs)
	})
	rf := e.finished("run-b")
	if rf.Outcome != "completed" || rf.SessionID == nil || *rf.SessionID != *first.SessionID {
		t.Fatalf("finished = %+v", rf)
	}
	r := e.finalReport()
	if len(r.SessionEvents) != 1 || r.SessionEvents[0] != "load:"+*first.SessionID {
		t.Fatalf("session events = %v", r.SessionEvents)
	}
	if len(r.Prompts) != 1 || r.Prompts[0] != "continue please" {
		t.Fatalf("prompts = %v", r.Prompts)
	}
	if r.Replayed == 0 {
		t.Fatal("the fake agent replayed nothing, so the test proves nothing")
	}
	if got := messages(e, "run-b"); got != "fresh answer" {
		t.Fatalf("run updates carry %q; the replayed history must be dropped", got)
	}
	var servers []map[string]any
	if json.Unmarshal(r.McpServers, &servers) != nil || len(servers) != 1 {
		t.Fatalf("load request carried mcp servers %s", r.McpServers)
	}
}

func TestResumeUsesResumeSessionWhenAdvertised(t *testing.T) {
	t.Setenv("FAKEAGENT_SESSIONS_DIR", t.TempDir())
	t.Setenv("FAKEAGENT_RESUME", "1")
	e := newEnvWithCache(t, twoTurns, 1, t.TempDir())
	e.startRunWith("run-a", "MEG-5", func(rs *protocol.RunStart) { rs.Prompt = "first turn" })
	first := e.finished("run-a")
	e.startRunWith("run-b", "MEG-5", func(rs *protocol.RunStart) {
		rs.ResumeSessionID, rs.ResumePrompt = *first.SessionID, "continue please"
	})
	rf := e.finished("run-b")
	r := e.finalReport()
	if rf.Outcome != "completed" || len(r.SessionEvents) != 1 || r.SessionEvents[0] != "resume:"+*first.SessionID || r.Replayed != 0 {
		t.Fatalf("finished = %+v, report = %+v", rf, r)
	}
	if got := messages(e, "run-b"); got != "fresh answer" {
		t.Fatalf("messages = %q", got)
	}
}

func TestResumeWithEmptyResumePromptUsesPrompt(t *testing.T) {
	t.Setenv("FAKEAGENT_SESSIONS_DIR", t.TempDir())
	e := newEnvWithCache(t, twoTurns, 1, t.TempDir())
	e.startRunWith("run-a", "MEG-6", func(rs *protocol.RunStart) { rs.Prompt = "first turn" })
	first := e.finished("run-a")
	e.startRunWith("run-b", "MEG-6", func(rs *protocol.RunStart) {
		rs.Prompt, rs.ResumeSessionID = "full prompt", *first.SessionID
	})
	e.finished("run-b")
	if r := e.finalReport(); len(r.Prompts) != 1 || r.Prompts[0] != "full prompt" {
		t.Fatalf("prompts = %v", r.Prompts)
	}
}

func TestResumeFallbackToNewSessionWithFullPrompt(t *testing.T) {
	cases := map[string]struct{ env, id string }{
		"session/load fails":   {"", "fake-session-404"},
		"no load or resume":    {"FAKEAGENT_NO_LOAD", "fake-session-404"},
		"session/resume fails": {"FAKEAGENT_RESUME", "fake-session-404"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			t.Setenv("FAKEAGENT_SESSIONS_DIR", t.TempDir())
			if c.env != "" {
				t.Setenv(c.env, "1")
			}
			e := newEnvWithCache(t, twoTurns, 1, t.TempDir())
			e.startRunWith("run-fb", "MEG-7", func(rs *protocol.RunStart) {
				rs.Prompt, rs.ResumePrompt, rs.ResumeSessionID = "full prompt", "continue please", c.id
			})
			rf := e.finished("run-fb")
			if rf.Outcome != "completed" || rf.SessionID == nil {
				t.Fatalf("finished = %+v", rf)
			}
			r := e.finalReport()
			last := r.SessionEvents[len(r.SessionEvents)-1]
			if !strings.HasPrefix(last, "new:") || last != "new:"+*rf.SessionID {
				t.Fatalf("events = %v, reported session %q", r.SessionEvents, *rf.SessionID)
			}
			if len(r.Prompts) != 1 || r.Prompts[0] != "full prompt" {
				t.Fatalf("prompts = %v", r.Prompts)
			}
			if got := messages(e, "run-fb"); got != "started over" {
				t.Fatalf("messages = %q", got)
			}
			if log := e.runLog("run-fb"); !strings.Contains(log, "runner: resume_fallback: ") {
				t.Fatalf("log = %q", log)
			}
		})
	}
}

func TestTokenNotInRunLog(t *testing.T) {
	t.Setenv("FAKEAGENT_ECHO_MCP", "1") // the agent writes its mcpServers, token included, to stderr
	e := newEnvWithCache(t, `[{"say":"hi"}]`, 1, t.TempDir())
	e.startRunWith("run-tok", "MEG-8", withMcp("http://127.0.0.1:1/api/mcp"))
	e.finished("run-tok")
	log := e.runLog("run-tok")
	if !strings.Contains(log, "mcpServers") {
		t.Fatalf("the agent's stderr never reached the log, so the test proves nothing: %q", log)
	}
	if strings.Contains(log, runToken) {
		t.Fatalf("the run log holds the token:\n%s", log)
	}
	if !strings.Contains(log, "[redacted]") {
		t.Fatalf("log = %q", log)
	}
	for _, f := range e.srv.Frames() {
		if strings.Contains(string(f.Raw), runToken) {
			t.Fatalf("a frame to the server holds the token: %s", f.Raw)
		}
	}
}

func TestRedactingWriterCatchesATokenSplitAcrossWrites(t *testing.T) {
	var sb strings.Builder
	w := newRedactor(&sb, "abcdef")
	for _, part := range []string{"x abc", "d", "ef y ab", "c z"} {
		if _, err := w.Write([]byte(part)); err != nil {
			t.Fatal(err)
		}
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	if got := sb.String(); got != "x [redacted] y abc z" {
		t.Fatalf("got %q", got)
	}
}

func compact(t *testing.T, raw json.RawMessage) string {
	t.Helper()
	var b bytes.Buffer
	if err := json.Compact(&b, raw); err != nil {
		t.Fatal(err)
	}
	return b.String()
}

// A resumed session gets the same isolation _meta and the same mode as a new one.
func TestResumedSessionGetsMetaAndModeLikeANewOne(t *testing.T) {
	for name, env := range map[string]string{"session/load": "", "session/resume": "FAKEAGENT_RESUME"} {
		t.Run(name, func(t *testing.T) {
			t.Setenv("FAKEAGENT_SESSIONS_DIR", t.TempDir())
			if env != "" {
				t.Setenv(env, "1")
			}
			e := newEnvWithCache(t, twoTurns, 1, t.TempDir())
			e.startRunWith("run-a", "MEG-9", func(rs *protocol.RunStart) { rs.Prompt = "first turn" })
			first := e.finished("run-a")
			fresh := e.finalReport()
			if len(fresh.Meta) == 0 || len(fresh.ModesSet) != 1 {
				t.Fatalf("new session report = %+v", fresh)
			}
			e.startRunWith("run-b", "MEG-9", func(rs *protocol.RunStart) {
				rs.ResumeSessionID, rs.ResumePrompt = *first.SessionID, "continue please"
			})
			e.finished("run-b")
			got := e.finalReport()
			if compact(t, got.Meta) != compact(t, fresh.Meta) {
				t.Fatalf("meta = %s, new session had %s", got.Meta, fresh.Meta)
			}
			if strings.Join(got.ModesSet, ",") != strings.Join(fresh.ModesSet, ",") {
				t.Fatalf("modes set = %v, new session had %v", got.ModesSet, fresh.ModesSet)
			}
		})
	}
}

// Whatever the agent says, the run token never leaves the runner in a
// run_update or in run_finished, whole or split across flushes.
func TestTokenNotInRunUpdatesOrSummary(t *testing.T) {
	scenarios := map[string]string{
		"one chunk": `[{"say":"the token is ` + runToken + ` ok"}]`,
		"split across flushes": `[{"say":"the token is ` + runToken[:12] + `"},{"plan":[["a","pending"]]},` +
			`{"say":"` + runToken[12:] + ` ok"}]`,
		"ends on a token prefix": `[{"say":"all done ` + runToken[:20] + `"}]`,
		"tool title":             `[{"tool":{"kind":"other","title":"echo ` + runToken + `"}}]`,
	}
	for name, sc := range scenarios {
		t.Run(name, func(t *testing.T) {
			e := newEnvWithCache(t, sc, 1, t.TempDir())
			e.startRunWith("run-leak", "MEG-10", withMcp("http://127.0.0.1:1/api/mcp"))
			rf := e.finished("run-leak")
			if rf.Outcome != "completed" {
				t.Fatalf("finished = %+v", rf)
			}
			frames := 0
			for _, f := range e.srv.Frames() {
				if f.Type == protocol.TypeRunUpdate || f.Type == protocol.TypeRunFinished {
					frames++
					if strings.Contains(string(f.Raw), runToken) || strings.Contains(string(f.Raw), runToken[:20]) {
						t.Fatalf("frame leaks the token: %s", f.Raw)
					}
				}
			}
			if strings.Contains(messages(e, "run-leak"), runToken) {
				t.Fatalf("messages put together hold the token: %q", messages(e, "run-leak"))
			}
			if frames < 2 {
				t.Fatalf("only %d frames", frames)
			}
			if name == "one chunk" && !strings.Contains(messages(e, "run-leak"), "[redacted]") {
				t.Fatalf("messages = %q", messages(e, "run-leak"))
			}
		})
	}
}

// A title (or command) the adapter cuts at 200 (100) characters is redacted
// before it is cut, so a token straddling the cut leaves no usable prefix.
func TestCutTitleOrCommandKeepsNoTokenPrefix(t *testing.T) {
	scenarios := map[string]string{
		"title":   `[{"tool":{"kind":"other","title":"` + strings.Repeat("x", 190) + runToken + ` tail"}}]`,
		"command": `[{"exec":{"command":"` + strings.Repeat("x", 90) + runToken + `"}}]`,
	}
	for name, sc := range scenarios {
		t.Run(name, func(t *testing.T) {
			e := newEnvWithCache(t, sc, 1, t.TempDir())
			e.startRunWith("run-cut", "MEG-11", withMcp("http://127.0.0.1:1/api/mcp"))
			e.finished("run-cut")
			n := 0
			for _, f := range e.srv.Frames() {
				if f.Type != protocol.TypeRunUpdate {
					continue
				}
				n++
				if strings.Contains(string(f.Raw), runToken[:9]) { // "mgr_" + 5 characters
					t.Fatalf("a cut string keeps a token prefix: %s", f.Raw)
				}
			}
			if n == 0 {
				t.Fatal("no updates")
			}
		})
	}
}

// The adapter's output counts against the log cap; the runner's own lines never do.
func TestRunnerLogLinesSurviveTheCap(t *testing.T) {
	t.Setenv("FAKEAGENT_ECHO_MCP", "1")
	e := newEnvWithCache(t, `[{"stop":"refusal"}]`, 1, t.TempDir(), func(m *Manager) { m.LogCap = 40 })
	e.startRunWith("run-cap", "MEG-12", withMcp("http://127.0.0.1:1/api/mcp"))
	rf := e.finished("run-cap")
	if rf.Error == nil || *rf.Error != "stopped:refusal" {
		t.Fatalf("finished = %+v", rf)
	}
	log := e.runLog("run-cap")
	if !strings.Contains(log, "[log truncated]") || !strings.Contains(log, "runner: stopped:refusal") {
		t.Fatalf("log = %q", log)
	}
	if strings.Contains(log, runToken) {
		t.Fatalf("log holds the token: %q", log)
	}
}

// With the cap falling inside the token, the output must hold no piece of it:
// the token is replaced first and the cap cuts the replacement.
func TestStderrCapNeverCutsTheTokenOpen(t *testing.T) {
	var sb strings.Builder
	_, stderr, closeAll := logWriters(&sb, 10, "abcdef")
	_, _ = stderr.Write([]byte("0123456 abcdef"))
	closeAll()
	got := sb.String()
	if strings.Contains(got, "ab") || !strings.HasPrefix(got, "0123456 [r") {
		t.Fatalf("log = %q", got)
	}
}

func TestRunnerLinesAreNotCappedButAreRedacted(t *testing.T) {
	var sb strings.Builder
	runner, stderr, closeAll := logWriters(&sb, 5, "abcdef")
	_, _ = stderr.Write([]byte("0123456789"))
	_, _ = runner.Write([]byte("runner: failed abcdef\n"))
	closeAll()
	if got := sb.String(); !strings.Contains(got, "runner: failed [redacted]\n") {
		t.Fatalf("log = %q", got)
	}
}

func TestRedactorCloseReleasesShortTailsAndWithholdsLongOnes(t *testing.T) {
	for in, want := range map[string]string{
		"x abc":   "x abc",        // 3 characters: released as they are
		"x abcd":  "x abcd",       // 4 characters
		"x abcde": "x [redacted]", // longer than 4: could be most of the token
	} {
		var sb strings.Builder
		w := newRedactor(&sb, "abcdefghij")
		_, _ = w.Write([]byte(in))
		_ = w.Close()
		if sb.String() != want {
			t.Errorf("%q -> %q, want %q", in, sb.String(), want)
		}
	}
}
