// Package conn keeps the runner's WebSocket connection to the MegooColab
// server alive: dial, hello, heartbeat, reconnect with backoff.
package conn

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math/rand/v2"
	"net/http"
	"net/url"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"

	"github.com/mmhy2003/megoocolab/runner/internal/config"
	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

var (
	// ErrUnauthorized means the server closed with 4401: the token is revoked or invalid.
	ErrUnauthorized = errors.New("token revoked or invalid — run `megoocolab-runner login`")
	// ErrReplaced means the server closed with 4409: a newer runner took over.
	ErrReplaced = errors.New("another runner signed in with this account")
)

const (
	defaultHeartbeat = 15 * time.Second
	defaultBackoff   = time.Second
	defaultBackoffMx = 30 * time.Second
	jitterFraction   = 0.2
	readLimit        = 4 << 20
)

// Client is the runner's connection to the server. Set the exported tuning
// fields before calling Run; they exist so tests can run in milliseconds.
type Client struct {
	HeartbeatInterval time.Duration  // default 15 s
	BackoffBase       time.Duration  // default 1 s
	BackoffMax        time.Duration  // default 30 s
	Jitter            func() float64 // returns [0,1); 0.5 means no jitter. Default rand.Float64
	// OnState, if set, is told about "connected", "reconnecting in 2s" and
	// "stopped: <reason>". It is called from the Run goroutine.
	OnState func(string)
	// OnDisconnect, if set, is called from the Run goroutine whenever a session
	// ends with an error that will be retried, before "reconnecting in ..." is
	// announced. The server fails a run when its runner disconnects, so callers
	// stop their in-flight work here.
	OnDisconnect func(error)

	cfg      config.Config
	version  string
	probe    func() []protocol.AgentAvailability
	messages chan protocol.Envelope

	mu   sync.Mutex
	conn *websocket.Conn
}

// New builds a client. agentsProbe is called on every (re)connect to fill hello; it may be nil.
func New(cfg config.Config, version string, agentsProbe func() []protocol.AgentAvailability) *Client {
	return &Client{
		HeartbeatInterval: defaultHeartbeat,
		BackoffBase:       defaultBackoff,
		BackoffMax:        defaultBackoffMx,
		Jitter:            rand.Float64,
		cfg:               cfg,
		version:           version,
		probe:             agentsProbe,
		messages:          make(chan protocol.Envelope, 64),
	}
}

// Messages delivers server messages. It is closed when Run returns. The
// consumer must keep reading: a full channel pauses reading from the socket.
func (c *Client) Messages() <-chan protocol.Envelope { return c.messages }

// WSURL converts the configured http(s):// base URL to the runner websocket URL.
func WSURL(base string) (string, error) {
	u, err := url.Parse(strings.TrimRight(base, "/"))
	if err != nil {
		return "", err
	}
	switch u.Scheme {
	case "http":
		u.Scheme = "ws"
	case "https":
		u.Scheme = "wss"
	default:
		return "", fmt.Errorf("server URL %q must be http:// or https://", base)
	}
	u.Path += "/api/runner/ws"
	return u.String(), nil
}

// backoffDelay is base*2^attempt capped at max, then scaled by ±20% using jitter in [0,1).
func backoffDelay(base, max time.Duration, attempt int, jitter float64) time.Duration {
	d := base
	for i := 0; i < attempt && d < max; i++ {
		d *= 2
	}
	if d > max {
		d = max
	}
	return time.Duration(float64(d) * (1 + jitterFraction*(2*jitter-1)))
}

// Run connects and keeps reconnecting until ctx is cancelled (returns ctx.Err())
// or the server says to stop (ErrUnauthorized, ErrReplaced). Call it once.
func (c *Client) Run(ctx context.Context) error {
	defer close(c.messages)
	attempt := 0
	for {
		gotWelcome, err := c.session(ctx)
		switch {
		case ctx.Err() != nil:
			return ctx.Err()
		case errors.Is(err, ErrUnauthorized), errors.Is(err, ErrReplaced):
			c.state("stopped: " + err.Error())
			return err
		}
		if gotWelcome {
			attempt = 0
		}
		if c.OnDisconnect != nil {
			c.OnDisconnect(err)
		}
		delay := backoffDelay(c.BackoffBase, c.BackoffMax, attempt, c.Jitter())
		attempt++
		c.state(fmt.Sprintf("reconnecting in %s (%v)", delay.Round(time.Millisecond), err))
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(delay):
		}
	}
}

func (c *Client) state(s string) {
	if c.OnState != nil {
		c.OnState(s)
	}
}

// Send writes msg as a JSON text frame on the live connection.
func (c *Client) Send(msg any) error {
	c.mu.Lock()
	ws := c.conn
	c.mu.Unlock()
	if ws == nil {
		return errors.New("not connected")
	}
	return writeJSON(ws, msg)
}

func writeJSON(ws *websocket.Conn, msg any) error {
	data, err := json.Marshal(msg)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return ws.Write(ctx, websocket.MessageText, data)
}

// session runs one connection. gotWelcome reports whether the server answered
// hello, which is what resets the backoff (so a server that accepts and then
// immediately closes does not cause a hot loop).
func (c *Client) session(ctx context.Context) (gotWelcome bool, err error) {
	wsURL, err := WSURL(c.cfg.URL)
	if err != nil {
		return false, err
	}
	dialCtx, cancelDial := context.WithTimeout(ctx, 15*time.Second)
	ws, _, err := websocket.Dial(dialCtx, wsURL, &websocket.DialOptions{
		HTTPHeader: http.Header{"Authorization": {"Bearer " + c.cfg.Token}},
	})
	cancelDial()
	if err != nil {
		return false, err
	}
	ws.SetReadLimit(readLimit)

	sctx, cancel := context.WithCancel(ctx)
	defer cancel()
	defer ws.CloseNow()

	var agents []protocol.AgentAvailability
	if c.probe != nil {
		agents = c.probe()
	}
	if err := writeJSON(ws, protocol.NewHello(c.version, runtime.GOOS, runtime.GOARCH, agents)); err != nil {
		return false, err
	}
	c.mu.Lock()
	c.conn = ws
	c.mu.Unlock()
	defer func() {
		c.mu.Lock()
		c.conn = nil
		c.mu.Unlock()
	}()
	c.state("connected")

	go func() {
		t := time.NewTicker(c.HeartbeatInterval)
		defer t.Stop()
		for {
			select {
			case <-sctx.Done():
				return
			case <-t.C:
				if writeJSON(ws, protocol.NewHeartbeat()) != nil {
					cancel() // unblocks the read below
					return
				}
			}
		}
	}()

	for {
		_, data, err := ws.Read(sctx)
		if err != nil {
			return gotWelcome, classify(err)
		}
		env, derr := protocol.Decode(data)
		if derr != nil {
			continue // not ours to act on; the server only sends typed frames
		}
		gotWelcome = gotWelcome || env.Type == protocol.TypeWelcome
		select {
		case c.messages <- env:
		case <-sctx.Done():
			return gotWelcome, sctx.Err()
		}
	}
}

// classify maps a websocket close code to a sentinel error.
func classify(err error) error {
	switch websocket.CloseStatus(err) {
	case protocol.CloseUnauthorized:
		return ErrUnauthorized
	case protocol.CloseReplaced:
		return ErrReplaced
	}
	return err
}
