//go:build !windows

package cmd

import (
	"errors"
	"slices"
	"testing"

	"github.com/kardianos/service"
)

// fakeKardianos embeds the interface so it only overrides what Install uses.
type fakeKardianos struct {
	service.Service
	status       service.Status
	statusErr    error
	uninstallErr error
	calls        []string
}

func (f *fakeKardianos) Status() (service.Status, error) { return f.status, f.statusErr }
func (f *fakeKardianos) Stop() error                     { f.calls = append(f.calls, "stop"); return nil }
func (f *fakeKardianos) Uninstall() error {
	f.calls = append(f.calls, "uninstall")
	return f.uninstallErr
}
func (f *fakeKardianos) Install() error { f.calls = append(f.calls, "install"); return nil }

func assertCalls(t *testing.T, f *fakeKardianos, want ...string) {
	t.Helper()
	if !slices.Equal(f.calls, want) {
		t.Fatalf("calls = %v, want %v", f.calls, want)
	}
}

func TestLibInstallReplacesFailedUnit(t *testing.T) {
	f := &fakeKardianos{statusErr: errors.New("unit is failed")}
	if err := (libManager{f}).Install(); err != nil {
		t.Fatal(err)
	}
	assertCalls(t, f, "stop", "uninstall", "install")
}

func TestLibInstallFresh(t *testing.T) {
	f := &fakeKardianos{statusErr: service.ErrNotInstalled}
	if err := (libManager{f}).Install(); err != nil {
		t.Fatal(err)
	}
	assertCalls(t, f, "install")
}

func TestLibInstallReplacesStopped(t *testing.T) {
	f := &fakeKardianos{status: service.StatusStopped}
	if err := (libManager{f}).Install(); err != nil {
		t.Fatal(err)
	}
	assertCalls(t, f, "stop", "uninstall", "install")
}

func TestLibInstallReplacesRunning(t *testing.T) {
	f := &fakeKardianos{status: service.StatusRunning}
	if err := (libManager{f}).Install(); err != nil {
		t.Fatal(err)
	}
	assertCalls(t, f, "stop", "uninstall", "install")
}

func TestLibInstallUninstallError(t *testing.T) {
	boom := errors.New("boom")
	f := &fakeKardianos{status: service.StatusStopped, uninstallErr: boom}
	if err := (libManager{f}).Install(); !errors.Is(err, boom) {
		t.Fatalf("err = %v, want %v", err, boom)
	}
	assertCalls(t, f, "stop", "uninstall")
}
