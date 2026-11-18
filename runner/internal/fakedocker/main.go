// Command fakedocker stands in for docker in the services tests. Each call
// appends one JSON line {"args":[...],"env":{...}} to $FAKEDOCKER_LOG, where
// env holds the names listed in $FAKEDOCKER_SHOW that are set. Then:
//   - a verb in $FAKEDOCKER_FAIL (comma-separated) prints
//     "fakedocker: <verb> failed" to stderr and exits 1;
//   - the first $FAKEDOCKER_PORT_TAKEN `up` calls fail with "port is already
//     allocated" (counted in the file $FAKEDOCKER_LOG.up);
//   - `up` first sleeps $FAKEDOCKER_UP_SLEEP_MS milliseconds;
//   - `config` prints $FAKEDOCKER_CONFIG (default {"name":"x","services":{}});
//   - `ps`, `volume ls` and `network ls` print leftover1 when
//     $FAKEDOCKER_LEFTOVER=1;
//   - `logs` prints "fake logs"; anything else exits 0.
//
// The verb is args[0] for plain docker, and for compose the first argument
// after `compose` that is not a flag or a flag's value.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"slices"
	"strconv"
	"strings"
	"time"
)

func main() { os.Exit(run(os.Args[1:])) }

func run(args []string) int {
	if err := logCall(args); err != nil {
		fmt.Fprintln(os.Stderr, "fakedocker: log:", err)
		return 2
	}
	verb := verbOf(args)
	if slices.Contains(strings.Split(os.Getenv("FAKEDOCKER_FAIL"), ","), verb) {
		fmt.Fprintf(os.Stderr, "fakedocker: %s failed\n", verb)
		return 1
	}
	switch verb {
	case "up":
		if ms, _ := strconv.Atoi(os.Getenv("FAKEDOCKER_UP_SLEEP_MS")); ms > 0 {
			time.Sleep(time.Duration(ms) * time.Millisecond)
		}
		if portTaken() {
			fmt.Fprintln(os.Stderr, "Error response from daemon: Bind for 127.0.0.1:5432 failed: port is already allocated")
			return 1
		}
	case "config":
		cfg := os.Getenv("FAKEDOCKER_CONFIG")
		if cfg == "" {
			cfg = `{"name":"x","services":{}}`
		}
		fmt.Println(cfg)
	case "ps", "volume", "network":
		lists := verb == "ps" || (len(args) > 1 && args[1] == "ls")
		if lists && os.Getenv("FAKEDOCKER_LEFTOVER") == "1" {
			fmt.Println("leftover1")
		}
	case "logs":
		fmt.Println("fake logs")
	}
	return 0
}

// verbOf returns args[0], or for compose the first argument after it that is
// not a flag or the value of -p, -f, --env-file or --project-directory.
func verbOf(args []string) string {
	if len(args) == 0 {
		return ""
	}
	if args[0] != "compose" {
		return args[0]
	}
	for i := 1; i < len(args); i++ {
		switch a := args[i]; {
		case a == "-p" || a == "-f" || a == "--env-file" || a == "--project-directory":
			i++
		case strings.HasPrefix(a, "-"):
		default:
			return a
		}
	}
	return ""
}

func logCall(args []string) error {
	env := map[string]string{}
	for _, name := range strings.Split(os.Getenv("FAKEDOCKER_SHOW"), ",") {
		if v, ok := os.LookupEnv(name); ok && name != "" {
			env[name] = v
		}
	}
	line, err := json.Marshal(struct {
		Args []string          `json:"args"`
		Env  map[string]string `json:"env"`
	}{args, env})
	if err != nil {
		return err
	}
	path := os.Getenv("FAKEDOCKER_LOG")
	if path == "" {
		return nil
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	if _, err := f.Write(append(line, '\n')); err != nil {
		f.Close()
		return err
	}
	return f.Close()
}

// portTaken counts this `up` in $FAKEDOCKER_LOG.up and reports whether it is
// one of the first $FAKEDOCKER_PORT_TAKEN.
func portTaken() bool {
	limit, _ := strconv.Atoi(os.Getenv("FAKEDOCKER_PORT_TAKEN"))
	if limit <= 0 {
		return false
	}
	counter := os.Getenv("FAKEDOCKER_LOG") + ".up"
	n := 0
	if b, err := os.ReadFile(counter); err == nil {
		n, _ = strconv.Atoi(strings.TrimSpace(string(b)))
	}
	n++
	_ = os.WriteFile(counter, []byte(strconv.Itoa(n)), 0o600)
	return n <= limit
}
