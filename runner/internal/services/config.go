// Package services gives every worktree its own test services: the Docker
// Compose sets a repository declares in megoocolab.toml, started on free ports
// for one check and removed when it ends.
package services

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strings"
	"unicode/utf8"

	toml "github.com/pelletier/go-toml/v2"
)

// FileName is the file a repository declares its service sets in.
const FileName = "megoocolab.toml"

// Set is one service set: the Compose files to start and the variables the
// check gets.
type Set struct {
	Name        string
	Description string
	Compose     []string          // absolute, cleaned paths, in file order
	Ports       []string          // variable names, in file order
	Env         map[string]string // values as written, before ${...} expansion
}

// File is a loaded and checked megoocolab.toml.
type File struct {
	Path string // absolute path of megoocolab.toml
	Dir  string // Canonical(its folder): the worktree
	Sets map[string]Set
}

// Names returns the set names, sorted.
func (f *File) Names() []string {
	names := make([]string, 0, len(f.Sets))
	for name := range f.Sets {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// ErrNoFile is returned (wrapped) by Find when no folder holds the file.
var ErrNoFile = errors.New("no megoocolab.toml in this folder or any parent")

const (
	maxDescription = 200
	maxSetName     = 20
	reservedPrefix = "MEGOO_SERVICES_"
)

var (
	setNameRe = regexp.MustCompile(`^[a-z][a-z0-9]*(-[a-z0-9]+)*$`)
	varNameRe = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)
)

// validSetName reports whether name may name a set. Hyphens only join
// letters and digits, so ProjectName always gives a name IsOurs accepts.
func validSetName(name string) bool {
	return len(name) <= maxSetName && setNameRe.MatchString(name)
}

type setDoc struct {
	Description string            `toml:"description"`
	Compose     []string          `toml:"compose"`
	Ports       []string          `toml:"ports"`
	Env         map[string]string `toml:"env"`
}

type fileDoc struct {
	Services map[string]setDoc `toml:"services"`
}

// Find looks for megoocolab.toml in start, then in each parent folder, and
// returns its path.
func Find(start string) (string, error) {
	dir, err := filepath.Abs(start)
	if err != nil {
		return "", err
	}
	for {
		path := filepath.Join(dir, FileName)
		if info, err := os.Stat(path); err == nil && !info.IsDir() {
			return path, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", fmt.Errorf("%s: %w", start, ErrNoFile)
		}
		dir = parent
	}
}

// Load reads and checks the file at path. Every error is one line naming the
// file and the key at fault.
func Load(path string) (*File, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return nil, err
	}
	r, err := os.Open(abs)
	if err != nil {
		return nil, err
	}
	defer r.Close()

	var doc fileDoc
	if err := toml.NewDecoder(r).DisallowUnknownFields().Decode(&doc); err != nil {
		return nil, fmt.Errorf("%s: %s", abs, decodeProblem(err))
	}

	folder := filepath.Dir(abs)
	f := &File{Path: abs, Dir: Canonical(folder), Sets: map[string]Set{}}
	names := make([]string, 0, len(doc.Services))
	for name := range doc.Services {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		set, err := checkSet(folder, name, doc.Services[name])
		if err != nil {
			return nil, fmt.Errorf("%s: %w", abs, err)
		}
		f.Sets[name] = set
	}
	return f, nil
}

// decodeProblem turns a TOML decoding error into one line.
func decodeProblem(err error) string {
	var strict *toml.StrictMissingError
	if errors.As(err, &strict) && len(strict.Errors) > 0 {
		return strings.Join(strict.Errors[0].Key(), ".") + ": unknown key"
	}
	var decode *toml.DecodeError
	if errors.As(err, &decode) {
		line, _ := decode.Position()
		return fmt.Sprintf("line %d: %s", line, oneLine(strings.TrimPrefix(decode.Error(), "toml: ")))
	}
	return oneLine(err.Error())
}

func oneLine(s string) string {
	return strings.Join(strings.Fields(s), " ")
}

func checkSet(folder, name string, doc setDoc) (Set, error) {
	key := "services." + name
	fail := func(field, format string, args ...any) (Set, error) {
		if field != "" {
			field = "." + field
		}
		return Set{}, fmt.Errorf("%s%s: %s", key, field, fmt.Sprintf(format, args...))
	}
	if !validSetName(name) {
		return fail("", "a set name is up to 20 lowercase letters, digits and single hyphens between them, starting with a letter")
	}

	if strings.ContainsAny(doc.Description, "\r\n") {
		return fail("description", "must be one line")
	}
	if utf8.RuneCountInString(doc.Description) > maxDescription {
		return fail("description", "longer than %d characters", maxDescription)
	}

	if doc.Compose == nil {
		return fail("compose", "required")
	}
	if len(doc.Compose) == 0 {
		return fail("compose", "must list at least one Compose file")
	}
	compose := make([]string, 0, len(doc.Compose))
	for _, c := range doc.Compose {
		if filepath.IsAbs(c) || filepath.VolumeName(c) != "" || strings.HasPrefix(c, "/") {
			return fail("compose", "%q must be relative to the file's folder", c)
		}
		p := filepath.Join(folder, filepath.FromSlash(c))
		rel, err := filepath.Rel(folder, p)
		if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return fail("compose", "%q is outside the file's folder", c)
		}
		info, err := os.Stat(p)
		if err != nil {
			return fail("compose", "%q does not exist", c)
		}
		if info.IsDir() {
			return fail("compose", "%q is a folder, not a file", c)
		}
		compose = append(compose, p)
	}

	for i, port := range doc.Ports {
		if problem := varProblem(port); problem != "" {
			return fail("ports", "%s", problem)
		}
		if slices.Contains(doc.Ports[:i], port) {
			return fail("ports", "%q is listed twice", port)
		}
	}

	envNames := make([]string, 0, len(doc.Env))
	for n := range doc.Env {
		envNames = append(envNames, n)
	}
	sort.Strings(envNames)
	for _, n := range envNames {
		if problem := varProblem(n); problem != "" {
			return fail("env", "%s", problem)
		}
		if slices.Contains(doc.Ports, n) {
			return fail("env", "%q is also a port", n)
		}
		if strings.ContainsAny(doc.Env[n], "\r\n") {
			return fail("env", "the value of %q must be one line", n)
		}
	}

	return Set{
		Name:        name,
		Description: doc.Description,
		Compose:     compose,
		Ports:       doc.Ports,
		Env:         doc.Env,
	}, nil
}

// varProblem says what is wrong with a variable name, or "" when it is fine.
func varProblem(name string) string {
	if !varNameRe.MatchString(name) {
		return fmt.Sprintf("%q is not a valid variable name", name)
	}
	if strings.HasPrefix(strings.ToUpper(name), reservedPrefix) {
		return fmt.Sprintf("%q is reserved", name)
	}
	return ""
}
