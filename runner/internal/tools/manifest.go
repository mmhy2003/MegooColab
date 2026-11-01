package tools

import (
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
)

// Entry is one tool the runner installed for one program, with the fingerprint of what it wrote.
type Entry struct {
	Program      string `json:"program"`
	Kind         string `json:"kind"`
	Name         string `json:"name"`
	ToolID       string `json:"tool_id"`
	Rev          int    `json:"rev"`
	Fingerprint  string `json:"fingerprint"`
	ReadOnlySafe bool   `json:"read_only_safe"`
}

// Manifest is everything the runner installed. Entries not in it are never touched.
type Manifest struct {
	Entries []Entry `json:"entries"`
	path    string
}

// ManifestPath is <user config dir>/megoocolab/tools-manifest.json, next to the runner's own config.
func ManifestPath() (string, error) {
	dir, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "megoocolab", "tools-manifest.json"), nil
}

// LoadManifest reads the manifest; a missing file is an empty one.
func LoadManifest() (*Manifest, error) {
	path, err := ManifestPath()
	if err != nil {
		return nil, err
	}
	m := &Manifest{Entries: []Entry{}, path: path}
	data, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return m, nil
	}
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal(data, m); err != nil {
		return nil, err
	}
	if m.Entries == nil {
		m.Entries = []Entry{}
	}
	return m, nil
}

// Save writes the manifest, readable by the user only.
func (m *Manifest) Save() error {
	data, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return err
	}
	return WriteFileAtomic(m.path, data, true)
}

// Find is the entry for that program, kind and name, or nil.
func (m *Manifest) Find(program, kind, name string) *Entry {
	for i := range m.Entries {
		e := &m.Entries[i]
		if e.Program == program && e.Kind == kind && e.Name == name {
			return e
		}
	}
	return nil
}

// Put adds the entry or replaces the one with the same program, kind and name.
func (m *Manifest) Put(e Entry) {
	if old := m.Find(e.Program, e.Kind, e.Name); old != nil {
		*old = e
		return
	}
	m.Entries = append(m.Entries, e)
}

// Remove drops the entry for that program, kind and name.
func (m *Manifest) Remove(program, kind, name string) {
	kept := m.Entries[:0]
	for _, e := range m.Entries {
		if e.Program != program || e.Kind != kind || e.Name != name {
			kept = append(kept, e)
		}
	}
	m.Entries = kept
}
