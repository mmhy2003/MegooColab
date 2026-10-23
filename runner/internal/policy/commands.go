package policy

import (
	"regexp"
	"strings"
)

var readOnlyPrograms = map[string]bool{
	"git": true, "ls": true, "dir": true, "cat": true, "type": true, "head": true,
	"tail": true, "rg": true, "grep": true, "find": true, "wc": true, "pwd": true,
}

// Anything that chains, redirects, substitutes or expands is refused outright
// (even inside quotes: refusing is always safe, and the agent can retry plainly).
const shellMeta = ";&|<>`$()%^\n\r\x00"

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
	key := prog
	if prog == "git" {
		if len(args) == 0 {
			return false
		}
		key = "git " + args[0]
		args = args[1:]
	}
	sp, ok := specs[key]
	if !ok {
		return false
	}
	return sp.accepts(args)
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

var envAssignment = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*=`)

// FirstTokenBase is the program name of a command line for run updates: the
// basename of the first token only (never the directory, never the arguments).
// Leading VAR=value assignments are skipped, since their values can be secrets.
// It returns "" when no plain program name remains.
func FirstTokenBase(cmd string) string {
	toks, ok := tokenize(cmd)
	if !ok {
		toks = strings.Fields(cmd)
	}
	for len(toks) > 0 && envAssignment.MatchString(toks[0]) {
		toks = toks[1:]
	}
	if len(toks) == 0 {
		return ""
	}
	t := toks[0]
	t = t[strings.LastIndexAny(t, `/\`)+1:]
	if strings.HasSuffix(strings.ToLower(t), ".exe") {
		t = t[:len(t)-4]
	}
	if strings.Contains(t, "=") {
		return ""
	}
	return t
}
