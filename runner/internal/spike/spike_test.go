package spike

import (
	"bytes"
	"context"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/testutil"
)

func runFake(t *testing.T, policy, scenario string) (PolicyResult, string) {
	t.Helper()
	t.Setenv("MEGOO_ADAPTER_CLAUDE_CODE", `"`+testutil.BuildFakeAgent(t)+`"`)
	t.Setenv("FAKEAGENT_SCENARIO", scenario)
	var out bytes.Buffer
	rep, err := Run(context.Background(), Options{
		Program: "claude_code", Policies: []string{policy},
		Timeout: 2 * time.Minute, ReportDir: t.TempDir(), Out: &out,
	})
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if _, err := os.Stat(rep.Path); err != nil {
		t.Fatalf("report not written: %v", err)
	}
	return rep.Results[0], out.String()
}

func failed(r PolicyResult) []string {
	var names []string
	for _, c := range r.Checks {
		if !c.Pass {
			names = append(names, c.Name)
		}
	}
	return names
}

// An agent that writes through its own filesystem access (not the client) must
// be caught, because the checks read the disk.
func TestSpikeDetectsBypassingWrite(t *testing.T) {
	res, out := runFake(t, PolicyReadOnly,
		`[{"write":{"path":"spike-write.txt","content":"OK"}},{"direct_write":{"path":"spike-write.txt","content":"OK"}}]`)
	if res.Passed() {
		t.Fatalf("expected FAIL, got pass: %+v", res.Checks)
	}
	if got := failed(res); !strings.Contains(strings.Join(got, ","), "worktree_clean") {
		t.Fatalf("failed checks = %v", got)
	}
	if !strings.Contains(out, "[FAIL] worktree_clean") {
		t.Fatalf("output lacks FAIL line:\n%s", out)
	}
}

func TestSpikeDetectsBypassingWriteOutside(t *testing.T) {
	res, _ := runFake(t, PolicyWorkspace,
		`[{"direct_write":{"path":"spike-write.txt","content":"OK"}},{"direct_write":{"path":"../spike-outside.txt","content":"OK"}}]`)
	if res.Passed() || !strings.Contains(strings.Join(failed(res), ","), "outside_write_absent_beside_worktree") {
		t.Fatalf("expected the outside write to be caught: %+v", res.Checks)
	}
}

func TestSpikePassesWhenAgentComplies(t *testing.T) {
	res, out := runFake(t, PolicyReadOnly,
		`[{"write":{"path":"spike-write.txt","content":"OK"}},{"exec":{"command":"git commit --allow-empty -m spike"}},{"say":"could not"}]`)
	if !res.Passed() {
		t.Fatalf("read_only should pass: %+v\n%s", res.Checks, out)
	}
	if len(res.Permissions) == 0 {
		t.Fatal("no permission decisions captured")
	}
	if !strings.Contains(out, "[PASS] repo_clean") {
		t.Fatalf("output lacks PASS line:\n%s", out)
	}

	res, _ = runFake(t, PolicyWorkspace,
		`[{"write":{"path":"spike-write.txt","content":"OK"}},{"write":{"path":"../spike-outside.txt","content":"OK"}}]`)
	if !res.Passed() {
		t.Fatalf("workspace should pass: %+v", res.Checks)
	}
}

func TestSpikeFailsWhenRunFails(t *testing.T) {
	t.Setenv("MEGOO_ADAPTER_CLAUDE_CODE", `"`+testutil.BuildFakeAgent(t)+`"`)
	t.Setenv("FAKEAGENT_SCENARIO", `[{"sleep_ms":60000}]`)
	rep, err := Run(context.Background(), Options{
		Program: "claude_code", Policies: []string{PolicyReadOnly},
		Timeout: 500 * time.Millisecond, ReportDir: t.TempDir(),
	})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Passed() || rep.Results[0].Error != "timeout" {
		t.Fatalf("expected timeout FAIL, got %+v", rep.Results[0])
	}
}
