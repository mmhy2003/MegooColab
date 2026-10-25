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
		errors.New("cannot load config"):          1,
	}
	for err, want := range cases {
		if got := exitCode(err); got != want {
			t.Errorf("exitCode(%v) = %d, want %d", err, got, want)
		}
	}
	if exitStoppedByServer == 0 || exitStoppedByServer == 1 {
		t.Fatalf("exitStoppedByServer = %d must differ from success and generic failure", exitStoppedByServer)
	}
}

func TestSystemdUnitDoesNotRestartAfterServerStop(t *testing.T) {
	script, _ := serviceConfig("/usr/bin").Option["SystemdScript"].(string)
	want := "RestartPreventExitStatus=" + strconv.Itoa(exitStoppedByServer) + "\n"
	if !strings.Contains(script, want) {
		t.Errorf("SystemdScript lacks %q:\n%s", want, script)
	}
}
