#!/usr/bin/env python3
"""Napoleon/Empire PFH0 pack tool: list, extract, build.

Layout: 'PFH0', u32 type (0 boot,1 release,2 patch,3 mod,4 movie), u32 dep_count,
u32 dep_index_size, u32 file_count, u32 file_index_size, dep names (\\0-terminated),
file index (u32 size + \\0-terminated path, backslash separators), then file data in index order.
"""
import argparse, fnmatch, os, struct, sys

HDR = struct.Struct("<4s5I")


def read_index(path):
    with open(path, "rb") as f:
        magic, ptype, ndeps, dep_sz, nfiles, idx_sz = HDR.unpack(f.read(HDR.size))
        if magic != b"PFH0":
            raise ValueError(f"{path}: not PFH0 ({magic!r})")
        deps = [d.decode() for d in f.read(dep_sz).split(b"\0") if d]
        idx = f.read(idx_sz)
    entries, pos, off = [], 0, HDR.size + dep_sz + idx_sz
    for _ in range(nfiles):
        (size,) = struct.unpack_from("<I", idx, pos)
        end = idx.index(b"\0", pos + 4)
        entries.append((idx[pos + 4:end].decode("latin-1"), off, size))
        pos, off = end + 1, off + size
    if pos != idx_sz:
        raise ValueError(f"{path}: index parse ended at {pos}, expected {idx_sz}")
    return ptype, deps, entries


def extract(pack, out, pattern):
    _, _, entries = read_index(pack)
    n = 0
    with open(pack, "rb") as f:
        for name, off, size in entries:
            rel = name.replace("\\", "/")
            if not fnmatch.fnmatch(rel, pattern):
                continue
            dst = os.path.join(out, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            f.seek(off)
            with open(dst, "wb") as o:
                o.write(f.read(size))
            n += 1
    return n


def build(out, root, ptype=3):
    files = sorted(
        os.path.relpath(os.path.join(d, fn), root)
        for d, _, fns in os.walk(root) for fn in fns
    )
    idx = b"".join(
        struct.pack("<I", os.path.getsize(os.path.join(root, r))) + r.replace(os.sep, "\\").encode("latin-1") + b"\0"
        for r in files
    )
    with open(out, "wb") as o:
        o.write(HDR.pack(b"PFH0", ptype, 0, 0, len(files), len(idx)) + idx)
        for r in files:
            with open(os.path.join(root, r), "rb") as f:
                o.write(f.read())
    return len(files)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("pack"); p.add_argument("pattern", nargs="?", default="*")
    p = sub.add_parser("extract"); p.add_argument("pack"); p.add_argument("out"); p.add_argument("pattern", nargs="?", default="*")
    p = sub.add_parser("build"); p.add_argument("out"); p.add_argument("root"); p.add_argument("--type", type=int, default=3)
    a = ap.parse_args()
    if a.cmd == "list":
        ptype, deps, entries = read_index(a.pack)
        for name, _, size in entries:
            if fnmatch.fnmatch(name.replace("\\", "/"), a.pattern):
                print(f"{size:12d} {name}")
        print(f"# type={ptype} deps={deps} files={len(entries)}", file=sys.stderr)
    elif a.cmd == "extract":
        print(extract(a.pack, a.out, a.pattern), "files extracted")
    else:
        print(build(a.out, a.root, a.type), "files packed")


if __name__ == "__main__":
    main()
