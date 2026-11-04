// Package mask replaces the values a run must never report — its MCP token and its secrets — with labels: the token
// with [redacted], a secret with [NAME]. Values shorter than MinLength are left alone (blanking them would mangle
// ordinary text).
package mask

import (
	"bytes"
	"encoding/json"
	"net/url"
	"sort"
	"strings"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// Redacted is what the run's MCP token becomes.
const Redacted = "[redacted]"

// MinLength is the shortest secret value that is blanked.
const MinLength = 4

// Pair is one value and what it becomes.
type Pair struct{ Value, Label string }

// Set is a run's values, the longest first so that one containing another is replaced whole.
type Set []Pair

// Token is the set of just the run's MCP token ("" gives an empty set).
func Token(token string) Set { return Build(token, nil) }

// Build is the set for a run: its MCP token and its secrets' values.
func Build(token string, secrets []protocol.RunSecret) Set {
	var s Set
	if token != "" {
		s = append(s, Pair{Value: token, Label: Redacted})
	}
	seen := map[string]bool{}
	for _, sec := range secrets {
		if len(sec.Value) < MinLength {
			continue
		}
		for _, f := range Forms(sec.Value) {
			if !seen[f] {
				seen[f] = true
				s = append(s, Pair{Value: f, Label: "[" + sec.Name + "]"})
			}
		}
	}
	sort.SliceStable(s, func(i, j int) bool { return len(s[i].Value) > len(s[j].Value) })
	return s
}

// Forms are the ways a value commonly appears written into other text, each at least MinLength long: as it is,
// trimmed (a value pasted with a newline), JSON-escaped, and percent-encoded (in a URL path or a query). The server
// blanks the same forms (backend/app/secrets/blanking.py).
func Forms(value string) []string {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(value)
	escaped := strings.TrimSuffix(strings.TrimSpace(buf.String()), `"`)
	escaped = strings.TrimPrefix(escaped, `"`)
	query := url.QueryEscape(value)
	candidates := []string{value, strings.TrimSpace(value), escaped, query, strings.ReplaceAll(query, "+", "%20"),
		url.PathEscape(value)}
	var out []string
	for _, c := range candidates {
		if len(c) >= MinLength {
			out = append(out, c)
		}
	}
	return out
}

// Empty reports that there is nothing to replace.
func (s Set) Empty() bool { return len(s) == 0 }

// Replace replaces every value in text.
func (s Set) Replace(text string) string {
	for _, p := range s {
		text = strings.ReplaceAll(text, p.Value, p.Label)
	}
	return text
}

// HeldBack is the length of the longest end of text that is a proper start of any value: the part a streamed text
// must hold back until more arrives, so a value split across two pieces is still replaced.
func (s Set) HeldBack(text string) int {
	keep := 0
	for _, p := range s {
		for n := min(len(text), len(p.Value)-1); n > keep; n-- {
			if strings.HasSuffix(text, p.Value[:n]) {
				keep = n
				break
			}
		}
	}
	return keep
}
