package services

import (
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

const exampleFile = `# megoocolab.toml
[services.test]
description = "PostgreSQL, Meilisearch and Valkey for backend pytest"
compose = ["tools/test-services/docker-compose.yml"]
ports = ["DB_PORT", "MEILI_PORT", "VALKEY_PORT"]

[services.test.env]
TEST_DATABASE_URL = "postgresql+asyncpg://megoo:megoo@localhost:${DB_PORT}/megoo_test"
MEILI_URL = "http://localhost:${MEILI_PORT}"

[services.e2e]
compose = ["compose.yml"]
`

// writeFile writes content to dir/name, creating parent folders.
func writeFile(t *testing.T, dir, name, content string) string {
	t.Helper()
	path := filepath.Join(dir, filepath.FromSlash(name))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestLoadValidFile(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "tools/test-services/docker-compose.yml", "services: {}\n")
	writeFile(t, dir, "compose.yml", "services: {}\n")
	path := writeFile(t, dir, FileName, exampleFile)

	f, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	abs, _ := filepath.Abs(path)
	if f.Path != abs {
		t.Errorf("Path = %q, want %q", f.Path, abs)
	}
	if f.Dir != Canonical(dir) {
		t.Errorf("Dir = %q, want %q", f.Dir, Canonical(dir))
	}
	if got := f.Names(); !reflect.DeepEqual(got, []string{"e2e", "test"}) {
		t.Errorf("Names() = %v", got)
	}
	want := Set{
		Name:        "test",
		Description: "PostgreSQL, Meilisearch and Valkey for backend pytest",
		Compose:     []string{filepath.Join(filepath.Dir(abs), "tools", "test-services", "docker-compose.yml")},
		Ports:       []string{"DB_PORT", "MEILI_PORT", "VALKEY_PORT"},
		Env: map[string]string{
			"TEST_DATABASE_URL": "postgresql+asyncpg://megoo:megoo@localhost:${DB_PORT}/megoo_test",
			"MEILI_URL":         "http://localhost:${MEILI_PORT}",
		},
	}
	if got := f.Sets["test"]; !reflect.DeepEqual(got, want) {
		t.Errorf("Sets[test] =\n%#v\nwant\n%#v", got, want)
	}
	if !filepath.IsAbs(f.Sets["e2e"].Compose[0]) {
		t.Errorf("e2e compose not absolute: %q", f.Sets["e2e"].Compose[0])
	}
}

func TestLoadRejects(t *testing.T) {
	set := func(name, body string) string {
		return "[services." + name + "]\n" + body
	}
	ok := `compose = ["c.yml"]` + "\n"
	cases := []struct {
		name    string
		content string
		key     string // what the error must name
	}{
		{"unknown top-level key", "foo = 1\n" + set("test", ok), "foo"},
		{"unknown key in a set", set("test", ok+"foo = 1\n"), "services.test.foo"},
		{"missing compose", set("test", `ports = ["A"]`+"\n"), "services.test.compose"},
		{"empty compose", set("test", "compose = []\n"), "services.test.compose"},
		{"compose file missing", set("test", `compose = ["nope.yml"]`+"\n"), "services.test.compose"},
		{"compose path absolute", set("test", `compose = ["`+filepath.ToSlash(filepath.Join(os.TempDir(), "c.yml"))+`"]`+"\n"), "services.test.compose"},
		{"compose path leaving the folder", set("test", `compose = ["../x.yml"]`+"\n"), "services.test.compose"},
		{"set name upper case", set("Test", ok), "services.Test"},
		{"set name starts with digit", set("1x", ok), "services.1x"},
		{"set name too long", set(strings.Repeat("a", 21), ok), "services." + strings.Repeat("a", 21)},
		{"set name underscore", set("a_b", ok), "services.a_b"},
		{"port name starts with digit", set("test", ok+`ports = ["1X"]`+"\n"), "services.test.ports"},
		{"port name with hyphen", set("test", ok+`ports = ["A-B"]`+"\n"), "services.test.ports"},
		{"reserved port", set("test", ok+`ports = ["MEGOO_SERVICES_PROJECT"]`+"\n"), "services.test.ports"},
		{"reserved port lower case", set("test", ok+`ports = ["megoo_services_x"]`+"\n"), "services.test.ports"},
		{"env name starts with digit", set("test", ok+"[services.test.env]\n1X = \"v\"\n"), "services.test.env"},
		{"env name with hyphen", set("test", ok+"[services.test.env]\nA-B = \"v\"\n"), "services.test.env"},
		{"reserved env", set("test", ok+"[services.test.env]\nMEGOO_SERVICES_PROJECT = \"v\"\n"), "services.test.env"},
		{"reserved env lower case", set("test", ok+"[services.test.env]\nmegoo_services_x = \"v\"\n"), "services.test.env"},
		{"port repeated", set("test", ok+`ports = ["A", "A"]`+"\n"), "services.test.ports"},
		{"port and env", set("test", ok+`ports = ["A"]`+"\n[services.test.env]\nA = \"v\"\n"), "services.test.env"},
		{"description with newline", set("test", ok+`description = "a\nb"`+"\n"), "services.test.description"},
		{"description too long", set("test", ok+`description = "`+strings.Repeat("é", 201)+`"`+"\n"), "services.test.description"},
		{"env value with newline", set("test", ok+"[services.test.env]\nA = \"a\\nb\"\n"), "services.test.env"},
		{"invalid TOML", "[services.test\n", "line 1"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			dir := t.TempDir()
			writeFile(t, dir, "c.yml", "services: {}\n")
			path := writeFile(t, dir, FileName, c.content)
			f, err := Load(path)
			if err == nil {
				t.Fatalf("Load succeeded: %+v", f)
			}
			msg := err.Error()
			if strings.Contains(msg, "\n") {
				t.Errorf("error has more than one line: %q", msg)
			}
			abs, _ := filepath.Abs(path)
			if !strings.HasPrefix(msg, abs+": ") {
				t.Errorf("error %q does not start with the path %q", msg, abs)
			}
			if !strings.Contains(msg, ": "+c.key) {
				t.Errorf("error %q does not name %q", msg, c.key)
			}
		})
	}
}

func TestMegooVersionIsAllowed(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "c.yml", "services: {}\n")
	path := writeFile(t, dir, FileName, "[services.e2e]\ncompose = [\"c.yml\"]\n[services.e2e.env]\nMEGOO_VERSION = \"${MEGOO_SERVICES_PROJECT}\"\n")
	if _, err := Load(path); err != nil {
		t.Fatalf("Load: %v", err)
	}
}

func TestFindWalksUp(t *testing.T) {
	root := t.TempDir()
	want := writeFile(t, root, FileName, "")
	deep := filepath.Join(root, "a", "b")
	if err := os.MkdirAll(deep, 0o755); err != nil {
		t.Fatal(err)
	}
	got, err := Find(deep)
	if err != nil {
		t.Fatalf("Find: %v", err)
	}
	if Canonical(got) != Canonical(want) {
		t.Errorf("Find = %q, want %q", got, want)
	}

	empty := t.TempDir()
	if _, err := Find(empty); !errors.Is(err, ErrNoFile) {
		t.Errorf("Find(no file) err = %v, want ErrNoFile", err)
	}
}

func TestLoadEmptyServices(t *testing.T) {
	dir := t.TempDir()
	path := writeFile(t, dir, FileName, "# nothing yet\n")
	f, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if len(f.Sets) != 0 || len(f.Names()) != 0 {
		t.Errorf("Sets = %v, want none", f.Sets)
	}
}
