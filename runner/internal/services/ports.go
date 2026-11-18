package services

import (
	"errors"
	"net"
)

// PickPorts returns n distinct free TCP ports on 127.0.0.1. Tests may replace it.
var PickPorts = pickPorts

// pickPorts holds n listeners open at once, so the ports differ, then closes
// them and returns their ports.
func pickPorts(n int) ([]int, error) {
	listeners := make([]net.Listener, 0, n)
	defer func() {
		for _, l := range listeners {
			l.Close()
		}
	}()
	ports := make([]int, 0, n)
	for range n {
		l, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			return nil, errors.New("no free port on 127.0.0.1: " + err.Error())
		}
		listeners = append(listeners, l)
		ports = append(ports, l.Addr().(*net.TCPAddr).Port)
	}
	return ports, nil
}
