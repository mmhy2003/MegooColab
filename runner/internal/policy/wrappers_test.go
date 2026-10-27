package policy_test

import (
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/policy"
)

// Codex runs every command through a shell: `powershell.exe -Command "<script>"` on Windows, `bash -lc
// '<script>'` elsewhere, often chaining several commands. A read-only run accepts such a wrapper only when
// every command of the script, split on ";" and "|", is itself a plain read-only command.
func TestReadOnlyShellWrappers(t *testing.T) {
	allowed := []string{
		// what Codex really sent on Windows
		`"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -Command "Get-ChildItem -Force | Select-Object Mode,Name; rg --files -g 'README*' -g 'AGENTS.md' -g '*.py' -g 'pyproject.toml'"`,
		`powershell.exe -Command "Get-Location; Get-ChildItem -Recurse -Filter '*.py' | Select-Object -First 50 FullName"`,
		// ... and its second try: the adapter splices quotes POSIX-style; "!" excludes a glob in rg
		`"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -Command "Get-Location; rg --files -g '"'!node_modules'"' -g '"'!vendor'"'; git log -5 --oneline"`,
		`powershell -NoProfile -NonInteractive -Command "Get-Content -Path app/sign.py -TotalCount 40"`,
		`pwsh -c "Select-String -Pattern 'HMAC' -Path app/sign.py -Context 2,3"`,
		`powershell -Command "git log --oneline -n 5; git status"`,
		`powershell -Command "gc app/sign.py | Measure-Object -Line"`,
		`powershell -Command "get-childitem -force -recurse -include '*.md'"`,
		`powershell -Command "Get-Content C:/repo/a.txt -Raw | Out-String -Width 200"`,
		`powershell -Command "Test-Path -Path app/sign.py; Get-Item app/sign.py"`,
		`powershell -Command "Get-ChildItem | Sort-Object -Property Name -Descending | Select-Object -First 5"`,
		`/bin/bash -lc 'rg --files | head -n 50'`,
		`bash -c "cat app/sign.py"`,
		"sh -c ls",
		`zsh -lc 'git diff --stat; git status --short'`,
		"bash -l -c 'ls -la'",
		// rg and PowerShell's own commands never glob-expand their arguments (unlike MSYS programs), so a
		// quoted pattern may start with a glob character
		"rg -g '*.go' foo", "rg --files -g '*.py'",
	}
	for _, c := range allowed {
		if !policy.ReadOnlyCommand(c) {
			t.Errorf("%q should be allowed", c)
		}
	}
	denied := []string{
		// anything that writes, runs or reaches outside plain reading
		`powershell -Command "Remove-Item a.txt"`, `powershell -Command "Get-ChildItem | Remove-Item"`,
		`powershell -Command "Get-Content a.txt > b.txt"`, `powershell -Command "Get-ChildItem | Out-File x"`,
		`powershell -Command "Set-Content a b"`, `powershell -Command "Start-Process calc"`, `powershell -Command "iex x"`,
		`powershell -Command "Get-ChildItem; Invoke-Expression x"`, `powershell -Command "& calc"`, `powershell -Command ". ./x.ps1"`,
		`powershell -Command "Get-ChildItem | ForEach-Object { rm $_ }"`, `powershell -Command "Sort-Object -Property { 1 }"`,
		`powershell -Command "Select-Object @{n='a';e={1}}"`, `powershell -Command "Get-Content (Get-Item a)"`,
		`powershell -Command "Get-Content a # c"`, `powershell -Command "[IO.File]::Delete('a')"`,
		`powershell -Command "Get-Content $env:USERPROFILE/.ssh/id_rsa"`, `powershell -Command "Get-Content -Wait a.txt"`,
		`powershell -Command "Get-ChildItem -Rec"`, `powershell -Command "Get-ChildItem -Path:x"`, `powershell -Command "Get-ChildItem -Filter *.py"`,
		// PowerShell drives other than a file path: the environment, variables, functions, the registry, certificates
		`powershell -Command "Get-ChildItem Env:"`, `powershell -Command "Get-Content env:PATH"`, `powershell -Command "gci Variable:"`,
		`powershell -Command "Get-ChildItem -Path Env:"`, `powershell -Command "Get-ChildItem function:"`, `powershell -Command "cat env:USERNAME"`,
		`powershell -Command "Get-Item HKLM:/Software"`, `powershell -Command "Get-ChildItem Cert:/CurrentUser"`, `powershell -Command "type env:x"`,
		// broken or ambiguous scripts
		`powershell -Command "Get-ChildItem || Remove-Item x"`, `powershell -Command "Get-ChildItem;; ls"`, `powershell -Command "Get-ChildItem;"`,
		`powershell -Command "| ls"`, `powershell -Command "ls|ls|ls|ls|ls|ls|ls|ls|ls|ls|ls"`,
		`powershell -Command "Get-ChildItem -Force | Select-Object Mode,Name; rg --pre=x foo"`,
		// wrapper forms other than one -Command script
		`powershell -Command Get-ChildItem Remove-Item`, "powershell -EncodedCommand ZQBjAGgAbwA=", "powershell -File x.ps1",
		"powershell -ExecutionPolicy Bypass -Command ls", `powershell "ls"`, "powershell -Command", `powershell -Command "powershell -Command ls"`,
		`./powershell -Command ls`, "cmd /c dir", "cmd.exe /c type a", `powershell -Command "ls" -Command "rm x"`,
		// bash, sh and zsh
		"bash -lc 'ls && rm x'", "bash -c 'cat a > b'", "bash -c 'rm -rf x'", "bash -c 'ls; rm x'", "bash -c 'echo $(id)'",
		`bash -c "ls" extra`, "bash -i -c ls", "bash -c", "bash script.sh", "bash -lc 'cat a | sh'", "bash -lc 'ls\nrm x'",
		`bash -c 'cat ~/.ssh/id_rsa'`, "bash -c 'ls &'", "bash -c 'ls !x'", `powershell -Command "rg !x"`, `bash -c "ls\"; rm x; \""`, "sh -c 'bash -c ls'", "bash -lc '`id`'",
	}
	for _, c := range denied {
		if policy.ReadOnlyCommand(c) {
			t.Errorf("%q must be denied", c)
		}
	}
	// the wrapper does not lift the existing rules for the commands inside it
	for _, inner := range []string{"git push", "find . -delete", "rg --pre ./evil foo", "git log --output=x", "tail -f a"} {
		for _, wrap := range []string{`powershell -Command "%s"`, "bash -lc '%s'"} {
			c := strings.Replace(wrap, "%s", inner, 1)
			if policy.ReadOnlyCommand(c) {
				t.Errorf("%q must be denied", c)
			}
		}
	}
}
