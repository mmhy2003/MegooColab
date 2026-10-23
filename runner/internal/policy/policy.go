// Package policy decides what an ACP agent may do. The runner enforces it on
// every permission request and file operation; the agent is never trusted.
package policy

import (
	"fmt"

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
}

// New builds the policy of the given kind for a worktree root.
func New(kind Kind, root string) (Policy, error) {
	if root == "" {
		return nil, fmt.Errorf("policy: empty root")
	}
	switch kind {
	case ReadOnly:
		return readOnly{root: root}, nil
	case Workspace:
		return workspace{root: root}, nil
	}
	return nil, fmt.Errorf("policy: unknown kind %q", kind)
}

// readOnly: nothing is ever written; only plain read-only commands run.
type readOnly struct{ root string }

func (p readOnly) CheckWrite(string) Decision {
	return deny("read-only policy: writes are not allowed")
}

func (p readOnly) CheckRead(path string) Decision { return checkInside(p.root, path, "read") }

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

// workspace: reads and writes stay inside the worktree; commands run there.
type workspace struct{ root string }

func (p workspace) CheckWrite(path string) Decision { return checkInside(p.root, path, "write") }
func (p workspace) CheckRead(path string) Decision  { return checkInside(p.root, path, "read") }

func (p workspace) CheckTool(kind acp.ToolKind, _ string, locations []string, _ string) Decision {
	switch kind {
	case acp.ToolKindEdit, acp.ToolKindDelete, acp.ToolKindMove:
		if len(locations) == 0 {
			return deny("workspace policy: no path to verify")
		}
		fallthrough
	case acp.ToolKindRead, acp.ToolKindSearch:
		for _, l := range locations {
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

func checkInside(root, path, verb string) Decision {
	if _, ok := InsideRoot(root, path); !ok {
		return deny("outside the worktree: " + verb + " denied")
	}
	return allow("inside the worktree")
}
