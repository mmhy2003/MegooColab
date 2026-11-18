package services

import (
	"fmt"
	"net/http"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"
)

// TestMain lets the test binary stand in for the command Run wraps: with
// SERVICES_TEST_HELPER set it does what the variable says and exits.
//   - exit:N   exits with code N
//   - env:NAME prints the value of NAME and exits 0
//   - get:NAME GETs http://127.0.0.1:<$NAME>/ and exits 0 on 200, else 1
//   - sleep    sleeps 30 s
func TestMain(m *testing.M) {
	mode, ok := os.LookupEnv("SERVICES_TEST_HELPER")
	if !ok || mode == "" {
		os.Exit(m.Run())
	}
	switch {
	case strings.HasPrefix(mode, "exit:"):
		code, err := strconv.Atoi(strings.TrimPrefix(mode, "exit:"))
		if err != nil {
			fmt.Fprintln(os.Stderr, "helper:", err)
			os.Exit(2)
		}
		os.Exit(code)
	case strings.HasPrefix(mode, "env:"):
		fmt.Println(os.Getenv(strings.TrimPrefix(mode, "env:")))
		os.Exit(0)
	case strings.HasPrefix(mode, "get:"):
		resp, err := http.Get("http://127.0.0.1:" + os.Getenv(strings.TrimPrefix(mode, "get:")) + "/")
		if err != nil {
			fmt.Fprintln(os.Stderr, "helper:", err)
			os.Exit(1)
		}
		resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			fmt.Fprintln(os.Stderr, "helper:", resp.Status)
			os.Exit(1)
		}
		os.Exit(0)
	case mode == "sleep":
		time.Sleep(30 * time.Second)
		os.Exit(0)
	}
	fmt.Fprintf(os.Stderr, "helper: unknown mode %q\n", mode)
	os.Exit(2)
}
