package protocol

import (
	"encoding/json"
	"reflect"
	"sort"
	"strings"
	"testing"
)

// Expected JSON keys per message, derived by reading backend/app/runner/protocol.py.
func TestWireFieldNames(t *testing.T) {
	errStr := "boom"
	cases := []struct {
		name string
		msg  any
		keys []string
	}{
		{"hello", NewHello("1", "linux", "amd64", []AgentAvailability{{AgentID: "a", Available: true}}),
			[]string{"agents", "arch", "capabilities", "os", "runner_version", "type"}},
		{"agent report", AgentAvailability{AgentID: "a", Problems: []string{}}, []string{"agent_id", "available", "problems"}},
		{"heartbeat", NewHeartbeat(), []string{"type"}},
		{"agent_status", NewAgentStatus("a", true, nil), []string{"agent_id", "available", "problems", "type"}},
		{"run_update", RunUpdate{Type: TypeRunUpdate, Data: map[string]any{}}, []string{"data", "kind", "run_id", "seq", "type"}},
		{"run_finished", RunFinished{Type: TypeRunFinished, Error: &errStr}, []string{"error", "outcome", "run_id", "summary", "type"}},
		{"run_finished no error", RunFinished{Type: TypeRunFinished}, []string{"outcome", "run_id", "summary", "type"}},
		{"run_finished v2", RunFinished{Type: TypeRunFinished, SessionID: new(string), GitBefore: &GitState{}, GitAfter: &GitState{}},
			[]string{"git_after", "git_before", "outcome", "run_id", "session_id", "summary", "type"}},
		{"git state", GitState{}, []string{"branch", "dirty", "head"}},
		{"welcome", Welcome{Type: TypeWelcome, Agents: []WelcomeAgent{{Bindings: []WelcomeBinding{{}}}}}, []string{"agents", "type", "user_id"}},
		{"welcome agent", WelcomeAgent{}, []string{"agent_id", "bindings", "max_concurrent_runs", "name", "program"}},
		{"welcome binding", WelcomeBinding{}, []string{"local_path", "project_key"}},
		{"run_start", RunStart{Type: TypeRunStart}, []string{"agent_id", "local_path", "policy", "prompt", "run_id", "task", "type"}},
		{"run task", RunTask{}, []string{"description_md", "key", "project_key", "title"}},
		{"run_cancel", RunCancel{Type: TypeRunCancel}, []string{"run_id", "type"}},
		{"config_changed", ConfigChanged{Type: TypeConfigChanged}, []string{"type"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			data, err := json.Marshal(c.msg)
			if err != nil {
				t.Fatal(err)
			}
			var m map[string]json.RawMessage
			if err := json.Unmarshal(data, &m); err != nil {
				t.Fatal(err)
			}
			got := make([]string, 0, len(m))
			for k := range m {
				got = append(got, k)
			}
			sort.Strings(got)
			if !reflect.DeepEqual(got, c.keys) {
				t.Fatalf("keys = %v, want %v", got, c.keys)
			}
			ptr := reflect.New(reflect.TypeOf(c.msg))
			if err := json.Unmarshal(data, ptr.Interface()); err != nil {
				t.Fatal(err)
			}
			again, _ := json.Marshal(ptr.Elem().Interface())
			if string(again) != string(data) {
				t.Fatalf("round trip changed JSON:\n%s\n%s", data, again)
			}
		})
	}
}

func TestListsNeverNull(t *testing.T) {
	data, _ := json.Marshal(NewHello("1", "linux", "amd64", nil))
	if string(data) != `{"type":"hello","runner_version":"1","os":"linux","arch":"amd64","agents":[],"capabilities":["workflow/1","branch/1"]}` {
		t.Fatalf("hello = %s", data)
	}
	data, _ = json.Marshal(NewHello("1", "l", "a", []AgentAvailability{{AgentID: "x"}}))
	if !strings.Contains(string(data), `"problems":[]`) {
		t.Fatalf("hello = %s, want empty problems list", data)
	}
}

func TestEnvelope(t *testing.T) {
	env, err := Decode([]byte(`{"type":"run_cancel","run_id":"r1"}`))
	if err != nil || env.Type != TypeRunCancel {
		t.Fatalf("decode: %v %+v", err, env)
	}
	var rc RunCancel
	if err := env.Into(&rc); err != nil || rc.RunID != "r1" {
		t.Fatalf("into: %v %+v", err, rc)
	}
	if _, err := Decode([]byte(`{"x":1}`)); err == nil {
		t.Fatal("want error for missing type")
	}
	if _, err := Decode([]byte(`nope`)); err == nil {
		t.Fatal("want error for bad json")
	}
}

func TestNewRunUpdateDefaultsDataToEmptyMap(t *testing.T) {
	data, _ := json.Marshal(NewRunUpdate("r1", 1, "message", nil))
	if string(data) != `{"type":"run_update","run_id":"r1","seq":1,"kind":"message","data":{}}` {
		t.Fatalf("run_update = %s", data)
	}
	data, _ = json.Marshal(NewRunUpdate("r1", 2, "message", map[string]any{"text": "hi"}))
	if !strings.Contains(string(data), `"data":{"text":"hi"}`) {
		t.Fatalf("run_update = %s", data)
	}
}
