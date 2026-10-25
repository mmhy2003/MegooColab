package jobs

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"time"

	"github.com/coder/acp-go-sdk"

	"github.com/mmhy2003/megoocolab/runner/internal/adapters"
)

// adapterProc is a started adapter process and its ACP pipes.
type adapterProc struct {
	cmd    *exec.Cmd
	stdin  io.WriteCloser
	stdout io.ReadCloser
}

// startAdapter launches the adapter in dir. Runs and `doctor --acp` both use it,
// so a capability check starts the adapter exactly as a run does.
func startAdapter(spec adapters.Spec, dir string, stderr io.Writer) (*adapterProc, error) {
	cmd := exec.Command(spec.Command, spec.Args...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), spec.Env...)
	cmd.Stderr = stderr
	cmd.WaitDelay = 5 * time.Second // a grandchild holding a pipe cannot block Wait forever
	ownProcessGroup(cmd)
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("cannot start the adapter: %w", err)
	}
	return &adapterProc{cmd: cmd, stdin: stdin, stdout: stdout}, nil
}

// initRequest is the ACP initialize request of a run (and of a capability check).
func initRequest() acp.InitializeRequest {
	return acp.InitializeRequest{
		ProtocolVersion: acp.ProtocolVersionNumber,
		ClientCapabilities: acp.ClientCapabilities{
			Fs:       acp.FileSystemCapabilities{ReadTextFile: true, WriteTextFile: true},
			Terminal: false,
		},
	}
}
