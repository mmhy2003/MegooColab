package conn

import (
	"context"
	"encoding/json"
	"errors"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mmhy2003/megoocolab/runner/internal/config"
	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
	"github.com/mmhy2003/megoocolab/runner/internal/testserver"
)

const token = "mgc_testtoken"

// newTestClient wires a client to a fake server with millisecond timings.
func newTestClient(t *testing.T, s *testserver.Server, tok string) *Client {
	t.Helper()
	c := New(config.Config{URL: s.URL(), Token: tok}, "9.9.9", func() []protocol.AgentAvailability {
		return []protocol.AgentAvailability{{AgentID: "agent-1", Available: true}}
	})
	c.HeartbeatInterval = 50 * time.Millisecond
	c.BackoffBase = 5 * time.Millisecond
	c.BackoffMax = 20 * time.Millisecond
	c.Jitter = func() float64 { return 0.5 }
	return c
}

// start runs the client and returns a channel with Run's result. The channel
// is closed after the result, so it can be read again by the cleanup.
func start(t *testing.T, c *Client) (cancel func(), done <-chan error) {
	t.Helper()
	ctx, cancelCtx := context.WithCancel(context.Background())
	ch := make(chan error, 1)
	go func() { ch <- c.Run(ctx); close(ch) }()
	t.Cleanup(func() {
		cancelCtx()
		select {
		case <-ch:
		case <-time.After(5 * time.Second):
			t.Error("Run did not return after cancel")
		}
	})
	return cancelCtx, ch
}

func waitErr(t *testing.T, done <-chan error) error {
	t.Helper()
	select {
	case err := <-done:
		return err
	case <-time.After(5 * time.Second):
		t.Fatal("Run did not stop")
		return nil
	}
}

func TestHelloAdvertisesWorkflowCapability(t *testing.T) {
	s := testserver.New(t, token)
	c := newTestClient(t, s, token)
	start(t, c)

	var hello protocol.Hello
	if err := json.Unmarshal(s.WaitFrame(t, "hello").Raw, &hello); err != nil {
		t.Fatal(err)
	}
	if strings.Join(hello.Capabilities, ",") != "workflow/1,branch/1,model/1" {
		t.Fatalf("capabilities = %v", hello.Capabilities)
	}
}

func TestHelloAndHeartbeat(t *testing.T) {
	s := testserver.New(t, token)
	c := newTestClient(t, s, token)
	start(t, c)

	f := s.WaitFrame(t, "hello")
	var hello protocol.Hello
	if err := json.Unmarshal(f.Raw, &hello); err != nil {
		t.Fatal(err)
	}
	if hello.RunnerVersion != "9.9.9" || hello.OS != runtime.GOOS || hello.Arch != runtime.GOARCH {
		t.Fatalf("hello = %+v", hello)
	}
	if len(hello.Agents) != 1 || hello.Agents[0].AgentID != "agent-1" || !hello.Agents[0].Available {
		t.Fatalf("hello agents = %+v", hello.Agents)
	}
	s.WaitNthFrame(t, "heartbeat", 3)

	select {
	case env := <-c.Messages():
		if env.Type != protocol.TypeWelcome {
			t.Fatalf("first message = %q", env.Type)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("welcome not delivered on Messages()")
	}
}

func TestDeliversScriptedServerMessages(t *testing.T) {
	s := testserver.New(t, token)
	c := newTestClient(t, s, token)
	start(t, c)
	s.WaitFrame(t, "hello")
	<-c.Messages() // welcome

	if err := s.Send(protocol.RunCancel{Type: protocol.TypeRunCancel, RunID: "run-1"}); err != nil {
		t.Fatal(err)
	}
	env := <-c.Messages()
	var rc protocol.RunCancel
	if env.Type != protocol.TypeRunCancel || env.Into(&rc) != nil || rc.RunID != "run-1" {
		t.Fatalf("got %q %+v", env.Type, rc)
	}
}

func TestSendWritesFrame(t *testing.T) {
	s := testserver.New(t, token)
	c := newTestClient(t, s, token)
	if err := c.Send(protocol.NewHeartbeat()); err == nil {
		t.Fatal("Send before connecting should fail")
	}
	start(t, c)
	s.WaitFrame(t, "hello")
	st := protocol.NewAgentStatus("agent-1", false, []string{"node missing"})
	if err := c.Send(st); err != nil {
		t.Fatal(err)
	}
	f := s.WaitFrame(t, "agent_status")
	var got protocol.AgentStatus
	if err := json.Unmarshal(f.Raw, &got); err != nil || got.Available || got.Problems[0] != "node missing" {
		t.Fatalf("got %+v err %v", got, err)
	}
}

func TestReconnectsAfterDrop(t *testing.T) {
	codes := map[string]int{"abnormal": 1011, "idle 4408": protocol.CloseIdle, "protocol error 4400": protocol.CloseProtocolError}
	for name, code := range codes {
		t.Run(name, func(t *testing.T) {
			s := testserver.New(t, token)
			c := newTestClient(t, s, token)
			start(t, c)
			s.WaitConnected(t, 1)
			s.WaitFrame(t, "hello")
			s.Close(code, "bye")
			s.WaitNthFrame(t, "hello", 2) // second connection says hello again
			if s.Connections() < 2 {
				t.Fatalf("connections = %d", s.Connections())
			}
		})
	}
}

func TestStopsOn4401(t *testing.T) {
	s := testserver.New(t, token)
	s.RejectWith(protocol.CloseUnauthorized)
	c := newTestClient(t, s, token)
	_, done := start(t, c)
	if err := waitErr(t, done); !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("err = %v, want ErrUnauthorized", err)
	}
	if s.Connections() != 1 {
		t.Fatalf("connections = %d, want 1 (no retry)", s.Connections())
	}
}

func TestStopsOn4401AfterConnected(t *testing.T) {
	s := testserver.New(t, token)
	c := newTestClient(t, s, token)
	_, done := start(t, c)
	s.WaitFrame(t, "hello")
	s.Close(protocol.CloseUnauthorized, "revoked")
	if err := waitErr(t, done); !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("err = %v, want ErrUnauthorized", err)
	}
}

func TestStopsOn4409(t *testing.T) {
	s := testserver.New(t, token)
	c := newTestClient(t, s, token)
	_, done := start(t, c)
	s.WaitFrame(t, "hello")
	s.Close(protocol.CloseReplaced, "replaced")
	if err := waitErr(t, done); !errors.Is(err, ErrReplaced) {
		t.Fatalf("err = %v, want ErrReplaced", err)
	}
	if s.Connections() != 1 {
		t.Fatalf("connections = %d, want 1 (no retry)", s.Connections())
	}
}

func TestBearerHeaderSent(t *testing.T) {
	s := testserver.New(t, token)
	c := newTestClient(t, s, token)
	start(t, c)
	s.WaitFrame(t, "hello")
	if got := s.AuthHeaders(); len(got) != 1 || got[0] != "Bearer "+token {
		t.Fatalf("Authorization headers = %q", got)
	}
}

func TestWrongTokenIsUnauthorized(t *testing.T) {
	s := testserver.New(t, token)
	c := newTestClient(t, s, "mgc_other")
	_, done := start(t, c)
	if err := waitErr(t, done); !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("err = %v, want ErrUnauthorized", err)
	}
}

func TestCancelStopsRun(t *testing.T) {
	s := testserver.New(t, token)
	c := newTestClient(t, s, token)
	cancel, done := start(t, c)
	s.WaitFrame(t, "hello")
	cancel()
	if err := waitErr(t, done); !errors.Is(err, context.Canceled) {
		t.Fatalf("err = %v, want context.Canceled", err)
	}
	if _, open := <-c.Messages(); open {
		// drain the welcome, then expect closed
		if _, open := <-c.Messages(); open {
			t.Fatal("Messages() should be closed after Run returns")
		}
	}
}

func TestStateCallback(t *testing.T) {
	s := testserver.New(t, token)
	c := newTestClient(t, s, token)
	states := make(chan string, 16)
	c.OnState = func(st string) { states <- st }
	start(t, c)
	s.WaitFrame(t, "hello")
	s.Close(1011, "x")
	want := []string{"connected", "reconnecting in", "connected"}
	for i, w := range want {
		select {
		case got := <-states:
			if len(got) < len(w) || got[:len(w)] != w {
				t.Fatalf("state %d = %q, want prefix %q", i, got, w)
			}
		case <-time.After(5 * time.Second):
			t.Fatalf("state %d (%q) never came", i, w)
		}
	}
}

func TestBackoffDelay(t *testing.T) {
	base, max := time.Second, 30*time.Second
	cases := []struct {
		attempt int
		jitter  float64
		want    time.Duration
	}{
		{0, 0.5, time.Second},
		{1, 0.5, 2 * time.Second},
		{4, 0.5, 16 * time.Second},
		{5, 0.5, 30 * time.Second}, // 32 s capped
		{50, 0.5, 30 * time.Second},
		{0, 0, 800 * time.Millisecond},  // -20%
		{0, 1, 1200 * time.Millisecond}, // +20%
		{50, 1, 36 * time.Second},       // jitter applies to the capped value
	}
	for _, c := range cases {
		if got := backoffDelay(base, max, c.attempt, c.jitter); got != c.want {
			t.Errorf("attempt %d jitter %v = %v, want %v", c.attempt, c.jitter, got, c.want)
		}
	}
}

func TestWSURL(t *testing.T) {
	cases := map[string]string{
		"http://localhost:8000":    "ws://localhost:8000/api/runner/ws",
		"https://colab.example.io": "wss://colab.example.io/api/runner/ws",
		"https://x.io/base":        "wss://x.io/base/api/runner/ws",
	}
	for in, want := range cases {
		got, err := WSURL(in)
		if err != nil || got != want {
			t.Errorf("WSURL(%q) = %q, %v; want %q", in, got, err, want)
		}
	}
	if _, err := WSURL("ftp://x"); err == nil {
		t.Error("WSURL(ftp) should fail")
	}
}

func TestOnDisconnectCalledOnReconnectableLoss(t *testing.T) {
	s := testserver.New(t, token)
	c := newTestClient(t, s, token)
	got := make(chan error, 4)
	var states []string
	var mu sync.Mutex
	c.OnState = func(st string) { mu.Lock(); states = append(states, st); mu.Unlock() }
	c.OnDisconnect = func(err error) {
		mu.Lock()
		// it must run before the "reconnecting" state is announced
		for _, st := range states {
			if strings.HasPrefix(st, "reconnecting") {
				err = errors.New("called after reconnecting state")
			}
		}
		mu.Unlock()
		got <- err
	}
	start(t, c)
	s.WaitFrame(t, "hello")
	s.Close(1011, "bye")
	select {
	case err := <-got:
		if err == nil || strings.Contains(err.Error(), "after reconnecting") {
			t.Fatalf("OnDisconnect err = %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("OnDisconnect not called")
	}
	s.WaitNthFrame(t, "hello", 2)
}

func TestEnvelopesCarryConnectionNumber(t *testing.T) {
	s := testserver.New(t, token)
	c := newTestClient(t, s, token)
	start(t, c)
	s.WaitFrame(t, "hello")
	_ = s.Send(protocol.RunCancel{Type: protocol.TypeRunCancel, RunID: "a"})
	first := nextCancel(t, c)
	s.Close(1011, "bye")
	s.WaitNthFrame(t, "hello", 2)
	_ = s.Send(protocol.RunCancel{Type: protocol.TypeRunCancel, RunID: "b"})
	second := nextCancel(t, c)
	if first.Conn != 1 || second.Conn != 2 {
		t.Fatalf("connection numbers = %d, %d; want 1, 2", first.Conn, second.Conn)
	}
	if c.Session() != 2 {
		t.Fatalf("Session() = %d, want 2", c.Session())
	}
}

// nextCancel returns the next run_cancel, skipping the welcomes the fake server sends.
func nextCancel(t *testing.T, c *Client) protocol.Envelope {
	t.Helper()
	for {
		select {
		case env := <-c.Messages():
			if env.Type == protocol.TypeRunCancel {
				return env
			}
		case <-time.After(5 * time.Second):
			t.Fatal("no run_cancel")
		}
	}
}
