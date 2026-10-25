package main

import (
	"encoding/json"
	"fmt"
	"os"
)

// Step is one scripted action. Exactly one field is set.
type Step struct {
	Say         *string     `json:"say,omitempty"`
	Plan        [][]string  `json:"plan,omitempty"`
	Tool        *ToolStep   `json:"tool,omitempty"`
	Write       *FileStep   `json:"write,omitempty"`
	Read        *FileStep   `json:"read,omitempty"`
	Exec        *ExecStep   `json:"exec,omitempty"`
	DirectWrite *FileStep   `json:"direct_write,omitempty"`
	SleepMS     *int        `json:"sleep_ms,omitempty"`
	Stop        *string     `json:"stop,omitempty"`
	Commit      *CommitStep `json:"commit,omitempty"`
	ReportFile  *PathStep   `json:"report_file,omitempty"`
}

// CommitStep runs `git commit --allow-empty -m Message` in the agent's cwd.
type CommitStep struct {
	Message string `json:"message"`
}

// PathStep names a file (relative to the agent's cwd) to look at.
type PathStep struct {
	Path string `json:"path"`
}

type ToolStep struct {
	Kind  string `json:"kind"`
	Title string `json:"title"`
	Path  string `json:"path"`
}

type FileStep struct {
	Path    string `json:"path"`
	Content string `json:"content"`
}

type ExecStep struct {
	Command string `json:"command"`
}

// typeName is the step's report label.
func (s Step) typeName() string {
	switch {
	case s.Say != nil:
		return "say"
	case s.Plan != nil:
		return "plan"
	case s.Tool != nil:
		return "tool"
	case s.Write != nil:
		return "write"
	case s.Read != nil:
		return "read"
	case s.Exec != nil:
		return "exec"
	case s.DirectWrite != nil:
		return "direct_write"
	case s.SleepMS != nil:
		return "sleep"
	case s.Stop != nil:
		return "stop"
	case s.Commit != nil:
		return "commit"
	case s.ReportFile != nil:
		return "report_file"
	}
	return "unknown"
}

// loadScenario reads FAKEAGENT_SCENARIO (a JSON array of steps).
func loadScenario() ([]Step, error) {
	raw := os.Getenv("FAKEAGENT_SCENARIO")
	if raw == "" {
		return nil, nil
	}
	var steps []Step
	if err := json.Unmarshal([]byte(raw), &steps); err != nil {
		return nil, fmt.Errorf("FAKEAGENT_SCENARIO: %w", err)
	}
	return steps, nil
}

// StepResult is one entry of the report's "steps" array.
type StepResult struct {
	Type    string `json:"type"`
	Outcome string `json:"outcome,omitempty"` // tool/exec: allowed | rejected | cancelled
	OK      *bool  `json:"ok,omitempty"`      // write
	Error   string `json:"error,omitempty"`
	Length  *int   `json:"length,omitempty"`  // read: characters read, not the content
	Exists  *bool  `json:"exists,omitempty"`  // report_file
	Content string `json:"content,omitempty"` // report_file: the file's text, if it exists
}

// Report is written to FAKEAGENT_REPORT on exit.
type Report struct {
	Initialize InitSummary     `json:"initialize"`
	Cwd        string          `json:"cwd"`
	Meta       json.RawMessage `json:"meta"`
	ModesSet   []string        `json:"modes_set"`
	Steps      []StepResult    `json:"steps"`
	Cancelled  bool            `json:"cancelled"`
}

type InitSummary struct {
	ProtocolVersion int    `json:"protocol_version"`
	ClientName      string `json:"client_name,omitempty"`
	ClientVersion   string `json:"client_version,omitempty"`
	FSRead          bool   `json:"fs_read"`
	FSWrite         bool   `json:"fs_write"`
	Terminal        bool   `json:"terminal"`
}
