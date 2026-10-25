package cmd

import "strings"

// Windows has no per-user service in kardianos/service, so the runner is
// registered as a per-user scheduled task that starts at logon. These helpers
// are platform independent so they can be tested everywhere.

func taskCreateArgs(exe string) []string {
	return []string{
		"/Create", "/SC", "ONLOGON", "/RL", "LIMITED", "/TN", serviceName,
		"/TR", `"` + exe + `" run --background`, "/F",
	}
}

func taskArgs(verb string) []string { return []string{verb, "/TN", serviceName} }

// parseTaskStatus reads the "Status:" line of `schtasks /Query /FO LIST /V`.
func parseTaskStatus(out string) string {
	for _, line := range strings.Split(out, "\n") {
		k, v, ok := strings.Cut(line, ":")
		if ok && strings.TrimSpace(k) == "Status" {
			if strings.EqualFold(strings.TrimSpace(v), "Running") {
				return "running"
			}
			return "stopped"
		}
	}
	return "stopped"
}
