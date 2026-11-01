package tools

import (
	"bytes"
	"fmt"
	"regexp"
	"sort"
	"strings"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

var bareKey = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

// tomlKey is a key as TOML needs it written: bare when it can be, quoted otherwise.
func tomlKey(k string) string {
	if bareKey.MatchString(k) {
		return k
	}
	return tomlString(k)
}

// tomlString is a TOML basic string.
func tomlString(s string) string {
	var b strings.Builder
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\b':
			b.WriteString(`\b`)
		case '\t':
			b.WriteString(`\t`)
		case '\n':
			b.WriteString(`\n`)
		case '\f':
			b.WriteString(`\f`)
		case '\r':
			b.WriteString(`\r`)
		default:
			if r < 0x20 || r == 0x7f {
				fmt.Fprintf(&b, `\u%04X`, r)
			} else {
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
	return b.String()
}

func writeTable(b *bytes.Buffer, header string, values map[string]string) {
	if len(values) == 0 {
		return
	}
	keys := make([]string, 0, len(values))
	for k := range values {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	fmt.Fprintf(b, "\n[%s]\n", header)
	for _, k := range keys {
		fmt.Fprintf(b, "%s = %s\n", tomlKey(k), tomlString(values[k]))
	}
}

// renderCodexBlock is the [mcp_servers.<name>] table, and its subtable, Codex reads for an MCP server.
func renderCodexBlock(name string, m protocol.McpPayload) []byte {
	var b bytes.Buffer
	table := "mcp_servers." + tomlKey(name)
	fmt.Fprintf(&b, "[%s]\n", table)
	if m.Transport == "http" {
		fmt.Fprintf(&b, "url = %s\n", tomlString(m.URL))
		writeTable(&b, table+".http_headers", m.Headers)
		return b.Bytes()
	}
	args := make([]string, len(m.Args))
	for i, a := range m.Args {
		args[i] = tomlString(a)
	}
	fmt.Fprintf(&b, "command = %s\nargs = [%s]\n", tomlString(m.Command), strings.Join(args, ", "))
	writeTable(&b, table+".env", m.Env)
	return b.Bytes()
}

// headerPath is the dotted key of a table header line ("[a.b]", "[[a]]", `[a."b.c"]`), or nil when the line
// is not a header.
func headerPath(line string) []string {
	s := strings.TrimSpace(line)
	if !strings.HasPrefix(s, "[") {
		return nil
	}
	s = strings.TrimLeft(s, "[")
	var parts []string
	var cur strings.Builder
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case c == '"' || c == '\'':
			j := i + 1
			for j < len(s) && s[j] != c {
				if c == '"' && s[j] == '\\' {
					j++
				}
				j++
			}
			if j >= len(s) {
				return nil
			}
			cur.WriteString(s[i+1 : j]) // escapes inside names are rare; kept as written
			i = j
		case c == '.':
			parts = append(parts, strings.TrimSpace(cur.String()))
			cur.Reset()
		case c == ']':
			return append(parts, strings.TrimSpace(cur.String()))
		case c == ' ' || c == '\t':
		default:
			cur.WriteByte(c)
		}
	}
	return nil
}

// ours says whether a header belongs to [mcp_servers.<name>] or one of its subtables.
func ours(path []string, name string) bool {
	return len(path) >= 2 && path[0] == "mcp_servers" && path[1] == name
}

// replaceTable removes [mcp_servers.<name>] and its subtables from doc and, when block is not nil, appends
// block at the end after one blank line. Every other byte of doc is kept as it was.
func replaceTable(doc []byte, name string, block []byte) []byte {
	lines := strings.SplitAfter(string(doc), "\n")
	var out strings.Builder
	skipping := false
	// comments and blank lines after our table's last value: they belong to whatever follows it
	var held []string
	for _, line := range lines {
		if path := headerPath(line); path != nil {
			if ours(path, name) {
				skipping, held = true, nil
				continue
			}
			if skipping {
				for len(held) > 0 && strings.TrimSpace(held[0]) == "" && strings.HasSuffix(out.String(), "\n\n") {
					held = held[1:]
				}
				for _, h := range held {
					out.WriteString(h)
				}
			}
			skipping, held = false, nil
		}
		if skipping {
			if t := strings.TrimSpace(line); t == "" || strings.HasPrefix(t, "#") {
				held = append(held, line)
			} else {
				held = nil
			}
			continue
		}
		out.WriteString(line)
	}
	text := strings.TrimRight(out.String(), "\n")
	if text != "" {
		text += "\n"
	}
	if block == nil {
		return []byte(text)
	}
	if text != "" {
		text += "\n"
	}
	return []byte(text + string(block))
}
