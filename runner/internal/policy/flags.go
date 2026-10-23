package policy

import "strings"

// flagSpec is the allowlist of options for one read-only program (or git
// subcommand). Every option not named here is refused: that covers unknown
// flags, abbreviated long options, and bundled short flags containing a letter
// that is not allowed. Positional arguments (anything not starting with "-")
// are accepted.
type flagSpec struct {
	short    string   // bundleable boolean short flags, e.g. "inv" for -i -n -v and -inv
	shortVal string   // short flags whose value is the next token (never attached, never bundled mid-cluster)
	long     []string // boolean long flags, exact match, no "=value"
	longVal  []string // long flags with a value: "--name=value" or "--name value", exact name
	words    []string // single-dash words (find's -name, -type), boolean
	wordsVal []string // single-dash words that take the next token as value
	digits   bool     // "-5" style count
}

func (f flagSpec) accepts(args []string) bool {
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "--":
			return true // the rest are operands
		case a == "-" || !strings.HasPrefix(a, "-"):
			continue
		case strings.HasPrefix(a, "--"):
			name, _, hasEq := strings.Cut(a, "=")
			switch {
			case !hasEq && has(f.long, name):
			case has(f.longVal, name):
				if !hasEq {
					i++
					if i >= len(args) {
						return false
					}
				}
			default:
				return false
			}
		case has(f.words, a):
		case has(f.wordsVal, a):
			i++
			if i >= len(args) {
				return false
			}
		case len(f.words)+len(f.wordsVal) > 0:
			return false // find: single-dash words only
		case f.digits && allDigits(a[1:]):
		default:
			cluster := a[1:]
			for j, r := range cluster {
				switch {
				case strings.ContainsRune(f.short, r):
				case strings.ContainsRune(f.shortVal, r) && j == len(cluster)-1:
					i++
					if i >= len(args) {
						return false
					}
				default:
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
		"--cached", "--staged", "--check", "--no-color", "--ignore-all-space", "--no-ext-diff"},
	shortVal: "nSGU",
	longVal:  []string{"--max-count", "--since", "--until", "--author", "--committer", "--grep", "--format", "--pretty", "--unified", "--diff-filter"},
	digits:   true,
}

// specs maps a program (or "git <subcommand>") to its allowed options.
var specs = map[string]flagSpec{
	"git status":   {short: "sbv", long: []string{"--short", "--branch", "--porcelain", "--long", "--ignored"}, longVal: []string{"--porcelain"}},
	"git log":      gitHistory,
	"git show":     gitHistory,
	"git diff":     gitHistory,
	"git blame":    {short: "wesl", shortVal: "L", long: []string{"--porcelain", "--line-porcelain"}},
	"git ls-files": {short: "comdsz", long: []string{"--cached", "--others", "--modified", "--deleted", "--stage", "--exclude-standard", "--full-name"}},
	"git grep": {
		short:    "invwlLchHIaEFPq",
		shortVal: "eABC",
		long: []string{"--ignore-case", "--line-number", "--invert-match", "--word-regexp", "--files-with-matches", "--files-without-match", "--count",
			"--fixed-strings", "--extended-regexp", "--perl-regexp", "--cached", "--untracked", "--quiet"},
		longVal: []string{"--max-depth"},
	},
	"ls":   {short: "alhRtrSdFAi1", long: []string{"--all", "--almost-all", "--human-readable", "--recursive", "--classify"}},
	"dir":  {},
	"cat":  {short: "nbsAETv"},
	"type": {},
	"head": {short: "qv", shortVal: "nc", longVal: []string{"--lines", "--bytes"}, digits: true},
	"tail": {short: "qv", shortVal: "nc", longVal: []string{"--lines", "--bytes"}, digits: true},
	"wc":   {short: "lwcmL"},
	"pwd":  {short: "LP"},
	"grep": {
		short:    "invwlLchHrREFPsqoaI",
		shortVal: "eABCm",
		long: []string{"--ignore-case", "--line-number", "--invert-match", "--word-regexp", "--files-with-matches", "--files-without-match", "--count",
			"--fixed-strings", "--extended-regexp", "--perl-regexp", "--recursive", "--quiet", "--only-matching"},
		longVal: []string{"--include", "--exclude", "--exclude-dir", "--max-count"},
	},
	"rg": {
		short:    "inNvwlcsSFHIu",
		shortVal: "eABCmgt",
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
