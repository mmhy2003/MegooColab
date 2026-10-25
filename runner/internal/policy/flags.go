package policy

import "strings"

// flagSpec is the allowlist of options for one read-only program (or git
// subcommand). Every option not named here is refused: that covers unknown
// flags, abbreviated long options, and bundled short flags containing a letter
// that is not allowed. Positional arguments (anything not starting with "-")
// are accepted.
//
// Two rules remove whole classes of bypass: a "--" token is refused (no
// end-of-options handling), and a flag's value is only ever accepted attached
// to the flag ("--format=x", "-n5"). The token after a flag is never treated as
// that flag's value, so it is always judged as an argument of its own. (find is
// the exception: its operators really do take the next token, which then may
// start with "-" only as a signed count such as "-5" or "-10k".)
type flagSpec struct {
	short    string   // bundleable boolean short flags, e.g. "inv" for -i -n -v and -inv
	shortVal string   // short flags with an attached free-form value ("-efoo"): the rest of the cluster is that value
	shortNum string   // short flags with an attached numeric value ("-n5", "-L1,5"); anything else denies
	long     []string // boolean long flags, exact match, no "=value"
	longVal  []string // long flags with an attached value: "--name=value" only
	words    []string // find: single-dash operators without an argument
	wordsVal []string // find: single-dash operators whose argument is the next token
	digits   bool     // "-5" style count
}

func (f flagSpec) accepts(args []string) bool {
	find := len(f.words)+len(f.wordsVal) > 0
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "--":
			return false
		case a == "-" || !strings.HasPrefix(a, "-"):
			continue
		case strings.HasPrefix(a, "--"):
			name, _, hasEq := strings.Cut(a, "=")
			switch {
			case !hasEq && has(f.long, name):
			case hasEq && has(f.longVal, name):
			default:
				return false
			}
		case has(f.words, a):
		case has(f.wordsVal, a):
			i++ // find's real syntax: the operator's argument is the next token
			if i >= len(args) || strings.HasPrefix(args[i], "-") && !signedCount(args[i]) {
				return false // a skipped value never looks like an option ("-mtime -5" and "-size -10k" do not)
			}
		case find:
			return false // find: single-dash operators from the lists only
		case f.digits && allDigits(a[1:]):
		default:
			for _, r := range a[1:] {
				if strings.ContainsRune(f.shortVal, r) {
					break // the rest of the cluster is this flag's attached value
				}
				if strings.ContainsRune(f.shortNum, r) {
					if !numericValue(a[1:], r) {
						return false
					}
					break
				}
				if !strings.ContainsRune(f.short, r) {
					return false
				}
			}
		}
	}
	return true
}

func has(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// numericValue checks the text after the first occurrence of flag in cluster.
func numericValue(cluster string, flag rune) bool {
	_, rest, _ := strings.Cut(cluster, string(flag))
	for _, r := range rest {
		if !(r >= '0' && r <= '9') && r != ',' && r != '+' && r != '-' {
			return false
		}
	}
	return true
}

// signedCount matches find's "-5" / "-10k" numeric arguments: "-", digits, at most one letter.
func signedCount(s string) bool {
	s = strings.TrimPrefix(s, "-")
	if n := len(s); n > 1 && (s[n-1] >= 'a' && s[n-1] <= 'z' || s[n-1] >= 'A' && s[n-1] <= 'Z') {
		s = s[:n-1]
	}
	return allDigits(s)
}

func allDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

// Options shared by the git history commands (log, show, diff).
var gitHistory = flagSpec{
	short: "pswu",
	long: []string{"--oneline", "--stat", "--shortstat", "--numstat", "--summary", "--name-only", "--name-status", "--patch", "--no-patch",
		"--graph", "--decorate", "--no-decorate", "--all", "--merges", "--no-merges", "--follow", "--reverse", "--abbrev-commit",
		"--cached", "--staged", "--check", "--no-color", "--ignore-all-space", "--no-ext-diff", "--pretty"},
	shortVal: "SG",
	shortNum: "nU",
	longVal:  []string{"--max-count", "--since", "--until", "--author", "--committer", "--grep", "--format", "--pretty", "--unified", "--diff-filter"},
	digits:   true,
}

// specs maps a program (or "git <subcommand>") to its allowed options.
var specs = map[string]flagSpec{
	"git status":   {short: "sbv", long: []string{"--short", "--branch", "--porcelain", "--long", "--ignored"}, longVal: []string{"--porcelain"}},
	"git log":      gitHistory,
	"git show":     gitHistory,
	"git diff":     gitHistory,
	"git blame":    {short: "wesl", shortNum: "L", long: []string{"--porcelain", "--line-porcelain"}},
	"git ls-files": {short: "comdsz", long: []string{"--cached", "--others", "--modified", "--deleted", "--stage", "--exclude-standard", "--full-name"}},
	"git grep": {
		short:    "invwlLchHIaEFPq",
		shortVal: "e",
		shortNum: "ABC",
		long: []string{"--ignore-case", "--line-number", "--invert-match", "--word-regexp", "--files-with-matches", "--files-without-match", "--count",
			"--fixed-strings", "--extended-regexp", "--perl-regexp", "--cached", "--untracked", "--quiet"},
		longVal: []string{"--max-depth"},
	},
	"ls":   {short: "alhRtrSdFAi1", long: []string{"--all", "--almost-all", "--human-readable", "--recursive", "--classify"}},
	"dir":  {},
	"cat":  {short: "nbsAETv"},
	"type": {},
	"head": {short: "qv", shortNum: "nc", longVal: []string{"--lines", "--bytes"}, digits: true},
	"tail": {short: "qv", shortNum: "nc", longVal: []string{"--lines", "--bytes"}, digits: true},
	"wc":   {short: "lwcmL"},
	"pwd":  {short: "LP"},
	"grep": {
		short:    "invwlLchHrREFPsqoaI",
		shortVal: "e",
		shortNum: "ABCm",
		long: []string{"--ignore-case", "--line-number", "--invert-match", "--word-regexp", "--files-with-matches", "--files-without-match", "--count",
			"--fixed-strings", "--extended-regexp", "--perl-regexp", "--recursive", "--quiet", "--only-matching"},
		longVal: []string{"--include", "--exclude", "--exclude-dir", "--max-count"},
	},
	"rg": {
		short:    "inNvwlcsSFHIu",
		shortVal: "egt",
		shortNum: "ABCm",
		long: []string{"--ignore-case", "--smart-case", "--line-number", "--no-line-number", "--invert-match", "--word-regexp", "--files-with-matches",
			"--files-without-match", "--count", "--fixed-strings", "--hidden", "--heading", "--no-heading", "--files", "--no-ignore", "--follow"},
		longVal: []string{"--glob", "--type", "--max-count", "--max-depth"},
	},
	"find": {
		words: []string{"-empty", "-print", "-print0", "-L", "-H", "-P", "-not", "-a", "-o", "-depth"},
		wordsVal: []string{"-name", "-iname", "-path", "-ipath", "-type", "-maxdepth", "-mindepth", "-size", "-mtime", "-mmin", "-newer",
			"-regex", "-perm", "-user"},
	},
}
