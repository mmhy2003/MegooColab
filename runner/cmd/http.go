package cmd

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

func getBearer(client *http.Client, url, token string) (int, []byte, error) {
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return 0, nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	resp, err := client.Do(req)
	if err != nil {
		return 0, nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	return resp.StatusCode, body, err
}

// tokenScopes asks the server which scopes the presented token has.
func tokenScopes(client *http.Client, base, token string) ([]string, error) {
	status, body, err := getBearer(client, base+"/api/tokens/self", token)
	if err != nil {
		return nil, fmt.Errorf("could not reach %s: %w", base, err)
	}
	if status != http.StatusOK {
		return nil, fmt.Errorf("the server rejected this token (HTTP %d)", status)
	}
	var out struct {
		Scopes []string `json:"scopes"`
	}
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("unexpected response from %s/api/tokens/self: %w", base, err)
	}
	return out.Scopes, nil
}

func hasScope(scopes []string, want string) bool {
	for _, s := range scopes {
		if s == want {
			return true
		}
	}
	return false
}
