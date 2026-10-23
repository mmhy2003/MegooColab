// Package acpclient is the runner's ACP client: it answers an agent's permission
// and file requests according to a policy and reports metadata only (never code)
// about what the agent does.
package acpclient

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/coder/acp-go-sdk"
	"github.com/mmhy2003/megoocolab/runner/internal/policy"
)

// DefaultFlushInterval is how often buffered agent message text is sent.
const DefaultFlushInterval = 1500 * time.Millisecond

// EmitFunc receives one run update. kind and data follow the server's
// allow-list. It is called with the client's lock held, in order, so it must
// not call back into the Client.
type EmitFunc func(kind string, data map[string]any)

// Option configures a Client.
type Option func(*Client)

// WithFlushInterval overrides the message coalescing interval (for tests).
func WithFlushInterval(d time.Duration) Option { return func(c *Client) { c.interval = d } }

type toolInfo struct {
	kind    acp.ToolKind
	command string
	title   string
}

// Client implements acp.Client.
type Client struct {
	pol      policy.Policy
	root     string
	emit     EmitFunc
	interval time.Duration

	mu    sync.Mutex // guards everything below and serializes emit
	msg   strings.Builder
	timer *time.Timer
	tools map[acp.ToolCallId]*toolInfo
}

var _ acp.Client = (*Client)(nil)

// New returns a client that enforces pol on files under root and reports through emit.
func New(pol policy.Policy, root string, emit func(kind string, data map[string]any), opts ...Option) *Client {
	c := &Client{pol: pol, root: root, emit: emit, interval: DefaultFlushInterval, tools: map[acp.ToolCallId]*toolInfo{}}
	for _, o := range opts {
		o(c)
	}
	return c
}

// Flush sends any buffered agent message text. The run manager calls it when a
// prompt turn ends.
func (c *Client) Flush() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.flushLocked()
}

func (c *Client) flushLocked() {
	if c.timer != nil {
		c.timer.Stop()
		c.timer = nil
	}
	text := c.msg.String()
	c.msg.Reset()
	if strings.TrimSpace(text) == "" {
		return
	}
	runes := []rune(text)
	for len(runes) > 0 {
		n := min(len(runes), maxText)
		c.emit("message", map[string]any{"text": string(runes[:n])})
		runes = runes[n:]
	}
}

// emitLocked sends an update after any pending message text, keeping order.
func (c *Client) emitLocked(kind string, data map[string]any) {
	c.flushLocked()
	c.emit(kind, data)
}

func (c *Client) send(kind string, data map[string]any) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.emitLocked(kind, data)
}

func (c *Client) addMessage(text string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.msg.WriteString(text)
	if c.timer == nil {
		c.timer = time.AfterFunc(c.interval, c.Flush)
	}
}

// RequestPermission answers by policy: allow_once or reject_once, whichever the
// agent offers. A standing approval (allow_always) is never given. With no
// suitable option the outcome is "cancelled", never an approval.
func (c *Client) RequestPermission(_ context.Context, p acp.RequestPermissionRequest) (acp.RequestPermissionResponse, error) {
	kind := acp.ToolKindOther
	if p.ToolCall.Kind != nil {
		kind = *p.ToolCall.Kind
	}
	title := ""
	if p.ToolCall.Title != nil {
		title = *p.ToolCall.Title
	}
	command := commandOf(p.ToolCall.RawInput)
	c.mu.Lock()
	if known := c.tools[p.ToolCall.ToolCallId]; known != nil { // the request may omit what tool_call carried
		if p.ToolCall.Kind == nil {
			kind = known.kind
		}
		if command == "" {
			command = known.command
		}
		if title == "" {
			title = known.title
		}
	}
	c.mu.Unlock()
	locations := make([]string, 0, len(p.ToolCall.Locations))
	for _, l := range p.ToolCall.Locations {
		locations = append(locations, l.Path)
	}

	d := c.pol.CheckTool(kind, title, locations, command)
	want := acp.PermissionOptionKindRejectOnce
	if d.Allow {
		want = acp.PermissionOptionKindAllowOnce
	}
	var option *acp.PermissionOption
	for i := range p.Options {
		if p.Options[i].Kind == want {
			option = &p.Options[i]
			break
		}
	}
	reason := d.Reason
	if option == nil && d.Allow {
		d = policy.Decision{Allow: false}
		reason = "no allow-once option offered"
	}

	c.mu.Lock()
	c.emitLocked("permission", permissionData(kind, displayTitle(kind, title, command), d.Allow, reason))
	if d.Allow && kind == acp.ToolKindExecute {
		if base := policy.FirstTokenBase(command); base != "" {
			c.emit("command", map[string]any{"command": truncate(base, 100)})
		}
	}
	c.mu.Unlock()

	if option == nil {
		return acp.RequestPermissionResponse{Outcome: acp.NewRequestPermissionOutcomeCancelled()}, nil
	}
	return acp.RequestPermissionResponse{Outcome: acp.NewRequestPermissionOutcomeSelected(option.OptionId)}, nil
}

// ReadTextFile serves a read inside the worktree.
func (c *Client) ReadTextFile(_ context.Context, p acp.ReadTextFileRequest) (acp.ReadTextFileResponse, error) {
	if d := c.pol.CheckRead(p.Path); !d.Allow {
		return acp.ReadTextFileResponse{}, errors.New("read denied: " + d.Reason)
	}
	real, ok := policy.InsideRoot(c.root, p.Path)
	if !ok {
		return acp.ReadTextFileResponse{}, errors.New("read denied: outside the worktree")
	}
	b, err := os.ReadFile(real)
	if err != nil {
		return acp.ReadTextFileResponse{}, err
	}
	content := string(b)
	if p.Line != nil || p.Limit != nil {
		lines := strings.SplitAfter(content, "\n")
		if lines[len(lines)-1] == "" {
			lines = lines[:len(lines)-1]
		}
		start := 0
		if p.Line != nil && *p.Line > 1 {
			start = *p.Line - 1
		}
		start = min(start, len(lines))
		end := len(lines)
		if p.Limit != nil && *p.Limit >= 0 {
			end = min(end, start+*p.Limit)
		}
		content = strings.Join(lines[start:end], "")
	}
	return acp.ReadTextFileResponse{Content: content}, nil
}

// WriteTextFile writes inside the worktree if the policy allows it. A denial is
// reported as a permission update; a write as a file_change with counts only.
func (c *Client) WriteTextFile(_ context.Context, p acp.WriteTextFileRequest) (acp.WriteTextFileResponse, error) {
	rel, inside := policy.Relative(c.root, p.Path)
	shown := rel
	if !inside {
		shown = "(outside the worktree)"
	}
	d := c.pol.CheckWrite(p.Path)
	real, ok := policy.InsideRoot(c.root, p.Path)
	if d.Allow && !ok { // a policy that allows paths the root check refuses is a bug: fail closed
		d = policy.Decision{Reason: "outside the worktree: write denied"}
	}
	if !d.Allow {
		c.send("permission", permissionData(acp.ToolKindEdit, "Write "+shown, false, d.Reason))
		return acp.WriteTextFileResponse{}, errors.New("write denied: " + d.Reason)
	}

	var old string
	if b, err := os.ReadFile(real); err == nil {
		old = string(b)
	} else if !errors.Is(err, os.ErrNotExist) {
		return acp.WriteTextFileResponse{}, err
	}
	if err := os.MkdirAll(filepath.Dir(real), 0o755); err != nil {
		return acp.WriteTextFileResponse{}, err
	}
	if err := os.WriteFile(real, []byte(p.Content), 0o644); err != nil {
		return acp.WriteTextFileResponse{}, err
	}
	added, removed := lineCounts(old, p.Content)
	c.send("file_change", fileChangeData(rel, added, removed))
	return acp.WriteTextFileResponse{}, nil
}

// SessionUpdate maps what the agent reports to metadata. Message text is
// buffered; plans and tool calls go out as they come. Content blocks, diffs,
// raw input and raw output are never read into any update.
func (c *Client) SessionUpdate(_ context.Context, n acp.SessionNotification) error {
	u := n.Update
	switch {
	case u.AgentMessageChunk != nil:
		if t := u.AgentMessageChunk.Content.Text; t != nil {
			c.addMessage(t.Text)
		}
	case u.Plan != nil:
		c.send("plan", map[string]any{"entries": planEntries(u.Plan.Entries)})
	case u.ToolCall != nil:
		tc := u.ToolCall
		info := &toolInfo{kind: tc.Kind, command: commandOf(tc.RawInput), title: tc.Title}
		c.mu.Lock()
		c.tools[tc.ToolCallId] = info
		c.emitLocked("tool", toolData(info.kind, displayTitle(info.kind, info.title, info.command), tc.Status))
		c.mu.Unlock()
	case u.ToolCallUpdate != nil:
		c.toolUpdate(u.ToolCallUpdate)
	}
	return nil
}

func (c *Client) toolUpdate(tu *acp.SessionToolCallUpdate) {
	c.mu.Lock()
	defer c.mu.Unlock()
	info := c.tools[tu.ToolCallId]
	if info == nil {
		info = &toolInfo{kind: acp.ToolKindOther}
		c.tools[tu.ToolCallId] = info
	}
	changed := false
	if tu.Kind != nil {
		info.kind, changed = *tu.Kind, true
	}
	if tu.Title != nil {
		info.title, changed = *tu.Title, true
	}
	if cmd := commandOf(tu.RawInput); cmd != "" {
		info.command = cmd
	}
	var status acp.ToolCallStatus
	if tu.Status != nil {
		status, changed = *tu.Status, true
	}
	if !changed { // content / raw output only: nothing to report
		return
	}
	c.emitLocked("tool", toolData(info.kind, displayTitle(info.kind, info.title, info.command), status))
}

func (c *Client) CreateTerminal(context.Context, acp.CreateTerminalRequest) (acp.CreateTerminalResponse, error) {
	return acp.CreateTerminalResponse{}, errNotSupported
}

func (c *Client) KillTerminal(context.Context, acp.KillTerminalRequest) (acp.KillTerminalResponse, error) {
	return acp.KillTerminalResponse{}, errNotSupported
}

func (c *Client) TerminalOutput(context.Context, acp.TerminalOutputRequest) (acp.TerminalOutputResponse, error) {
	return acp.TerminalOutputResponse{}, errNotSupported
}

func (c *Client) ReleaseTerminal(context.Context, acp.ReleaseTerminalRequest) (acp.ReleaseTerminalResponse, error) {
	return acp.ReleaseTerminalResponse{}, errNotSupported
}

func (c *Client) WaitForTerminalExit(context.Context, acp.WaitForTerminalExitRequest) (acp.WaitForTerminalExitResponse, error) {
	return acp.WaitForTerminalExitResponse{}, errNotSupported
}
