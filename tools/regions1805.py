#!/usr/bin/env python3
"""Build and check the 1805 whole-world region polygons (outside the vanilla Europe theatre).

Inputs : data/world1805/factions.json, data/world1805/regions.json,
         work/geodata/ne_10m_admin_1_states_provinces.zip   (Natural Earth admin-1, public domain),
         work/city_lonlat.json                              (vanilla settlement lon/lat)
Outputs: work/world1805/regions_1805.geojson   one MultiPolygon per region (lon/lat, Full profile)
         work/world1805/preview.png            equirectangular 3600x1800, fill = owner primary colour

Selector language (regions.json "admin1" list, each entry selects NE admin-1 units):
  {"admin": "Peru"} | {"iso_a2": "AU"}        every unit of that country           (rank 1, fallback)
  + "box": [w,s,e,n]                          only units whose centroid lies in the box, half-open (rank 2)
  + "names": [..]                             only units with these names, ascii-folded (rank 3)
  + "codes": [..]                             adm1_code list, may stand alone      (rank 3)
  + "clip": {"boxes": [[w,s,e,n],..]}         geometric: only the part of the unit inside the boxes
Precedence: higher rank wins a unit.  Equal rank between a full_only child and its merge_into parent: child wins.
Equal rank between two other regions is an error, except clipped claims, which split the unit; the one
unclipped claim (if any) receives the remainder.  Full profile = every region; Lean = regions without
full_only, each absorbing the children whose merge_into points at it.

Run: .venv/bin/python tools/regions1805.py     (exit code 1 on any failed check)
"""
import json, math, os, pickle, re, sys, unicodedata
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
SHP = P("work/geodata/ne_10m_admin_1_states_provinces.zip")
FACT = P("data/world1805/factions.json")
REGS = P("data/world1805/regions.json")
CITY = P("work/city_lonlat.json")
OUT_DIR = P("work/world1805")
VANILLA_BOX = (-13.0, 34.0, 44.0, 64.0)          # lon_w, lat_s, lon_e, lat_n of the vanilla theatre
PREFIXES = ("ame_", "afr_", "mea_", "asi_", "eas_", "oce_")
TIERS = ("core", "interest", "periphery")
FTIERS = ("AI-M", "AI-m", "subsidiary", "rebel")
ERR, WARN = [], []


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def ring_has(x, y, ring):
    """Even-odd ray casting against one closed ring (list of (x, y))."""
    inside, n = False, len(ring)
    for i in range(n):
        x1, y1 = ring[i]; x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def poly_has(x, y, poly):
    """poly = (exterior_ring, [hole_rings]) ."""
    return ring_has(x, y, poly[0]) and not any(ring_has(x, y, h) for h in poly[1])


def geom_polys(g):
    return [g] if g.geom_type == "Polygon" else [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon"]


def point_in_geom(x, y, g):
    for p in geom_polys(g):
        if poly_has(x, y, (list(p.exterior.coords), [list(r.coords) for r in p.interiors])):
            return True
    return False


def hav_km(lo1, la1, lo2, la2):
    a = math.sin(math.radians(la2 - la1) / 2) ** 2 + math.cos(math.radians(la1)) * math.cos(math.radians(la2)) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def load_units():
    from shapely.geometry import shape
    import shapefile
    cache = P("work/world1805/units_cache.pkl")
    stamp = os.path.getmtime(SHP)
    if os.path.exists(cache):
        d = pickle.load(open(cache, "rb"))
        if d["stamp"] == stamp:
            from shapely import wkb
            for u in d["units"]:
                u["geom"] = wkb.loads(u.pop("wkb"))
            return d["units"]
    r = shapefile.Reader(SHP)
    units = []
    for s in r.iterShapeRecords():
        d = s.record.as_dict(); g = shape(s.shape.__geo_interface__)
        if not g.is_valid:
            g = g.buffer(0)
        c = g.centroid
        units.append(dict(code=d["adm1_code"], name=d["name"] or "", admin=d["admin"], iso=d["iso_a2"], lon=c.x, lat=c.y, geom=g))
    os.makedirs(OUT_DIR, exist_ok=True)
    pickle.dump(dict(stamp=stamp, units=[dict({k: v for k, v in u.items() if k != "geom"}, wkb=u["geom"].wkb) for u in units]), open(cache, "wb"))
    return units


def in_box(u, b):
    return b[0] <= u["lon"] < b[2] and b[1] <= u["lat"] < b[3]


def select(units, sel, rkey):
    """Return (rank, [units], clip_boxes|None) for one selector."""
    pool = units
    if "admin" in sel:
        pool = [u for u in pool if u["admin"] == sel["admin"]]
        if not pool: ERR.append(f"{rkey}: admin '{sel['admin']}' matches no unit")
    if "iso_a2" in sel:
        pool = [u for u in pool if u["iso"] == sel["iso_a2"]]
        if not pool: ERR.append(f"{rkey}: iso '{sel['iso_a2']}' matches no unit")
    rank = 1
    if "box" in sel:
        pool = [u for u in pool if in_box(u, sel["box"])]; rank = 2
        if not pool: ERR.append(f"{rkey}: box {sel['box']} on {sel.get('admin')} matches no unit")
    if "names" in sel:
        want = {norm(n): n for n in sel["names"]}
        got = defaultdict(list)
        for u in pool:
            if norm(u["name"]) in want: got[norm(u["name"])].append(u)
        for k, n in want.items():
            if k not in got: ERR.append(f"{rkey}: name '{n}' not found under {sel.get('admin') or sel.get('iso_a2')}")
        pool = [u for lst in got.values() for u in lst]; rank = 3
    if "codes" in sel:
        cs = set(sel["codes"]); pool = [u for u in (units if "admin" not in sel and "iso_a2" not in sel else pool) if u["code"] in cs]; rank = 3
    clip = sel.get("clip", {}).get("boxes") if "clip" in sel else None
    return rank, pool, clip


def resolve(units, regions):
    from shapely.geometry import box as sbox
    from shapely.ops import unary_union
    parent = {r["key"]: r.get("merge_into") for r in regions}
    def ancestors(k):
        out = []
        while parent.get(k): k = parent[k]; out.append(k)
        return out
    claims = defaultdict(list)                        # unit idx -> [(rank, region_key, clip_boxes)]
    idx = {id(u): i for i, u in enumerate(units)}
    for r in regions:
        for sel in r["admin1"]:
            rank, pool, clip = select(units, sel, r["key"])
            for u in pool: claims[idx[id(u)]].append((rank, r["key"], clip))
    pieces = defaultdict(list)                        # region -> [geom]
    owner_of = {}                                     # unit idx -> region (whole units only)
    multi = []
    for i, cl in claims.items():
        top = max(c[0] for c in cl)
        tc = [c for c in cl if c[0] == top]
        keys = {c[1] for c in tc}
        keys = {k for k in keys if not any(k in ancestors(o) for o in keys if o != k)}   # child beats its ancestor
        tc = [c for c in tc if c[1] in keys]
        u = units[i]
        whole = [c for c in tc if c[2] is None]
        clipped = [c for c in tc if c[2] is not None]
        if len({c[1] for c in whole}) > 1:
            ERR.append(f"unit {u['admin']}/{u['name']}: claimed by {sorted({c[1] for c in whole})} at rank {top}")
            continue
        if not clipped:
            if whole:
                pieces[whole[0][1]].append(u["geom"]); owner_of[i] = whole[0][1]
            continue
        rest = u["geom"]; multi.append(u)
        for _, k, bx in clipped:
            part = rest.intersection(unary_union([sbox(*b) for b in bx]))
            if not part.is_empty: pieces[k].append(part); rest = rest.difference(part)
        fallback = whole[0][1] if whole else None
        if fallback is None:                          # lower-rank unclipped claim takes the remainder
            low = sorted([c for c in cl if c[2] is None], key=lambda c: -c[0])
            fallback = low[0][1] if low else None
        if fallback and not rest.is_empty: pieces[fallback].append(rest)
        elif rest.area > 0.01: WARN.append(f"unit {u['admin']}/{u['name']}: clipped remainder {rest.area:.2f} deg2 unassigned")
        owner_of[i] = "|clipped|"
    geoms = {k: unary_union(v) for k, v in pieces.items()}
    return geoms, owner_of


def to_multi(g):
    from shapely.geometry import MultiPolygon
    ps = geom_polys(g)
    return MultiPolygon(ps)


def lean_key(k, regions_by):
    while regions_by[k].get("merge_into"): k = regions_by[k]["merge_into"]
    return k


def acceptable_unassigned(u):
    if u["admin"] == "Antarctica" or u["lat"] < -58.5: return True
    if VANILLA_BOX[0] <= u["lon"] <= VANILLA_BOX[2] and VANILLA_BOX[1] <= u["lat"] <= VANILLA_BOX[3]: return True
    if u["iso"] in ("NO", "SE", "FI") and u["name"] not in ("Svalbard", "Bouvet Island"): return True
    return False


def main():
    from shapely.geometry import Point, mapping
    factions = json.load(open(FACT))
    regions = [r for r in json.load(open(REGS)) if not r.get("split_of")]   # splits: vanilla areas, not admin-1 (world_regions)
    fby = {f["key"]: f for f in factions}; rby = {r["key"]: r for r in regions}
    vanilla = {f["key"] for f in factions if f.get("vanilla")}
    # ---- schema checks
    for f in factions:
        for k in ("key", "name", "culture_group", "religion", "government", "tier", "capital_region", "colour_primary", "colour_secondary", "playable_candidate", "notes", "confidence"):
            if k not in f: ERR.append(f"faction {f.get('key')}: missing {k}")
        if f["tier"] not in FTIERS: ERR.append(f"faction {f['key']}: bad tier {f['tier']}")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", f["key"]): ERR.append(f"faction key not snake_case ascii: {f['key']}")
        if f["colour_primary"] == f["colour_secondary"]: ERR.append(f"faction {f['key']}: primary == secondary colour")
    if len(fby) != len(factions): ERR.append("duplicate faction keys")
    if len(rby) != len(regions): ERR.append("duplicate region keys")
    for r in regions:
        for k in ("key", "name", "owner", "tier", "capital", "port", "admin1", "climate", "notes", "confidence"):
            if k not in r: ERR.append(f"region {r.get('key')}: missing {k}")
        if not r["key"].startswith(PREFIXES): ERR.append(f"region {r['key']}: bad prefix")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", r["key"]): ERR.append(f"region key not snake_case ascii: {r['key']}")
        if r["tier"] not in TIERS: ERR.append(f"region {r['key']}: bad tier")
        if r["owner"] not in fby: ERR.append(f"region {r['key']}: owner '{r['owner']}' not in factions.json")
        if r.get("full_only"):
            m = rby.get(r.get("merge_into"))
            if not m or m.get("full_only"): ERR.append(f"region {r['key']}: bad merge_into {r.get('merge_into')}")
            elif m["owner"] != r["owner"]: ERR.append(f"region {r['key']}: owner differs from merge_into {m['key']}")
    owned = defaultdict(list)
    for r in regions: owned[r["owner"]].append(r["key"])
    for f in factions:
        if f.get("vanilla"): continue
        if f["key"] not in owned: ERR.append(f"faction {f['key']} owns no region")
        elif f["capital_region"] not in owned[f["key"]]: ERR.append(f"faction {f['key']}: capital_region {f['capital_region']} not owned by it")
        elif rby[f["capital_region"]].get("full_only"): ERR.append(f"faction {f['key']}: capital_region {f['capital_region']} is full_only (must exist in Lean)")
    # ---- geometry
    units = load_units()
    geoms, owner_of = resolve(units, regions)
    for r in regions:
        if r["key"] not in geoms or geoms[r["key"]].is_empty: ERR.append(f"region {r['key']}: no polygon")
    # capitals / ports
    for r in regions:
        g = geoms.get(r["key"])
        if g is None: continue
        c = r["capital"]
        if not point_in_geom(c["lon"], c["lat"], g):
            ERR.append(f"region {r['key']}: capital {c['name']} ({c['lon']},{c['lat']}) outside polygon, off by {Point(c['lon'], c['lat']).distance(g):.3f} deg")
        if r["port"]:
            d = Point(r["port"]["lon"], r["port"]["lat"]).distance(g)
            if d > 0.15: WARN.append(f"region {r['key']}: port {r['port']['name']} is {d:.2f} deg from its polygon")
    # overlaps between regions
    from shapely.strtree import STRtree
    keys = [k for k in geoms]; tree = STRtree([geoms[k] for k in keys])
    for i, k in enumerate(keys):
        for j in tree.query(geoms[k]):
            if j > i and geoms[k].intersection(geoms[keys[j]]).area > 1e-6:
                ERR.append(f"regions {k} and {keys[j]} overlap by {geoms[k].intersection(geoms[keys[j]]).area:.4f} deg2")
    # vanilla-settlement proximity
    city = json.load(open(CITY))
    for i, u in enumerate(units):
        if i in owner_of and owner_of[i] != "|clipped|":
            for cn, (lo, la) in city.items():
                if hav_km(u["lon"], u["lat"], lo, la) < 50:
                    WARN.append(f"unit {u['admin']}/{u['name']} (region {owner_of[i]}) centroid within 50 km of vanilla settlement {cn}")
    # unassigned report
    un = defaultdict(list); bad = defaultdict(list)
    for i, u in enumerate(units):
        if i not in owner_of:
            un[u["admin"]].append(u["name"] or "(blank)")
            if not acceptable_unassigned(u): bad[u["admin"]].append(f"{u['name'] or '(blank)'}({u['lon']:.1f},{u['lat']:.1f})")
    for a, lst in sorted(bad.items()): ERR.append(f"unassigned outside vanilla theatre: {a}: {'; '.join(lst)}")
    # ---- outputs
    os.makedirs(OUT_DIR, exist_ok=True)
    feats = []
    for r in regions:
        g = geoms.get(r["key"])
        if g is None: continue
        mg = to_multi(g)
        try:
            import shapely
            mg = to_multi(shapely.set_precision(mg, 0.0001))
        except Exception: pass
        props = {k: r[k] for k in ("key", "name", "owner", "tier", "climate", "confidence")}
        props.update(capital=r["capital"], port=r["port"], full_only=bool(r.get("full_only")), lean_key=lean_key(r["key"], rby),
                     impassable=bool(r.get("impassable")))
        feats.append(dict(type="Feature", properties=props, geometry=mapping(mg)))
    json.dump(dict(type="FeatureCollection", features=feats), open(P("work/world1805/regions_1805.geojson"), "w"), separators=(",", ":"))
    render(units, owner_of, geoms, regions, fby)
    # ---- report
    print(f"factions: {len(factions)} ({len(vanilla)} vanilla refs); by tier:", dict(sorted(defaultdict(int, {t: sum(1 for f in factions if f['tier'] == t and not f.get('vanilla')) for t in FTIERS}).items())),
          "| vanilla by tier:", {t: sum(1 for f in factions if f['tier'] == t and f.get('vanilla')) for t in FTIERS})
    lean = [r for r in regions if not r.get("full_only")]
    print(f"regions: Full {len(regions)}  Lean {len(lean)}")
    cont = {"ame_": "Americas+N.Atlantic", "afr_": "Africa", "mea_": "Middle East/Caucasus", "asi_": "Russia-east/Central+South Asia", "eas_": "East+SE Asia", "oce_": "Oceania"}
    for p, n in cont.items():
        sub = [r for r in regions if r["key"].startswith(p)]
        print(f"  {p:5s} {n:32s} full {len(sub):3d} lean {sum(1 for r in sub if not r.get('full_only')):3d} | " +
              " ".join(f"{t}:{sum(1 for r in sub if r['tier'] == t)}" for t in TIERS))
    print("  tiers (full):", {t: sum(1 for r in regions if r['tier'] == t) for t in TIERS}, "| impassable:", [r["key"] for r in regions if r.get("impassable")])
    print(f"units: {len(units)} total, {len(owner_of)} assigned, {len(units) - len(owner_of)} unassigned")
    print("unassigned admin-1 units by country (acceptable = vanilla theatre / Nordic / Antarctica unless listed as ERROR):")
    for a, lst in sorted(un.items()):
        print(f"  {a} [{len(lst)}]: " + "; ".join(lst[:6]) + (" ..." if len(lst) > 6 else ""))
    # colour distinctness
    pc = [(f["key"], f["colour_primary"]) for f in factions]
    close = [(a, b, round(math.dist(ca, cb), 1)) for i, (a, ca) in enumerate(pc) for b, cb in pc[i + 1:] if math.dist(ca, cb) < 45]
    for a, b, d in close: WARN.append(f"faction colours close: {a} / {b} (rgb distance {d})")
    for w in WARN[:60]: print("WARN", w)
    if len(WARN) > 60: print(f"WARN ... {len(WARN) - 60} more")
    for e in ERR: print("ERROR", e)
    print(f"checks: {len(ERR)} errors, {len(WARN)} warnings")
    return len(ERR)


def render(units, owner_of, geoms, regions, fby):
    from PIL import Image, ImageDraw
    W, H = 3600, 1800
    im = Image.new("RGB", (W, H), (176, 208, 232)); d = ImageDraw.Draw(im)
    X = lambda lo: (lo + 180) * W / 360
    Y = lambda la: (90 - la) * H / 180
    def draw(g, fill, outline):
        for p in sorted(geom_polys(g), key=lambda q: -q.area):
            d.polygon([(X(x), Y(y)) for x, y in p.exterior.coords], fill=fill, outline=outline)
    for i, u in enumerate(units):                       # unassigned first (grey; red when unacceptable)
        if i not in owner_of:
            draw(u["geom"], (235, 235, 235) if acceptable_unassigned(u) else (255, 0, 0), (170, 170, 170))
    rby = {r["key"]: r for r in regions}
    for k, g in sorted(geoms.items(), key=lambda kv: -kv[1].area):
        col = tuple(fby[rby[k]["owner"]]["colour_primary"])
        if rby[k].get("impassable"): col = tuple((c + 255) // 2 for c in col)
        draw(g, col, (40, 40, 40))
    for r in regions:
        x, y = X(r["capital"]["lon"]), Y(r["capital"]["lat"])
        d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(0, 0, 0), outline=(255, 255, 255), width=2)
    im.save(P("work/world1805/preview.png"))


def selftest():
    sq = ([(0, 0), (4, 0), (4, 4), (0, 4)], [[(1, 1), (2, 1), (2, 2), (1, 2)]])
    assert poly_has(3, 3, sq) and not poly_has(1.5, 1.5, sq) and not poly_has(5, 1, sq)
    assert norm("Kægalla") == "kgalla" and norm("Québec") == "quebec" and norm("Ōsaka") == "osaka"
    assert abs(hav_km(0, 0, 1, 0) - 111.19) < 0.3
    assert acceptable_unassigned(dict(admin="Antarctica", lat=-80, lon=0, iso="AQ", name="")) and not acceptable_unassigned(dict(admin="Peru", lat=-10, lon=-75, iso="PE", name="x"))


if __name__ == "__main__":
    selftest()
    sys.exit(1 if main() else 0)
