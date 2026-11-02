package jobs

import (
	"context"
	"encoding/base64"
	"fmt"
	"net/http"
	"os"
	"time"

	"github.com/coder/acp-go-sdk"

	"github.com/mmhy2003/megoocolab/runner/internal/images"
	"github.com/mmhy2003/megoocolab/runner/internal/policy"
	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// imageTimeout bounds one image download.
const imageTimeout = 60 * time.Second

// runImages is how a run shows people's images to its agent: as image blocks when the program takes them in a
// prompt, else as files in a folder of the run's own that the policy lets it read (removed when the run ends).
type runImages struct {
	blocks bool          // the agent takes image blocks (promptCapabilities.image)
	pol    policy.Policy // where the folder is allowed for reading
	dir    string        // created on first use
	n      int           // files written so far: the next is numbered n+1
}

// fetchImages downloads the images a run start or steer lists, in order.
func (m *Manager) fetchImages(ctx context.Context, imgs []protocol.RunImage) ([][]byte, error) {
	client := m.HTTPClient
	if client == nil {
		client = &http.Client{Timeout: imageTimeout}
	}
	out := make([][]byte, 0, len(imgs))
	for _, img := range imgs {
		data, err := images.Fetch(ctx, client, m.ServerURL, m.Token, img)
		if err != nil {
			return nil, fmt.Errorf("could not download image %s: %w", img.Filename, err)
		}
		out = append(out, data)
	}
	return out, nil
}

// content is the prompt (or steer) for the agent: the text, then the images as blocks, or the text with where
// their files are.
func (r *run) content(text string, imgs []protocol.RunImage, data [][]byte) ([]acp.ContentBlock, error) {
	if len(imgs) == 0 {
		return []acp.ContentBlock{acp.TextBlock(text)}, nil
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	ri := &r.images
	if ri.blocks {
		blocks := []acp.ContentBlock{acp.TextBlock(text)}
		for i, img := range imgs {
			blocks = append(blocks, acp.ImageBlock(base64.StdEncoding.EncodeToString(data[i]), img.ContentType))
		}
		return blocks, nil
	}
	if ri.dir == "" {
		dir, err := os.MkdirTemp("", "megoo-images-")
		if err != nil {
			return nil, err
		}
		ri.dir = dir
		ri.pol.AllowRead(dir)
	}
	paths, err := images.WriteFiles(ri.dir, ri.n+1, imgs, data)
	if err != nil {
		return nil, err
	}
	ri.n += len(paths)
	return []acp.ContentBlock{acp.TextBlock(text + images.FilesText(paths))}, nil
}

// removeImages deletes the run's image folder, if it made one.
func (r *run) removeImages() {
	r.mu.Lock()
	dir := r.images.dir
	r.images.dir = ""
	r.mu.Unlock()
	if dir != "" {
		_ = os.RemoveAll(dir)
	}
}
