package services

import (
	"reflect"
	"strings"
	"testing"
)

func lookupFrom(m map[string]string) func(string) (string, bool) {
	return func(name string) (string, bool) {
		v, ok := m[name]
		return v, ok
	}
}

func TestExpand(t *testing.T) {
	lookup := lookupFrom(map[string]string{"A": "1", "B": "two"})
	for in, want := range map[string]string{
		"${A}":       "1",
		"x${A}y${B}": "x1ytwo",
		"plain text": "plain text",
		"cost $5":    "cost $5",
		"$":          "$",
		"a$b${A}":    "a$b1",
		"open ${A":   "open ${A",
	} {
		got, err := Expand(in, lookup)
		if err != nil {
			t.Errorf("Expand(%q): %v", in, err)
			continue
		}
		if got != want {
			t.Errorf("Expand(%q) = %q, want %q", in, got, want)
		}
	}

	if _, err := Expand("x${A}${C}", lookup); err == nil || !strings.Contains(err.Error(), "C") {
		t.Errorf("Expand(unknown C) error = %v, want one naming C", err)
	}
}

func TestVars(t *testing.T) {
	set := Set{
		Name:  "test",
		Ports: []string{"DB_PORT"},
		Env: map[string]string{
			"URL": "pg://localhost:${DB_PORT}/${MEGOO_SERVICES_PROJECT}",
			"K":   "${SECRET}",
		},
	}
	const p = "megoo-mc-52-test-3fa9c1d2"
	got, err := Vars(set, map[string]int{"DB_PORT": 5000}, p, lookupFrom(map[string]string{"SECRET": "s"}))
	if err != nil {
		t.Fatalf("Vars: %v", err)
	}
	want := []string{
		"DB_PORT=5000",
		"K=s",
		"MEGOO_SERVICES_PROJECT=" + p,
		"URL=pg://localhost:5000/" + p,
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("Vars = %q, want %q", got, want)
	}

	// Ports come before the environment: a process variable of the same name
	// does not win.
	got, err = Vars(set, map[string]int{"DB_PORT": 5000}, p, lookupFrom(map[string]string{"SECRET": "s", "DB_PORT": "1"}))
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Errorf("Vars with DB_PORT in the environment = %q, %v, want %q", got, err, want)
	}

	// A port without a picked number is an error, not DB_PORT=0.
	if _, err := Vars(Set{Name: "test", Ports: []string{"DB_PORT"}}, map[string]int{}, p, lookupFrom(nil)); err == nil || !strings.Contains(err.Error(), "DB_PORT") {
		t.Errorf("Vars without a port number: error = %v, want one naming DB_PORT", err)
	}

	// Another env key does not expand.
	set.Env = map[string]string{"A": "x", "B": "${A}"}
	_, err = Vars(set, map[string]int{"DB_PORT": 5000}, p, lookupFrom(nil))
	wantErr := "services.test.env.B: ${A} is not a port, MEGOO_SERVICES_PROJECT or a variable in the environment"
	if err == nil || err.Error() != wantErr {
		t.Errorf("Vars error = %v, want %q", err, wantErr)
	}
}
