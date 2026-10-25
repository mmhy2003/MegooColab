package jobs

import (
	"context"
	"errors"
	"fmt"
	"io"

	"github.com/coder/acp-go-sdk"

	"github.com/mmhy2003/megoocolab/runner/internal/acpclient"
	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

// mcpServerName is how MegooColab's MCP server is named inside the agent.
const mcpServerName = "megoocolab"

// mcpServers is the MCP server list for a session: MegooColab's own server,
// carrying the run's bearer token, for a workflow run; none otherwise.
func mcpServers(a *protocol.McpAccess) []acp.McpServer {
	if a == nil {
		return []acp.McpServer{}
	}
	return []acp.McpServer{{Http: &acp.McpServerHttpInline{
		Name:    mcpServerName,
		Url:     a.URL,
		Headers: []acp.HttpHeader{{Name: "Authorization", Value: "Bearer " + a.Token}},
	}}}
}

// openedSession is the session a run prompts, and what to prompt it with.
type openedSession struct {
	id     acp.SessionId
	modes  *acp.SessionModeState
	prompt string
}

// sessionRequest is what opening a session needs.
type sessionRequest struct {
	ac      *acp.ClientSideConnection
	client  *acpclient.Client
	caps    acp.AgentCapabilities
	rs      protocol.RunStart
	cwd     string
	meta    map[string]any
	servers []acp.McpServer
	log     io.Writer
}

// openSession resumes the stored session when the run asks for it and the agent
// can; otherwise it starts a new one with the full prompt. When a resume fails,
// the resume prompt (an answer, a rejection, findings) follows the full prompt,
// so the new session still gets it.
func openSession(ctx context.Context, q sessionRequest) (openedSession, error) {
	prompt := q.rs.Prompt
	if q.rs.ResumeSessionID != "" {
		s, err := resumeSession(ctx, q)
		if err == nil {
			return s, nil
		}
		fmt.Fprintf(q.log, "runner: resume_fallback: %v\n", err)
		if ctx.Err() != nil {
			return openedSession{}, ctx.Err()
		}
		if q.rs.ResumePrompt != "" {
			prompt += "\n\n" + q.rs.ResumePrompt
		}
	}
	resp, err := q.ac.NewSession(ctx, acp.NewSessionRequest{Cwd: q.cwd, McpServers: q.servers, Meta: q.meta})
	if err != nil {
		return openedSession{}, err
	}
	return openedSession{id: resp.SessionId, modes: resp.Modes, prompt: prompt}, nil
}

// resumeSession continues the stored session (session/resume, else session/load).
func resumeSession(ctx context.Context, q sessionRequest) (openedSession, error) {
	id := acp.SessionId(q.rs.ResumeSessionID)
	prompt := q.rs.ResumePrompt
	if prompt == "" {
		prompt = q.rs.Prompt
	}
	switch {
	case q.caps.SessionCapabilities.Resume != nil:
		resp, err := q.ac.ResumeSession(ctx, acp.ResumeSessionRequest{SessionId: id, Cwd: q.cwd, McpServers: q.servers, Meta: q.meta})
		if err != nil {
			return openedSession{}, fmt.Errorf("session/resume: %w", err)
		}
		return openedSession{id: id, modes: resp.Modes, prompt: prompt}, nil
	case q.caps.LoadSession:
		// The agent replays the old conversation as updates while it loads;
		// none of it is a run update.
		q.client.SetReplaying(true)
		resp, err := q.ac.LoadSession(ctx, acp.LoadSessionRequest{SessionId: id, Cwd: q.cwd, McpServers: q.servers, Meta: q.meta})
		q.client.SetReplaying(false)
		if err != nil {
			return openedSession{}, fmt.Errorf("session/load: %w", err)
		}
		return openedSession{id: id, modes: resp.Modes, prompt: prompt}, nil
	}
	return openedSession{}, errors.New("the agent supports neither session/resume nor session/load")
}

// tokenOf is the run's MCP token, or "" for a run without MCP.
func tokenOf(a *protocol.McpAccess) string {
	if a == nil {
		return ""
	}
	return a.Token
}
