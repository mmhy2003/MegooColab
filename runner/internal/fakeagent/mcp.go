package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/coder/acp-go-sdk"
)

// firstHTTPMcp is the session's first HTTP MCP server.
func firstHTTPMcp(servers []acp.McpServer) *acp.McpServerHttpInline {
	for _, s := range servers {
		if s.Http != nil {
			return s.Http
		}
	}
	return nil
}

// callMcpTool talks to a stateless Streamable HTTP MCP server: initialize,
// then tools/call. It returns the tool result as JSON and whether it succeeded.
func callMcpTool(ctx context.Context, srv *acp.McpServerHttpInline, tool string, args map[string]any) (result string, ok bool, err error) {
	if srv == nil {
		return "", false, fmt.Errorf("the session has no HTTP MCP server")
	}
	if args == nil {
		args = map[string]any{}
	}
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	session := ""
	post := func(id int, method string, params any) (json.RawMessage, error) {
		body, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": id, "method": method, "params": params})
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, srv.Url, bytes.NewReader(body))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Accept", "application/json, text/event-stream")
		for _, h := range srv.Headers {
			req.Header.Set(h.Name, h.Value)
		}
		if session != "" {
			req.Header.Set("Mcp-Session-Id", session)
		}
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()
		if s := resp.Header.Get("Mcp-Session-Id"); s != "" {
			session = s
		}
		raw, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
		if err != nil {
			return nil, err
		}
		if resp.StatusCode/100 != 2 {
			return nil, fmt.Errorf("http %d: %s", resp.StatusCode, strings.TrimSpace(string(raw)))
		}
		return rpcMessage(resp.Header.Get("Content-Type"), raw)
	}

	if _, err := post(1, "initialize", map[string]any{
		"protocolVersion": "2025-03-26",
		"capabilities":    map[string]any{},
		"clientInfo":      map[string]any{"name": "fakeagent", "version": "0"},
	}); err != nil {
		return "", false, fmt.Errorf("initialize: %w", err)
	}
	msg, err := post(2, "tools/call", map[string]any{"name": tool, "arguments": args})
	if err != nil {
		return "", false, err
	}
	var env struct {
		Result json.RawMessage `json:"result"`
		Error  *struct {
			Message string `json:"message"`
		} `json:"error"`
	}
	if err := json.Unmarshal(msg, &env); err != nil {
		return "", false, err
	}
	if env.Error != nil {
		return "", false, fmt.Errorf("%s", env.Error.Message)
	}
	var tr struct {
		IsError bool `json:"isError"`
	}
	_ = json.Unmarshal(env.Result, &tr)
	return string(env.Result), !tr.IsError, nil
}

// rpcMessage returns the JSON-RPC message of a response that is plain JSON or
// an event stream (the last data: event is taken).
func rpcMessage(contentType string, raw []byte) (json.RawMessage, error) {
	if !strings.HasPrefix(contentType, "text/event-stream") {
		return raw, nil
	}
	var last string
	sc := bufio.NewScanner(bytes.NewReader(raw))
	sc.Buffer(make([]byte, 0, 64<<10), 4<<20)
	for sc.Scan() {
		if d, ok := strings.CutPrefix(sc.Text(), "data:"); ok {
			last = strings.TrimSpace(d)
		}
	}
	if last == "" {
		return nil, fmt.Errorf("no data in event stream")
	}
	return json.RawMessage(last), nil
}
