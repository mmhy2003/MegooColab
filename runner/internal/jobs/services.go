package jobs

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/policy"
	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
	"github.com/mmhy2003/megoocolab/runner/internal/services"
)

const (
	// servicesWait is how long removing a worktree's services may take when its run ends.
	servicesWait = 2 * time.Minute
	// servicesSweepEvery is how often the runner removes services whose check is no longer running.
	servicesSweepEvery = time.Hour
)

// rolePlan is the workflow role of a planning run (RunStart.Role).
const rolePlan = "plan"

// servicesPrompt is what a run's prompt gets about megoocolab.toml: a writable
// run the "Test services" section, the first run of a planning session the
// planning one, other runs (drafts, the other read-only roles, a continued
// planning session) nothing. An invalid file goes to the run's log and the
// run gets nothing.
func servicesPrompt(rs protocol.RunStart, kind policy.Kind, wt string, logf io.Writer) string {
	var section func(string) (string, error)
	switch {
	case rs.Draft != nil:
		return ""
	case kind == policy.Workspace:
		section = services.PromptSection
	case kind == policy.ReadOnly && rs.Role == rolePlan && rs.ResumeSessionID == "":
		section = services.PlanSection
	default:
		return ""
	}
	text, err := section(wt)
	if err != nil {
		fmt.Fprintf(logf, "runner: services: %v\n", err)
	}
	return text
}

// servicesDir is where this runner keeps the records of the service sets its
// runs start.
func (m *Manager) servicesDir() string { return filepath.Join(m.cacheRoot, "services") }

// servicesEnv is what an agent needs to call `megoocolab-runner services run`:
// this runner's folder first on PATH and the records folder. Without the
// executable's path, PATH is left alone and the run log says why.
func (m *Manager) servicesEnv(logf io.Writer) []string {
	var env []string
	if exe, err := m.Executable(); err != nil {
		fmt.Fprintf(logf, "runner: services: cannot find the runner executable: %v\n", err)
	} else {
		env = append(env, "PATH="+filepath.Dir(exe)+string(os.PathListSeparator)+os.Getenv("PATH"))
	}
	return append(env, "MEGOO_SERVICES_DIR="+m.servicesDir())
}

// removeServices removes whatever service sets worktree wt still has, once its
// run is over. A failure goes to the run's log and the runner's; the records
// stay, so the sweep tries again.
func (m *Manager) removeServices(wt string, logf io.Writer) {
	ctx, cancel := context.WithTimeout(context.Background(), servicesWait)
	defer cancel()
	if err := services.CleanWorktree(ctx, m.servicesDir(), wt); err != nil {
		fmt.Fprintf(logf, "runner: services: %v\n", err)
		fmt.Fprintf(m.Log, "services: %v\n", err)
	}
}

// sweepServices removes the service sets whose check is no longer running, now
// and then every servicesSweepEvery until ctx ends.
func (m *Manager) sweepServices(ctx context.Context) {
	ticker := time.NewTicker(servicesSweepEvery)
	defer ticker.Stop()
	for {
		if err := services.Sweep(ctx, m.servicesDir(), time.Now()); err != nil {
			fmt.Fprintf(m.Log, "services: %v\n", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
