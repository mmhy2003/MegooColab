//go:build linux

package gitstate

import (
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestFifoStandingInForATrackedFileDoesNotHang(t *testing.T) {
	dir := repo(t)
	before, err := Capture(dir)
	if err != nil {
		t.Fatal(err)
	}
	a := filepath.Join(dir, "a.txt")
	if err := os.Remove(a); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Mkfifo(a, 0o644); err != nil {
		t.Fatal(err)
	}
	type res struct {
		dirty bool
		err   error
	}
	ch := make(chan res, 1)
	go func() {
		st, err := CaptureAfter(dir, &before)
		ch <- res{st.Dirty, err}
	}()
	select {
	case r := <-ch:
		if !r.dirty {
			t.Fatalf("dirty=%v err=%v", r.dirty, r.err)
		}
	case <-time.After(8 * time.Second):
		t.Fatal("CaptureAfter hangs on a FIFO")
	}
}

func TestSizeMarkedFileEditWithRestoredMtimeIsSeenViaCtime(t *testing.T) {
	old := maxFileBytes
	maxFileBytes = 4
	t.Cleanup(func() { maxFileBytes = old })
	dir := repo(t)
	p := filepath.Join(dir, "big")
	if err := os.WriteFile(p, []byte("aaaaaaaa"), 0o644); err != nil {
		t.Fatal(err)
	}
	before, err := Capture(dir)
	if err != nil {
		t.Fatal(err)
	}
	fi, _ := os.Stat(p)
	time.Sleep(20 * time.Millisecond)
	if err := os.WriteFile(p, []byte("bbbbbbbb"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(p, fi.ModTime(), fi.ModTime()); err != nil {
		t.Fatal(err)
	}
	st, err := CaptureAfter(dir, &before)
	if err != nil || !st.Dirty {
		t.Fatalf("dirty=%v err=%v", st.Dirty, err)
	}
}

func TestUnreadableFileGetsAMarkerAndIsStable(t *testing.T) {
	dir := repo(t)
	p := filepath.Join(dir, "secret")
	if err := os.WriteFile(p, []byte("s"), 0o000); err != nil {
		t.Fatal(err)
	}
	if f, err := os.Open(p); err == nil {
		f.Close()
		t.Skip("running as a user that can read mode 000 files")
	}
	fp, err := fingerprint(dir, statusEntries(mustStatus(t, dir)))
	if err != nil || !strings.Contains(fp, "unreadable:permission") {
		t.Fatalf("%q %v", fp, err)
	}
	before, err := Capture(dir)
	if err != nil {
		t.Fatal(err)
	}
	st, err := CaptureAfter(dir, &before)
	if err != nil || st.Dirty {
		t.Fatalf("unchanged: dirty=%v err=%v", st.Dirty, err)
	}
}
