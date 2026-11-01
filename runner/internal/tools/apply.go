package tools

import (
	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// maxDetail caps what a result says about a failure.
const maxDetail = 300

// detail is a failure, said briefly. The errors in this package name files, never a value from a tool.
func detail(err error) string {
	s := err.Error()
	if len(s) > maxDetail {
		s = s[:maxDetail]
	}
	return s
}

func fingerprint(tr Translator, home, kind, name string) (string, bool, error) {
	if kind == "skill" {
		return tr.SkillFingerprint(home, name)
	}
	return tr.MCPFingerprint(home, name)
}

func install(tr Translator, home string, t Tool) (string, error) {
	if t.Kind == "skill" {
		files, err := DecodeFiles(t)
		if err != nil {
			return "", err
		}
		return tr.InstallSkill(home, t.Name, files)
	}
	return tr.InstallMCP(home, t)
}

func uninstall(tr Translator, home, kind, name string) error {
	if kind == "skill" {
		return tr.RemoveSkill(home, name)
	}
	return tr.RemoveMCP(home, name)
}

// Apply makes each listed program hold exactly the pushed tools that the runner manages: it installs or
// updates every tool, and removes what it installed before and is no longer pushed. An entry made by hand
// with a pushed tool's name is left alone (conflict) unless the tool is in takeOver. Programs not listed, and
// entries the manifest does not name, are never touched; nor are the tools named in keep (still wanted, but not
// sendable now). The manifest is saved once, at the end.
func Apply(home string, m *Manifest, programs []string, tools []Tool, takeOver, keep []string) []protocol.ToolResult {
	takeOK := map[string]bool{}
	for _, n := range takeOver {
		takeOK[n] = true
	}
	kept := map[string]bool{}
	for _, n := range keep {
		kept[n] = true
	}
	var results []protocol.ToolResult
	for _, program := range programs {
		tr, ok := For(program)
		wanted := map[string]bool{}
		for _, t := range tools {
			wanted[t.Kind+"/"+t.Name] = true
			r := protocol.ToolResult{ToolID: t.ToolID, Name: t.Name, Kind: t.Kind, Program: program, Rev: t.Rev}
			if !ok {
				r.Status = protocol.ToolNotSupported
				results = append(results, r)
				continue
			}
			_, exists, err := fingerprint(tr, home, t.Kind, t.Name)
			switch {
			case err != nil:
				r.Status, r.Detail = protocol.ToolFailed, detail(err)
			case exists && m.Find(program, t.Kind, t.Name) == nil && !takeOK[t.Name]:
				r.Status = protocol.ToolConflict
			default:
				fp, err := install(tr, home, t)
				if err != nil {
					r.Status, r.Detail = protocol.ToolFailed, detail(err)
					break
				}
				m.Put(Entry{Program: program, Kind: t.Kind, Name: t.Name, ToolID: t.ToolID, Rev: t.Rev,
					Fingerprint: fp, ReadOnlySafe: t.ReadOnlySafe})
				r.Status = protocol.ToolInstalled
			}
			results = append(results, r)
		}
		if !ok {
			continue
		}
		for _, e := range append([]Entry(nil), m.Entries...) {
			if e.Program != program || wanted[e.Kind+"/"+e.Name] || kept[e.Name] {
				continue
			}
			r := protocol.ToolResult{ToolID: e.ToolID, Name: e.Name, Kind: e.Kind, Program: program}
			if err := uninstall(tr, home, e.Kind, e.Name); err != nil {
				r.Status, r.Detail = protocol.ToolFailed, detail(err)
			} else {
				m.Remove(program, e.Kind, e.Name)
				r.Status = protocol.ToolRemoved
			}
			results = append(results, r)
		}
	}
	if err := m.Save(); err != nil {
		for i := range results {
			if results[i].Status == protocol.ToolInstalled || results[i].Status == protocol.ToolRemoved {
				results[i].Status, results[i].Detail = protocol.ToolFailed, "the tools manifest could not be saved"
			}
		}
	}
	return results
}
