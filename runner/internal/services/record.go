package services

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Record is what the runner keeps about a started service set, in
// <dir>/<project>.json, so it can be removed later by whoever finds it.
type Record struct {
	Project  string    `json:"project"`
	Worktree string    `json:"worktree"` // Canonical
	Set      string    `json:"set"`
	Compose  []string  `json:"compose"`
	EnvFile  string    `json:"env_file"`
	Built    []string  `json:"built"`
	PID      int       `json:"pid"`
	Started  time.Time `json:"started"`
}

// ErrBusy is Claim's answer when the set is already running in the worktree.
var ErrBusy = errors.New("already running in this worktree")

// processAlive tells whether the process that started a set still runs;
// tests replace it.
var processAlive = alive

// Dir returns the folder of the records: $MEGOO_SERVICES_DIR, else
// <user cache>/megoocolab/services.
func Dir() (string, error) {
	if d := os.Getenv("MEGOO_SERVICES_DIR"); d != "" {
		return d, nil
	}
	cache, err := os.UserCacheDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(cache, "megoocolab", "services"), nil
}

func recordPath(dir, project string) string {
	return filepath.Join(dir, project+".json")
}

// Claim writes rec's record only if none exists yet. When one does, the set
// is either still running (ErrBusy) or was left by a check whose services
// could not be removed.
func Claim(dir string, rec Record) error {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(rec, "", "  ")
	if err != nil {
		return err
	}
	path := recordPath(dir, rec.Project)
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if errors.Is(err, fs.ErrExist) {
		if old, rerr := readRecord(path); rerr == nil && processAlive(old.PID) {
			return ErrBusy
		}
		return fmt.Errorf("an earlier check's services could not be removed (%s); run `megoocolab-runner services clean`", path)
	}
	if err != nil {
		return err
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		os.Remove(path)
		return err
	}
	if err := f.Close(); err != nil {
		os.Remove(path)
		return err
	}
	return nil
}

// Save replaces rec's record: a temp file renamed over it, so a reader never
// sees half a record.
func Save(dir string, rec Record) error {
	data, err := json.MarshalIndent(rec, "", "  ")
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(dir, rec.Project+".json.tmp-*")
	if err != nil {
		return err
	}
	tmp := f.Name()
	if _, err := f.Write(data); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	if err := f.Close(); err != nil {
		os.Remove(tmp)
		return err
	}
	if err := os.Rename(tmp, recordPath(dir, rec.Project)); err != nil {
		os.Remove(tmp)
		return err
	}
	return nil
}

// List returns the records in dir. Only <project>.json files whose project is
// one the runner names (IsOurs) and matches the file name count; anything
// else in the folder is ignored, and so are records that cannot be read.
func List(dir string) ([]Record, error) {
	entries, err := os.ReadDir(dir)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var recs []Record
	for _, e := range entries {
		project, ok := strings.CutSuffix(e.Name(), ".json")
		if !ok || e.IsDir() || !IsOurs(project) {
			continue
		}
		rec, err := readRecord(filepath.Join(dir, e.Name()))
		if err != nil || rec.Project != project {
			continue
		}
		recs = append(recs, rec)
	}
	return recs, nil
}

func readRecord(path string) (Record, error) {
	var rec Record
	data, err := os.ReadFile(path)
	if err != nil {
		return rec, err
	}
	err = json.Unmarshal(data, &rec)
	return rec, err
}
