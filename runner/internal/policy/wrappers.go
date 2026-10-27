package policy

import (
	"regexp"
	"strings"
)

// Shell wrappers. Codex runs every command through a shell, `powershell.exe -Command "<script>"` on Windows and
// `bash -lc '<script>'` elsewhere, often chaining several commands with ";" and "|". A read-only run accepts a
// wrapper only in one of the exact forms below, with a script whose every command, split on ";" and "|", is a
// plain read-only command by the same rules as a command on its own. Nothing else in a script is accepted:
// no "&&", "||", "&", redirection, substitution, variables, script blocks, comments, double quotes or escapes,
// so each shell splits the script into the same commands this check sees.

// maxScriptCommands bounds a wrapped script.
const maxScriptCommands = 10

// scriptMeta is refused anywhere in a wrapped script (";" and "|" are the only separators allowed). "!" is
// left to the per-command check, which allows it only inside single quotes (literal in every shell; rg's
// "-g '!vendor'" excludes a glob).
const scriptMeta = "&<>`$()%^\n\r\x00\"\\{}@#"

// powerShellOptions may come before -Command: they only switch off the profile, the banner and prompts.
var powerShellOptions = map[string]bool{"-noprofile": true, "-noninteractive": true, "-nologo": true}

// unwrapShell returns the script of a recognised shell wrapper and whether it is PowerShell. Any other use of
// a shell (another option, more than one script argument, a script file) is not a wrapper and stays denied.
func unwrapShell(cmd string) (script string, powerShell bool, ok bool) {
	toks, ok := tokenize(cmd)
	if !ok || len(toks) < 3 {
		return "", false, false
	}
	prog, ok := programName(toks[0])
	if !ok {
		return "", false, false
	}
	args := toks[1:]
	switch prog {
	case "powershell", "pwsh":
		for len(args) > 2 && powerShellOptions[strings.ToLower(args[0])] {
			args = args[1:]
		}
		if len(args) == 2 && (strings.EqualFold(args[0], "-Command") || strings.EqualFold(args[0], "-c")) {
			return args[1], true, true
		}
	case "bash", "sh", "zsh":
		if len(args) == 2 && (args[0] == "-c" || args[0] == "-lc") {
			return args[1], false, true
		}
		if len(args) == 3 && args[0] == "-l" && args[1] == "-c" {
			return args[2], false, true
		}
	}
	return "", false, false
}

// readOnlyScript: every command of a wrapped script is a plain read-only command.
func readOnlyScript(script string, powerShell bool) bool {
	if strings.ContainsAny(script, scriptMeta) || strings.Contains(script, "||") {
		return false
	}
	commands := strings.Split(strings.ReplaceAll(script, ";", "|"), "|")
	if len(commands) > maxScriptCommands {
		return false
	}
	for _, c := range commands {
		c = strings.Trim(c, " ")
		if c == "" || !readOnlyCommand(c, powerShell) {
			return false
		}
	}
	return true
}

// PowerShell's own read-only commands (and their usual aliases), each with an exact parameter list. Parameters
// are matched case-insensitively and never abbreviated; a parameter's value is the next word.
var powerShellSpecs = func() map[string]flagSpec {
	childItem := flagSpec{
		words:    []string{"-force", "-recurse", "-name", "-file", "-directory", "-hidden"},
		wordsVal: []string{"-path", "-literalpath", "-filter", "-include", "-exclude", "-depth"},
	}
	content := flagSpec{
		words:    []string{"-raw", "-force"},
		wordsVal: []string{"-path", "-literalpath", "-totalcount", "-head", "-tail", "-first", "-last", "-encoding", "-readcount"},
	}
	selectString := flagSpec{
		words:    []string{"-simplematch", "-casesensitive", "-list", "-notmatch", "-allmatches", "-quiet", "-raw"},
		wordsVal: []string{"-pattern", "-path", "-literalpath", "-context", "-include", "-exclude", "-encoding"},
	}
	return map[string]flagSpec{
		"get-childitem": childItem, "gci": childItem,
		"get-content": content, "gc": content,
		"select-string": selectString, "sls": selectString,
		"select-object":  {words: []string{"-unique"}, wordsVal: []string{"-first", "-last", "-skip", "-property", "-expandproperty", "-index"}},
		"sort-object":    {words: []string{"-descending", "-unique", "-casesensitive"}, wordsVal: []string{"-property", "-top", "-bottom"}},
		"measure-object": {words: []string{"-line", "-word", "-character", "-sum", "-average", "-maximum", "-minimum"}, wordsVal: []string{"-property"}},
		"get-item":       {words: []string{"-force"}, wordsVal: []string{"-path", "-literalpath"}},
		"test-path":      {wordsVal: []string{"-path", "-literalpath", "-pathtype"}},
		"out-string":     {words: []string{"-stream"}, wordsVal: []string{"-width"}},
		"get-location":   {},
	}
}()

// psDrive is a PowerShell drive-qualified word ("Env:", "variable:x", "HKLM:/..."). Only a file path on a
// lettered drive ("C:/x") is a file: the others reach the environment, variables, functions, the registry or
// certificates, which no read of the repository needs.
var psDrive = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_]*:`)
var fileDrive = regexp.MustCompile(`^[A-Za-z]:/`)

func powerShellDriveWord(tok string) bool {
	return psDrive.MatchString(tok) && !fileDrive.MatchString(tok)
}
