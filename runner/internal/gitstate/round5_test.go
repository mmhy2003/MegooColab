package gitstate

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// An earlier run leaves HEAD on a second branch under the task prefix. The
// read-only agent commits on the real task branch and switches back.
func TestShadowBranchUnderThePrefixCannotHideACommit(t *testing.T) {
	main := repo(t)
	wt := filepath.Join(t.TempDir(), "wt")
	run(t, main, "worktree", "add", "-q", "-b", "megoo/MEG-5-title", wt)
	run(t, wt, "checkout", "-q", "-b", "megoo/MEG-5-shadow") // an earlier run's leftover
	if err := Pin(wt, main); err != nil {
		t.Fatal(err)
	}
	before, err := CapturePrefixed(wt, "megoo/MEG-5-")
	if err != nil {
		t.Fatal(err)
	}
	if !before.OnBranchPrefix("megoo/MEG-5-") {
		t.Fatal("the manager's gate would refuse")
	}
	run(t, wt, "checkout", "-q", "megoo/MEG-5-title")
	if err := os.WriteFile(filepath.Join(wt, "evil.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, wt, "add", ".")
	run(t, wt, "commit", "-q", "-m", "agent commit")
	run(t, wt, "checkout", "-q", "megoo/MEG-5-shadow")
	st, err := CaptureAfter(wt, &before)
	if err != nil || !st.Dirty {
		t.Fatalf("dirty=%v err=%v", st.Dirty, err)
	}
}

func TestBranchCreatedOrDeletedUnderThePrefixIsDirty(t *testing.T) {
	for name, change := range map[string]func(t *testing.T, wt string){
		"created": func(t *testing.T, wt string) { run(t, wt, "branch", "megoo/MEG-6-new") },
		"deleted": func(t *testing.T, wt string) { run(t, wt, "branch", "-D", "megoo/MEG-6-old") },
	} {
		t.Run(name, func(t *testing.T) {
			main := repo(t)
			wt := filepath.Join(t.TempDir(), "wt")
			run(t, main, "worktree", "add", "-q", "-b", "megoo/MEG-6-title", wt)
			run(t, wt, "branch", "megoo/MEG-6-old")
			if err := Pin(wt, main); err != nil {
				t.Fatal(err)
			}
			before, err := CapturePrefixed(wt, "megoo/MEG-6-")
			if err != nil {
				t.Fatal(err)
			}
			change(t, wt)
			st, err := CaptureAfter(wt, &before)
			if err != nil || !st.Dirty {
				t.Fatalf("dirty=%v err=%v", st.Dirty, err)
			}
		})
	}
}

func TestUnchangedRunWithAnOldSlugBranchIsNotDirty(t *testing.T) {
	main := repo(t)
	wt := filepath.Join(t.TempDir(), "wt")
	run(t, main, "worktree", "add", "-q", "-b", "megoo/MEG-7-title", wt)
	run(t, wt, "branch", "megoo/MEG-7-old-slug")
	if err := Pin(wt, main); err != nil {
		t.Fatal(err)
	}
	before, err := CapturePrefixed(wt, "megoo/MEG-7-")
	if err != nil {
		t.Fatal(err)
	}
	st, err := CaptureAfter(wt, &before)
	if err != nil || st.Dirty {
		t.Fatalf("dirty=%v err=%v", st.Dirty, err)
	}
	// another task's branch is none of this run's business
	run(t, wt, "branch", "megoo/MEG-8-other")
	st, err = CaptureAfter(wt, &before)
	if err != nil || st.Dirty {
		t.Fatalf("another task's branch: dirty=%v err=%v", st.Dirty, err)
	}
}

func joinConfig(kv ...string) string {
	var b strings.Builder
	for i := 0; i < len(kv); i += 2 {
		b.WriteString(kv[i] + "\n" + kv[i+1] + "\x00")
	}
	return b.String()
}

func TestStockLfsFilterIsLeftAloneAndOthersAreSwitchedOff(t *testing.T) {
	stock := joinConfig(
		"filter.lfs.clean", "git-lfs clean -- %f",
		"filter.lfs.smudge", "git-lfs smudge -- %f",
		"filter.lfs.process", "git-lfs filter-process",
		"filter.lfs.required", "true",
	)
	if got := filterOffArgs(stock); len(got) != 0 {
		t.Fatalf("stock lfs must stay on: %v", got)
	}
	for name, cfg := range map[string]string{
		"lookalike process": joinConfig("filter.lfs.process", "git-lfs filter-process; touch x"),
		"changed clean":     joinConfig("filter.lfs.process", "git-lfs filter-process", "filter.lfs.clean", "evil %f"),
		"changed smudge":    joinConfig("filter.lfs.process", "git-lfs filter-process", "filter.lfs.smudge", "evil"),
		"no process":        joinConfig("filter.lfs.clean", "git-lfs clean -- %f"),
	} {
		got := strings.Join(filterOffArgs(cfg), " ")
		for _, want := range []string{"filter.lfs.clean=", "filter.lfs.smudge=", "filter.lfs.process=", "filter.lfs.required=false"} {
			if !strings.Contains(got, want) {
				t.Fatalf("%s: missing %s in %q", name, want, got)
			}
		}
	}
	got := strings.Join(filterOffArgs(joinConfig("filter.x.clean", "sh -c evil", "filter.a.b.smudge", "s")), " ")
	for _, want := range []string{"filter.x.clean=", "filter.a.b.process=", "filter.a.b.required=false"} {
		if !strings.Contains(got, want) {
			t.Fatalf("missing %s in %q", want, got)
		}
	}
}
