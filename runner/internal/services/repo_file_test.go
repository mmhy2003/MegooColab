package services

import (
	"reflect"
	"strings"
	"testing"
)

// TestRepositoryFileLoads checks this repository's own megoocolab.toml: it
// loads, declares the three sets, and every ${...} in it resolves.
func TestRepositoryFileLoads(t *testing.T) {
	f, err := Load("../../../megoocolab.toml")
	if err != nil {
		t.Fatal(err)
	}
	if got, want := f.Names(), []string{"e2e", "migrate", "test"}; !reflect.DeepEqual(got, want) {
		t.Errorf("Names() = %v, want %v", got, want)
	}
	if got, want := f.Sets["e2e"].Ports, []string{"HTTP_PORT", "HTTPS_PORT"}; !reflect.DeepEqual(got, want) {
		t.Errorf("e2e ports = %v, want %v", got, want)
	}

	for _, name := range f.Names() {
		set := f.Sets[name]
		ports := map[string]int{}
		for i, port := range set.Ports {
			ports[port] = 40000 + i
		}
		if _, err := Vars(set, ports, ProjectName(f.Dir, name), lookupFrom(nil)); err != nil {
			t.Errorf("Vars(%s): %v", name, err)
		}
	}

	section, err := PromptSection("../../..")
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"`test`", "`migrate`", "`e2e`"} {
		if !strings.Contains(section, name) {
			t.Errorf("PromptSection has no %s:\n%s", name, section)
		}
	}
}
