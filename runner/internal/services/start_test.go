package services

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

// testSet writes a Compose file in a new worktree and returns a File with one
// set "test" using it, with the port DB_PORT and an env entry naming it.
func testSet(t *testing.T) (*File, Set) {
	t.Helper()
	worktree := Canonical(t.TempDir())
	compose := writeFile(t, worktree, "compose.yml", "services: {}\n")
	set := Set{
		Name:    "test",
		Compose: []string{compose},
		Ports:   []string{"DB_PORT"},
		Env:     map[string]string{"DB_URL": "pg://localhost:${DB_PORT}/x"},
	}
	f := &File{Path: filepath.Join(worktree, FileName), Dir: worktree, Sets: map[string]Set{"test": set}}
	return f, set
}

// loggedCall is one docker call from the fake docker's log.
type loggedCall struct {
	Args []string
	Env  map[string]string
}

func loggedCalls(t *testing.T, log string) []loggedCall {
	t.Helper()
	f, err := os.Open(log)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	var out []loggedCall
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		var c loggedCall
		if err := json.Unmarshal(sc.Bytes(), &c); err != nil {
			t.Fatalf("log line %q: %v", sc.Text(), err)
		}
		out = append(out, c)
	}
	return out
}

// verbs returns the compose verb (or plain docker verb) of each call.
func verbs(cs [][]string) []string {
	var out []string
	for _, args := range cs {
		verb := args[0]
		if verb == "compose" {
			for i := 1; i < len(args); i++ {
				if a := args[i]; a == "-p" || a == "-f" || a == "--env-file" {
					i++
				} else if !strings.HasPrefix(a, "-") {
					verb = a
					break
				}
			}
		}
		out = append(out, verb)
	}
	return out
}

func TestStartCallsInOrder(t *testing.T) {
	log := fakeDocker(t)
	t.Setenv("FAKEDOCKER_SHOW", "DB_PORT,MEGOO_SERVICES_PROJECT")
	t.Setenv("FAKEDOCKER_CONFIG", `{"services":{"app":{"build":{}},"web":{"build":{},"image":"web:x"},"db":{"image":"postgres"}}}`)
	dir := t.TempDir()
	f, set := testSet(t)
	var stderr strings.Builder

	rec, vars, err := start(context.Background(), dir, f, set, &stderr)
	if err != nil {
		t.Fatalf("start: %v (stderr %q)", err, stderr.String())
	}
	p := ProjectName(f.Dir, "test")
	envFile := filepath.Join(dir, p+".env")
	base := []string{"compose", "-p", p, "--env-file", envFile, "-f", set.Compose[0]}
	got := loggedCalls(t, log)
	var args [][]string
	for _, c := range got {
		args = append(args, c.Args)
	}
	wantCalls(t, args, [][]string{
		append(slices.Clone(base), "config", "--format", "json"),
		append(slices.Clone(base), "up", "-d", "--build", "--wait", "--wait-timeout", "300"),
	})

	port := got[1].Env["DB_PORT"]
	if port == "" || port == "0" {
		t.Fatalf("up got DB_PORT %q", port)
	}
	if got[1].Env["MEGOO_SERVICES_PROJECT"] != p {
		t.Errorf("up got MEGOO_SERVICES_PROJECT %q, want %q", got[1].Env["MEGOO_SERVICES_PROJECT"], p)
	}
	wantVars := []string{"DB_PORT=" + port, "DB_URL=pg://localhost:" + port + "/x", "MEGOO_SERVICES_PROJECT=" + p}
	if !slices.Equal(vars, wantVars) {
		t.Errorf("vars = %q, want %q", vars, wantVars)
	}

	env, err := os.ReadFile(envFile)
	if err != nil {
		t.Fatalf("env file: %v", err)
	}
	wantEnv := "DB_PORT='" + port + "'\nDB_URL='pg://localhost:" + port + "/x'\nMEGOO_SERVICES_PROJECT='" + p + "'\n"
	if string(env) != wantEnv {
		t.Errorf("env file = %q, want %q", env, wantEnv)
	}

	onDisk, err := readRecord(filepath.Join(dir, p+".json"))
	if err != nil {
		t.Fatalf("record: %v", err)
	}
	if want := []string{p + "-app", "web:x"}; !slices.Equal(onDisk.Built, want) {
		t.Errorf("record Built = %q, want %q", onDisk.Built, want)
	}
	if onDisk.Project != p || onDisk.Worktree != f.Dir || onDisk.Set != "test" || onDisk.EnvFile != envFile ||
		onDisk.PID != os.Getpid() || !slices.Equal(onDisk.Compose, set.Compose) || onDisk.Started.IsZero() {
		t.Errorf("record = %+v", onDisk)
	}
	if !slices.Equal(rec.Built, onDisk.Built) || rec.Project != p {
		t.Errorf("returned record = %+v, want the one on disk %+v", rec, onDisk)
	}
}

func TestStartRetriesATakenPort(t *testing.T) {
	log := fakeDocker(t)
	t.Setenv("FAKEDOCKER_PORT_TAKEN", "2")
	dir := t.TempDir()
	f, set := testSet(t)
	var stderr strings.Builder

	rec, _, err := start(context.Background(), dir, f, set, &stderr)
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	if n := strings.Count(strings.Join(verbs(calls(t, log)), " "), "up"); n != 3 {
		t.Errorf("up called %d times, want 3: %q", n, calls(t, log))
	}
	if !strings.Contains(stderr.String(), "port is already allocated") {
		t.Errorf("stderr %q does not show up's output", stderr.String())
	}
	if !exists(filepath.Join(dir, rec.Project+".json")) {
		t.Error("no record after a successful retry")
	}
}

func TestStartGivesUpAfterThreeTakenPorts(t *testing.T) {
	log := fakeDocker(t)
	t.Setenv("FAKEDOCKER_PORT_TAKEN", "3")
	dir := t.TempDir()
	f, set := testSet(t)
	var stderr strings.Builder

	if _, _, err := start(context.Background(), dir, f, set, &stderr); err == nil {
		t.Fatal("start succeeded with every port taken")
	}
	if n := strings.Count(strings.Join(verbs(calls(t, log)), " "), "up"); n != 3 {
		t.Errorf("up called %d times, want 3", n)
	}
	p := ProjectName(f.Dir, "test")
	if exists(filepath.Join(dir, p+".json")) || exists(filepath.Join(dir, p+".env")) {
		t.Error("record or env file left after a failed start")
	}
}

func TestStartFailureSavesLogsAndRemoves(t *testing.T) {
	log := fakeDocker(t)
	t.Setenv("FAKEDOCKER_FAIL", "up")
	dir := t.TempDir()
	f, set := testSet(t)
	var stderr strings.Builder

	if _, _, err := start(context.Background(), dir, f, set, &stderr); err == nil {
		t.Fatal("start succeeded with up failing")
	}
	p := ProjectName(f.Dir, "test")
	logPath := filepath.Join(dir, "logs", p+".log")
	data, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("log file: %v", err)
	}
	if !strings.Contains(string(data), "fake logs") {
		t.Errorf("log file = %q, want the containers' logs", data)
	}
	vs := verbs(calls(t, log))
	if !slices.Contains(vs, "down") {
		t.Errorf("no down call: %q", vs)
	}
	if i, j := slices.Index(vs, "logs"), slices.Index(vs, "down"); i < 0 || i > j {
		t.Errorf("logs must be saved before down: %q", vs)
	}
	if want := "--no-color --timestamps"; !strings.Contains(strings.Join(calls(t, log)[slices.Index(vs, "logs")], " "), "logs "+want) {
		t.Errorf("logs call = %q", calls(t, log)[slices.Index(vs, "logs")])
	}
	if exists(filepath.Join(dir, p+".json")) {
		t.Error("record left after a failed start")
	}
	if want := "megoocolab-runner services: logs saved to " + logPath; !strings.Contains(stderr.String(), want) {
		t.Errorf("stderr %q does not contain %q", stderr.String(), want)
	}
	if !strings.Contains(stderr.String(), "fakedocker: up failed") {
		t.Errorf("stderr %q does not show up's output", stderr.String())
	}
}

func TestStartFailureBeforeUpStartsNothing(t *testing.T) {
	log := fakeDocker(t)
	t.Setenv("FAKEDOCKER_FAIL", "config")
	dir := t.TempDir()
	f, set := testSet(t)

	if _, _, err := start(context.Background(), dir, f, set, &strings.Builder{}); err == nil {
		t.Fatal("start succeeded with config failing")
	}
	if vs := verbs(calls(t, log)); !slices.Equal(vs, []string{"config"}) {
		t.Errorf("docker calls %q, want only config", vs)
	}
	p := ProjectName(f.Dir, "test")
	if exists(filepath.Join(dir, p+".json")) || exists(filepath.Join(dir, p+".env")) {
		t.Error("record or env file left after a failed start")
	}
}

func TestStartRefusesASingleQuote(t *testing.T) {
	log := fakeDocker(t)
	dir := t.TempDir()
	f, set := testSet(t)
	set.Env = map[string]string{"PASSWORD": "it's"}

	_, _, err := start(context.Background(), dir, f, set, &strings.Builder{})
	if want := "services.test.env.PASSWORD: a value cannot contain a single quote"; err == nil || err.Error() != want {
		t.Errorf("start error = %v, want %q", err, want)
	}
	if got := calls(t, log); len(got) != 0 {
		t.Errorf("docker called: %q", got)
	}
	if p := ProjectName(f.Dir, "test"); exists(filepath.Join(dir, p+".json")) {
		t.Error("record left after a refused start")
	}
}

func TestStartRefusesWhenBusy(t *testing.T) {
	log := fakeDocker(t)
	dir := t.TempDir()
	f, set := testSet(t)
	if err := Claim(dir, testRecord(t, f.Dir, "test", os.Getpid())); err != nil {
		t.Fatal(err)
	}

	if _, _, err := start(context.Background(), dir, f, set, &strings.Builder{}); !errors.Is(err, ErrBusy) {
		t.Errorf("start error = %v, want ErrBusy", err)
	}
	if got := calls(t, log); len(got) != 0 {
		t.Errorf("docker called: %q", got)
	}
}

func TestCheckReportsMissingAndStoppedDocker(t *testing.T) {
	fakeDocker(t)
	if err := Check(context.Background()); err != nil {
		t.Errorf("Check with docker: %v", err)
	}

	t.Setenv("FAKEDOCKER_FAIL", "version")
	if err := Check(context.Background()); err == nil || err.Error() != "Docker Compose is not available" {
		t.Errorf("Check without compose = %v", err)
	}

	t.Setenv("FAKEDOCKER_FAIL", "info")
	if err := Check(context.Background()); err == nil || err.Error() != "Docker is not running" {
		t.Errorf("Check with docker stopped = %v", err)
	}

	t.Setenv("PATH", t.TempDir())
	if err := Check(context.Background()); err == nil || err.Error() != "Docker is not installed (docker not found on PATH)" {
		t.Errorf("Check without docker = %v", err)
	}
}
