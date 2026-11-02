// Package images fetches the images a run or a steer carries (capability images/1) and, for an agent program
// that can't take them in its prompt, writes them where it may read them.
package images

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// MaxBytes is the server's limit on one image.
const MaxBytes = 5 << 20

// Fetch downloads one image from the server with the runner's token. Its body must be exactly the announced size.
func Fetch(ctx context.Context, client *http.Client, base, token string, img protocol.RunImage) ([]byte, error) {
	if img.Size < 0 || img.Size > MaxBytes {
		return nil, fmt.Errorf("%d bytes is over the %d byte limit", img.Size, MaxBytes)
	}
	url := strings.TrimRight(base, "/") + "/api/runner/images/" + img.ID
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("the server answered %d", resp.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, img.Size+1))
	if err != nil {
		return nil, err
	}
	if int64(len(data)) != img.Size {
		return nil, errors.New("the download is not the size the server announced")
	}
	return data, nil
}

var unsafeName = regexp.MustCompile(`[^A-Za-z0-9._-]+`)

// WriteFiles writes the images into dir as "<n>-<name>", numbered from first, and returns their paths.
func WriteFiles(dir string, first int, imgs []protocol.RunImage, data [][]byte) ([]string, error) {
	paths := make([]string, 0, len(imgs))
	for i, img := range imgs {
		name := strings.Trim(unsafeName.ReplaceAllString(filepath.Base(filepath.ToSlash(img.Filename)), "_"), "._")
		if name == "" {
			name = "image"
		}
		path := filepath.Join(dir, fmt.Sprintf("%d-%s", first+i, name))
		if err := os.WriteFile(path, data[i], 0o600); err != nil {
			return nil, err
		}
		paths = append(paths, path)
	}
	return paths, nil
}

// FilesText tells the agent where its images are, for a prompt or a steer.
func FilesText(paths []string) string {
	var b strings.Builder
	b.WriteString("\n\n## Image files\nOpen these with your file reader:")
	for i, p := range paths {
		fmt.Fprintf(&b, "\n%d. %s", i+1, p)
	}
	return b.String()
}
