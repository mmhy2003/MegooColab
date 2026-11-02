// Package policy decides what an ACP agent may do. The runner enforces it on
// every permission request and file operation; the agent is never trusted.
package policy

import (
	"fmt"
	"path/filepath"
	"sync"

	"github.com/coder/acp-go-sdk"
)

// Kind names a policy. The values are identical to the backend's RunPolicy.
type Kind string

const (
	ReadOnly  Kind = "read_only"
	Workspace Kind = "workspace"
)

// Decision is the verdict on one request. Reason is short, static text that is
// safe to send to the server: it never contains paths or file contents.
type Decision struct {
	Allow  bool
	Reason string
}

func allow(reason string) Decision { return Decision{Allow: true, Reason: reason} }
func deny(reason string) Decision  { return Decision{Reason: reason} }

// Policy is the set of checks the ACP client applies.
type Policy interface {
	// CheckTool judges a tool call before it runs. command is the command line for
	// execute tools (empty otherwise); locations are the file paths it touches.
	CheckTool(kind acp.ToolKind, title string, locations []string, command string) Decision
	CheckWrite(path string) Decision
	CheckRead(path string) Decision
	// AllowRead lets the agent also read inside dir (the run's images, when its program can't take them in
	// the prompt). Writes there stay refused.
	AllowRead(dir string)
	// ResolveRead is InsideRoot for a read: the resolved path when it is inside the worktree or an allowed folder.
	ResolveRead(path string) (string, bool)
}

// readDirs are the folders outside the worktree a run may read, shared by a policy's copies.
type readDirs struct {
	mu   sync.Mutex
	dirs []string
}

func (d *readDirs) add(dir string) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.dirs = append(d.dirs, dir)
}

func (d *readDirs) resolve(path string) (string, bool) {
	d.mu.Lock()
	defer d.mu.Unlock()
	for _, dir := range d.dirs {
		if !filepath.IsAbs(path) {
			continue // a relative path means the worktree
		}
		if real, ok := InsideRoot(dir, path); ok {
			return real, true
		}
	}
	return "", false
}

// New builds the policy of the given kind for a worktree root.
func New(kind Kind, root string) (Policy, error) {
	if root == "" {
		return nil, fmt.Errorf("policy: empty root")
	}
	switch kind {
	case ReadOnly:
		return readOnly{root: root, extra: &readDirs{}}, nil
	case Workspace:
		return workspace{root: root, extra: &readDirs{}}, nil
	}
	return nil, fmt.Errorf("policy: unknown kind %q", kind)
}

// readOnly: nothing is ever written; only plain read-only commands run.
type readOnly struct {
	root  string
	extra *readDirs
}

func (p readOnly) AllowRead(dir string)                   { p.extra.add(dir) }
func (p readOnly) ResolveRead(path string) (string, bool) { return resolveRead(p.root, p.extra, path) }

func (p readOnly) CheckWrite(string) Decision {
	return deny("read-only policy: writes are not allowed")
}

func (p readOnly) CheckRead(path string) Decision { return checkRead(p.root, p.extra, path) }

func (p readOnly) CheckTool(kind acp.ToolKind, _ string, _ []string, command string) Decision {
	switch kind {
	case acp.ToolKindRead, acp.ToolKindSearch, acp.ToolKindThink, acp.ToolKindFetch:
		return allow("read-only policy: read access")
	case acp.ToolKindExecute:
		if ReadOnlyCommand(command) {
			return allow("read-only policy: read-only command")
		}
		return deny("read-only policy: command is not on the read-only list")
	case acp.ToolKindEdit, acp.ToolKindDelete, acp.ToolKindMove:
		return deny("read-only policy: changes are not allowed")
	}
	return deny("read-only policy: tool not allowed")
}

// workspace: reads and writes stay inside the worktree (reads also in an allowed folder); commands run there.
type workspace struct {
	root  string
	extra *readDirs
}

func (p workspace) CheckWrite(path string) Decision        { return checkInside(p.root, path, "write") }
func (p workspace) CheckRead(path string) Decision         { return checkRead(p.root, p.extra, path) }
func (p workspace) AllowRead(dir string)                   { p.extra.add(dir) }
func (p workspace) ResolveRead(path string) (string, bool) { return resolveRead(p.root, p.extra, path) }

func (p workspace) CheckTool(kind acp.ToolKind, _ string, locations []string, _ string) Decision {
	switch kind {
	case acp.ToolKindEdit, acp.ToolKindDelete, acp.ToolKindMove:
		if len(locations) == 0 {
			return deny("workspace policy: no path to verify")
		}
		fallthrough
	case acp.ToolKindRead, acp.ToolKindSearch:
		for _, l := range locations {
			if kind == acp.ToolKindRead {
				if _, ok := p.extra.resolve(l); ok {
					continue // the run's images
				}
			}
			if d := checkInside(p.root, l, "access"); !d.Allow {
				return d
			}
		}
		return allow("workspace policy: inside the worktree")
	case acp.ToolKindThink, acp.ToolKindFetch, acp.ToolKindExecute, acp.ToolKindOther:
		return allow("workspace policy")
	}
	return deny("workspace policy: tool not allowed")
}

func checkRead(root string, extra *readDirs, path string) Decision {
	if _, ok := extra.resolve(path); ok {
		return allow("the run's own files")
	}
	return checkInside(root, path, "read")
}

func resolveRead(root string, extra *readDirs, path string) (string, bool) {
	if real, ok := InsideRoot(root, path); ok {
		return real, true
	}
	return extra.resolve(path)
}

func checkInside(root, path, verb string) Decision {
	if _, ok := InsideRoot(root, path); !ok {
		return deny("outside the worktree: " + verb + " denied")
	}
	return allow("inside the worktree")
}
