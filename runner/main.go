package main

import "github.com/mmhy2003/megoocolab/runner/cmd"

// version is set at build time: -ldflags "-X main.version=1.2.3".
var version = "dev"

func main() {
	cmd.Execute(version)
}
