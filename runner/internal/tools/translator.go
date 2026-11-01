package tools

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// Translator writes the hub's tools in one agent program's own user-level format. Adding an agent program
// means adding a Translator; nothing else changes.
type Translator interface {
	Program() string
	InstallMCP(home string, t Tool) (fingerprint string, err error)
	RemoveMCP(home, name string) error
	// MCPFingerprint is the fingerprint of the entry with that name as it is now, and whether there is one.
	MCPFingerprint(home, name string) (fp string, exists bool, err error)
	InstallSkill(home, name string, files []File) (fingerprint string, err error)
	RemoveSkill(home, name string) error
	SkillFingerprint(home, name string) (fp string, exists bool, err error)
	ScanMCP(home string) ([]protocol.FoundTool, error)
	ScanSkills(home string) ([]protocol.FoundTool, error)
}

var translators = map[string]Translator{}

func register(t Translator) { translators[t.Program()] = t }

// For is the translator for an agent program ("claude_code", "codex").
func For(program string) (Translator, bool) {
	t, ok := translators[program]
	return t, ok
}

// Programs lists the programs with a translator, sorted.
func Programs() []string {
	out := make([]string, 0, len(translators))
	for p := range translators {
		out = append(out, p)
	}
	sort.Strings(out)
	return out
}

// npxLike are launchers that are .cmd scripts on Windows: a program cannot start them directly.
var npxLike = map[string]bool{"npx": true, "npm": true, "pnpm": true, "pnpx": true, "yarn": true, "bunx": true}

// WindowsCommand runs a .cmd launcher through cmd /c on Windows, where it cannot be started directly.
func WindowsCommand(goos, command string, args []string) (string, []string) {
	if goos != "windows" || !npxLike[strings.TrimSuffix(strings.ToLower(command), ".cmd")] {
		return command, args
	}
	return "cmd", append([]string{"/c", command}, args...)
}

// unwrapWindowsCommand is WindowsCommand's reverse, for what a scan finds.
func unwrapWindowsCommand(command string, args []string) (string, []string) {
	if strings.EqualFold(command, "cmd") && len(args) >= 2 && strings.EqualFold(args[0], "/c") {
		return args[1], args[2:]
	}
	return command, args
}

// fingerprintJSON is the sha256 of v as canonical JSON (keys sorted at every level).
func fingerprintJSON(v any) string {
	data, _ := json.Marshal(v)
	var generic any
	if json.Unmarshal(data, &generic) == nil {
		data, _ = json.Marshal(generic)
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

// fingerprintFiles is the sha256 over the files, sorted by path.
func fingerprintFiles(files []File) string {
	sorted := append([]File(nil), files...)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].Path < sorted[j].Path })
	h := sha256.New()
	for _, f := range sorted {
		h.Write([]byte(f.Path))
		h.Write([]byte{0})
		h.Write(f.Content)
		h.Write([]byte{0})
	}
	return hex.EncodeToString(h.Sum(nil))
}

// maxSkillBytes is the most a skill may hold, the hub's own limit.
const maxSkillBytes = 2 << 20

// readSkill reads a skill folder's files (paths with "/"); errTooLarge past maxSkillBytes.
func readSkill(dir string) ([]File, error) {
	var files []File
	total := 0
	err := filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		if !d.Type().IsRegular() {
			return nil // links and devices are not part of a skill
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		if total += len(data); total > maxSkillBytes {
			return errTooLarge
		}
		rel, _ := filepath.Rel(dir, path)
		files = append(files, File{Path: filepath.ToSlash(rel), Content: data})
		return nil
	})
	return files, err
}

var errTooLarge = fmt.Errorf("too large")

// installSkillDir writes files into <root>/<name> as a whole: into a fresh folder next to it, then swapped in,
// so a half-written skill is never what the program reads.
func installSkillDir(root, name string, files []File) (string, error) {
	if !filepath.IsLocal(name) || strings.ContainsAny(name, `/\`) {
		return "", fmt.Errorf("skill name %q not allowed", name)
	}
	if err := os.MkdirAll(root, 0o755); err != nil {
		return "", err
	}
	tmp, err := os.MkdirTemp(root, "."+name+".new-*")
	if err != nil {
		return "", err
	}
	defer os.RemoveAll(tmp) // gone after the swap
	for _, f := range files {
		if !filepath.IsLocal(filepath.FromSlash(f.Path)) {
			return "", fmt.Errorf("skill file path %q not allowed", f.Path)
		}
		path := filepath.Join(tmp, filepath.FromSlash(f.Path))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			return "", err
		}
		if err := os.WriteFile(path, f.Content, 0o644); err != nil {
			return "", err
		}
	}
	target := filepath.Join(root, name)
	old := ""
	if _, err := os.Stat(target); err == nil {
		old = filepath.Join(root, "."+name+".old-"+filepath.Base(tmp))
		if err := os.Rename(target, old); err != nil {
			return "", err
		}
	}
	if err := os.Rename(tmp, target); err != nil {
		if old != "" {
			_ = os.Rename(old, target)
		}
		return "", err
	}
	if old != "" {
		_ = os.RemoveAll(old)
	}
	return fingerprintFiles(files), nil
}

// removeSkillDir removes <root>/<name>; a missing one is already gone.
func removeSkillDir(root, name string) error {
	if !filepath.IsLocal(name) || strings.ContainsAny(name, `/\`) {
		return fmt.Errorf("skill name %q not allowed", name)
	}
	return os.RemoveAll(filepath.Join(root, name))
}

func skillFingerprint(dir string) (string, bool, error) {
	if _, err := os.Stat(dir); os.IsNotExist(err) {
		return "", false, nil
	}
	files, err := readSkill(dir)
	if err == errTooLarge {
		return "too-large", true, nil
	}
	if err != nil {
		return "", false, err
	}
	return fingerprintFiles(files), true, nil
}

// scanSkills lists the skills (folders with a SKILL.md) under each root.
func scanSkills(program string, roots ...string) []protocol.FoundTool {
	var out []protocol.FoundTool
	seen := map[string]bool{}
	for _, root := range roots {
		entries, err := os.ReadDir(root)
		if err != nil {
			continue
		}
		for _, e := range entries {
			name := e.Name()
			if !e.IsDir() || strings.HasPrefix(name, ".") || seen[name] {
				continue
			}
			dir := filepath.Join(root, name)
			if _, err := os.Stat(filepath.Join(dir, "SKILL.md")); err != nil {
				continue
			}
			seen[name] = true
			found := protocol.FoundTool{Program: program, Kind: "skill", Name: name}
			files, err := readSkill(dir)
			switch {
			case err == errTooLarge:
				found.Problem = "too large"
			case err != nil:
				found.Problem = "unreadable"
			default:
				found.Files = EncodeFiles(files)
			}
			out = append(out, found)
		}
	}
	return out
}
