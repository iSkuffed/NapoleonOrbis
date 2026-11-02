#!/usr/bin/env python3
"""ESF (ABCE) reader/writer for Empire/Napoleon: Total War, round-trip exact.

Header: u32 magic 0xABCE, u32 0, u32 timestamp, u32 offset of the record-name table.
Name table: u16 count, then u16 len + ascii per name.
Values: 1-byte type tag. Scalars 0x01-0x10 (sizes below), 0x0e utf16 / 0x0f ascii strings
(u16 char count). 0x41-0x50 = array of the matching scalar: u32 absolute end offset + raw bytes.
0x80 record: u16 name idx, u8 version, u32 end offset, children until end.
0x81 record array: u16 name idx, u8 version, u32 end offset, u32 count, then per item
u32 end offset + children.
"""
import struct, sys

SCALAR = {  # tag: (name, struct fmt)
    0x01: ("bool", "<?"), 0x02: ("i8", "<b"), 0x03: ("i16", "<h"), 0x04: ("i32", "<i"),
    0x05: ("i64", "<q"), 0x06: ("u8", "<B"), 0x07: ("u16", "<H"), 0x08: ("u32", "<I"),
    0x09: ("u64", "<Q"), 0x0a: ("f32", "<f"), 0x0b: ("f64", "<d"), 0x0c: ("xy", "<2f"),
    0x0d: ("xyz", "<3f"), 0x10: ("angle", "<H"),
}
TYPE_BY_NAME = {v[0]: k for k, v in SCALAR.items()} | {"utf16": 0x0e, "ascii": 0x0f}


class Rec:
    """0x80 record (items is None) or 0x81 record array (items = list of child lists)."""
    __slots__ = ("name", "version", "children", "items")

    def __init__(self, name, version=0, children=None, items=None):
        self.name, self.version, self.children, self.items = name, version, children or [], items

    def find(self, name):
        return next((c for c in self.children if isinstance(c, Rec) and c.name == name), None)

    def findall(self, name):
        return [c for c in self.children if isinstance(c, Rec) and c.name == name]



class Val:
    __slots__ = ("tag", "value")  # arrays keep raw bytes in value

    def __init__(self, tag, value):
        self.tag, self.value = tag, value


    def array(self):
        name, fmt = SCALAR[self.tag & 0x3f]
        n = struct.calcsize(fmt)
        cnt = (len(self.value) + n - 1) // n               # a ragged tail raises struct.error as before
        if len(self.value) % n:
            raise struct.error("unpack_from requires a buffer of at least %d bytes" % (cnt * n))
        if len(fmt) == 2:
            return list(struct.unpack(f"<{cnt}{fmt[1]}", self.value))
        return list(struct.iter_unpack(fmt, self.value))


class Esf:
    def __init__(self, root, timestamp=0, names=None):
        # names: original record-name table, kept so rewrites reproduce it exactly
        self.root, self.timestamp, self.names = root, timestamp, names or []


def load(path):
    with open(path, "rb") as f:
        return loads(f.read())


_ST = {t: struct.Struct(fmt) for t, (_, fmt) in SCALAR.items()}
_SZ = {t: st.size for t, st in _ST.items()}
_U16, _U32, _HBI = struct.Struct("<H"), struct.Struct("<I"), struct.Struct("<HBI")


def loads(b):
    magic, zero, ts, names_off = struct.unpack_from("<4I", b, 0)
    if magic != 0xABCE:
        raise ValueError(f"unsupported ESF magic {magic:#x}")
    (n,) = struct.unpack_from("<H", b, names_off)
    pos, names = names_off + 2, []
    for _ in range(n):
        (ln,) = struct.unpack_from("<H", b, pos)
        names.append(b[pos + 2:pos + 2 + ln].decode("ascii"))
        pos += 2 + ln
    if pos != len(b):
        raise ValueError(f"trailing {len(b) - pos} bytes after name table")
    u16, u32, hbi = _U16.unpack_from, _U32.unpack_from, _HBI.unpack_from
    st, sz = _ST, _SZ

    def node(pos):
        t = b[pos]; pos += 1
        if t in st:
            v = st[t].unpack_from(b, pos)
            return Val(t, v[0] if len(v) == 1 else v), pos + sz[t]
        if t in (0x0e, 0x0f):
            (ln,) = u16(b, pos)
            w = 2 if t == 0x0e else 1
            raw = b[pos + 2:pos + 2 + ln * w]
            return Val(t, raw.decode("utf-16-le" if w == 2 else "latin-1")), pos + 2 + ln * w
        if 0x41 <= t <= 0x50:
            (end,) = u32(b, pos)
            return Val(t, bytes(b[pos + 4:end])), end
        if t in (0x80, 0x81):
            ni, ver, end = hbi(b, pos)
            pos += 7
            if t == 0x80:
                kids, pos = seq(pos, end)
                return Rec(names[ni], ver, kids), pos
            (cnt,) = u32(b, pos); pos += 4
            items = []
            for _ in range(cnt):
                (iend,) = u32(b, pos)
                kids, pos = seq(pos + 4, iend)
                items.append(kids)
            if pos != end:
                raise ValueError(f"record array {names[ni]} ended at {pos}, expected {end}")
            return Rec(names[ni], ver, None, items), pos
        raise ValueError(f"unknown ESF tag {t:#x} at {pos - 1}")

    def seq(pos, end):
        out = []
        ap = out.append
        while pos < end:
            t = b[pos]
            if t in st:                                    # scalars inline: the bulk of every file
                v = st[t].unpack_from(b, pos + 1)
                ap(Val(t, v[0] if len(v) == 1 else v)); pos += 1 + sz[t]
            else:
                v, pos = node(pos)
                ap(v)
        if pos != end:
            raise ValueError(f"overran record end {end} (at {pos})")
        return out, pos

    root, end = node(16)
    if end != names_off:
        raise ValueError(f"root ended at {end}, name table at {names_off}")
    return Esf(root, ts, names)


def dumps(esf):
    names = list(esf.names)
    index = {nm: i for i, nm in enumerate(names)}

    def nid(name):
        if name not in index:
            index[name] = len(names); names.append(name)
        return index[name]

    out = bytearray(struct.pack("<4I", 0xABCE, 0, esf.timestamp, 0))

    def w(n):
        nonlocal out
        if isinstance(n, Val):
            t = n.tag; out.append(t)
            if t in SCALAR:
                fmt = SCALAR[t][1]
                out += struct.pack(fmt, *n.value) if isinstance(n.value, tuple) else struct.pack(fmt, n.value)
            elif t in (0x0e, 0x0f):
                raw = n.value.encode("utf-16-le" if t == 0x0e else "latin-1")
                out += struct.pack("<H", len(raw) // (2 if t == 0x0e else 1)) + raw
            else:
                out += struct.pack("<I", len(out) + 4 + len(n.value)) + n.value
            return
        out.append(0x80 if n.items is None else 0x81)
        out += struct.pack("<HB", nid(n.name), n.version)
        at = len(out); out += b"\0\0\0\0"
        if n.items is None:
            for c in n.children: w(c)
        else:
            out += struct.pack("<I", len(n.items))
            for it in n.items:
                iat = len(out); out += b"\0\0\0\0"
                for c in it: w(c)
                struct.pack_into("<I", out, iat, len(out))
        struct.pack_into("<I", out, at, len(out))

    w(esf.root)
    struct.pack_into("<I", out, 12, len(out))
    out += struct.pack("<H", len(names))
    for nm in names:
        out += struct.pack("<H", len(nm)) + nm.encode("ascii")
    return bytes(out)


def dump_tree(n, depth=0, max_items=3, max_depth=99, file=sys.stdout):
    pad = "  " * depth
    if isinstance(n, Val):
        name = SCALAR.get(n.tag, ("utf16" if n.tag == 0x0e else "ascii" if n.tag == 0x0f else None,))[0]
        if name is None:
            base = SCALAR[n.tag & 0x3f]
            cnt = len(n.value) // struct.calcsize(base[1])
            print(f"{pad}{base[0]}[{cnt}]", file=file)
        else:
            print(f"{pad}{name} {n.value!r}", file=file)
        return
    if depth >= max_depth:
        print(f"{pad}<{n.name} v{n.version}> ...", file=file); return
    if n.items is None:
        print(f"{pad}<{n.name} v{n.version}>", file=file)
        for c in n.children: dump_tree(c, depth + 1, max_items, max_depth, file)
    else:
        print(f"{pad}<{n.name} v{n.version} x{len(n.items)}>", file=file)
        for i, it in enumerate(n.items[:max_items]):
            print(f"{pad}  [{i}]", file=file)
            for c in it: dump_tree(c, depth + 2, max_items, max_depth, file)
        if len(n.items) > max_items:
            print(f"{pad}  ... {len(n.items) - max_items} more", file=file)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dump", "roundtrip"])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--items", type=int, default=3)
    ap.add_argument("--depth", type=int, default=99)
    a = ap.parse_args()
    for p in a.files:
        raw = open(p, "rb").read()
        e = loads(raw)
        if a.cmd == "dump":
            dump_tree(e.root, max_items=a.items, max_depth=a.depth)
        else:
            print("OK  " if dumps(e) == raw else "DIFF", p)
