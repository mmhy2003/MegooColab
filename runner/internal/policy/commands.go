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
	if !plainCommand(cmd) || strings.ContainsAny(cmd, shellMeta) {
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

const (
	sq = rune(39) // single quote
	bs = rune(92) // backslash
)

// literalStart: a glob in a word starting with one of these only matches names
// starting with the same character, never an option.
const literalStart = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./"

// plainCommand accepts only text that bash, PowerShell and cmd all split into
// the same words and leave unexpanded (no globs, braces, ~, variables, escapes):
//   - unquoted text uses only [A-Za-z0-9._/:,+=-], and the space character is the only
//     separator (no tabs or newlines);
//   - "@" is refused everywhere: PowerShell splats "@name" and MSYS programs
//     read options from an "@file" response file (even when quoted);
//   - "," may not start a word or a quoted segment: PowerShell's unary ","
//     turns ",--output=x" into an option. Interior commas ("1,5") are kept;
//   - PowerShell drops the quotes of a single-quoted word, and MSYS programs
//     (git's find, grep, ls ...) then brace-, tilde- and glob-expand it, so a
//     quoted segment holds no "{", "}" or "~", and holds a glob character
//     ("*", "?", "[", "]") only when every match is sure not to be an option:
//     the word starts with a literal [A-Za-z0-9_./] ("'x*.go'", "'.*'"), or the
//     quote follows "=" in a word starting with "--" ("--glob='*.go'"). A word
//     starting with "-" (or with a glob) could match a worktree file named
//     "-a" or "-delete", even in a value position ("find . -name '-*'");
//   - a single-quoted segment starts a word (or follows "=") and ends it, is not
//     empty, and holds no whitespace, quote or backslash, so cmd (which keeps the
//     quotes literally) still sees one word.
//
// Anything else, including double quotes and non-ASCII, is refused.
func plainCommand(cmd string) bool {
	if strings.ContainsRune(cmd, '@') {
		return false
	}
	atWordStart := true
	prev := ' '
	in := false
	wordQuote := false // the current quoted segment starts its word (not after "=")
	n := 0             // length of the current quoted content
	var first rune     // first character of the current word (quotes excluded)
	longFlag := false  // the current word starts with "--"
	wlen := 0          // characters of the current word so far (quotes excluded)
	for _, r := range cmd {
		if r != sq && r != ' ' {
			switch wlen {
			case 0:
				first = r
			case 1:
				longFlag = first == '-' && r == '-'
			}
			wlen++
		}
		if in {
			switch {
			case r == sq:
				if n == 0 {
					return false
				}
				in = false
			case r <= ' ' || r == 0x7f || r == '"' || r == bs || r > 0x7e, strings.ContainsRune("{}~", r):
				return false
			case n == 0 && r == ',':
				return false
			case strings.ContainsRune("*?[]", r) && !strings.ContainsRune(literalStart, first) && (wordQuote || !longFlag):
				return false
			default:
				n++
			}
			prev = r
			continue
		}
		switch {
		case r == ' ':
			atWordStart, wlen, first, longFlag = true, 0, 0, false
		case r == sq:
			if !atWordStart && prev != '=' {
				return false
			}
			in, n, wordQuote, atWordStart = true, 0, atWordStart, false
		case prev == sq && !atWordStart: // text glued to a closing quote
			return false
		case r == ',' && atWordStart:
			return false
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9', strings.ContainsRune("._/:,+=-", r):
			atWordStart = false
		default:
			return false
		}
		prev = r
	}
	return !in
}

// tokenize splits on spaces and tabs, honouring single and double quotes and a
// backslash before a space or quote (other backslashes stay literal, so Windows
// paths keep them). An unterminated quote fails.
func tokenize(s string) ([]string, bool) {
	var toks []string
	var cur strings.Builder
	inTok := false
	var quote rune
	runes := []rune(s)
	for i := 0; i < len(runes); i++ {
		r := runes[i]
		switch {
		case quote == 0 && r == '\\' && i+1 < len(runes) && strings.ContainsRune(" \t\"'", runes[i+1]):
			// an escaped space or quote is part of the token; other backslashes stay literal (Windows paths)
			i++
			cur.WriteRune(runes[i])
			inTok = true
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
		return "" // cannot be split cleanly: report nothing rather than a fragment
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
