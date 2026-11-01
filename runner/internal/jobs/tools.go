package jobs

import (
	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
	"github.com/mmhy2003/megoocolab/runner/internal/tools"
)

// toolsJob runs a Tool Hub job off the message loop, one at a time: pushes, scans and drift checks touch the
// same settings files and manifest.
func (m *Manager) toolsJob(job func()) {
	m.wg.Add(1)
	go func() {
		defer m.wg.Done()
		m.toolsMu.Lock()
		defer m.toolsMu.Unlock()
		job()
	}()
}

// applyPush installs the pushed tools for each listed program and reports what it did.
func (m *Manager) applyPush(p protocol.ToolsPush) {
	home, err := tools.Home()
	var man *tools.Manifest
	if err == nil {
		man, err = tools.LoadManifest()
	}
	if err != nil {
		results := []protocol.ToolResult{}
		for _, program := range p.Programs {
			for _, t := range p.Tools {
				results = append(results, protocol.ToolResult{ToolID: t.ToolID, Name: t.Name, Kind: t.Kind, Program: program,
					Rev: t.Rev, Status: protocol.ToolFailed, Detail: "the tools manifest could not be read"})
			}
		}
		_ = m.send(protocol.NewToolsReport(p.PushID, results))
		return
	}
	results := tools.Apply(home, man, p.Programs, p.Tools, p.TakeOver)
	_ = m.send(protocol.NewToolsReport(p.PushID, results))
}

// sendDrift tells the server which installed tools no longer match what the runner wrote.
func (m *Manager) sendDrift() {
	home, err := tools.Home()
	if err != nil {
		return
	}
	man, err := tools.LoadManifest()
	if err != nil {
		return
	}
	_ = m.send(protocol.NewToolsDrift(tools.Drift(home, man)))
}

// scanTools lists what was set up by hand, for an import.
func (m *Manager) scanTools(scanID string) {
	home, err := tools.Home()
	var man *tools.Manifest
	if err == nil {
		man, err = tools.LoadManifest()
	}
	if err != nil {
		_ = m.send(protocol.NewToolsFound(scanID, nil))
		return
	}
	_ = m.send(protocol.NewToolsFound(scanID, tools.Scan(home, man)))
}
