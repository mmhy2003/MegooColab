package mask

import (
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/protocol"
)

func TestBuildPutsTheLongestValueFirstAndSkipsShortOnes(t *testing.T) {
	s := Build("mgr_token", []protocol.RunSecret{{Name: "A", Value: "abcd"}, {Name: "B", Value: "abcdef"}, {Name: "C", Value: "xyz"}})
	if got := s.Replace("abcdef abcd xyz mgr_token"); got != "[B] [A] xyz [redacted]" {
		t.Fatalf("got %q", got)
	}
	if !Build("", nil).Empty() {
		t.Fatal("an empty set is not empty")
	}
}

func TestHeldBackIsTheLongestPrefixOfAnyValue(t *testing.T) {
	s := Build("", []protocol.RunSecret{{Name: "A", Value: "abcdef"}, {Name: "B", Value: "zzzzzzzz"}})
	for in, want := range map[string]int{"x abc": 3, "x zzzzz": 5, "x y": 0, "abcdef": 0} {
		if got := s.HeldBack(in); got != want {
			t.Errorf("HeldBack(%q) = %d, want %d", in, got, want)
		}
	}
}
