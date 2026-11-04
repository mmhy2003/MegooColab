package jobs

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/mask"
	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

func (e *env) startRunWithSecrets(runID string, secrets []protocol.RunSecret) {
	e.startRunWith(runID, "MEG-1", func(rs *protocol.RunStart) { rs.Secrets = secrets })
}

func messageText(e *env, runID string) string {
	var sb strings.Builder
	for _, u := range e.updates(runID) {
		if u.Kind == "message" {
			sb.WriteString(jsonStr(u.Data))
		}
	}
	return sb.String()
}

func TestSecretsReachTheAgentEnvironment(t *testing.T) {
	e := newEnvWithCache(t, `[{"say_env":"STAGING_DB_PASSWORD"}]`, 1, t.TempDir())
	e.startRunWithSecrets("run-1", []protocol.RunSecret{{Name: "STAGING_DB_PASSWORD", Value: "s3cr3t-value"}})
	rf := e.finished("run-1")
	if rf.Outcome != "completed" {
		t.Fatalf("finished = %+v", rf)
	}
	got := messageText(e, "run-1")
	if !strings.Contains(got, "[STAGING_DB_PASSWORD]") || strings.Contains(got, "s3cr3t-value") {
		t.Fatalf("messages = %s", got)
	}
	if strings.Contains(rf.Summary, "s3cr3t-value") {
		t.Fatalf("summary = %q", rf.Summary)
	}
	log, err := os.ReadFile(filepath.Join(e.cache, "logs", "run-1.log"))
	if err != nil || strings.Contains(string(log), "s3cr3t-value") {
		t.Fatalf("run log holds the value (%v)", err)
	}
}

func TestReservedSecretNamesAreNotSet(t *testing.T) {
	e := newEnvWithCache(t, `[{"say_env":"PATH"}]`, 1, t.TempDir())
	e.startRunWithSecrets("run-1", []protocol.RunSecret{{Name: "PATH", Value: "/nowhere-at-all"}})
	e.finished("run-1")
	if got := messageText(e, "run-1"); strings.Contains(got, "[PATH]") || !strings.Contains(got, string(os.PathListSeparator)) {
		t.Fatalf("the agent's PATH was replaced: %s", got)
	}
}

func TestShortSecretValuesAreNotBlanked(t *testing.T) {
	e := newEnvWithCache(t, `[{"say_env":"PIN"}]`, 1, t.TempDir())
	e.startRunWithSecrets("run-1", []protocol.RunSecret{{Name: "PIN", Value: "abc"}})
	e.finished("run-1")
	if got := messageText(e, "run-1"); !strings.Contains(got, "abc") {
		t.Fatalf("messages = %s", got)
	}
}

func TestRedactorHoldsBackEverySecret(t *testing.T) {
	var sb strings.Builder
	w := newRedactor(&sb, mask.Build("tok_abcdef", []protocol.RunSecret{{Name: "DB", Value: "hunter2hunter2"}}))
	for _, part := range []string{"pw hunter2", "hunter2 and tok_ab", "cdef end"} {
		_, _ = w.Write([]byte(part))
	}
	_ = w.Close()
	if got := sb.String(); got != "pw [DB] and [redacted] end" {
		t.Fatalf("got %q", got)
	}
}

func TestSteerErrorIsBlanked(t *testing.T) {
	r := &run{masks: mask.Build("", []protocol.RunSecret{{Name: "DB", Value: "hunter2hunter2"}})}
	if got := r.blankText("could not use hunter2hunter2"); got != "could not use [DB]" {
		t.Fatalf("got %q", got)
	}
}
