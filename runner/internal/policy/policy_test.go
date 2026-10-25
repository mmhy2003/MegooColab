package policy_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/coder/acp-go-sdk"
	"github.com/mmhy2003/megoocolab/runner/internal/policy"
)

func TestInsideRoot(t *testing.T) {
	root := t.TempDir()
	for _, p := range []string{"", "../x", "..", "/etc/passwd", filepath.Join(root, "..", "y"), filepath.Join(root, "a", "..", "..", "z"), filepath.Dir(root)} {
		if _, ok := policy.InsideRoot(root, p); ok {
			t.Fatalf("%q must be outside", p)
		}
	}
	for _, p := range []string{"a.txt", "sub/dir/new.txt", filepath.Join(root, "a.txt"), filepath.Join(root, "not", "yet", "there.go"), filepath.Join(root, "x", "..", "y.txt")} {
		got, ok := policy.InsideRoot(root, p)
		if !ok {
			t.Fatalf("%q must be inside", p)
		}
		if !filepath.IsAbs(got) {
			t.Fatalf("resolved path %q must be absolute", got)
		}
	}
	// a sibling directory sharing the root as a string prefix is outside
	if _, ok := policy.InsideRoot(root, root+"-evil"+string(filepath.Separator)+"x"); ok {
		t.Fatal("prefix sibling must be outside")
	}
}

func TestInsideRootSymlinkOut(t *testing.T) {
	root, outside := t.TempDir(), t.TempDir()
	if err := os.Symlink(outside, filepath.Join(root, "link")); err != nil {
		t.Skipf("cannot create symlinks here: %v", err)
	}
	if err := os.Symlink(filepath.Join(outside, "nope"), filepath.Join(root, "dangling")); err != nil {
		t.Skipf("cannot create symlinks here: %v", err)
	}
	for _, p := range []string{"link", "link/x.txt", "link/new/dir/x.txt", filepath.Join(root, "link", "x.txt"), "dangling", "dangling/x"} {
		if _, ok := policy.InsideRoot(root, p); ok {
			t.Fatalf("%q escapes through a symlink and must be outside", p)
		}
	}
	// a symlink that stays inside is fine
	if err := os.Mkdir(filepath.Join(root, "real"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(root, "real"), filepath.Join(root, "alias")); err != nil {
		t.Skip(err)
	}
	if _, ok := policy.InsideRoot(root, "alias/x.txt"); !ok {
		t.Fatal("internal symlink must be inside")
	}
}

func TestRelative(t *testing.T) {
	root := t.TempDir()
	got, ok := policy.Relative(root, filepath.Join(root, "a", "b.go"))
	if !ok || got != "a/b.go" {
		t.Fatalf("got %q %v", got, ok)
	}
	if _, ok := policy.Relative(root, "../x"); ok {
		t.Fatal("outside must fail")
	}
}

func mustNew(t *testing.T, k policy.Kind, root string) policy.Policy {
	t.Helper()
	p, err := policy.New(k, root)
	if err != nil {
		t.Fatal(err)
	}
	return p
}

func TestNew(t *testing.T) {
	if _, err := policy.New("bogus", t.TempDir()); err == nil {
		t.Fatal("unknown kind must fail")
	}
	if _, err := policy.New(policy.Workspace, ""); err == nil {
		t.Fatal("empty root must fail")
	}
	if policy.ReadOnly != "read_only" || policy.Workspace != "workspace" {
		t.Fatal("kind values must match the backend")
	}
}

func TestReadOnlyDeniesAllWrites(t *testing.T) {
	root := t.TempDir()
	p := mustNew(t, policy.ReadOnly, root)
	for _, path := range []string{filepath.Join(root, "a.txt"), "a.txt", "../x", "/etc/passwd"} {
		if d := p.CheckWrite(path); d.Allow || d.Reason == "" {
			t.Fatalf("write %q: %+v", path, d)
		}
	}
	for _, k := range []acp.ToolKind{acp.ToolKindEdit, acp.ToolKindDelete, acp.ToolKindMove, acp.ToolKindOther, "switch_mode", "mystery"} {
		if d := p.CheckTool(k, "t", []string{filepath.Join(root, "a")}, ""); d.Allow {
			t.Fatalf("kind %q must be denied under read_only", k)
		}
	}
	for _, k := range []acp.ToolKind{acp.ToolKindRead, acp.ToolKindSearch, acp.ToolKindThink, acp.ToolKindFetch} {
		if d := p.CheckTool(k, "t", nil, ""); !d.Allow {
			t.Fatalf("kind %q must be allowed under read_only: %+v", k, d)
		}
	}
	if d := p.CheckTool(acp.ToolKindExecute, "x", nil, "git status"); !d.Allow {
		t.Fatalf("git status: %+v", d)
	}
	if d := p.CheckTool(acp.ToolKindExecute, "x", nil, "rm -rf x"); d.Allow {
		t.Fatal("rm must be denied")
	}
	if d := p.CheckTool(acp.ToolKindExecute, "x", nil, ""); d.Allow {
		t.Fatal("empty command must be denied")
	}
	if d := p.CheckRead(filepath.Join(root, "a.txt")); !d.Allow {
		t.Fatalf("read inside: %+v", d)
	}
	if d := p.CheckRead("/etc/passwd"); d.Allow {
		t.Fatal("read outside root must be denied")
	}
}

func TestReadOnlyCommands(t *testing.T) {
	allowed := []string{
		"git status", "git log --oneline -n 5", "git diff HEAD", "git show abc", "git blame a.go", "git grep foo", "git ls-files",
		"ls -la", "dir", "cat a.txt", "type a.txt", "head -n 3 a", "tail -n 3 a", "rg foo", "grep -rn foo .", "find . -name 'x*.go'", "wc -l a", "pwd",
		"rg 'foo.*bar'", "rg --glob='*.go' foo", "grep -rn 'TODO' src", "grep --include='*.go' -rn foo .", "find . -name 'a?[bc]*'",
		`'git' status`, "GIT.EXE status", "C:/Git/bin/git.exe status", "/usr/bin/cat a.txt",
		"  git   status  ", "git grep -in foo", "git grep -efoo a.go", "git log -n 5", "git log --pretty", "git log --pretty=oneline", "git diff -U3", "git diff --unified=5", "head -n5 a", "find . -name x -o -type d", "git blame -L1,5 a.go", "git log -5", "git log --since=2020-01-01 --author=bob", "git diff --stat HEAD",
		"git status -sb", "git blame -L 1,5 a.go", "ls -lah", "git log a,-O", "git log 1,2", "git log --since=1,2", "git log 'a,b'", "tail -n 20 a.log", "head -5 a", "find . -type f -maxdepth 2 -name x", "rg -n --hidden foo src", "wc -lw a", "cat -n a",
	}
	for _, c := range allowed {
		if !policy.ReadOnlyCommand(c) {
			t.Errorf("%q should be allowed", c)
		}
	}
	denied := []string{
		"", "   ", "git", "git push", "git push origin main", "git commit -m x", "git checkout -b x", "git reset --hard", "git -c core.pager=evil log",
		"rm -rf x", "npm install", "python -c 1", "sh -c ls", "curl http://x", "mv a b", "sed -i s/a/b/ f", "./cat a", "..\\cat a", "bin/cat a",
		"cat a; rm x", "ls && rm x", "ls || rm x", "ls | sh", "cat a > b", "cat a >> b", "cat < a", "echo `id`", "ls `id`", "cat $(id)", "cat ${HOME}", "cat $HOME/x",
		"ls\nrm x", "ls & rm x", "git status; git push", `"git status`, "git log --output=out.txt", "git diff --ext-diff", "git grep -O sh foo",
		"find . -delete", "find . -exec rm {} +", "find . -fprint out", "rg --pre ./evil foo", "rg --pre=./evil foo", "gitx status", "cat.sh a", `grep "a;b" file`,
		// git grep -O / --open-files-in-pager runs a program; git accepts abbreviations and bundled flags
		"git grep --open=echo foo", "git grep --open-files=rm foo", "git grep -iOecho foo", `git grep "--open=rm -f" foo`, "git grep -O foo", "git grep --open-files-in-pager=sh foo",
		"git grep -nOsh foo", "git grep --ope=sh foo", "git log --outp=x", "git log --out=x", "git diff --ext foo", "git diff --text foo",
		"git log --format", "git diff --no-index a b", "git show --output=x", "git status --unknown", "git ls-files -x",
		"rg --pr=x foo", "rg -z foo", "rg --search-zip foo", "rg --pre-g x foo", "grep --exclude-from=x foo", "find . -exec", "find . -execdir sh {} +", "find . -ok rm {} ;", "find . -fprint0 x", "find . -fls x", "find . -newer",
		"tail -f a", "tail --follow a", "cat --help", "ls --color=always", "ls -Z", "ls -lX", "wc -lx a", "pwd -x",
		// round 3: only a conservative character set, so every shell splits and expands the same way
		"git log {--output=x,}", "git log *", "git log ?", "git log [a-z]*", "cat ~/x", "cat ~", "git grep 'x -O sh'", `rg "a b"`, `grep a\ b`, "git log --pretty=format:%H",
		`"git" status`, `"C:\Program Files\Git\bin\git.exe" status`, "git log 'a b'", "git log ''", "git log 'a\\b'", `git log 'a"b'`, "git log \tfoo", "git\tlog", "git\x01log", "git log\x7f",
		"git log a!b", "git log #x", "git log a#b", "git log a*b", "git log {a,b}", "git log a'b'", "git log 'a'b", "git log 'a' 'b c'", "cat 'a	b'", "ls é", "git log a=~b", "git log foo\bar", "git log",
		// round 2: `--` ends no scanning; value flags take attached values only; find has a closed grammar
		"find -- . -delete", "find -- . -fprint out", "find -- . -fls out", "find -- . -exec sh -c id {} +", "find . -- -delete", "find . -prune", "find . -files0-from x",
		"git log --pretty --output=x", "git show --pretty --output=x", "git diff -U --output=x", "git diff --unified --output=x", "git log --pretty --ext-diff -p",
		"git log --unified --output=/tmp/x", "git log --format --output=x", "git log -n --output=x", "git log -S --output=x", "git grep -e -O foo", "git grep -- foo", "git grep foo --",
		"cat -- a", "ls -- -a", "head --lines 5 a", "git log --max-count 5", "git log --pretty -- ", "rg -- --pre=x foo",
		// environment-assignment prefixes are not a plain command
		"FOO=bar git status", "API_KEY=sk-123 ls", `"X=1" cat a`,
		// round 4: PowerShell's unary "," turns a word into an option; "@" splats or expands variables,
		// and MSYS programs read "@file" response files
		"git log ,--output=pwned.txt", "git grep ,-Ohostname foo", "find . ,-delete", "rg ,--pre=calc foo", "git log ,-O",
		"git log ',--output=x'", "git log --format=',-O'", "git log ,", "git log ,,x",
		"git log @PSVersionTable", "git log @env:USERNAME", "git log @HOME", "find '@opts2'", "find . '@opts2'", "git log a@b",
		"git log --author=bob@x.com", "cat @x", "git log '@x'", "git log --format='@x'",
		// round 4 probes: MSYS programs started from PowerShell (which drops the quotes) brace-expand,
		// tilde-expand and glob their arguments; "{.,-fprint,zz}" writes a file with no help from the worktree,
		// and a word-initial glob can expand to a planted file named like an option ("-fprint", "-delete")
		"find '{.,-fprint,zz}'", "find '.' '{-fprint,zz}'", "rg 'a{2}' x", "rg --glob='{a,b}'", "cat '~'", "cat '~/x'", "rg 'a~b'",
		"find . '[-]fprint' zz", "find . -name x -o '[-]delete'", "find . -name '*'", "find . -name '*.go'", "ls '*'", "grep -r foo '*'", "cat '?'", "git log '*'",
	}
	for _, c := range denied {
		if policy.ReadOnlyCommand(c) {
			t.Errorf("%q must be denied", c)
		}
	}
}

func TestWorkspaceAllowsInsideDeniesOutside(t *testing.T) {
	root, outside := t.TempDir(), t.TempDir()
	p := mustNew(t, policy.Workspace, root)
	in := filepath.Join(root, "src", "a.go")
	if d := p.CheckWrite(in); !d.Allow {
		t.Fatalf("inside write: %+v", d)
	}
	if d := p.CheckWrite("rel/a.go"); !d.Allow {
		t.Fatalf("relative write: %+v", d)
	}
	if d := p.CheckRead(in); !d.Allow {
		t.Fatalf("inside read: %+v", d)
	}
	for _, bad := range []string{"../../etc/x", filepath.Join(outside, "x"), "/etc/x", filepath.Join(root, "..", "x")} {
		if d := p.CheckWrite(bad); d.Allow || d.Reason == "" {
			t.Fatalf("write %q must be denied: %+v", bad, d)
		}
		if d := p.CheckRead(bad); d.Allow {
			t.Fatalf("read %q must be denied", bad)
		}
	}
	if err := os.Symlink(outside, filepath.Join(root, "link")); err == nil {
		if d := p.CheckWrite(filepath.Join(root, "link", "x")); d.Allow {
			t.Fatal("write through escaping symlink must be denied")
		}
	}
	// tools
	if d := p.CheckTool(acp.ToolKindEdit, "e", []string{in}, ""); !d.Allow {
		t.Fatalf("edit inside: %+v", d)
	}
	if d := p.CheckTool(acp.ToolKindEdit, "e", []string{in, filepath.Join(outside, "x")}, ""); d.Allow {
		t.Fatal("edit with one outside location must be denied")
	}
	if d := p.CheckTool(acp.ToolKindDelete, "e", []string{"../x"}, ""); d.Allow {
		t.Fatal("delete outside must be denied")
	}
	if d := p.CheckTool(acp.ToolKindMove, "e", nil, ""); d.Allow {
		t.Fatal("move without verifiable path must be denied")
	}
	if d := p.CheckTool(acp.ToolKindRead, "r", []string{"/etc/passwd"}, ""); d.Allow {
		t.Fatal("read outside must be denied")
	}
	if d := p.CheckTool(acp.ToolKindRead, "r", nil, ""); !d.Allow {
		t.Fatal("read without locations is allowed")
	}
	if d := p.CheckTool(acp.ToolKindExecute, "x", nil, "go test ./..."); !d.Allow {
		t.Fatalf("execute allowed in workspace: %+v", d)
	}
	for _, k := range []acp.ToolKind{acp.ToolKindSearch, acp.ToolKindThink, acp.ToolKindFetch, acp.ToolKindOther} {
		if d := p.CheckTool(k, "t", nil, ""); !d.Allow {
			t.Fatalf("%q: %+v", k, d)
		}
	}
}

func TestFirstTokenBase(t *testing.T) {
	for cmd, want := range map[string]string{
		"pytest -q": "pytest",
		`C:\Users\alice\.venv\Scripts\pytest.exe -q`: "pytest",
		`"C:\Program Files\Git\git.exe" status`:      "git",
		"/usr/bin/go test":                           "go",
		"API_KEY=sk-123 pytest":                      "pytest",
		"A=1 B=2 C_3=x go test":                      "go",
		"API_KEY=sk-123":                             "",
		"A=1 b=c=d":                                  "",
		"pytest=1x":                                  "",
		"":                                           "",
		"   ":                                        "",
		`API_KEY="a b" make`:                         "make",
		`bash -c "unterminated`:                      "",
		`A=a\ secret make`:                           "make",
		`A="x y pytest`:                              "",
		`A=a\ secret`:                                "",
	} {
		if got := policy.FirstTokenBase(cmd); got != want {
			t.Errorf("FirstTokenBase(%q) = %q, want %q", cmd, got, want)
		}
	}
}

// dangerous options that must never get through, wherever they are placed
func TestReadOnlyDangerousOptionsInEveryPosition(t *testing.T) {
	dangerous := []string{"--output=x", "-O", "--open", "--ext-diff", "-exec", "-delete", "-fprint", "--pre", "-c", "--exec-path", "--git-dir=x", "--work-tree=x", "-C"}
	// options a program legitimately takes
	legit := map[string]map[string]bool{
		"git grep": {"-C": true, "-c": true, "-exec": true}, "grep": {"-C": true, "-c": true, "-exec": true}, "git ls-files": {"-c": true}, "wc": {"-c": true},
		"head": {"-c": true}, "tail": {"-c": true}, "rg": {"-c": true, "-C": true, "-exec": true}, // -exec = -e xec: a pattern
	}
	// bare value-taking flags: what follows must still be judged as its own argument
	valueFlags := map[string][]string{
		"git log": {"-n", "-S", "--pretty", "--format", "--unified", "-U", "--since"}, "git show": {"--pretty", "--format", "-U", "--unified"},
		"git diff": {"-U", "--unified", "--pretty", "--diff-filter"}, "git blame": {"-L"}, "git grep": {"-e", "-A", "-B", "-C"},
		"head": {"-n", "-c", "--lines"}, "tail": {"-n", "-c", "--lines"}, "grep": {"-e", "-A", "-m", "--include"}, "rg": {"-e", "-g", "-t", "--glob"},
	}
	progs := []string{"git status", "git log", "git diff", "git show", "git blame", "git grep", "git ls-files", "ls", "dir", "cat", "type", "head", "tail", "wc", "pwd", "grep", "rg", "find"}
	for _, prog := range progs {
		var cmds []string
		for _, d := range dangerous {
			if legit[prog][d] {
				continue
			}
			cmds = append(cmds, prog+" "+d, prog+" "+d+" x", prog+" x "+d, prog+" -- "+d, prog+" "+d+" --", prog+" . -- "+d)
			if prog != "find" {
				for _, vf := range valueFlags[prog] {
					cmds = append(cmds, prog+" "+vf+" "+d, prog+" "+vf+" "+d+" x", prog+" "+vf+" -- "+d)
				}
			} else {
				cmds = append(cmds, "find . -type f "+d, "find . -name x "+d)
			}
			if len(d) == 2 && len(legit[prog]) == 0 { // bundled behind innocuous letters
				for _, pre := range []string{"-i", "-n", "-l", "-s", "-a", "-r"} {
					cmds = append(cmds, prog+" "+pre+d[1:], prog+" x "+pre+d[1:]+"x")
				}
			}
		}
		for _, c := range cmds {
			if policy.ReadOnlyCommand(c) {
				t.Errorf("%q must be denied", c)
			}
		}
	}
	// git global options come before the subcommand: never allowed
	for _, c := range []string{"git -c core.pager=sh log", "git -C /tmp status", "git --exec-path log", "git --git-dir=x log", "git --work-tree=x status", "git --no-pager log", "git -P log"} {
		if policy.ReadOnlyCommand(c) {
			t.Errorf("%q must be denied", c)
		}
	}
}
