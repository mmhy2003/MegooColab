//go:build !windows

package cmd

func relaunchHiddenIfNeeded() (bool, error) { return false, nil }
