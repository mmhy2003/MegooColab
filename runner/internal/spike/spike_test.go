package spike

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/testutil"
	"github.com/mmhy2003/megoocolab/runner/internal/worktree"
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

// An agent that hides its write: it adds the file to .git/info/exclude (inside
// the repository's .git, outside the worktree) and writes the file directly.
// git status --porcelain would show nothing.
func TestSpikeDetectsIgnoredWriteAndGitInternals(t *testing.T) {
	res, out := runFake(t, PolicyReadOnly,
		`[{"direct_write":{"path":"../../../../repo/.git/info/exclude","content":"spike-write.txt\n"}},{"direct_write":{"path":"spike-write.txt","content":"OK"}}]`)
	got := strings.Join(failed(res), ",")
	for _, want := range []string{"worktree_clean", "spike_write_absent", "git_internals_unchanged"} {
		if !strings.Contains(got, want) {
			t.Errorf("check %s did not fail; failed = %s\n%s", want, got, out)
		}
	}
}

func fixture(t *testing.T) baseline {
	t.Helper()
	dir := t.TempDir()
	repo := filepath.Join(dir, "repo")
	if err := initRepo(repo); err != nil {
		t.Fatal(err)
	}
	wt, branch, err := worktree.Ensure(repo, filepath.Join(dir, "cache"), agentID, taskKey, taskTitle)
	if err != nil {
		t.Fatal(err)
	}
	return captureBaseline(repo, wt, branch)
}

func mustGit(t *testing.T, dir string, args ...string) {
	t.Helper()
	if out, err := git(dir, args...); err != nil {
		t.Fatalf("git %v: %v: %s", args, err, out)
	}
}

func failedNames(cs []Check) string {
	var n []string
	for _, c := range cs {
		if !c.Pass {
			n = append(n, c.Name)
		}
	}
	return strings.Join(n, ",")
}

func TestCheckReadOnlyUntouchedPasses(t *testing.T) {
	b := fixture(t)
	if f := failedNames(checkReadOnly(b)); f != "" {
		t.Fatalf("untouched read_only failed: %s", f)
	}
	if f := failedNames(checkWorkspace(b)); f == "" || !strings.Contains(f, "inside_write_exists") {
		t.Fatalf("workspace with no write must fail inside_write_exists, got %q", f)
	}
}

// skip-worktree hides an edit of a tracked file from git status.
func TestCheckReadOnlyDetectsSkipWorktreeEdit(t *testing.T) {
	b := fixture(t)
	mustGit(t, b.wt, "update-index", "--skip-worktree", "README.md")
	if err := os.WriteFile(filepath.Join(b.wt, "README.md"), []byte("changed\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if out, _ := git(b.wt, "status", "--porcelain"); out != "" {
		t.Fatalf("test premise: status should hide the edit, got %q", out)
	}
	if f := failedNames(checkReadOnly(b)); !strings.Contains(f, "readme_unchanged") {
		t.Fatalf("skip-worktree edit not caught: %q", f)
	}
}

func TestCheckReadOnlyDetectsCommitAndRefs(t *testing.T) {
	b := fixture(t)
	mustGit(t, b.wt, "commit", "--allow-empty", "-q", "-m", "spike")
	f := failedNames(checkReadOnly(b))
	for _, want := range []string{"worktree_head_unchanged", "refs_unchanged"} {
		if !strings.Contains(f, want) {
			t.Errorf("%s did not fail: %q", want, f)
		}
	}

	b = fixture(t)
	mustGit(t, b.repo, "tag", "sneaky")
	mustGit(t, b.repo, "branch", "extra")
	if f := failedNames(checkReadOnly(b)); !strings.Contains(f, "refs_unchanged") {
		t.Fatalf("extra tag/branch not caught: %q", f)
	}
	if f := failedNames(checkReadOnly(b)); strings.Contains(f, "head_unchanged") {
		t.Fatalf("HEAD did not move: %q", f)
	}
}

func TestCheckReadOnlyDetectsHook(t *testing.T) {
	b := fixture(t)
	if err := os.WriteFile(filepath.Join(b.repo, ".git", "hooks", "post-commit"), []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	if f := failedNames(checkReadOnly(b)); !strings.Contains(f, "git_internals_unchanged") {
		t.Fatalf("new hook not caught: %q", f)
	}
}

func TestCheckWorkspace(t *testing.T) {
	b := fixture(t)
	write := func(content string) {
		if err := os.WriteFile(filepath.Join(b.wt, "spike-write.txt"), []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	write("OK\n")
	if f := failedNames(checkWorkspace(b)); f != "" {
		t.Fatalf("good workspace failed: %s", f)
	}
	// the agent's own branch may move
	mustGit(t, b.wt, "add", ".")
	mustGit(t, b.wt, "commit", "-q", "-m", "work")
	if f := failedNames(checkWorkspace(b)); f != "" {
		t.Fatalf("a commit on the task branch must be allowed: %s", f)
	}
	write("nope")
	if f := failedNames(checkWorkspace(b)); !strings.Contains(f, "inside_write_content") {
		t.Fatalf("wrong content not caught: %q", f)
	}
	write("OK")
	mustGit(t, b.repo, "commit", "--allow-empty", "-q", "-m", "on main")
	if f := failedNames(checkWorkspace(b)); !strings.Contains(f, "repo_head_unchanged") {
		t.Fatalf("binding repo commit not caught: %q", f)
	}
	if err := os.WriteFile(filepath.Join(b.repo, "stray.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if f := failedNames(checkWorkspace(b)); !strings.Contains(f, "repo_clean") {
		t.Fatalf("stray file in binding repo not caught: %q", f)
	}
}

func TestRunRecordsSetupFailureAndKeepsEarlierResults(t *testing.T) {
	t.Setenv("MEGOO_ADAPTER_CLAUDE_CODE", `"`+testutil.BuildFakeAgent(t)+`"`)
	t.Setenv("FAKEAGENT_SCENARIO", `[{"say":"hi"}]`)
	rep, err := Run(context.Background(), Options{
		Program: "claude_code", Timeout: time.Minute, ReportDir: t.TempDir(),
		setupHook: func(policy string) error {
			if policy == PolicyWorkspace {
				return errors.New("boom")
			}
			return nil
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(rep.Results) != 2 || !rep.Results[0].Passed() || rep.Results[1].Passed() {
		t.Fatalf("results = %+v", rep.Results)
	}
	if rep.Results[1].Checks[0].Name != "setup" || rep.Path == "" {
		t.Fatalf("setup failure not recorded: %+v", rep.Results[1])
	}
}

func TestRunStopsWhenContextCancelled(t *testing.T) {
	t.Setenv("MEGOO_ADAPTER_CLAUDE_CODE", `"`+testutil.BuildFakeAgent(t)+`"`)
	t.Setenv("FAKEAGENT_SCENARIO", `[{"sleep_ms":60000}]`)
	ctx, cancel := context.WithCancel(context.Background())
	go func() { time.Sleep(1500 * time.Millisecond); cancel() }()
	start := time.Now()
	rep, err := Run(ctx, Options{Program: "claude_code", Timeout: time.Minute, ReportDir: t.TempDir()})
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("err = %v", err)
	}
	if len(rep.Results) != 1 || time.Since(start) > 30*time.Second {
		t.Fatalf("the second policy must not start: %d results after %v", len(rep.Results), time.Since(start))
	}
}
