package policy

import (
	"regexp"
	"strings"
)

var readOnlyPrograms = map[string]bool{
	"git": true, "ls": true, "dir": true, "cat": true, "type": true, "head": true,
	"tail": true, "rg": true, "grep": true, "find": true, "wc": true, "pwd": true,
}

var readOnlyGitSubcommands = map[string]bool{
	"status": true, "log": true, "diff": true, "show": true, "blame": true, "grep": true, "ls-files": true,
}

// Anything that chains, redirects, substitutes or expands is refused outright
// (even inside quotes: refusing is always safe, and the agent can retry plainly).
const shellMeta = ";&|<>`$()%^\n\r\x00"

// Flags that make an otherwise read-only program write files or run other programs.
var dangerousArgs = map[string][]string{
	"git":  {"--output", "--ext-diff", "--textconv", "--open-files-in-pager", "--exec", "-O"},
	"find": {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"},
	"rg":   {"--pre", "--hostname-bin"},
}

var driveAbs = regexp.MustCompile(`^[A-Za-z]:[\\/]`)

// ReadOnlyCommand reports whether cmd is a single, plain invocation of one of
// the allowed read-only programs (for git, with an allowed subcommand).
//
// The program is the first token with quotes stripped, reduced to its lowercase
// basename without ".exe". A first token with a directory part must be an
// absolute path: "./cat" or "bin/cat" would run a file from the worktree.
func ReadOnlyCommand(cmd string) bool {
	if strings.ContainsAny(cmd, shellMeta) {
		return false
	}
	toks, ok := tokenize(cmd)
	if !ok || len(toks) == 0 {
		return false
	}
	prog, ok := programName(toks[0])
	if !ok || !readOnlyPrograms[prog] {
		return false
	}
	args := toks[1:]
	if prog == "git" && (len(args) == 0 || !readOnlyGitSubcommands[args[0]]) {
		return false
	}
	for _, a := range args {
		for _, bad := range dangerousArgs[prog] {
			if a == bad || strings.HasPrefix(a, bad+"=") || (strings.HasPrefix(bad, "--") && strings.HasPrefix(a, bad)) || (bad == "-O" && strings.HasPrefix(a, "-O")) {
				return false
			}
		}
	}
	return true
}

// tokenize splits on spaces and tabs, honouring single and double quotes (no
// escapes, so Windows paths keep their backslashes). An unterminated quote fails.
func tokenize(s string) ([]string, bool) {
	var toks []string
	var cur strings.Builder
	inTok := false
	var quote rune
	for _, r := range s {
		switch {
		case quote != 0:
			if r == quote {
				quote = 0
			} else {
				cur.WriteRune(r)
			}
		case r == '"' || r == '\'':
			quote, inTok = r, true
		case r == ' ' || r == '\t':
			if inTok {
				toks = append(toks, cur.String())
				cur.Reset()
				inTok = false
			}
		default:
			cur.WriteRune(r)
			inTok = true
		}
	}
	if quote != 0 {
		return nil, false
	}
	if inTok {
		toks = append(toks, cur.String())
	}
	return toks, true
}

// programName returns the lowercase basename of tok without ".exe".
func programName(tok string) (string, bool) {
	i := strings.LastIndexAny(tok, `/\`)
	if i >= 0 {
		abs := (strings.HasPrefix(tok, "/") && !strings.HasPrefix(tok, "//")) ||
			(strings.HasPrefix(tok, `\`) && !strings.HasPrefix(tok, `\\`)) ||
			driveAbs.MatchString(tok)
		if !abs {
			return "", false
		}
	}
	name := strings.ToLower(tok[i+1:])
	name = strings.TrimSuffix(name, ".exe")
	return name, name != ""
}

// FirstTokenBase is the program name of a command line for run updates: the
// basename of the first token only (never the directory, never the arguments).
func FirstTokenBase(cmd string) string {
	toks, ok := tokenize(cmd)
	if !ok || len(toks) == 0 {
		fields := strings.Fields(cmd)
		if len(fields) == 0 {
			return ""
		}
		toks = fields[:1]
	}
	t := toks[0]
	t = t[strings.LastIndexAny(t, `/\`)+1:]
	if strings.HasSuffix(strings.ToLower(t), ".exe") {
		t = t[:len(t)-4]
	}
	return t
}
