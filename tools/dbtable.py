#!/usr/bin/env python3
"""Napoleon: Total War binary DB table reader/writer, round-trip exact (schema: tools/schemas/schema_nap.ron).

Layout (little endian): [FD FE FC FF, u16 char count, UTF-16LE GUID]? [FC FD FE FF, u32 version]? (no marker => v0),
u8 (=1), u32 row count, then rows of fields in schema order. Field types:
  Boolean u8 | I16 | I32 | I64 | F32 | StringU8 u16 byte count + bytes | StringU16 u16 char count + UTF-16LE |
  OptionalStringU8/U16 u8 flag (0 => None) then the string.
Table name = parent directory minus '_tables'. Schema is the RPFM schema_nap.ron (see its header note for licence).
TSV: header = field names; bool true/false; floats shortest float32 repr; None = \\N; \\t \\n \\r \\\\ escaped in strings.
"""
import argparse, os, re, struct, sys

SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas", "schema_nap.ron")
GUID_M, VER_M = b"\xfd\xfe\xfc\xff", b"\xfc\xfd\xfe\xff"
_schema = None


def schema():
    """{table_dir_name: {version: [(field, type)]}} by a line scan of the RON (indent-based; 'fields' only, not localised_fields)."""
    global _schema
    if _schema is None:
        _schema, tbl, ver, infields, name = {}, None, None, False, None
        rx = re.compile(r'^( +)(?:"(\w+)": \[|(version): (\d+),|(fields): \[|(localised_fields): |name: "([^"]*)",|field_type: (\w+),)')
        for ln in open(SCHEMA, encoding="utf-8"):
            m = rx.match(ln)
            if not m:
                continue
            ind = len(m.group(1))
            if ind == 8 and m.group(2):
                tbl = _schema.setdefault(m.group(2), {})
            elif ind == 16 and m.group(3):
                ver = int(m.group(4)); tbl[ver] = []
            elif ind == 16:
                infields = bool(m.group(5))
            elif ind == 24 and infields:
                if m.group(7) is not None:
                    name = m.group(7)
                elif m.group(8):
                    tbl[ver].append((name, m.group(8)))
    return _schema


def table_name(path):
    d = os.path.basename(os.path.dirname(os.path.abspath(path)))
    return d[:-7] if d.endswith("_tables") else d


def fields_for(table, ver):
    t = schema().get(table + "_tables")
    if t is None:
        raise KeyError(f"no schema for table '{table}'")
    if ver not in t:
        raise KeyError(f"no schema definition for '{table}' version {ver} (have {sorted(t)})")
    return t[ver]


def _rd_str(d, p, wide):
    (n,) = struct.unpack_from("<H", d, p)
    p += 2
    if wide:
        return d[p:p + 2 * n].decode("utf-16-le", "surrogatepass"), p + 2 * n
    return d[p:p + n].decode("latin-1"), p + n  # latin-1 keeps any byte sequence lossless


def _wr_str(s, wide):
    if wide:
        b = s.encode("utf-16-le", "surrogatepass")
        return struct.pack("<H", len(b) // 2) + b
    b = s.encode("latin-1")
    return struct.pack("<H", len(b)) + b


_FIXED = {"Boolean": ("<B", 1), "I16": ("<h", 2), "I32": ("<i", 4), "I64": ("<q", 8), "F32": ("<f", 4)}


def parse(d, table=None):
    """-> dict(guid, version, flag, fields, rows). rows = list of lists (bool/int/float/str/None)."""
    p, guid, ver = 0, None, 0
    if d[:4] == GUID_M:
        (n,) = struct.unpack_from("<H", d, 4)
        guid, p = d[6:6 + 2 * n].decode("utf-16-le"), 6 + 2 * n
    if d[p:p + 4] == VER_M:
        (ver,) = struct.unpack_from("<I", d, p + 4)
        p += 8
    flag = d[p]
    (n,) = struct.unpack_from("<I", d, p + 1)
    p += 5
    fields = fields_for(table, ver)
    rows = []
    for _ in range(n):
        row = []
        for _, t in fields:
            if t in _FIXED:
                f, sz = _FIXED[t]
                v = struct.unpack_from(f, d, p)[0]
                if t == "Boolean":
                    if v > 1:
                        raise ValueError(f"bad bool {v} at {p}")
                    v = bool(v)
                p += sz
            elif t.startswith("Optional"):
                if d[p] > 1:
                    raise ValueError(f"bad optional flag at {p}")
                if d[p]:
                    v, p = _rd_str(d, p + 1, t.endswith("U16"))
                else:
                    v, p = None, p + 1
            elif t in ("StringU8", "StringU16"):
                v, p = _rd_str(d, p, t == "StringU16")
            else:
                raise ValueError(f"unsupported field type {t}")
            row.append(v)
        rows.append(row)
    if p != len(d):
        raise ValueError(f"{len(d) - p} trailing bytes (parsed to {p})")
    return dict(guid=guid, version=ver, flag=flag, fields=fields, rows=rows)


def build(t):
    out = []
    if t["guid"] is not None:
        g = t["guid"].encode("utf-16-le")
        out.append(GUID_M + struct.pack("<H", len(g) // 2) + g)
    if t["version"]:
        out.append(VER_M + struct.pack("<I", t["version"]))
    out.append(struct.pack("<BI", t["flag"], len(t["rows"])))
    types = [ty for _, ty in t["fields"]]
    for row in t["rows"]:
        for ty, v in zip(types, row):
            if ty in _FIXED:
                out.append(struct.pack(_FIXED[ty][0], v))
            elif ty.startswith("Optional"):
                out.append(b"\0" if v is None else b"\1" + _wr_str(v, ty.endswith("U16")))
            else:
                out.append(_wr_str(v, ty == "StringU16"))
    return b"".join(out)


def _esc(s):
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def _unesc(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            i += 1
            c = {"t": "\t", "n": "\n", "r": "\r"}.get(s[i], s[i])
        out.append(c)
        i += 1
    return "".join(out)


_fc = {}


def _f32s(v):
    k = struct.pack("<f", v)
    if k not in _fc:
        for p in range(0, 10):  # shortest decimal that round-trips as float32
            s = repr(round(v, p)) if v == v and abs(v) != float("inf") else repr(v)
            if struct.pack("<f", float(s)) == k:
                break
        else:
            s = "%.9g" % v
        _fc[k] = s
    return _fc[k]


def to_tsv(t):
    types = [ty for _, ty in t["fields"]]
    lines = ["\t".join(n for n, _ in t["fields"])]
    for row in t["rows"]:
        c = []
        for ty, v in zip(types, row):
            if v is None:
                c.append("\\N")
            elif ty == "Boolean":
                c.append("true" if v else "false")
            elif ty == "F32":
                c.append(_f32s(v))
            elif isinstance(v, str):
                c.append(_esc(v))
            else:
                c.append(str(v))
        lines.append("\t".join(c))
    return "\n".join(lines) + "\n"


def from_tsv(text, table, ver):
    fields = fields_for(table, ver)
    lines = [l for l in text.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    if lines[0].split("\t") != [n for n, _ in fields]:
        raise ValueError(f"TSV header does not match schema {table} v{ver}: {[n for n, _ in fields]}")
    rows = []
    for ln in lines[1:]:
        cells = ln.split("\t")
        if len(cells) != len(fields):
            raise ValueError(f"row has {len(cells)} cells, want {len(fields)}: {ln[:80]}")
        row = []
        for (n, ty), c in zip(fields, cells):
            if c == "\\N":
                if not ty.startswith("Optional"):
                    raise ValueError(f"\\N in non-optional field {n}")
                row.append(None)
            elif ty == "Boolean":
                row.append(c == "true")
            elif ty == "F32":
                row.append(float(c))
            elif ty in ("I16", "I32", "I64"):
                row.append(int(c))
            else:
                row.append(_unesc(c))
        rows.append(row)
    return dict(guid=None, version=ver, flag=1, fields=fields, rows=rows)


def load(path, table=None):
    return parse(open(path, "rb").read(), table or table_name(path))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("dump"); p.add_argument("file"); p.add_argument("--table")
    p = sub.add_parser("roundtrip"); p.add_argument("files", nargs="+")
    p = sub.add_parser("fromtsv"); p.add_argument("tsv"); p.add_argument("out")
    p.add_argument("--table", required=True); p.add_argument("--version", type=int, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "dump":
        sys.stdout.write(to_tsv(load(a.file, a.table)))
    elif a.cmd == "roundtrip":
        bad = 0
        for f in a.files:
            try:
                d = open(f, "rb").read()
                t = parse(d, table_name(f))
                ok, why = build(t) == d, "bytes differ"
                tag = f"v{t['version']}"
            except Exception as e:
                ok, why, tag = False, repr(e), ""
            bad += not ok
            print(("OK   " if ok else "FAIL ") + f + " " + tag + ("" if ok else " " + why))
        print(f"{len(a.files) - bad} ok, {bad} failed")
        sys.exit(1 if bad else 0)
    else:
        t = from_tsv(open(a.tsv, encoding="utf-8", newline="").read(), a.table, a.version)
        open(a.out, "wb").write(build(t))


if __name__ == "__main__":
    main()
