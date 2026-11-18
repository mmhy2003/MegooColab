package services

import (
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
)

// projectVar is the variable that holds the set's Compose project name.
const projectVar = "MEGOO_SERVICES_PROJECT"

// unknownVarError is returned by Expand for a ${NAME} the lookup lacks.
type unknownVarError struct{ name string }

func (e *unknownVarError) Error() string {
	return fmt.Sprintf("${%s} is not defined", e.name)
}

// Expand replaces each ${NAME} in s with its value from lookup. An unknown
// NAME is an error; a $ not followed by {...} is left as it is.
func Expand(s string, lookup func(string) (string, bool)) (string, error) {
	var b strings.Builder
	for {
		start := strings.Index(s, "${")
		if start < 0 {
			break
		}
		end := strings.IndexByte(s[start:], '}')
		if end < 0 {
			break
		}
		name := s[start+2 : start+end]
		value, ok := lookup(name)
		if !ok {
			return "", &unknownVarError{name: name}
		}
		b.WriteString(s[:start])
		b.WriteString(value)
		s = s[start+end+1:]
	}
	b.WriteString(s)
	return b.String(), nil
}

// Vars returns the variables a check of set gets, sorted NAME=VALUE: each
// port (ports must hold a number for every name in set.Ports), each env entry expanded, and MEGOO_SERVICES_PROJECT. An env value may
// name a port, MEGOO_SERVICES_PROJECT or a variable from lookup (the process
// environment), in that order, but not another env entry.
func Vars(set Set, ports map[string]int, project string, lookup func(string) (string, bool)) ([]string, error) {
	vars := make([]string, 0, len(set.Ports)+len(set.Env)+1)
	for _, name := range set.Ports {
		port, ok := ports[name]
		if !ok {
			return nil, fmt.Errorf("services.%s.ports: no port was picked for %s", set.Name, name)
		}
		vars = append(vars, name+"="+strconv.Itoa(port))
	}
	known := func(name string) (string, bool) {
		if port, ok := ports[name]; ok {
			return strconv.Itoa(port), true
		}
		if name == projectVar {
			return project, true
		}
		return lookup(name)
	}
	keys := make([]string, 0, len(set.Env))
	for key := range set.Env {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		value, err := Expand(set.Env[key], known)
		if unknown := (*unknownVarError)(nil); errors.As(err, &unknown) {
			return nil, fmt.Errorf("services.%s.env.%s: ${%s} is not a port, %s or a variable in the environment",
				set.Name, key, unknown.name, projectVar)
		} else if err != nil {
			return nil, fmt.Errorf("services.%s.env.%s: %w", set.Name, key, err)
		}
		vars = append(vars, key+"="+value)
	}
	vars = append(vars, projectVar+"="+project)
	sort.Strings(vars)
	return vars, nil
}
