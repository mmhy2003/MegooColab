package tools

import (
	"bytes"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"time"
)

// WriteFileAtomic writes data to a temporary file next to path, makes it private when asked (it may hold
// secrets), then renames it over path: a reader never sees half a file.
func WriteFileAtomic(path string, data []byte, private bool) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, "."+filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer os.Remove(name) // already gone after a successful rename
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if private {
		if err := MakePrivate(name); err != nil {
			return err
		}
	}
	return os.Rename(name, path)
}

// stamp is what a file looked like when it was read.
type stamp struct {
	exists bool
	size   int64
	mod    time.Time
	data   []byte
}

func stampOf(path string) (stamp, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return stamp{}, nil
	}
	if err != nil {
		return stamp{}, err
	}
	info, err := os.Stat(path)
	if err != nil {
		return stamp{}, err
	}
	return stamp{exists: true, size: info.Size(), mod: info.ModTime(), data: data}, nil
}

func (s stamp) same(o stamp) bool {
	return s.exists == o.exists && s.size == o.size && s.mod.Equal(o.mod) && bytes.Equal(s.data, o.data)
}

// ReplaceFile reads path (nil when it does not exist), lets edit change it and writes the result atomically.
// If the file changed between the read and the write (the program itself rewriting its config), it starts
// over with the new content, up to three times.
func ReplaceFile(path string, edit func(old []byte) ([]byte, error), private bool) error {
	for range 3 {
		before, err := stampOf(path)
		if err != nil {
			return err
		}
		next, err := edit(before.data)
		if err != nil {
			return err
		}
		now, err := stampOf(path)
		if err != nil {
			return err
		}
		if !before.same(now) {
			continue
		}
		return WriteFileAtomic(path, next, private)
	}
	return fmt.Errorf("%s kept changing while it was being updated", filepath.Base(path))
}
