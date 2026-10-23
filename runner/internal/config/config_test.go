package config

import (
	"os"
	"runtime"
	"testing"
)

func isolate(t *testing.T) {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("APPDATA", dir)
	t.Setenv("XDG_CONFIG_HOME", dir)
	t.Setenv("HOME", dir)
}

func TestSaveLoadRoundTripAndPermissions(t *testing.T) {
	isolate(t)
	if err := Save(Config{URL: "https://colab.example.com/", Token: "mgc_abc"}); err != nil {
		t.Fatal(err)
	}
	got, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if got.URL != "https://colab.example.com" || got.Token != "mgc_abc" {
		t.Fatalf("unexpected config %+v", got)
	}
	if runtime.GOOS != "windows" {
		p, _ := Path()
		st, err := os.Stat(p)
		if err != nil {
			t.Fatal(err)
		}
		if st.Mode().Perm() != 0o600 {
			t.Fatalf("mode = %v, want 0600", st.Mode().Perm())
		}
	}
}

func TestLoadMissingIsNotExist(t *testing.T) {
	isolate(t)
	if _, err := Load(); !os.IsNotExist(err) {
		t.Fatalf("want not-exist error, got %v", err)
	}
}

func TestURLNormalization(t *testing.T) {
	ok := map[string]string{
		"http://localhost:8000":         "http://localhost:8000",
		"https://x.example.com//":       "https://x.example.com",
		"  https://x.example.com/app/ ": "https://x.example.com/app",
	}
	for in, want := range ok {
		got, err := NormalizeURL(in)
		if err != nil || got != want {
			t.Errorf("NormalizeURL(%q) = %q, %v; want %q", in, got, err, want)
		}
	}
	for _, in := range []string{"", "ftp://x.com", "x.com", "https://", "javascript:alert(1)"} {
		if _, err := NormalizeURL(in); err == nil {
			t.Errorf("NormalizeURL(%q) should fail", in)
		}
	}
	isolate(t)
	if err := Save(Config{URL: "ftp://x", Token: "t"}); err == nil {
		t.Error("Save should reject a non-http URL")
	}
}
