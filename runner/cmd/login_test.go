package cmd

import (
	"errors"
	"os"
	"strings"
	"testing"

	"github.com/mmhy2003/megoocolab/runner/internal/config"
)

func TestLoadLoginWrapsConfigErrors(t *testing.T) {
	orig := loadConfig
	t.Cleanup(func() { loadConfig = orig })

	loadConfig = func() (config.Config, error) { return config.Config{}, os.ErrNotExist }
	_, err := loadLogin()
	if !errors.Is(err, errNotLoggedIn) {
		t.Fatalf("loadLogin() error = %v, want errNotLoggedIn", err)
	}
	if want := "run: megoocolab-runner login --url URL --token TOKEN"; !strings.Contains(err.Error(), want) {
		t.Errorf("loadLogin() error = %q, want it to contain %q", err, want)
	}

	good := config.Config{URL: "https://colab.example", Token: "t"}
	loadConfig = func() (config.Config, error) { return good, nil }
	cfg, err := loadLogin()
	if err != nil || cfg != good {
		t.Errorf("loadLogin() = %+v, %v; want %+v, nil", cfg, err, good)
	}
}
