package services

import (
	"net"
	"strconv"
	"testing"
)

func TestPickPortsDistinctAndFree(t *testing.T) {
	ports, err := PickPorts(3)
	if err != nil {
		t.Fatalf("PickPorts: %v", err)
	}
	if len(ports) != 3 {
		t.Fatalf("PickPorts(3) = %v", ports)
	}
	seen := map[int]bool{}
	for _, port := range ports {
		if port <= 0 {
			t.Errorf("port %d is not > 0", port)
		}
		if seen[port] {
			t.Errorf("port %d picked twice in %v", port, ports)
		}
		seen[port] = true
		l, err := net.Listen("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(port)))
		if err != nil {
			t.Errorf("port %d is not free afterwards: %v", port, err)
			continue
		}
		l.Close()
	}
}
