package tools

import "github.com/mmhy2003/megoocolab/runner/internal/protocol"

// scanBudget is how many bytes of skill files one scan answer may carry: the server reads a frame of 16 MiB at
// most. Skills past it are listed with a problem instead of their files.
var scanBudget = 8 << 20

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
	used := 0
	for i := range out {
		size := 0
		for _, f := range out[i].Files {
			size += len(f.ContentB64)
		}
		if used+size > scanBudget {
			out[i].Files, out[i].Problem = nil, "too large to send"
			continue
		}
		used += size
	}
	return out
}
