package images_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/images"
	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

var png = []byte("\x89PNG\r\n\x1a\n0123456789")

func server(t *testing.T, body []byte) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer tok" || r.URL.Path != "/api/runner/images/i1" {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write(body)
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestFetch(t *testing.T) {
	srv := server(t, png)
	img := protocol.RunImage{ID: "i1", Filename: "a.png", ContentType: "image/png", Size: int64(len(png))}
	got, err := images.Fetch(context.Background(), srv.Client(), srv.URL+"/", "tok", img)
	if err != nil || string(got) != string(png) {
		t.Fatalf("Fetch = %q %v", got, err)
	}
	if _, err := images.Fetch(context.Background(), srv.Client(), srv.URL, "wrong", img); err == nil {
		t.Fatal("a refused download is an error")
	}
}

func TestFetchRefusesOversizedBody(t *testing.T) {
	srv := server(t, append(png, 'x'))
	img := protocol.RunImage{ID: "i1", Filename: "a.png", ContentType: "image/png", Size: int64(len(png))}
	if _, err := images.Fetch(context.Background(), srv.Client(), srv.URL, "tok", img); err == nil {
		t.Fatal("a body longer than announced is refused")
	}
	short := protocol.RunImage{ID: "i1", Filename: "a.png", ContentType: "image/png", Size: int64(len(png)) + 5}
	if _, err := images.Fetch(context.Background(), srv.Client(), srv.URL, "tok", short); err == nil {
		t.Fatal("a body shorter than announced is refused")
	}
	huge := protocol.RunImage{ID: "i1", Filename: "a.png", ContentType: "image/png", Size: images.MaxBytes + 1}
	if _, err := images.Fetch(context.Background(), srv.Client(), srv.URL, "tok", huge); err == nil {
		t.Fatal("an image over the limit is refused before downloading")
	}
}

func TestWriteFiles(t *testing.T) {
	dir := t.TempDir()
	imgs := []protocol.RunImage{{Filename: "../../evil.png"}, {Filename: "b.png"}}
	paths, err := images.WriteFiles(dir, 1, imgs, [][]byte{png, png})
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) != 2 || filepath.Dir(paths[0]) != dir || filepath.Base(paths[0]) != "1-evil.png" || filepath.Base(paths[1]) != "2-b.png" {
		t.Fatalf("paths = %v", paths)
	}
	if b, _ := os.ReadFile(paths[1]); string(b) != string(png) {
		t.Fatal("content written")
	}
	text := images.FilesText(paths)
	if !strings.Contains(text, "## Image files") || !strings.Contains(text, "1. "+paths[0]) {
		t.Fatalf("text = %q", text)
	}
}
