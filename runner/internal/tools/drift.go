package tools

import "github.com/mmhy2003/megoocolab/runner/internal/protocol"

// Drift lists the installed tools that no longer match what the runner wrote: changed by hand, or gone.
func Drift(home string, m *Manifest) []protocol.ToolDrift {
	var out []protocol.ToolDrift
	for _, e := range m.Entries {
		tr, ok := For(e.Program)
		if !ok {
			continue
		}
		fp, exists, err := fingerprint(tr, home, e.Kind, e.Name)
		item := protocol.ToolDrift{Name: e.Name, Kind: e.Kind, Program: e.Program}
		switch {
		case err != nil || (exists && fp != e.Fingerprint):
			item.Status = protocol.DriftChanged
		case !exists:
			item.Status = protocol.DriftMissing
		default:
			continue
		}
		out = append(out, item)
	}
	return out
}
