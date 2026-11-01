package tools

import "github.com/mmhy2003/megoocolab/runner/internal/protocol"

// Scan lists the MCP servers and skills set up by hand for every program with a translator, leaving out
// what the runner itself installed. It changes nothing.
func Scan(home string, m *Manifest) []protocol.FoundTool {
	var out []protocol.FoundTool
	for _, program := range Programs() {
		tr, _ := For(program)
		mcps, err := tr.ScanMCP(home)
		if err != nil {
			mcps = nil // a settings file it cannot read: nothing to offer from it
		}
		skills, _ := tr.ScanSkills(home)
		for _, f := range append(mcps, skills...) {
			if m.Find(program, f.Kind, f.Name) == nil {
				out = append(out, f)
			}
		}
	}
	return out
}
