// Package jobs runs agent runs end to end: it creates the task worktree,
// launches the agent adapter over ACP with the run's policy, streams
// metadata-only updates to the server and reports how the run ended.
package jobs

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/coder/acp-go-sdk"

	"github.com/mmhy2003/megoocolab/runner/internal/acpclient"
	"github.com/mmhy2003/megoocolab/runner/internal/adapters"
	"github.com/mmhy2003/megoocolab/runner/internal/conn"
	"github.com/mmhy2003/megoocolab/runner/internal/gitstate"
	"github.com/mmhy2003/megoocolab/runner/internal/policy"
	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
	"github.com/mmhy2003/megoocolab/runner/internal/startbranch"
	"github.com/mmhy2003/megoocolab/runner/internal/worktree"
)

const (
	// earlyCancelLimit bounds the set of run ids cancelled before their run_start arrived.
	earlyCancelLimit = 256
	summaryLimit     = 2000
	errorLimit       = 300
	sessionIDLimit   = 200
	logCap           = 5 << 20
	shutdownWait     = 10 * time.Second
	// reapWait is how long a killed adapter gets to exit before its run moves on.
	reapWait = 5 * time.Second
)

var safeRunID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)

// Manager owns the runs of one runner connection.
type Manager struct {
	// Tuning and test hooks; set before Serve.
	LookPath      func(string) (string, error) // default exec.LookPath
	Kill          func(*exec.Cmd)              // kills the adapter's process tree; default killTree
	CancelGrace   time.Duration                // wait after session/cancel before killing; default 10 s
	ExitGrace     time.Duration                // wait for the adapter to exit after a finished turn; default 2 s
	FlushInterval time.Duration                // message coalescing interval; 0 keeps the default
	LogCap        int                          // bytes of adapter output kept per run log; default 5 MiB

	send      func(any) error
	cacheRoot string

	mu       sync.Mutex
	agents   map[string]protocol.WelcomeAgent
	order    []string // agent ids in welcome order
	runs     map[string]*run
	early    []string // run ids cancelled before they started, oldest first
	reported map[string]string
	closed   bool
	gen      int // connection generation; bumped by StopAll
	ended    int // highest connection number known to be lost
	wg       sync.WaitGroup
}

// New builds a manager. send writes a message to the server (conn.Client.Send).
func New(send func(any) error, cacheRoot string) *Manager {
	gitstate.SetHooksDir(filepath.Join(cacheRoot, "empty-hooks"))
	return &Manager{
		LookPath:    exec.LookPath,
		Kill:        killTree,
		CancelGrace: 10 * time.Second,
		ExitGrace:   2 * time.Second,
		LogCap:      logCap,
		send:        send,
		cacheRoot:   cacheRoot,
		agents:      map[string]protocol.WelcomeAgent{},
		runs:        map[string]*run{},
		reported:    map[string]string{},
	}
}

// run is one run in flight.
type run struct {
	m      *Manager
	id     string
	agent  string
	task   string
	prev   []*run // stopped runs of the same agent and task, still winding down
	ctx    context.Context
	abort  context.CancelFunc
	done   chan struct{}
	gen    int // the manager's generation when the run started
	client *acpclient.Client
	emitMu sync.Mutex // serializes seq assignment and sending
	seq    int
	closed bool // no more updates once run_finished is due

	mu              sync.Mutex
	cancelRequested bool
	conn            *acp.ClientSideConnection
	session         acp.SessionId
	cmd             *exec.Cmd
	summary         string
	sessionID       string
	gitBefore       *protocol.GitState
	gitAfter        *protocol.GitState
	snapBefore      *gitstate.Snapshot

	// secret is the run's MCP token; it never leaves in an update or the summary.
	// held is the end of the message text so far that may be the start of it.
	secret string
	held   string // guarded by emitMu
}

// emit sends one metadata update with the next seq. The acpclient calls it in order.
func (r *run) emit(kind string, data map[string]any) {
	r.emitMu.Lock()
	defer r.emitMu.Unlock()
	if r.closed || r.stale() {
		return
	}
	if r.secret != "" {
		if kind == "message" {
			data = r.redactMessage(data)
			if data == nil {
				return
			}
		} else {
			data = redactMap(data, r.secret)
		}
	}
	r.sendLocked(kind, data)
}

// sendLocked sends one update; emitMu is held.
func (r *run) sendLocked(kind string, data map[string]any) {
	r.seq++
	if kind == "message" {
		if text, ok := data["text"].(string); ok {
			r.mu.Lock()
			r.summary = truncate(text, summaryLimit)
			r.mu.Unlock()
		}
	}
	_ = r.m.send(protocol.NewRunUpdate(r.id, r.seq, kind, data))
}

// redactMessage replaces the token in message text, also when it is split
// across two flushes: the end of the text that could still become the token is
// held back until more text arrives. nil means there is nothing to send yet.
func (r *run) redactMessage(data map[string]any) map[string]any {
	text, _ := data["text"].(string)
	s := strings.ReplaceAll(r.held+text, r.secret, redacted)
	keep := heldBack(s, r.secret)
	r.held = s[len(s)-keep:]
	if s = s[:len(s)-keep]; s == "" {
		return nil
	}
	out := make(map[string]any, len(data))
	for k, v := range data {
		out[k] = v
	}
	out["text"] = s
	return out
}

// closeEmit makes every later emit a no-op; run_finished is the last message.
func (r *run) closeEmit() {
	r.emitMu.Lock()
	if held := r.held; held != "" && !r.closed && !r.stale() {
		// The text ended on something that looks like the start of the token: a
		// few characters pass, a longer start is withheld.
		r.held = ""
		r.mu.Lock()
		prev := r.summary
		r.mu.Unlock()
		held = releaseTail(held)
		r.sendLocked("message", map[string]any{"text": held})
		r.mu.Lock() // the tail belongs to the last message; it is not a message of its own
		r.summary = truncate(prev+held, summaryLimit)
		r.mu.Unlock()
	}
	r.closed = true
	r.emitMu.Unlock()
}

// stale reports that the connection this run belongs to is gone. The server
// has already failed the run, so nothing more is sent for it.
func (r *run) stale() bool {
	r.m.mu.Lock()
	defer r.m.mu.Unlock()
	return r.gen != r.m.gen
}

func (r *run) cancelled() bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.cancelRequested
}

func truncate(s string, n int) string {
	if r := []rune(s); len(r) > n {
		return string(r[:n])
	}
	return s
}

// Serve connects through c and drives the manager until the connection ends.
// Whatever ends it (cancellation, 4401, replaced), every run is stopped before
// it returns, and the connection's error is returned.
func (m *Manager) Serve(ctx context.Context, c *conn.Client) error {
	// The server fails a run when its runner disconnects, so any loss of the
	// connection stops the in-flight runs; new ones are accepted after reconnect.
	c.OnDisconnect = func(error) { m.StopAllUpTo(c.Session()) }
	done := make(chan error, 1)
	go func() { done <- c.Run(ctx) }()
	for env := range c.Messages() {
		m.Dispatch(ctx, env)
	}
	err := <-done
	sctx, cancel := context.WithTimeout(context.Background(), shutdownWait)
	defer cancel()
	m.Shutdown(sctx)
	return err
}

// Dispatch handles one server message.
func (m *Manager) Dispatch(ctx context.Context, env protocol.Envelope) {
	switch env.Type {
	case protocol.TypeWelcome:
		var w protocol.Welcome
		if env.Into(&w) == nil {
			m.HandleWelcome(w)
		}
	case protocol.TypeRunStart:
		var rs protocol.RunStart
		if env.Into(&rs) == nil {
			m.handleRunStart(ctx, rs, env.Conn)
		}
	case protocol.TypeRunCancel:
		var rc protocol.RunCancel
		if env.Into(&rc) == nil {
			m.HandleRunCancel(rc.RunID)
		}
	}
	// config_changed needs no action: the server follows it with a welcome.
}

// HandleWelcome stores the agents and bindings, then reports any availability
// that differs from what the runner last told the server.
func (m *Manager) HandleWelcome(w protocol.Welcome) {
	m.mu.Lock()
	m.agents = map[string]protocol.WelcomeAgent{}
	m.order = m.order[:0]
	for _, a := range w.Agents {
		m.agents[a.AgentID] = a
		m.order = append(m.order, a.AgentID)
	}
	m.mu.Unlock()

	for _, a := range m.probe() {
		key := availabilityKey(a)
		m.mu.Lock()
		same := m.reported[a.AgentID] == key
		m.reported[a.AgentID] = key
		m.mu.Unlock()
		if !same {
			_ = m.send(protocol.NewAgentStatus(a.AgentID, a.Available, a.Problems))
		}
	}
}

func availabilityKey(a protocol.AgentAvailability) string {
	return fmt.Sprintf("%t|%s", a.Available, strings.Join(a.Problems, "\n"))
}

// Probe reports every known agent's availability and records it as what the
// server has been told (it fills hello).
func (m *Manager) Probe() []protocol.AgentAvailability {
	out := m.probe()
	m.mu.Lock()
	for _, a := range out {
		m.reported[a.AgentID] = availabilityKey(a)
	}
	m.mu.Unlock()
	return out
}

func (m *Manager) probe() []protocol.AgentAvailability {
	var shared []string
	for _, tool := range []string{"node", "npx"} {
		if _, err := m.LookPath(tool); err != nil {
			shared = append(shared, tool+" not found")
		}
	}
	m.mu.Lock()
	agents := make([]protocol.WelcomeAgent, 0, len(m.order))
	for _, id := range m.order {
		agents = append(agents, m.agents[id])
	}
	m.mu.Unlock()

	out := make([]protocol.AgentAvailability, 0, len(agents))
	for _, a := range agents {
		problems := append([]string{}, shared...)
		for _, b := range a.Bindings {
			if b.LocalPath == "" || !filepath.IsAbs(b.LocalPath) {
				problems = append(problems, fmt.Sprintf("binding path %q is not an absolute path", b.LocalPath))
			} else if !isGitWorkTree(b.LocalPath) {
				problems = append(problems, b.LocalPath+" is not a git repository")
			}
		}
		out = append(out, protocol.AgentAvailability{AgentID: a.AgentID, Available: len(problems) == 0, Problems: problems})
	}
	return out
}

func isGitWorkTree(path string) bool {
	out, err := gitstate.Run(path, "rev-parse", "--is-inside-work-tree")
	return err == nil && strings.TrimSpace(string(out)) == "true"
}

// Active is the number of runs in flight.
func (m *Manager) Active() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return len(m.runs)
}

func (m *Manager) finish(runID, outcome, summary, errMsg string) {
	m.finishRun(runID, outcome, summary, errMsg, "", nil, nil)
}

// finishRun is finish for a run that got far enough to have a session and git states.
func (m *Manager) finishRun(runID, outcome, summary, errMsg, sessionID string, before, after *protocol.GitState) {
	rf := protocol.RunFinished{Type: protocol.TypeRunFinished, RunID: runID, Outcome: outcome, Summary: truncate(summary, summaryLimit), GitBefore: before, GitAfter: after}
	if sessionID != "" {
		s := truncate(sessionID, sessionIDLimit)
		rf.SessionID = &s
	}
	if errMsg != "" {
		e := truncate(errMsg, errorLimit)
		rf.Error = &e
	}
	_ = m.send(rf)
}

// HandleRunStart starts a run in the background, or answers right away when it
// cannot or must not start.
func (m *Manager) HandleRunStart(ctx context.Context, rs protocol.RunStart) {
	m.handleRunStart(ctx, rs, 0)
}

// handleRunStart is HandleRunStart for a run_start that arrived on connection
// number conn (0 if unknown). One from a connection already known to be lost
// is dropped: the server failed that run when the connection went away.
func (m *Manager) handleRunStart(ctx context.Context, rs protocol.RunStart, conn int) {
	m.mu.Lock()
	if conn > 0 && conn <= m.ended {
		m.mu.Unlock()
		return
	}
	if m.closed {
		m.mu.Unlock()
		m.finish(rs.RunID, "failed", "", "shutting_down")
		return
	}
	if m.takeEarlyCancelLocked(rs.RunID) {
		m.mu.Unlock()
		m.finish(rs.RunID, "cancelled", "", "")
		return
	}
	if old, dup := m.runs[rs.RunID]; dup {
		stale := old.gen != m.gen
		m.mu.Unlock()
		if stale { // the predecessor from the lost connection is still winding down
			m.finish(rs.RunID, "failed", "", "busy")
		}
		return
	}
	agent, ok := m.agents[rs.AgentID]
	if !ok {
		m.mu.Unlock()
		m.finish(rs.RunID, "failed", "", "unknown_agent")
		return
	}
	limit := max(agent.MaxConcurrentRuns, 1)
	n := 0
	var prev []*run
	for _, r := range m.runs {
		if r.agent != rs.AgentID {
			continue
		}
		if r.gen == m.gen {
			n++
		} else if r.task == rs.Task.Key {
			prev = append(prev, r) // stopped with a lost connection: the new run waits for it, never busy
		}
	}
	if n >= limit {
		m.mu.Unlock()
		m.finish(rs.RunID, "failed", "", "busy")
		return
	}
	// The run outlives the message that started it; Shutdown is what stops it.
	rctx, abort := context.WithCancel(context.WithoutCancel(ctx))
	r := &run{secret: tokenOf(rs.Mcp), m: m, id: rs.RunID, agent: rs.AgentID, task: rs.Task.Key, prev: prev,
		gen: m.gen, ctx: rctx, abort: abort, done: make(chan struct{})}
	m.runs[rs.RunID] = r
	m.wg.Add(1)
	m.mu.Unlock()

	go m.execute(r, rs, agent)
}

// HandleRunCancel stops a run: ACP session/cancel, then a kill after CancelGrace.
// A cancel for a run that has not started yet is remembered.
func (m *Manager) HandleRunCancel(runID string) {
	m.mu.Lock()
	r := m.runs[runID]
	if r == nil {
		m.early = append(m.early, runID)
		if len(m.early) > earlyCancelLimit {
			m.early = m.early[len(m.early)-earlyCancelLimit:]
		}
	}
	m.mu.Unlock()
	if r != nil {
		m.requestCancel(r)
	}
}

func (m *Manager) takeEarlyCancelLocked(runID string) bool {
	for i, id := range m.early {
		if id == runID {
			m.early = append(m.early[:i], m.early[i+1:]...)
			return true
		}
	}
	return false
}

func (m *Manager) requestCancel(r *run) {
	r.mu.Lock()
	if r.cancelRequested {
		r.mu.Unlock()
		return
	}
	r.cancelRequested = true
	ac, sid := r.conn, r.session
	r.mu.Unlock()

	if ac == nil { // still starting up: abandon the handshake; execute kills the process
		r.abort()
		return
	}
	go func() { _ = ac.Cancel(context.Background(), acp.CancelNotification{SessionId: sid}) }()
	go func() {
		select {
		case <-r.done:
		case <-time.After(m.CancelGrace):
			r.mu.Lock()
			cmd := r.cmd
			r.mu.Unlock()
			m.Kill(cmd)
		}
	}()
}

// StopAll cancels every run in flight (ACP cancel, then a kill after
// CancelGrace) and detaches them from the connection: they stop counting toward
// the concurrency limit and send nothing more. New runs are still accepted.
func (m *Manager) StopAll() []*run { return m.StopAllUpTo(0) }

// StopAllUpTo is StopAll for the loss of connection number lost (and every
// earlier one): run_starts that arrived on it, even if still queued, are dropped.
func (m *Manager) StopAllUpTo(lost int) []*run {
	m.mu.Lock()
	m.ended = max(m.ended, lost)
	m.gen++
	runs := make([]*run, 0, len(m.runs))
	for _, r := range m.runs {
		runs = append(runs, r)
	}
	m.mu.Unlock()
	for _, r := range runs {
		m.requestCancel(r)
	}
	return runs
}

// Shutdown cancels every run and waits for them to end. Runs still alive when
// ctx expires have their process trees killed.
func (m *Manager) Shutdown(ctx context.Context) {
	m.mu.Lock()
	m.closed = true
	m.mu.Unlock()
	runs := m.StopAll()
	finished := make(chan struct{})
	go func() { m.wg.Wait(); close(finished) }()
	select {
	case <-finished:
		return
	case <-ctx.Done():
	}
	for _, r := range runs {
		r.abort()
		r.mu.Lock()
		cmd := r.cmd
		r.mu.Unlock()
		m.Kill(cmd)
	}
	select {
	case <-finished:
	case <-time.After(2 * time.Second):
	}
}

func (m *Manager) execute(r *run, rs protocol.RunStart, agent protocol.WelcomeAgent) {
	defer m.wg.Done()
	outcome, errMsg := m.drive(r, rs, agent)
	if r.client != nil { // the process is gone; send what the agent said last
		r.client.Flush()
	}
	r.closeEmit()
	r.mu.Lock()
	summary, sessionID, before, after := r.summary, r.sessionID, r.gitBefore, r.gitAfter
	r.mu.Unlock()
	r.abort()
	close(r.done)

	m.mu.Lock()
	delete(m.runs, r.id)
	m.mu.Unlock()
	if !r.stale() {
		m.finishRun(r.id, outcome, summary, errMsg, sessionID, before, after)
	}
}

// bindingPath is the repository for the run's project. An agent with bindings
// but none for this project is not bound to it; only an agent with no bindings
// at all falls back to the path in run_start.
func (m *Manager) bindingPath(agent protocol.WelcomeAgent, rs protocol.RunStart) string {
	for _, b := range agent.Bindings {
		if b.ProjectKey == rs.Task.ProjectKey {
			return b.LocalPath
		}
	}
	if len(agent.Bindings) > 0 {
		return ""
	}
	return rs.LocalPath
}

func (m *Manager) openLog(runID string) (*os.File, error) {
	dir := filepath.Join(m.cacheRoot, "logs")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, err
	}
	return os.OpenFile(filepath.Join(dir, runID+".log"), os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
}

// stopReasonCode keeps agent-supplied text out of run_finished.
func stopReasonCode(r acp.StopReason) string {
	switch r {
	case acp.StopReasonMaxTokens, acp.StopReasonMaxTurnRequests, acp.StopReasonRefusal:
		return "stopped:" + string(r)
	}
	return "stopped:other"
}

// drive performs the run and returns its outcome and, for failures, a stable
// error code. The details of a failure go to the run's log file, never to the
// server.
func (m *Manager) drive(r *run, rs protocol.RunStart, agent protocol.WelcomeAgent) (outcome, errMsg string) {
	if !safeRunID.MatchString(rs.RunID) {
		return "failed", "log_failed"
	}
	file, err := m.openLog(rs.RunID)
	if err != nil {
		return "failed", "log_failed"
	}
	defer file.Close()
	logf, stderrLog, closeLogs := logWriters(file, m.LogCap, tokenOf(rs.Mcp))
	defer closeLogs() // runs before file.Close
	fail := func(code string, cause error) (string, string) {
		if cause != nil {
			fmt.Fprintf(logf, "runner: %s: %v\n", code, cause)
		} else {
			fmt.Fprintf(logf, "runner: %s\n", code)
		}
		if r.cancelled() {
			return "cancelled", ""
		}
		return "failed", code
	}

	// Cheap checks first, so a bad run leaves no worktree or branch behind.
	kind := policy.Kind(rs.Policy)
	if kind != policy.ReadOnly && kind != policy.Workspace {
		return fail("unknown_policy", nil)
	}
	spec, err := adapters.For(agent.Program)
	if err != nil {
		return fail("unsupported_program", err)
	}
	repo := m.bindingPath(agent, rs)
	if repo == "" {
		return fail("not_bound", nil)
	}
	// The task's worktree is shared: a run stopped with a lost connection must be gone first.
	if err := m.awaitPrevious(r, logf); err != nil {
		return fail("worktree_failed", err)
	}
	// A new task branch starts from the start branch (Branch from), fetched first; a reused one is left alone.
	var start startbranch.Result
	wt, taskBranch, created, err := worktree.EnsureFrom(r.ctx, logf, repo, m.cacheRoot, rs.AgentID, rs.Task.Key, rs.Task.Title,
		func() (string, error) {
			res, err := startbranch.Resolve(r.ctx, logf, repo, rs.Branch)
			start = res
			return res.StartPoint, err
		})
	switch {
	case errors.Is(err, startbranch.ErrStartBranchMissing):
		return fail("start_branch_missing", err)
	case errors.Is(err, startbranch.ErrRepositoryNotMatched):
		return fail("repository_not_matched", err)
	case errors.Is(err, startbranch.ErrStartBranchFetchFailed):
		return fail("start_branch_fetch_failed", err)
	case err != nil:
		return fail("worktree_failed", err)
	}
	// Reported until the server has it: a report lost with a dropped connection is sent again by the next run.
	report := created && start.Report
	if created && start.Report {
		if err := startbranch.Remember(repo, taskBranch, start); err != nil {
			fmt.Fprintf(logf, "runner: remembering the start branch: %v\n", err)
		}
	} else if !created && rs.Branch != nil && rs.Branch.StartBranch == "" {
		start, report = startbranch.Recall(repo, taskBranch)
	}
	if report {
		r.emit("branch", map[string]any{
			"start_branch": start.StartBranch, "default_branch": start.DefaultBranch, "repository_url": start.RepositoryURL,
		})
	}
	taskBranchPrefix := "megoo/" + rs.Task.Key + "-"
	pol, err := policy.New(kind, wt)
	if err != nil {
		return fail("policy_failed", err)
	}

	// Pinned before any agent runs: the git dir the runner reads is the one the
	// worktree had now, whatever the agent later does to its .git file.
	if err := gitstate.Pin(wt, repo); err != nil {
		return fail("git_state_unreadable", err)
	}

	// The states are read even when the run fails or is cancelled. A before
	// state that cannot be read is left out, and then so is the after state
	// unless the capture fails: the server never gets a guessed state. (An
	// after capture that fails with a before state present is sent as dirty,
	// see gitstate.CaptureAfter.)
	readBefore := func() {
		snap, err := gitstate.CapturePrefixed(wt, taskBranchPrefix)
		if err != nil {
			fmt.Fprintf(logf, "runner: git_before: %v\n", err)
			return
		}
		r.mu.Lock()
		r.gitBefore, r.snapBefore = &snap.State, &snap
		r.mu.Unlock()
	}
	// Registered before the adapter's reap, so it runs once the adapter is gone.
	defer func() {
		r.mu.Lock()
		before := r.snapBefore
		r.mu.Unlock()
		// Fails closed (see gitstate.CaptureAfter): with a baseline, a failed
		// capture still yields a dirty git_after.
		st, err := gitstate.CaptureAfter(wt, before)
		if err != nil {
			fmt.Fprintf(logf, "runner: git_after: %v\n", err)
			if before == nil {
				return
			}
		}
		r.mu.Lock()
		r.gitAfter = &st
		r.mu.Unlock()
	}()
	// Also with no files: it removes what an earlier run left in .megoocolab/.
	if err := gitstate.Materialize(wt, rs.Files); err != nil {
		readBefore()
		return fail("files_failed", err)
	}
	// git_before is read after the documents' commit, so that commit is the
	// run's starting point and not mistaken for the agent's change (R1).
	if len(rs.RepoFiles) > 0 {
		if err := gitstate.CommitRepoFiles(wt, rs.RepoFiles, rs.CommitMessage); err != nil {
			readBefore()
			return fail("commit_failed", err)
		}
	}
	readBefore()
	// R1 compares the before and after states. A read-only run without a before
	// state could not be checked at all, and an agent could cause that itself,
	// so it does not start.
	r.mu.Lock()
	// It must also start on the task's branch: with HEAD detached (or on another
	// branch) a commit on the task branch followed by a detach would go unseen.
	// The prefix, not Ensure's exact name: a worktree is reused when the task's
	// title, and so the slug, changed.
	unchecked := kind == policy.ReadOnly && (r.snapBefore == nil || !r.snapBefore.OnBranchPrefix(taskBranchPrefix))
	var cause error
	if unchecked && r.snapBefore == nil {
		cause = errors.New("the repository's state could not be read before the run")
	} else if unchecked {
		on := strings.TrimPrefix(r.snapBefore.Branch(), "refs/heads/")
		if on == "" {
			on = "detached"
		}
		cause = fmt.Errorf("HEAD is on %s, not on a %s* branch, so a read-only run cannot be checked", on, taskBranchPrefix)
	}
	r.mu.Unlock()
	if unchecked {
		return fail("git_state_unreadable", cause)
	}

	proc, err := startAdapter(spec, wt, stderrLog)
	if err != nil {
		return fail("adapter_start_failed", err)
	}
	cmd, stdin, stdout := proc.cmd, proc.stdin, proc.stdout
	r.mu.Lock()
	r.cmd = cmd
	r.mu.Unlock()
	graceful := false
	defer func() { m.reap(cmd, stdin, graceful) }()

	var opts []acpclient.Option
	if m.FlushInterval > 0 {
		opts = append(opts, acpclient.WithFlushInterval(m.FlushInterval))
	}
	opts = append(opts, acpclient.WithSecret(r.secret))
	client := acpclient.New(pol, wt, r.emit, opts...)
	r.client = client
	ac := acp.NewClientSideConnection(client, stdin, stdout)
	ac.SetLogger(slog.New(slog.NewTextHandler(io.Discard, nil)))

	initResp, err := ac.Initialize(r.ctx, initRequest())
	if err != nil {
		return fail("initialize_failed", err)
	}
	if rs.Mcp != nil && !initResp.AgentCapabilities.McpCapabilities.Http {
		return fail("mcp_http_unsupported", nil)
	}
	sess, err := openSession(r.ctx, sessionRequest{
		ac: ac, client: client, caps: initResp.AgentCapabilities, rs: rs, cwd: wt,
		meta: adapters.SessionMeta(agent.Program, kind), servers: mcpServers(rs.Mcp), log: logf,
	})
	if err != nil {
		return fail("session_failed", err)
	}
	r.mu.Lock()
	r.sessionID = string(sess.id)
	r.mu.Unlock()
	var available []string
	if sess.modes != nil {
		for _, md := range sess.modes.AvailableModes {
			available = append(available, string(md.Id))
		}
	}
	// The policy is enforced by the client whatever the mode; a refused mode is only logged.
	if mode := adapters.ModeFor(agent.Program, kind, available); mode != "" {
		if _, err := ac.SetSessionMode(r.ctx, acp.SetSessionModeRequest{SessionId: sess.id, ModeId: acp.SessionModeId(mode)}); err != nil {
			fmt.Fprintf(logf, "runner: set_mode %q failed: %v\n", mode, err)
		}
	}

	r.mu.Lock()
	r.conn, r.session = ac, sess.id
	cancelled := r.cancelRequested
	r.mu.Unlock()
	if cancelled {
		return "cancelled", ""
	}

	resp, err := ac.Prompt(r.ctx, acp.PromptRequest{
		SessionId: sess.id,
		Prompt:    []acp.ContentBlock{acp.TextBlock(sess.prompt)},
	})
	client.Flush()
	if err != nil {
		return fail("prompt_failed", err)
	}
	graceful = true
	switch resp.StopReason {
	case acp.StopReasonEndTurn:
		return "completed", ""
	case acp.StopReasonCancelled:
		// Read-only Claude runs in plan mode: the denied switch_mode ("Approve
		// Plan") ends the turn as cancelled. Only a cancel we asked for counts.
		if kind == policy.ReadOnly && !r.cancelled() {
			return "completed", ""
		}
		return "cancelled", ""
	}
	return fail(stopReasonCode(resp.StopReason), fmt.Errorf("agent stop reason %q", resp.StopReason))
}

// awaitPrevious waits until the stopped runs of the same agent and task (a lost
// connection's, still winding down) have fully ended, so two runs never share a
// worktree. They were already cancelled, which kills them after CancelGrace;
// past CancelGrace plus the reap time they are killed here, and then awaited:
// every step of a run's ending is bounded. An error means r itself was stopped
// meanwhile.
func (m *Manager) awaitPrevious(r *run, logf io.Writer) error {
	if len(r.prev) == 0 {
		return nil
	}
	fmt.Fprintf(logf, "runner: waiting for the previous run of this task to end\n")
	deadline := time.NewTimer(m.CancelGrace + reapWait)
	defer deadline.Stop()
	for _, old := range r.prev {
		select {
		case <-old.done:
			continue
		case <-r.ctx.Done():
			return fmt.Errorf("stopped while waiting for run %s", old.id)
		case <-deadline.C:
		}
		fmt.Fprintf(logf, "runner: run %s did not end in time; killing it\n", old.id)
		old.abort()
		old.mu.Lock()
		cmd := old.cmd
		old.mu.Unlock()
		m.Kill(cmd)
		select {
		case <-old.done:
		case <-r.ctx.Done():
			return fmt.Errorf("stopped while waiting for run %s", old.id)
		}
	}
	r.prev = nil
	return nil
}

// reap ends the adapter process: after a finished turn it gets ExitGrace to
// exit by itself once stdin closes; otherwise (or then) its tree is killed.
func (m *Manager) reap(cmd *exec.Cmd, stdin io.Closer, graceful bool) {
	_ = stdin.Close()
	exited := make(chan struct{})
	go func() { _ = cmd.Wait(); close(exited) }()
	if graceful {
		select {
		case <-exited:
			return
		case <-time.After(m.ExitGrace):
		}
	}
	m.Kill(cmd)
	select {
	case <-exited:
	case <-time.After(reapWait):
	}
}

// cappedWriter passes at most left bytes to w, then drops the rest, so a
// chatty adapter cannot fill the disk.
type cappedWriter struct {
	mu   sync.Mutex
	w    io.Writer
	left int
}

func (c *cappedWriter) Write(p []byte) (int, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.left <= 0 {
		return len(p), nil
	}
	chunk := p
	if len(chunk) > c.left {
		chunk = chunk[:c.left]
	}
	c.left -= len(chunk)
	if _, err := c.w.Write(chunk); err != nil {
		return 0, err
	}
	if c.left <= 0 {
		_, _ = io.WriteString(c.w, "\n[log truncated]\n")
	}
	return len(p), nil
}
