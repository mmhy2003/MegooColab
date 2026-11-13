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
		{"draft_done", DraftDone{Type: TypeDraftDone}, []string{"agent_id", "draft_id", "type"}},
		{"run_start draft", RunStart{Type: TypeRunStart, Draft: &RunDraft{ID: "d"}},
			[]string{"agent_id", "draft", "local_path", "policy", "prompt", "run_id", "task", "type"}},
		{"run draft", RunDraft{}, []string{"id"}},
		{"run secret", RunSecret{}, []string{"name", "value"}},
		{"run cron", RunCron{}, []string{"branch", "id"}},
		{"config_changed", ConfigChanged{Type: TypeConfigChanged}, []string{"type"}},
		{"run_steer", RunSteer{Type: TypeRunSteer}, []string{"message_id", "run_id", "text", "type"}},
		{"run_steer_result", NewRunSteerResult("r", "m", SteerInjected, ""), []string{"message_id", "outcome", "run_id", "type"}},
		{"run_steer_result error", NewRunSteerResult("r", "m", SteerFailed, "boom"), []string{"error", "message_id", "outcome", "run_id", "type"}},
		{"tools_push", ToolsPush{Type: TypeToolsPush, Programs: []string{}, Tools: []ToolPayload{}, TakeOver: []string{}},
			[]string{"programs", "push_id", "take_over", "tools", "type"}},
		{"tool payload mcp", ToolPayload{Mcp: &McpPayload{Headers: map[string]string{}, Args: []string{}, Env: map[string]string{}}},
			[]string{"kind", "mcp", "name", "read_only_safe", "rev", "tool_id"}},
		{"tool payload skill", ToolPayload{Files: []SkillFile{{}}}, []string{"files", "kind", "name", "read_only_safe", "rev", "tool_id"}},
		{"mcp payload", McpPayload{Transport: "http", URL: "u", Headers: map[string]string{}, Args: []string{}, Env: map[string]string{}},
			[]string{"args", "env", "headers", "transport", "url"}},
		{"skill file", SkillFile{}, []string{"content_b64", "path"}},
		{"tools_scan", ToolsScan{Type: TypeToolsScan}, []string{"scan_id", "type"}},
		{"tools_report", NewToolsReport("p", nil), []string{"push_id", "results", "type"}},
		{"tool result", ToolResult{ToolID: "t", Rev: 2}, []string{"detail", "kind", "name", "program", "rev", "status", "tool_id"}},
		{"tool result removed", ToolResult{}, []string{"detail", "kind", "name", "program", "status"}},
		{"tools_drift", NewToolsDrift(nil), []string{"items", "type"}},
		{"tool drift", ToolDrift{}, []string{"kind", "name", "program", "status"}},
		{"tools_found", NewToolsFound("s", nil), []string{"items", "scan_id", "type"}},
		{"found tool", FoundTool{Problem: "too large"}, []string{"kind", "name", "problem", "program"}},
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
	if string(data) != `{"type":"hello","runner_version":"1","os":"linux","arch":"amd64","agents":[],"capabilities":["workflow/1","branch/1","model/1","steer/1","tools/1","omp/1","images/1","drafts/1","secrets/1","crons/1","stagemodel/1"]}` {
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

func TestHelloAdvertisesSteer(t *testing.T) {
	h := NewHello("1", "linux", "amd64", nil)
	for _, c := range h.Capabilities {
		if c == "steer/1" {
			return
		}
	}
	t.Fatalf("capabilities = %v, want steer/1", h.Capabilities)
}

func TestHelloAdvertisesCrons(t *testing.T) {
	h := NewHello("1", "linux", "amd64", nil)
	for _, c := range h.Capabilities {
		if c == CapabilityCrons {
			return
		}
	}
	t.Fatalf("capabilities = %v, want crons/1", h.Capabilities)
}

func TestHelloAdvertisesSecrets(t *testing.T) {
	h := NewHello("1", "linux", "amd64", nil)
	for _, c := range h.Capabilities {
		if c == CapabilitySecrets {
			return
		}
	}
	t.Fatalf("capabilities = %v, want secrets/1", h.Capabilities)
}

func TestHelloAdvertisesDrafts(t *testing.T) {
	h := NewHello("1", "linux", "amd64", nil)
	for _, c := range h.Capabilities {
		if c == CapabilityDrafts {
			return
		}
	}
	t.Fatalf("capabilities = %v, want drafts/1", h.Capabilities)
}

func TestToolsPushRoundTrip(t *testing.T) {
	in := ToolsPush{Type: TypeToolsPush, PushID: "p1", Programs: []string{"claude_code", "codex"}, TakeOver: []string{"ctx"},
		Tools: []ToolPayload{
			{ToolID: "t1", Name: "ctx", Kind: "mcp", Rev: 3, ReadOnlySafe: true,
				Mcp: &McpPayload{Transport: "http", URL: "https://x/mcp", Headers: map[string]string{"X-Key": "s"}, Args: []string{}, Env: map[string]string{}}},
			{ToolID: "t2", Name: "ui", Kind: "skill", Rev: 1, Files: []SkillFile{{Path: "SKILL.md", ContentB64: "eA=="}}},
		}}
	data, _ := json.Marshal(in)
	env, err := Decode(data)
	if err != nil || env.Type != TypeToolsPush {
		t.Fatalf("decode: %v %q", err, env.Type)
	}
	var out ToolsPush
	if err := env.Into(&out); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(in, out) {
		t.Fatalf("round trip:\n%+v\n%+v", in, out)
	}
}

func TestHelloAdvertisesStageModel(t *testing.T) {
	h := NewHello("1", "linux", "amd64", nil)
	for _, c := range h.Capabilities {
		if c == "stagemodel/1" {
			return
		}
	}
	t.Fatalf("capabilities = %v, want stagemodel/1", h.Capabilities)
}

func TestRunStartDecodesModelChoice(t *testing.T) {
	var rs RunStart
	if err := json.Unmarshal([]byte(`{"type":"run_start","run_id":"r","model_choice":{"model":"","effort":"max"}}`), &rs); err != nil {
		t.Fatal(err)
	}
	if rs.ModelChoice == nil || rs.ModelChoice.Model != "" || rs.ModelChoice.Effort != "max" {
		t.Fatalf("model_choice = %+v", rs.ModelChoice)
	}
	var plain RunStart
	if err := json.Unmarshal([]byte(`{"type":"run_start","run_id":"r"}`), &plain); err != nil {
		t.Fatal(err)
	}
	if plain.ModelChoice != nil {
		t.Fatalf("no model_choice sent, got %+v", plain.ModelChoice)
	}
}
