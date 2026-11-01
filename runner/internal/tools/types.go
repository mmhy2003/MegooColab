package tools

import (
	"encoding/base64"
	"fmt"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// Tool is one tool of a push.
type Tool = protocol.ToolPayload

// File is one file of a skill, decoded.
type File struct {
	Path    string
	Content []byte
}

// DecodeFiles decodes a skill's base64 files.
func DecodeFiles(p protocol.ToolPayload) ([]File, error) {
	out := make([]File, 0, len(p.Files))
	for _, f := range p.Files {
		data, err := base64.StdEncoding.DecodeString(f.ContentB64)
		if err != nil {
			return nil, fmt.Errorf("skill file %s: %w", f.Path, err)
		}
		out = append(out, File{Path: f.Path, Content: data})
	}
	return out, nil
}

// EncodeFiles is DecodeFiles' reverse, for a scan's found skills.
func EncodeFiles(files []File) []protocol.SkillFile {
	out := make([]protocol.SkillFile, 0, len(files))
	for _, f := range files {
		out = append(out, protocol.SkillFile{Path: f.Path, ContentB64: base64.StdEncoding.EncodeToString(f.Content)})
	}
	return out
}
