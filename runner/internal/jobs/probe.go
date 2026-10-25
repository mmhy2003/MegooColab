package jobs

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"time"

	"github.com/coder/acp-go-sdk"

	"github.com/mmhy2003/megoocolab/runner/internal/acpclient"
	"github.com/mmhy2003/megoocolab/runner/internal/adapters"
	"github.com/mmhy2003/megoocolab/runner/internal/policy"
)

// ProbeTimeout bounds one capability check.
const ProbeTimeout = 60 * time.Second

// Capabilities are the ACP capabilities an adapter advertises.
type Capabilities struct {
	McpHTTP     bool
	LoadSession bool
	Resume      bool
}

// ProbeCapabilities starts the adapter the way a run does, runs Initialize
// only (no session, no token) and kills the process tree.
func ProbeCapabilities(ctx context.Context, program string) (Capabilities, error) {
	spec, err := adapters.For(program)
	if err != nil {
		return Capabilities{}, err
	}
	ctx, cancel := context.WithTimeout(ctx, ProbeTimeout)
	defer cancel()
	dir, err := os.MkdirTemp("", "megoocolab-doctor-")
	if err != nil {
		return Capabilities{}, err
	}
	defer os.RemoveAll(dir)
	pol, err := policy.New(policy.ReadOnly, dir)
	if err != nil {
		return Capabilities{}, err
	}

	proc, err := startAdapter(spec, dir, nil)
	if err != nil {
		return Capabilities{}, err
	}
	cmd, stdin, stdout := proc.cmd, proc.stdin, proc.stdout
	defer func() {
		_ = stdin.Close()
		killTree(cmd)
		done := make(chan struct{})
		go func() { _ = cmd.Wait(); close(done) }()
		select {
		case <-done:
		case <-time.After(10 * time.Second):
		}
	}()

	ac := acp.NewClientSideConnection(acpclient.New(pol, dir, func(string, map[string]any) {}), stdin, stdout)
	ac.SetLogger(slog.New(slog.NewTextHandler(io.Discard, nil)))
	resp, err := ac.Initialize(ctx, initRequest())
	if err != nil {
		return Capabilities{}, fmt.Errorf("initialize: %w", err)
	}
	c := resp.AgentCapabilities
	return Capabilities{
		McpHTTP:     c.McpCapabilities.Http,
		LoadSession: c.LoadSession,
		Resume:      c.SessionCapabilities.Resume != nil,
	}, nil
}
