package cmd

import (
	"bytes"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/config"
)

func fakeLook(missing ...string) func(string) (string, error) {
	return func(n string) (string, error) {
		for _, m := range missing {
			if m == n {
				return "", errors.New("not found")
			}
		}
		return "/usr/bin/" + n, nil
	}
}

func fakeRun(nodeVersion string) func(string, ...string) (string, error) {
	return func(name string, args ...string) (string, error) {
		if name == "node" {
			return nodeVersion + "\n", nil
		}
		return "", nil
	}
}

func TestDoctorReportsMissingNode(t *testing.T) {
	d := doctor{lookPath: fakeLook("node", "npx"), run: fakeRun("")}
	res := d.checkNode()
	if res.OK {
		t.Fatal("expected failure")
	}
	if !strings.Contains(res.Hint, "Install Node.js 20+ from https://nodejs.org") {
		t.Fatalf("hint = %q", res.Hint)
	}
	if got := res.Line(); !strings.HasPrefix(got, "[FAIL] node: ") {
		t.Fatalf("line = %q", got)
	}
}

func TestDoctorMissingNpx(t *testing.T) {
	d := doctor{lookPath: fakeLook("npx"), run: fakeRun("v20.1.0")}
	if res := d.checkNode(); res.OK || !strings.Contains(res.Hint, "npx") {
		t.Fatalf("got %+v", res)
	}
}

func TestDoctorNodeVersionTooOld(t *testing.T) {
	d := doctor{lookPath: fakeLook(), run: fakeRun("v18.19.0")}
	res := d.checkNode()
	if res.OK || !strings.Contains(res.Hint, "v18.19.0") || !strings.Contains(res.Hint, "https://nodejs.org") {
		t.Fatalf("got %+v", res)
	}
	d.run = fakeRun("v22.3.1")
	if res := d.checkNode(); !res.OK {
		t.Fatalf("v22 should pass: %+v", res)
	}
}

func TestDoctorGit(t *testing.T) {
	if res := (doctor{lookPath: fakeLook("git")}).checkGit(); res.OK || !strings.HasPrefix(res.Line(), "[FAIL] git: ") {
		t.Fatalf("got %+v", res)
	}
	if res := (doctor{lookPath: fakeLook()}).checkGit(); !res.OK || !strings.HasPrefix(res.Line(), "[OK] git: ") {
		t.Fatalf("got %+v", res)
	}
}

func TestDoctorServerChecks(t *testing.T) {
	scopes := `{"scopes":["runner"]}`
	status := http.StatusOK
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/tokens/self" || r.Header.Get("Authorization") != "Bearer mgc_good" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		w.WriteHeader(status)
		_, _ = w.Write([]byte(scopes))
	}))
	defer srv.Close()

	d := doctor{http: srv.Client()}
	if res := d.checkServer(config.Config{URL: srv.URL, Token: "mgc_good"}); !res.OK {
		t.Fatalf("got %+v", res)
	}
	if res := d.checkServer(config.Config{URL: srv.URL, Token: "mgc_bad"}); res.OK || !strings.Contains(res.Hint, "login") {
		t.Fatalf("got %+v", res)
	}
	scopes = `{"scopes":["mcp"]}`
	if res := d.checkServer(config.Config{URL: srv.URL, Token: "mgc_good"}); res.OK || !strings.Contains(res.Hint, "runner") {
		t.Fatalf("got %+v", res)
	}
	if res := d.checkServer(config.Config{URL: "http://127.0.0.1:1", Token: "x"}); res.OK || !strings.Contains(res.Hint, "reach") {
		t.Fatalf("got %+v", res)
	}
}

func TestDoctorConfigMissing(t *testing.T) {
	d := doctor{load: func() (config.Config, error) { return config.Config{}, errors.New("nope") }}
	if _, res := d.checkConfig(); res.OK || !strings.Contains(res.Hint, "megoocolab-runner login") {
		t.Fatalf("got %+v", res)
	}
}

func TestDoctorRunExitsNonZeroOnFailure(t *testing.T) {
	d := doctor{
		lookPath: fakeLook("git"),
		run:      fakeRun("v20.0.0"),
		load:     func() (config.Config, error) { return config.Config{}, errors.New("nope") },
	}
	var out bytes.Buffer
	if err := d.report(&out); err == nil {
		t.Fatal("expected error when a check fails")
	}
	s := out.String()
	if !strings.Contains(s, "[FAIL] config: ") || !strings.Contains(s, "[FAIL] git: ") || !strings.Contains(s, "[OK] node: ") {
		t.Fatalf("output:\n%s", s)
	}
}
