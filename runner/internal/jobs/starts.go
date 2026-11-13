package jobs

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
)

// starts are each program's starting model: the one a new session is on before the runner changes anything. A run
// that asks for "the program's own model" on a continued session is put back on it, whatever an earlier stage
// switched the session to. Kept in a file of the runner's cache, so a restarted runner still knows it.
type starts struct {
	mu        sync.Mutex
	path      string
	byProgram map[string]string
}

// loadStarts reads the starting models kept at path; a missing or unreadable file is none known.
func loadStarts(path string) *starts {
	s := &starts{path: path, byProgram: map[string]string{}}
	if b, err := os.ReadFile(path); err == nil {
		_ = json.Unmarshal(b, &s.byProgram)
		if s.byProgram == nil {
			s.byProgram = map[string]string{}
		}
	}
	return s
}

func (s *starts) get(program string) (string, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	m, ok := s.byProgram[program]
	return m, ok
}

// set records a program's starting model and writes the file when it changed.
func (s *starts) set(program, model string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if old, ok := s.byProgram[program]; ok && old == model {
		return nil
	}
	s.byProgram[program] = model
	b, err := json.Marshal(s.byProgram)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(s.path), 0o700); err != nil {
		return err
	}
	tmp := s.path + ".tmp"
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return err
	}
	if err := os.Rename(tmp, s.path); err != nil {
		return fmt.Errorf("keep starting models: %w", err)
	}
	return nil
}
