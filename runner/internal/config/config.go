// Package config reads and writes the runner's connection settings.
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

// Config is the content of <user config dir>/megoocolab/runner.json.
type Config struct {
	URL   string `json:"url"`
	Token string `json:"token"`
}

// Path is where the config file lives.
func Path() (string, error) {
	dir, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "megoocolab", "runner.json"), nil
}

// NormalizeURL trims whitespace and trailing slashes and requires http or https.
func NormalizeURL(raw string) (string, error) {
	raw = strings.TrimRight(strings.TrimSpace(raw), "/")
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return "", fmt.Errorf("invalid server URL %q: must be http:// or https://host", raw)
	}
	return raw, nil
}

// Load reads the config. A missing file yields an error satisfying os.IsNotExist.
func Load() (Config, error) {
	p, err := Path()
	if err != nil {
		return Config{}, err
	}
	data, err := os.ReadFile(p)
	if err != nil {
		return Config{}, err
	}
	var c Config
	if err := json.Unmarshal(data, &c); err != nil {
		return Config{}, fmt.Errorf("parse %s: %w", p, err)
	}
	if c.Token == "" {
		return Config{}, errors.New("config has no token")
	}
	if c.URL, err = NormalizeURL(c.URL); err != nil {
		return Config{}, err
	}
	return c, nil
}

// Save writes the config with owner-only permissions.
func Save(c Config) error {
	var err error
	if c.URL, err = NormalizeURL(c.URL); err != nil {
		return err
	}
	if c.Token == "" {
		return errors.New("token is empty")
	}
	p, err := Path()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	if err := os.WriteFile(p, data, 0o600); err != nil {
		return err
	}
	return os.Chmod(p, 0o600) // WriteFile keeps the mode of a pre-existing file
}
