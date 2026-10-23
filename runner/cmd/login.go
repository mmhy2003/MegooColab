package cmd

import (
	"fmt"
	"net/http"
	"time"

	"github.com/spf13/cobra"

	"github.com/mmhy2003/megoocolab/runner/internal/config"
)

func newLoginCmd() *cobra.Command {
	var url, token string
	c := &cobra.Command{
		Use:   "login --url URL --token TOKEN",
		Short: "Verify a MegooColab token and save it",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			base, err := config.NormalizeURL(url)
			if err != nil {
				return err
			}
			client := &http.Client{Timeout: 10 * time.Second}
			if err := verifyLogin(client, base, token); err != nil {
				return err
			}
			if err := config.Save(config.Config{URL: base, Token: token}); err != nil {
				return err
			}
			p, _ := config.Path()
			fmt.Fprintf(cmd.OutOrStdout(), "Logged in to %s. Saved %s\n", base, p)
			return nil
		},
	}
	c.Flags().StringVar(&url, "url", "", "MegooColab server URL")
	c.Flags().StringVar(&token, "token", "", "personal access token with the runner scope")
	_ = c.MarkFlagRequired("url")
	_ = c.MarkFlagRequired("token")
	return c
}

// verifyLogin checks the token against /api/auth/me and that it has the runner scope.
func verifyLogin(client *http.Client, base, token string) error {
	status, _, err := getBearer(client, base+"/api/auth/me", token)
	if err != nil {
		return fmt.Errorf("cannot reach %s: %w", base, err)
	}
	if status != http.StatusOK {
		return fmt.Errorf("the server rejected this token (HTTP %d); create a token with the runner scope in Settings", status)
	}
	scopes, err := tokenScopes(client, base, token)
	if err != nil {
		return err
	}
	if !hasScope(scopes, "runner") {
		return fmt.Errorf("this token has no runner scope (it has: %v); create a token with the runner scope", scopes)
	}
	return nil
}
