package gitstate

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

var (
	// maxFileBytes is the largest file whose content is hashed; maxTotalBytes
	// bounds the bytes hashed in one fingerprint. Vars so tests can lower them.
	maxFileBytes  int64 = 256 << 20
	maxTotalBytes int64 = 1 << 30
	// fingerprintTimeout is the deadline of a whole fingerprint. When it
	// expires the fingerprint fails: the after side then fails closed (see
	// CaptureAfter) and a before side that failed is handled by the caller.
	fingerprintTimeout = 60 * time.Second
)

// fpItem is one filesystem object under a status entry: the entry's own path
// (rel is ""), or a path found by walking a directory entry (a nested
// repository or submodule).
type fpItem struct {
	entry int
	rel   string
	path  string
	fi    os.FileInfo
	mark  string
}

// fingerprint is the working state: each status entry outside .megoocolab/
// with a mark for its current content. Sorted, so equal states give equal
// fingerprints.
//
// A regular file is marked with the SHA-256 of its content, streamed in Go with
// no filters and no git process: git's --stdin-paths mode C-unquotes names
// starting with a quote and splits names holding a newline, which made the
// whole fingerprint fail and blinded check R1. The values only have to compare
// equal between two snapshots, so they are not git object ids.
//
// A status entry that is a directory (a nested repository or a submodule) is
// walked, without following links, and its objects are marked the same way.
//
// Content is hashed smallest file first, so that a few huge files cannot use
// up the budget and leave small files unwatched. A file over maxFileBytes, or
// one that no longer fits in maxTotalBytes, is not hashed: it gets a stamp
// (see stampMark) instead. Everything that is not a regular file, a file that
// cannot be read and a file that changed while it was read get a stamp too, so
// that no entry can fail the whole fingerprint. Only the deadline can.
func fingerprint(dir string, entries []statusEntry) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), fingerprintTimeout)
	defer cancel()
	fail := func(err error) (string, error) { return "", fmt.Errorf("fingerprint: %w", err) }

	var items []*fpItem
	marks := make([]string, len(entries))
	isDir := make([]bool, len(entries))
	for i, e := range entries {
		if err := ctx.Err(); err != nil {
			return fail(err)
		}
		p := fsPath(filepath.Join(dir, filepath.FromSlash(e.path)))
		fi, err := os.Lstat(p)
		switch {
		case errors.Is(err, os.ErrNotExist):
			marks[i] = "deleted"
		case err != nil:
			marks[i] = "unreadable:" + errKind(err)
		case !isLink(fi) && fi.IsDir():
			isDir[i] = true
			if err := walkInto(ctx, &items, i, p); err != nil {
				return fail(err)
			}
		default:
			items = append(items, classify(&fpItem{entry: i, path: p, fi: fi}))
		}
	}

	var regular []*fpItem
	for _, it := range items {
		if it.mark == "" {
			regular = append(regular, it)
		}
	}
	sort.Slice(regular, func(a, b int) bool {
		if sa, sb := regular[a].fi.Size(), regular[b].fi.Size(); sa != sb {
			return sa < sb
		}
		return regular[a].path < regular[b].path
	})
	var total int64
	for _, it := range regular {
		if err := ctx.Err(); err != nil {
			return fail(err)
		}
		size := it.fi.Size()
		if size > maxFileBytes || total+size > maxTotalBytes {
			it.mark = stampMark("", it.fi)
			continue
		}
		mark, err := hashFile(ctx, it)
		if err != nil {
			return fail(err)
		}
		it.mark = mark
		total += size
	}

	sub := make([][]string, len(entries))
	for _, it := range items {
		if isDir[it.entry] {
			sub[it.entry] = append(sub[it.entry], it.rel+"="+it.mark)
		} else {
			marks[it.entry] = it.mark
		}
	}
	lines := make([]string, len(entries))
	for i, e := range entries {
		if isDir[i] {
			sort.Strings(sub[i])
			marks[i] = "dir{" + strings.Join(sub[i], ";") + "}"
		}
		lines[i] = e.raw + "\x00" + marks[i]
	}
	sort.Strings(lines)
	return strings.Join(lines, "\x00\x00"), nil
}

// walkInto adds every object below root (a directory status entry) to items.
// filepath.WalkDir does not follow links; each object is described with Lstat
// semantics.
func walkInto(ctx context.Context, items *[]*fpItem, entry int, root string) error {
	return filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if cerr := ctx.Err(); cerr != nil {
			return cerr
		}
		rel, _ := filepath.Rel(root, p)
		rel = filepath.ToSlash(rel)
		if err != nil {
			*items = append(*items, &fpItem{entry: entry, rel: rel, mark: "unreadable:" + errKind(err)})
			if d != nil && d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if p == root {
			return nil
		}
		fi, err := d.Info()
		if err != nil {
			*items = append(*items, &fpItem{entry: entry, rel: rel, mark: "unreadable:" + errKind(err)})
			return nil
		}
		if !isLink(fi) && fi.IsDir() {
			*items = append(*items, &fpItem{entry: entry, rel: rel, mark: "dir"})
			return nil
		}
		*items = append(*items, classify(&fpItem{entry: entry, rel: rel, path: p, fi: fi}))
		return nil
	})
}

// classify sets the mark of every object that is not a regular file; a regular
// file keeps an empty mark, to be hashed.
func classify(it *fpItem) *fpItem {
	fi := it.fi
	switch {
	case isLink(fi):
		if target, err := os.Readlink(it.path); err != nil {
			it.mark = stampMark("unreadable:"+errKind(err), fi)
		} else {
			it.mark = "link:" + target
		}
	case fi.IsDir():
		it.mark = "dir"
	case !fi.Mode().IsRegular():
		it.mark = stampMark("special:"+specialKind(fi.Mode()), fi)
	}
	return it
}

func specialKind(m os.FileMode) string {
	switch {
	case m&os.ModeNamedPipe != 0:
		return "fifo"
	case m&os.ModeSocket != 0:
		return "socket"
	case m&os.ModeCharDevice != 0:
		return "chardev"
	case m&os.ModeDevice != 0:
		return "device"
	}
	return "other"
}

// stampMark describes an object that was not hashed: its size and mtime and,
// where the platform has them (sysStamp), ctime, inode and device. An edit
// changes the size or the mtime, or the ctime, which cannot be set back from
// user space. kind, when given, prefixes the stamp.
func stampMark(kind string, fi os.FileInfo) string {
	s := fmt.Sprintf("size:%d:mtime:%d%s", fi.Size(), fi.ModTime().UnixNano(), sysStamp(fi))
	if kind != "" {
		return kind + ":" + s
	}
	return s
}

// ctxReader stops a copy when the deadline passes.
type ctxReader struct {
	ctx context.Context
	r   io.Reader
}

func (c ctxReader) Read(p []byte) (int, error) {
	if err := c.ctx.Err(); err != nil {
		return 0, err
	}
	return c.r.Read(p)
}

// hashFile streams a regular file through SHA-256. The file is opened without
// following a link and without blocking (a FIFO swapped in after the Lstat
// would otherwise hang the open), and the handle is checked to still be a
// regular file of the size the Lstat saw; if not, or if it shrinks while being
// read, the mark is changed-during-read plus a stamp. An error other than the
// deadline marks only this file.
func hashFile(ctx context.Context, it *fpItem) (string, error) {
	f, err := openNoFollow(it.path)
	if err != nil {
		return stampMark("unreadable:"+errKind(err), it.fi), nil
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return stampMark("unreadable:"+errKind(err), it.fi), nil
	}
	size := it.fi.Size()
	if !st.Mode().IsRegular() || st.Size() != size {
		return stampMark("changed-during-read", it.fi), nil
	}
	h := sha256.New()
	if _, err := io.CopyN(h, ctxReader{ctx, f}, size); err != nil {
		switch {
		case ctx.Err() != nil:
			return "", ctx.Err()
		case errors.Is(err, io.EOF):
			return stampMark("changed-during-read", it.fi), nil
		}
		return stampMark("unreadable:"+errKind(err), it.fi), nil
	}
	if st2, err := f.Stat(); err != nil || st2.Size() != size {
		return stampMark("changed-during-read", it.fi), nil
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func errKind(err error) string {
	switch {
	case errors.Is(err, os.ErrPermission):
		return "permission"
	case errors.Is(err, os.ErrNotExist):
		return "notexist"
	default:
		return "io"
	}
}
