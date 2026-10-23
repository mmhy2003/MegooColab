// Package testserver is an httptest fake of the MegooColab server's runner
// WebSocket (/api/runner/ws), for tests of the runner.
//
// Usage:
//
//	s := testserver.New(t, "mgc_token")   // closed automatically at test end
//	cfg := config.Config{URL: s.URL(), Token: "mgc_token"}
//	s.WaitConnected(t, 1)                  // block until the 1st connection exists
//	s.Send(protocol.RunCancel{...})        // push a server message to the live connection
//	f := s.WaitFrame(t, "hello")           // block until a frame of that type arrives
//	s.Close(4409, "replaced")              // close the live connection with a code
//	s.RejectWith(4401)                     // close every new connection immediately
//
// A wrong or missing bearer token is treated like the real server: the socket
// is accepted and then closed with 4401. When AutoWelcome is true (default) a
// hello is answered with an empty welcome.
package testserver

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/coder/websocket"
)

// Frame is one text frame received from the runner.
type Frame struct {
	Conn int    // 1-based index of the connection it arrived on
	Type string // the "type" field ("" if the frame had none)
	Raw  []byte
}

// Server is the fake. Create it with New.
type Server struct {
	// AutoWelcome answers hello with a welcome frame. Set before connecting.
	AutoWelcome bool

	token string
	ts    *httptest.Server

	mu       sync.Mutex
	cond     *sync.Cond
	conns    int
	live     *websocket.Conn
	frames   []Frame
	headers  []string
	rejectAs int
}

// New starts a server that accepts the given bearer token.
func New(t testing.TB, token string) *Server {
	s := &Server{AutoWelcome: true, token: token}
	s.cond = sync.NewCond(&s.mu)
	s.ts = httptest.NewServer(http.HandlerFunc(s.handle))
	t.Cleanup(s.ts.Close)
	return s
}

// URL is the http:// base URL to put in config.Config.URL.
func (s *Server) URL() string { return s.ts.URL }

// Connections is how many websocket connections have been accepted so far.
func (s *Server) Connections() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.conns
}

// AuthHeaders returns the Authorization header of every connection attempt, in order.
func (s *Server) AuthHeaders() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string(nil), s.headers...)
}

// Frames returns a copy of every frame received so far, across connections.
func (s *Server) Frames() []Frame {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]Frame(nil), s.frames...)
}

// RejectWith makes every new connection close immediately with code (0 turns it off).
func (s *Server) RejectWith(code int) {
	s.mu.Lock()
	s.rejectAs = code
	s.mu.Unlock()
}

// Send writes v as a JSON text frame to the live connection.
func (s *Server) Send(v any) error {
	data, err := json.Marshal(v)
	if err != nil {
		return err
	}
	s.mu.Lock()
	c := s.live
	s.mu.Unlock()
	if c == nil {
		return errors.New("testserver: no live connection")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	return c.Write(ctx, websocket.MessageText, data)
}

// Close closes the live connection with the given code (no-op if none).
func (s *Server) Close(code int, reason string) {
	s.mu.Lock()
	c := s.live
	s.mu.Unlock()
	if c != nil {
		_ = c.Close(websocket.StatusCode(code), reason)
	}
}

// WaitConnected blocks until at least n connections were accepted.
func (s *Server) WaitConnected(t testing.TB, n int) {
	t.Helper()
	s.wait(t, "connection", func() bool { return s.conns >= n })
}

// WaitFrame blocks until a frame of the given type has been received and
// returns the first such frame in arrival order.
func (s *Server) WaitFrame(t testing.TB, typ string) Frame {
	t.Helper()
	return s.WaitNthFrame(t, typ, 1)
}

// WaitNthFrame blocks until n frames of the given type have arrived and returns the nth.
func (s *Server) WaitNthFrame(t testing.TB, typ string, n int) Frame {
	t.Helper()
	var found Frame
	s.wait(t, "frame "+typ, func() bool {
		count := 0
		for _, f := range s.frames {
			if f.Type == typ {
				if count++; count == n {
					found = f
					return true
				}
			}
		}
		return false
	})
	return found
}

// wait blocks (up to 5 s) until cond, evaluated under the lock, holds.
func (s *Server) wait(t testing.TB, what string, cond func() bool) {
	t.Helper()
	timer := time.AfterFunc(5*time.Second, func() {
		s.mu.Lock()
		s.cond.Broadcast()
		s.mu.Unlock()
	})
	defer timer.Stop()
	deadline := time.Now().Add(5 * time.Second)
	s.mu.Lock()
	defer s.mu.Unlock()
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatalf("testserver: timed out waiting for %s", what)
		}
		s.cond.Wait()
	}
}

func (s *Server) handle(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/api/runner/ws" {
		http.NotFound(w, r)
		return
	}
	c, err := websocket.Accept(w, r, nil)
	if err != nil {
		return
	}
	c.SetReadLimit(4 << 20)
	auth := r.Header.Get("Authorization")

	s.mu.Lock()
	s.conns++
	idx := s.conns
	s.headers = append(s.headers, auth)
	reject := s.rejectAs
	if auth != "Bearer "+s.token {
		reject = 4401
	}
	if reject == 0 {
		s.live = c
	}
	s.cond.Broadcast()
	s.mu.Unlock()

	if reject != 0 {
		_ = c.Close(websocket.StatusCode(reject), "rejected")
		return
	}
	defer func() {
		s.mu.Lock()
		if s.live == c {
			s.live = nil
		}
		s.mu.Unlock()
	}()

	for {
		_, data, err := c.Read(r.Context())
		if err != nil {
			return
		}
		var head struct {
			Type string `json:"type"`
		}
		_ = json.Unmarshal(data, &head)
		s.mu.Lock()
		s.frames = append(s.frames, Frame{Conn: idx, Type: head.Type, Raw: data})
		auto := s.AutoWelcome
		s.cond.Broadcast()
		s.mu.Unlock()
		if auto && head.Type == "hello" {
			_ = c.Write(r.Context(), websocket.MessageText,
				[]byte(`{"type":"welcome","user_id":"00000000-0000-0000-0000-000000000001","agents":[]}`))
		}
	}
}
