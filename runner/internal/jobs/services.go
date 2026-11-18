package jobs

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
)

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
