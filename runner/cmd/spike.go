package cmd

import (
	"fmt"
	"time"

	"github.com/spf13/cobra"

	"github.com/mmhy2003/megoocolab/runner/internal/spike"
)

func newSpikeCmd() *cobra.Command {
	var program string
	var keep bool
	var timeout time.Duration
	cmd := &cobra.Command{
		Use:   "spike",
		Short: "Check that the real agent adapter obeys the permission policies (R1)",
		Long: "Runs the real adapter in a temporary git repository under the read_only and workspace\n" +
			"policies with fixed prompts, then checks the disk and git (not the agent's words).\n" +
			"Uses your existing login for the agent; it never asks for credentials.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if program != "claude_code" && program != "codex" {
				return fmt.Errorf("--program must be claude_code or codex")
			}
			out := cmd.OutOrStdout()
			rep, err := spike.Run(cmd.Context(), spike.Options{Program: program, Keep: keep, Timeout: timeout, Out: out})
			if rep != nil && rep.Path != "" {
				fmt.Fprintln(out, "report:", rep.Path)
			}
			if err != nil {
				return err
			}
			if !rep.Passed() {
				return fmt.Errorf("spike failed: at least one check did not pass")
			}
			fmt.Fprintln(out, "spike passed")
			return nil
		},
	}
	cmd.Flags().StringVar(&program, "program", "", "claude_code or codex")
	cmd.Flags().BoolVar(&keep, "keep", false, "keep the temporary repositories and worktrees")
	cmd.Flags().DurationVar(&timeout, "timeout", 5*time.Minute, "time limit per run")
	_ = cmd.MarkFlagRequired("program")
	return cmd
}
