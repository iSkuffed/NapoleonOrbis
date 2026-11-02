package main

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"io"
	"os"
	"strings"
	"unicode/utf16"
)

// ---- PFH0 packs (little endian): 'PFH0', type, dep_count, dep_size, file_count, index_size,
// deps, index (u32 size + NUL-terminated backslash path per file), data in index order.

func u32(n int) []byte { return binary.LittleEndian.AppendUint32(nil, uint32(n)) }

// buildPack makes a one-file pack of the given type (2 = patch, 3 = mod).
func buildPack(ptype int, name string, data []byte) []byte {
	idx := append(append(u32(len(data)), name...), 0)
	var b bytes.Buffer
	b.WriteString("PFH0")
	for _, n := range []int{ptype, 0, 0, 1, len(idx)} {
		b.Write(u32(n))
	}
	b.Write(idx)
	b.Write(data)
	return b.Bytes()
}

// readPackFile returns one file's bytes from a pack; name is matched case-insensitively.
func readPackFile(pack, name string) ([]byte, error) {
	f, err := os.Open(pack)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	var h [24]byte
	if _, err := io.ReadFull(f, h[:]); err != nil || string(h[:4]) != "PFH0" {
		return nil, fmt.Errorf("%s: not a PFH0 pack", pack)
	}
	le := binary.LittleEndian
	nfiles, depSz, idxSz := int(le.Uint32(h[16:])), int64(le.Uint32(h[12:])), int(le.Uint32(h[20:]))
	idx := make([]byte, idxSz)
	if _, err := f.ReadAt(idx, 24+depSz); err != nil {
		return nil, fmt.Errorf("%s: truncated index", pack)
	}
	pos, off := 0, 24+depSz+int64(idxSz)
	for i := 0; i < nfiles; i++ {
		if pos+5 > len(idx) {
			return nil, fmt.Errorf("%s: bad index", pack)
		}
		size := int64(le.Uint32(idx[pos:]))
		end := bytes.IndexByte(idx[pos+4:], 0)
		if end < 0 {
			return nil, fmt.Errorf("%s: bad index", pack)
		}
		if strings.EqualFold(string(idx[pos+4:pos+4+end]), name) {
			data := make([]byte, size)
			if _, err := f.ReadAt(data, off); err != nil {
				return nil, fmt.Errorf("%s: truncated data for %s", pack, name)
			}
			return data, nil
		}
		pos, off = pos+4+end+1, off+size
	}
	return nil, fmt.Errorf("%s: no %s inside", pack, name)
}

// ---- LOC: u16 BOM, 'LOC\0', u32 version, u32 count, then {key, text: u16 len + UTF-16LE; u8 tooltip}.

type locRow struct {
	Key, Text string
	Tip       byte
}

var locMagic = []byte{0xff, 0xfe, 'L', 'O', 'C', 0}

func parseLoc(d []byte) (ver uint32, rows []locRow, err error) {
	if len(d) < 14 || !bytes.Equal(d[:6], locMagic) {
		return 0, nil, fmt.Errorf("not a LOC file")
	}
	le := binary.LittleEndian
	ver, n, pos := le.Uint32(d[6:]), int(le.Uint32(d[10:])), 14
	str := func() (string, bool) {
		if pos+2 > len(d) {
			return "", false
		}
		l := int(le.Uint16(d[pos:]))
		if pos+2+2*l > len(d) {
			return "", false
		}
		u := make([]uint16, l)
		for i := range u {
			u[i] = le.Uint16(d[pos+2+2*i:])
		}
		pos += 2 + 2*l
		return string(utf16.Decode(u)), true
	}
	for i := 0; i < n; i++ {
		k, ok1 := str()
		t, ok2 := str()
		if !ok1 || !ok2 || pos >= len(d) {
			return 0, nil, fmt.Errorf("LOC truncated at row %d", i)
		}
		rows = append(rows, locRow{k, t, d[pos]})
		pos++
	}
	if pos != len(d) {
		return 0, nil, fmt.Errorf("LOC: %d trailing bytes", len(d)-pos)
	}
	return ver, rows, nil
}

func buildLoc(ver uint32, rows []locRow) []byte {
	var b bytes.Buffer
	b.Write(locMagic)
	b.Write(u32(int(ver)))
	b.Write(u32(len(rows)))
	for _, r := range rows {
		for _, s := range []string{r.Key, r.Text} {
			u := utf16.Encode([]rune(s))
			b.Write(binary.LittleEndian.AppendUint16(nil, uint16(len(u))))
			for _, c := range u {
				b.Write(binary.LittleEndian.AppendUint16(nil, c))
			}
		}
		b.WriteByte(r.Tip)
	}
	return b.Bytes()
}

// unesc undoes \t \n \r \\ (any other escaped char stands for itself), like tools/loc.py.
func unesc(s string) string {
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c == '\\' && i+1 < len(s) {
			i++
			c = s[i]
			switch c {
			case 't':
				c = '\t'
			case 'n':
				c = '\n'
			case 'r':
				c = '\r'
			}
		}
		b.WriteByte(c)
	}
	return b.String()
}

func parseTSV(s string) ([]locRow, error) {
	s = strings.TrimPrefix(s, "\xef\xbb\xbf")
	lines := strings.Split(s, "\n")
	if strings.TrimSuffix(lines[0], "\r") != "key\ttext\ttooltip" {
		return nil, fmt.Errorf("loc rows: bad TSV header")
	}
	var rows []locRow
	seen := map[string]bool{}
	for i, ln := range lines[1:] {
		if ln = strings.TrimSuffix(ln, "\r"); ln == "" {
			continue
		}
		f := strings.Split(ln, "\t")
		if len(f) != 3 {
			return nil, fmt.Errorf("loc rows: line %d has %d fields", i+2, len(f))
		}
		k := unesc(f[0])
		if seen[k] {
			return nil, fmt.Errorf("loc rows: line %d repeats key %q", i+2, k)
		}
		seen[k] = true
		rows = append(rows, locRow{k, unesc(f[1]), map[bool]byte{true: 1}[f[2] == "true"]})
	}
	return rows, nil
}

// mergeLoc: same key -> ours replaces theirs in place; new keys appended in our order.
func mergeLoc(theirs, ours []locRow) []locRow {
	byKey := map[string]locRow{}
	for _, r := range ours {
		byKey[r.Key] = r
	}
	out := make([]locRow, 0, len(theirs)+len(ours))
	seen := map[string]bool{}
	for _, r := range theirs {
		if o, ok := byKey[r.Key]; ok {
			r = o
			seen[r.Key] = true
		}
		out = append(out, r)
	}
	for _, r := range ours {
		if !seen[r.Key] {
			seen[r.Key] = true
			out = append(out, r)
		}
	}
	return out
}

// ---- user.script.txt: the game reads only UTF-16LE with BOM; we also accept UTF-8/ASCII input.

func decodeScript(b []byte) []string {
	var s string
	switch {
	case bytes.HasPrefix(b, []byte{0xff, 0xfe}):
		u := make([]uint16, (len(b)-2)/2)
		for i := range u {
			u[i] = binary.LittleEndian.Uint16(b[2+2*i:])
		}
		s = string(utf16.Decode(u))
	default:
		s = strings.TrimPrefix(string(b), "\xef\xbb\xbf")
	}
	if s == "" {
		return nil
	}
	s = strings.ReplaceAll(s, "\r\n", "\n")
	return strings.Split(strings.TrimSuffix(s, "\n"), "\n")
}

func encodeScript(lines []string) []byte {
	var u []uint16
	u = append(u, 0xfeff)
	for _, l := range lines {
		u = append(u, utf16.Encode([]rune(l+"\r\n"))...)
	}
	b := make([]byte, 0, 2*len(u))
	for _, c := range u {
		b = binary.LittleEndian.AppendUint16(b, c)
	}
	return b
}

func hasLine(lines []string, l string) bool {
	for _, x := range lines {
		if strings.EqualFold(strings.TrimSpace(x), l) {
			return true
		}
	}
	return false
}

// addLines appends lines not already present; returns the new list and what was added.
func addLines(lines, add []string) (out, added []string) {
	out = lines
	for _, l := range add {
		if !hasLine(out, l) {
			out = append(out[:len(out):len(out)], l)
			added = append(added, l)
		}
	}
	return
}

func removeLines(lines, rm []string) []string {
	var out []string
	for _, x := range lines {
		if !hasLine(rm, strings.TrimSpace(x)) {
			out = append(out, x)
		}
	}
	return out
}
