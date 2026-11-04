package jobs

import (
	"context"
	"fmt"
	"io"
	"strings"

	"github.com/mmhy2003/megoocolab/runner/internal/gitstate"
	"github.com/mmhy2003/megoocolab/runner/internal/startbranch"
)

// refreshCron brings a cron's worktree to the project's default branch: fetched from origin first, or the last fetched
// copy when origin can't be reached (startbranch.StartPoint). Whatever an earlier run left is thrown away. It returns
// the commit the run works on.
func refreshCron(ctx context.Context, logw io.Writer, repo, wt, branch string) (string, error) {
	origin, err := gitstate.Run(repo, "remote", "get-url", "origin")
	if origin = strings.TrimSpace(origin); err != nil {
		origin = ""
	}
	point, err := startbranch.StartPoint(ctx, logw, repo, origin, branch)
	if err != nil {
		return "", err
	}
	out, err := gitstate.Run(wt, "rev-parse", point+"^{commit}")
	if err != nil {
		return "", fmt.Errorf("reading %s: %w", point, err)
	}
	commit := strings.TrimSpace(out)
	if err := resetTo(wt, commit); err != nil {
		return "", err
	}
	return commit, nil
}

// resetCron throws away what the run changed or committed in the cron's worktree.
func resetCron(logw io.Writer, wt, commit string) {
	if err := resetTo(wt, commit); err != nil {
		fmt.Fprintf(logw, "runner: resetting the cron's worktree: %v\n", err)
	}
}

func resetTo(wt, commit string) error {
	if _, err := gitstate.Run(wt, "checkout", "--detach", "--force", commit); err != nil {
		return err
	}
	_, err := gitstate.Run(wt, "clean", "-fdx")
	return err
}
