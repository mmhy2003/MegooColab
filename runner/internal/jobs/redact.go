package jobs

import (
	"io"
	"strings"
	"sync"
)

const redacted = "[redacted]"

// redactor is the run log's writer: it replaces the run's MCP token with
// [redacted], even when the adapter's output splits the token across writes.
// It holds back only a trailing piece that could still turn into the token;
// Close writes that out.
type redactor struct {
	mu      sync.Mutex
	w       io.Writer
	secret  string
	pending string
}

func newRedactor(w io.Writer, secret string) *redactor { return &redactor{w: w, secret: secret} }

func (r *redactor) Write(p []byte) (int, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	s := strings.ReplaceAll(r.pending+string(p), r.secret, redacted)
	keep := heldBack(s, r.secret)
	r.pending = s[len(s)-keep:]
	if _, err := io.WriteString(r.w, s[:len(s)-keep]); err != nil {
		return 0, err
	}
	return len(p), nil
}

// Close writes out whatever was held back.
func (r *redactor) Close() error {
	r.mu.Lock()
	defer r.mu.Unlock()
	rest := r.pending
	r.pending = ""
	_, err := io.WriteString(r.w, rest)
	return err
}

// heldBack is the length of the longest suffix of s that is a proper prefix of secret.
func heldBack(s, secret string) int {
	for n := min(len(s), len(secret)-1); n > 0; n-- {
		if strings.HasSuffix(s, secret[:n]) {
			return n
		}
	}
	return 0
}

// redactMap returns a copy of data with the secret replaced in every string,
// however deep (plan entries are lists of maps).
func redactMap(data map[string]any, secret string) map[string]any {
	out := make(map[string]any, len(data))
	for k, v := range data {
		out[k] = redactValue(v, secret)
	}
	return out
}

func redactValue(v any, secret string) any {
	switch x := v.(type) {
	case string:
		return strings.ReplaceAll(x, secret, redacted)
	case map[string]any:
		return redactMap(x, secret)
	case []map[string]any:
		out := make([]map[string]any, len(x))
		for i, m := range x {
			out[i] = redactMap(m, secret)
		}
		return out
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = redactValue(e, secret)
		}
		return out
	case []string:
		out := make([]string, len(x))
		for i, e := range x {
			out[i] = strings.ReplaceAll(e, secret, redacted)
		}
		return out
	}
	return v
}
