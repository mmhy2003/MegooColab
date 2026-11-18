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
