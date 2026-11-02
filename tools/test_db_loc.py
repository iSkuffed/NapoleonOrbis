#!/usr/bin/env python3
"""Self-check for dbtable.py / loc.py: .venv/bin/python tools/test_db_loc.py"""
import glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbtable, loc

# loc: synthetic round-trip incl. escapes and non-BMP char
rows = [("a_key", "Hello\tWorld\n\\ \U0001F600", 0), ("b_key", "", 1)]
raw = loc.build(rows)
assert loc.parse(raw) == (1, rows) and loc.build(loc.parse(raw)[1]) == raw
assert loc.from_tsv(loc.to_tsv(rows)) == rows

# db: synthetic table via TSV (regions v1 schema), then parse back
v = max(dbtable.schema()["regions_tables"])
f = dbtable.fields_for("regions", v)
tsv = "\t".join(n for n, _ in f) + "\n" + "\t".join(
    {"StringU8": "x\\ty", "StringU16": "x", "I32": "5", "I64": "5", "I16": "5", "Boolean": "true", "F32": "0.1",
     "OptionalStringU8": "\\N", "OptionalStringU16": "o"}[t] for _, t in f) + "\n"
t = dbtable.from_tsv(tsv, "regions", v)
raw = dbtable.build(t)
t2 = dbtable.parse(raw, "regions")
assert t2["rows"] == t["rows"] and dbtable.build(t2) == raw and dbtable.to_tsv(t2) == tsv

# vanilla files (skipped if not extracted)
fa = "work/vanilla/db/factions_tables/factions"
if os.path.exists(fa):
    t = dbtable.load(fa)
    assert t["version"] == 3 and t["fields"][0][0] == "key" and dbtable.build(t) == open(fa, "rb").read()
    assert any(r[0] == "austria" for r in t["rows"])
for p in glob.glob("work/vanilla_loc/text/*.loc")[:1]:
    d = open(p, "rb").read()
    assert loc.build(*reversed(loc.parse(d))) == d
print("ok")
