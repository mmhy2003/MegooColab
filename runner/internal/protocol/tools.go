package protocol

// Tool Hub messages (plan 24): the server pushes a machine's whole wanted set of MCP servers and skills, the
// runner installs them at user level for each agent program and reports back; it also reports hand edits
// (drift) and, when asked, what was set up by hand (a scan for import).

// Message type names.
const (
	TypeToolsPush   = "tools_push"
	TypeToolsScan   = "tools_scan"
	TypeToolsReport = "tools_report"
	TypeToolsDrift  = "tools_drift"
	TypeToolsFound  = "tools_found"
)

// CapabilityTools is advertised in every hello: the runner takes tools_push and tools_scan, answers with
// tools_report and tools_found, and sends tools_drift after each welcome.
const CapabilityTools = "tools/1"

// What became of one tool for one program.
const (
	ToolInstalled    = "installed"
	ToolRemoved      = "removed"
	ToolFailed       = "failed"
	ToolConflict     = "conflict"      // an entry made by hand has that name: left alone
	ToolNotSupported = "not_supported" // the program cannot take this kind of tool
	ToolNotAvailable = "not_available" // not on this operating system
)

// Drift states.
const (
	DriftChanged = "changed"
	DriftMissing = "missing"
)

// McpPayload is an MCP server ready to write: secrets and ${NAME} placeholders already filled in, and the
// command already the one for this machine's system.
type McpPayload struct {
	Transport string            `json:"transport"` // "http" | "stdio"
	URL       string            `json:"url,omitempty"`
	Headers   map[string]string `json:"headers"`
	Command   string            `json:"command,omitempty"`
	Args      []string          `json:"args"`
	Env       map[string]string `json:"env"`
}

// SkillFile is one file of a skill, base64-encoded.
type SkillFile struct {
	Path       string `json:"path"`
	ContentB64 string `json:"content_b64"`
}

// ToolPayload is one tool of a push.
type ToolPayload struct {
	ToolID       string      `json:"tool_id"`
	Name         string      `json:"name"`
	Kind         string      `json:"kind"` // "mcp" | "skill"
	Rev          int         `json:"rev"`
	ReadOnlySafe bool        `json:"read_only_safe"`
	Mcp          *McpPayload `json:"mcp,omitempty"`
	Files        []SkillFile `json:"files,omitempty"`
}

// ToolsPush is the machine's whole wanted set: install or update these, remove what the runner installed
// before and is no longer listed. TakeOver names tools that may replace an entry made by hand.
type ToolsPush struct {
	Type     string        `json:"type"`
	PushID   string        `json:"push_id"`
	Programs []string      `json:"programs"`
	Tools    []ToolPayload `json:"tools"`
	TakeOver []string      `json:"take_over"`
}

// ToolsScan asks what MCP servers and skills were set up by hand on this machine.
type ToolsScan struct {
	Type   string `json:"type"`
	ScanID string `json:"scan_id"`
}

// ToolResult is what a push did for one tool in one program. Detail never holds a value from the tool.
type ToolResult struct {
	ToolID  string `json:"tool_id,omitempty"`
	Name    string `json:"name"`
	Kind    string `json:"kind"`
	Program string `json:"program"`
	Rev     int    `json:"rev,omitempty"`
	Status  string `json:"status"`
	Detail  string `json:"detail"`
}

// ToolsReport answers a tools_push.
type ToolsReport struct {
	Type    string       `json:"type"`
	PushID  string       `json:"push_id"`
	Results []ToolResult `json:"results"`
}

// ToolDrift is an installed tool that no longer matches what the runner wrote.
type ToolDrift struct {
	Name    string `json:"name"`
	Kind    string `json:"kind"`
	Program string `json:"program"`
	Status  string `json:"status"` // DriftChanged | DriftMissing
}

// ToolsDrift is sent after each welcome.
type ToolsDrift struct {
	Type  string      `json:"type"`
	Items []ToolDrift `json:"items"`
}

// FoundTool is something set up by hand, offered for import. Problem says why it cannot be imported.
type FoundTool struct {
	Program string      `json:"program"`
	Kind    string      `json:"kind"`
	Name    string      `json:"name"`
	Mcp     *McpPayload `json:"mcp,omitempty"`
	Files   []SkillFile `json:"files,omitempty"`
	Problem string      `json:"problem,omitempty"`
}

// ToolsFound answers a tools_scan.
type ToolsFound struct {
	Type   string      `json:"type"`
	ScanID string      `json:"scan_id"`
	Items  []FoundTool `json:"items"`
}

// NewToolsReport builds a tools_report with a non-nil results list.
func NewToolsReport(pushID string, results []ToolResult) ToolsReport {
	if results == nil {
		results = []ToolResult{}
	}
	return ToolsReport{Type: TypeToolsReport, PushID: pushID, Results: results}
}

// NewToolsDrift builds a tools_drift with a non-nil items list.
func NewToolsDrift(items []ToolDrift) ToolsDrift {
	if items == nil {
		items = []ToolDrift{}
	}
	return ToolsDrift{Type: TypeToolsDrift, Items: items}
}

// NewToolsFound builds a tools_found with a non-nil items list.
func NewToolsFound(scanID string, items []FoundTool) ToolsFound {
	if items == nil {
		items = []FoundTool{}
	}
	return ToolsFound{Type: TypeToolsFound, ScanID: scanID, Items: items}
}
