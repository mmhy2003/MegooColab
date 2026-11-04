package jobs

import (
	"io"
	"sync"

	"github.com/mmhy2003/megoocolab/runner/internal/mask"
)

const redacted = mask.Redacted

// redactor is the run log's writer: it replaces the run's MCP token with
// [redacted], even when the adapter's output splits the token across writes.
// It holds back only a trailing piece that could still turn into the token;
// Close writes that out.
type redactor struct {
	mu      sync.Mutex
	w       io.Writer
	masks   mask.Set
	pending string
}

func newRedactor(w io.Writer, masks mask.Set) *redactor { return &redactor{w: w, masks: masks} }

func (r *redactor) Write(p []byte) (int, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	s := r.masks.Replace(r.pending + string(p))
	keep := r.masks.HeldBack(s)
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
	rest := releaseTail(r.pending)
	r.pending = ""
	_, err := io.WriteString(r.w, rest)
	return err
}

// redactMap returns a copy of data with the secret replaced in every string,
// however deep (plan entries are lists of maps).
func redactMap(data map[string]any, masks mask.Set) map[string]any {
	out := make(map[string]any, len(data))
	for k, v := range data {
		out[k] = redactValue(v, masks)
	}
	return out
}

func redactValue(v any, masks mask.Set) any {
	switch x := v.(type) {
	case string:
		return masks.Replace(x)
	case map[string]any:
		return redactMap(x, masks)
	case []map[string]any:
		out := make([]map[string]any, len(x))
		for i, m := range x {
			out[i] = redactMap(m, masks)
		}
		return out
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = redactValue(e, masks)
		}
		return out
	case []string:
		out := make([]string, len(x))
		for i, e := range x {
			out[i] = masks.Replace(e)
		}
		return out
	}
	return v
}

// releaseTail is what to write for the held-back end of a stream that is over:
// up to 4 characters pass as they are, a longer start of the token is withheld.
func releaseTail(held string) string {
	if len(held) > 4 {
		return redacted
	}
	return held
}

// logWriters builds the writers of a run's log file. The runner's own lines go
// through the redactor only: they always reach the file. The adapter's stderr
// is redacted first and capped after, so the cap can never cut a token open.
// closeAll releases what the redactors hold; call it before closing the file.
func logWriters(file io.Writer, limit int, masks mask.Set) (runner, stderr io.Writer, closeAll func()) {
	capped := &cappedWriter{w: file, left: limit}
	if masks.Empty() {
		return file, capped, func() {}
	}
	rl, re := newRedactor(file, masks), newRedactor(capped, masks)
	return rl, re, func() { _ = re.Close(); _ = rl.Close() }
}
