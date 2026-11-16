package cmd

import (
	"errors"
	"fmt"
	"strconv"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/conn"
)

// A revoked token (4401) or a newer runner (4409) ends the session for good:
// the exit status tells the service manager not to restart into a loop.
func TestExitCodeForServerStop(t *testing.T) {
	cases := map[error]int{
		conn.ErrUnauthorized:                      exitStoppedByServer,
		conn.ErrReplaced:                          exitStoppedByServer,
		fmt.Errorf("serve: %w", conn.ErrReplaced): exitStoppedByServer,
		fmt.Errorf("x: %w", errNotLoggedIn):       exitStoppedByServer,
		errors.New("boom"):                        1,
	}
	for err, want := range cases {
		if got := exitCode(err, "linux", true); got != want {
			t.Errorf("exitCode(%v) = %d, want %d", err, got, want)
		}
	}
	if exitStoppedByServer == 0 || exitStoppedByServer == 1 {
		t.Fatalf("exitStoppedByServer = %d must differ from success and generic failure", exitStoppedByServer)
	}
}

// The LaunchAgent restarts only after an unsuccessful exit, so in macOS service
// mode an exit that only `login` can fix becomes 0.
func TestExitCodeMacServiceMode(t *testing.T) {
	cases := []struct {
		err         error
		goos        string
		interactive bool
		want        int
	}{
		{conn.ErrReplaced, "darwin", false, 0},
		{fmt.Errorf("x: %w", errNotLoggedIn), "darwin", false, 0},
		{errors.New("boom"), "darwin", false, 1},
		{conn.ErrReplaced, "darwin", true, exitStoppedByServer},
		{conn.ErrReplaced, "linux", false, exitStoppedByServer},
		{quietError{conn.ErrUnauthorized}, "windows", false, exitStoppedByServer},
	}
	for _, c := range cases {
		if got := exitCode(c.err, c.goos, c.interactive); got != c.want {
			t.Errorf("exitCode(%v, %s, %v) = %d, want %d", c.err, c.goos, c.interactive, got, c.want)
		}
	}
}

func TestSystemdUnitDoesNotRestartAfterServerStop(t *testing.T) {
	script, _ := serviceConfig("/usr/bin").Option["SystemdScript"].(string)
	want := "RestartPreventExitStatus=" + strconv.Itoa(exitStoppedByServer) + "\n"
	if !strings.Contains(script, want) {
		t.Errorf("SystemdScript lacks %q:\n%s", want, script)
	}
}
