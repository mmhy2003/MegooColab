package services

import (
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
)

// docker runs docker with args in dir (so no stray compose.yaml in the
// caller's folder is picked up), with env added to the runner's environment.
// docker is looked up on PATH at each call.
func docker(ctx context.Context, dir string, env []string, stdout, stderr io.Writer, args ...string) error {
	path, err := exec.LookPath("docker")
	if err != nil {
		return errors.New("docker not found on PATH")
	}
	cmd := exec.CommandContext(ctx, path, args...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), env...)
	cmd.Stdout = stdout
	cmd.Stderr = stderr
	return cmd.Run()
}

// Check tells whether docker, Docker Compose and the Docker daemon can be used.
func Check(ctx context.Context) error {
	if _, err := exec.LookPath("docker"); err != nil {
		return errors.New("Docker is not installed (docker not found on PATH)")
	}
	if err := docker(ctx, "", nil, nil, nil, "compose", "version"); err != nil {
		return errors.New("Docker Compose is not available")
	}
	if err := docker(ctx, "", nil, nil, nil, "info", "--format", "{{.ServerVersion}}"); err != nil {
		return errors.New("Docker is not running")
	}
	return nil
}
