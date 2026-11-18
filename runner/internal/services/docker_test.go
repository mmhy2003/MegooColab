package services

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// TestRealDocker starts testdata/real with the real docker, checks the
// command reaches the service on its port, and that nothing of the project is
// left afterwards. It runs only with MEGOO_DOCKER_TESTS=1 (CI on Linux).
func TestRealDocker(t *testing.T) {
	if os.Getenv("MEGOO_DOCKER_TESTS") != "1" {
		t.Skip("set MEGOO_DOCKER_TESTS=1 to run against the real docker")
	}
	worktree := Canonical(t.TempDir())
	if err := os.CopyFS(worktree, os.DirFS(filepath.Join("testdata", "real"))); err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	t.Setenv("MEGOO_SERVICES_DIR", dir)
	t.Setenv("SERVICES_TEST_HELPER", "get:WEB_PORT")

	var out runOutput
	code := Run(context.Background(), Options{
		Dir:     dir,
		Cwd:     worktree,
		Set:     "web",
		Command: []string{os.Args[0]},
		Stdout:  &out.stdout,
		Stderr:  &out.stderr,
	})
	if code != 0 {
		t.Fatalf("exit code %d, want 0\nstdout:\n%s\nstderr:\n%s", code, out.stdout.String(), out.stderr.String())
	}

	project := ProjectName(Canonical(worktree), "web")
	label := "label=com.docker.compose.project=" + project
	for _, list := range [][]string{
		{"ps", "-aq", "--filter", label},
		{"volume", "ls", "-q", "--filter", label},
		{"network", "ls", "-q", "--filter", label},
	} {
		got, err := exec.Command("docker", list...).Output()
		if err != nil {
			t.Fatalf("docker %s: %v", strings.Join(list, " "), err)
		}
		if ids := strings.TrimSpace(string(got)); ids != "" {
			t.Errorf("docker %s: left behind %q", strings.Join(list, " "), ids)
		}
	}
	if err := exec.Command("docker", "image", "inspect", project+"-web").Run(); err == nil {
		t.Errorf("image %s-web was not removed", project)
	}
	left, err := filepath.Glob(filepath.Join(dir, "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	if len(left) > 0 {
		t.Errorf("records left behind: %v", left)
	}
}
