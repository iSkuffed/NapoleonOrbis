#!/usr/bin/env python3
"""Napoleon: Total War localisation (.loc) reader/writer, round-trip exact.

Layout (little endian): u16 BOM 0xFEFF, 'LOC' + 0x00, u32 version (1), u32 count, then count entries of
  key  StringU16 (u16 char count + UTF-16LE), text StringU16, u8 tooltip flag (0/1).
TSV form: header `key<TAB>text<TAB>tooltip`; tab/newline/CR/backslash in text are escaped as \\t \\n \\r \\\\.
"""
import argparse, struct, sys

MAGIC = b"\xff\xfeLOC\x00"


def esc(s):
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def unesc(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            i += 1
            c = {"t": "\t", "n": "\n", "r": "\r"}.get(s[i], s[i])
        out.append(c)
        i += 1
    return "".join(out)


def parse(data):
    """-> (version, [(key, text, tooltip)])"""
    if data[:6] != MAGIC:
        raise ValueError(f"not a LOC file ({data[:6]!r})")
    ver, n = struct.unpack_from("<II", data, 6)
    pos, rows = 14, []
    for _ in range(n):
        s = []
        for _ in range(2):
            (l,) = struct.unpack_from("<H", data, pos)
            s.append(data[pos + 2:pos + 2 + 2 * l].decode("utf-16-le", "surrogatepass"))
            pos += 2 + 2 * l
        rows.append((s[0], s[1], data[pos]))
        pos += 1
    if pos != len(data):
        raise ValueError(f"{len(data) - pos} trailing bytes")
    return ver, rows


def build(rows, ver=1):
    out = [MAGIC, struct.pack("<II", ver, len(rows))]
    for k, t, tip in rows:
        for s in (k, t):
            out.append(struct.pack("<H", len(s.encode("utf-16-le", "surrogatepass")) // 2) + s.encode("utf-16-le", "surrogatepass"))
        out.append(bytes([tip]))
    return b"".join(out)


def to_tsv(rows):
    return "key\ttext\ttooltip\n" + "".join(f"{esc(k)}\t{esc(t)}\t{'true' if tip else 'false'}\n" for k, t, tip in rows)


def from_tsv(text):
    lines = text.split("\n")
    if lines[0] != "key\ttext\ttooltip":
        raise ValueError("bad TSV header")
    rows = []
    for ln in lines[1:]:
        if ln == "":
            continue
        k, t, tip = ln.split("\t")
        rows.append((unesc(k), unesc(t), 1 if tip == "true" else 0))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dump").add_argument("file")
    sub.add_parser("roundtrip").add_argument("files", nargs="+")
    p = sub.add_parser("fromtsv")
    p.add_argument("tsv"), p.add_argument("out")
    a = ap.parse_args(argv)
    if a.cmd == "dump":
        sys.stdout.write(to_tsv(parse(open(a.file, "rb").read())[1]))
    elif a.cmd == "roundtrip":
        bad = 0
        for f in a.files:
            d = open(f, "rb").read()
            try:
                ok = build(parse(d)[1], parse(d)[0]) == d
                why = "" if ok else "bytes differ"
            except Exception as e:
                ok, why = False, repr(e)
            bad += not ok
            print(("OK   " if ok else "FAIL ") + f + (" " + why if why else ""))
        print(f"{len(a.files) - bad} ok, {bad} failed")
        sys.exit(1 if bad else 0)
    else:
        rows = from_tsv(open(a.tsv, encoding="utf-8", newline="").read())
        open(a.out, "wb").write(build(rows))


if __name__ == "__main__":
    main()
