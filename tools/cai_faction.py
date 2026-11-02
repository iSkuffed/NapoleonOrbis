"""CAI faction generator (option 3) + the shared CAI belief / analyser helpers (moved here from land_probe_b).

clone_cai_faction() builds a complete, alive-shaped CAI faction for a new game faction from a template CAI faction
(land_probe_b: oldenburg's), with fresh CAI ids, so a new faction needs no dormant slot.  It can run N times: every
earlier generated faction is an ordinary faction to the next one.

CAI BDI component header, offsets from the CAI_BDI_COMPONENT_PROPERTY_SET index j (verified on vanilla):
  j+1 id; j+9 (owner, row in the owner's BLOCK_OWNS) pairs, the j+10 "A" pairs first then the j+11 "B" pairs;
  j+14 CAI_BDI_COMPONENT_BLOCK_OWNS rows [item, owner, f32, f32, type 0 / 1], the j+15 A rows first then the j+16
  B rows; j+12 / j+13 ancestors = dedup [o] + o.j12 (o.j13) over the owners linking x by a type 0 (1) row, j+17 / j+18
  descendants = dedup [y] + y.j17 (y.j18) over the items of the type 0 (1) rows: caches keyed by the row type, not by
  the A / B parts (exact as sets on both vanilla startposes; the game unlinks a deleted component by this rule, so a
  link cached in the wrong one dangles and the next save does not load, research/18); j+19 subjects, j+20
  referenced-by (kept symmetric).  Analysers (CAI_ANALYSER record, the body or in the item list): [0] owned list (=
  the rows, B only), [1] (key, belief) pairs.

  .venv/bin/python tools/cai_faction.py STARTPOS [BASE_STARTPOS]   header invariants of every generated CAI faction
      (CAI id above BASE's id counter) + global issue counts per kind against BASE (default work/world/probe5)
  .venv/bin/python tools/cai_faction.py fix IN OUT    fix_caches on a startpos or a save written before the fix
"""
import bisect, collections, copy, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import campaign_misc as cm
from esf import Rec, Val


BELIEF_SHARED = ('CAI_HISTORY', 'CAI_THEATRE_RELATIVE_MILITARY_STRENGTHS')
OWNS = 'CAI_BDI_COMPONENT_BLOCK_OWNS'


def cai_index(sp):
    """(by: component id -> (item list, j), parent: id(item list) -> container Rec) over CAI_INTERFACE."""
    by, parent = {}, {}

    def walk(r):
        for kids in ([r.children] if r.items is None else r.items):
            for j, c in enumerate(kids):
                if isinstance(c, Rec):
                    if c.name == 'CAI_BDI_COMPONENT_PROPERTY_SET' and j + 1 < len(kids) and isinstance(kids[j + 1], Val):
                        by[kids[j + 1].value] = (kids, j); parent[id(kids)] = r
                    walk(c)
    walk(cm.first_rec(sp.root, 'CAI_INTERFACE'))
    return by, parent


def cai_kind(by, x):
    return by[x][0][-1].name if x in by and isinstance(by[x][0][-1], Rec) else None


def cai_sub(k, n):
    return next(c for c in k if isinstance(c, Rec) and c.name == n)


def subst_ids(x, m):
    """Replace every u32 (0x08) / u32-array (0x48) value found in m, in place."""
    import world_zones as wz
    if isinstance(x, list):
        for c in x: subst_ids(c, m)
    elif isinstance(x, Rec):
        for kids in ([x.children] if x.items is None else x.items): subst_ids(kids, m)
    elif x.tag == 0x08 and x.value in m: x.value = m[x.value]
    elif x.tag == 0x48 and set(x.array()) & set(m):
        x.value = wz.u32a([m.get(v, v) for v in x.array()]).value


def keyed_analysers(by, covers, tkeys, skip=('CAI_BASIC_REGION_GROUP_ANALYSIS',)):
    """[(item list, j, CAI_ANALYSER, BLOCK_OWNS, template pairs)]: the analysers whose key set covers one of the id
    sets in covers, with their (key, belief) pairs keyed by an id in tkeys (beliefs of a kind in skip left out)."""
    out = []
    for x, (k, j) in by.items():
        a = next((c for c in k if isinstance(c, Rec) and c.name == 'CAI_ANALYSER'), None)
        if a is None or not (isinstance(a.children[1], Val) and a.children[1].tag == 0x48):
            continue
        p = a.children[1].array()
        keys = set(p[0::2])
        tp = [(y, b) for y, b in zip(p[0::2], p[1::2]) if y in tkeys and cai_kind(by, b) not in skip]
        if tp and any(keys >= c for c in covers):
            out.append((k, j, a, cai_sub(k, OWNS), tp))
    return out


def check_owners(by, ana):
    """Template sanity: each analyser's owned list = its BLOCK_OWNS rows = j+16, each template belief's j+9 =
    [owning analyser, row], one analyser per template belief."""
    tids = [b for *_, tp in ana for _, b in tp]
    assert len(tids) == len(set(tids)), 'one analyser per template belief'
    for k, j, a, abo, tp in ana:
        own = a.children[0].array()
        assert k[j + 16].value == len(own) == len(abo.items) and [r[0].value for r in abo.items] == own
        for _, b in tp:
            bk, bj = by[b]
            assert bk[bj + 9].array() == [k[j + 1].value, own.index(b)], (b, 'j+9 = [owning analyser, row]')
    return tids


def register_owned(k, j, a, abo, b, nb, c, cj, key=None):
    """Analyser (k, j, a, abo) owns clone nb (c, cj) of its belief b: owned list, BLOCK_OWNS row, clone j+9 =
    [analyser, row], j+16, j+18 (+ what the clone owns); key: also add the (key, nb) pair."""
    import world_zones as wz
    c[cj + 9] = wz.u32a([k[j + 1].value, len(abo.items)])
    row = copy.deepcopy(next(r for r in abo.items if r[0].value == b)); row[0].value = nb
    abo.items.append(row)
    a.children[0] = wz.u32a(a.children[0].array() + [nb])
    if key is not None:
        a.children[1] = wz.u32a(a.children[1].array() + [key, nb])
    k[j + 16].value = len(a.children[0].array())
    k[j + 18] = wz.u32a(k[j + 18].array() + [nb] + c[cj + 18].array())


def clone_beliefs(by, parent, ana, m, owns, keep, fix=None):
    """Clone every template belief of ana with ids substituted by m (m must map each template key and belief to its
    new id) into the template's pool, owned by the same analyser under the mapped key.  Each clone BLOCK_OWNS only
    ids in owns (j+16/j+18 follow), keeps only ids passing keep in its subjects (j+19) / referenced-by (j+20), body
    fixed by fix(kind, body children); then subjects <-> referenced-by made symmetric.  Returns {new id: (list, j)}."""
    import world_zones as wz
    clones = {}
    for k, j, a, abo, tp in ana:
        for y, b in tp:
            bk, bj = by[b]
            c = copy.deepcopy(bk); subst_ids(c, m)
            bo = cai_sub(c, OWNS)
            bo.items = [r for r in bo.items if r[0].value in owns]
            c[bj + 18] = wz.u32a([r[0].value for r in bo.items]); c[bj + 16].value = len(bo.items)
            for o in (19, 20):
                c[bj + o] = wz.u32a([x for x in c[bj + o].array() if keep(x)])
            if fix:
                fix(cai_kind(by, b), c[-1].children)
            assert parent[id(bk)].items is not None
            parent[id(bk)].items.append(c)
            clones[m[b]] = (c, bj)
            register_owned(k, j, a, abo, b, m[b], c, bj, m[y])
    by.update(clones)
    for nb, (c, cj) in clones.items():                 # subjects (j+19) <-> referenced-by (j+20)
        for s, o in [(s, 20) for s in c[cj + 19].array()] + [(r, 19) for r in c[cj + 20].array()]:
            k, j = by[s]
            if nb not in k[j + o].array():
                k[j + o] = wz.u32a(k[j + o].array() + [nb])
    return clones


# ---------------------------------------------------------------- option 3: clone_cai_faction
PS = 'CAI_BDI_COMPONENT_PROPERTY_SET'
# region-level / per-object CAI records: a reference to one that is neither the template faction's own (its WT records)
# nor a region record mapped onto the new faction's (rmap) is "foreign"; a non-structural component owning one or
# keyed by one (body[0]) is not cloned: those are perception beliefs the AI rebuilds (b2: a 179-component dormant
# manager owning three regions ran 3 AI turns)
FOREIGN_KINDS = frozenset((
    'CAI_RESOURCE_MOBILE', 'CAI_UNIT', 'CAI_CHARACTER', 'CAI_REGION', 'CAI_SETTLEMENT', 'CAI_BUILDING_SLOT',
    'CAI_REGION_SLOT', 'CAI_BASIC_REGION_GROUP_ANALYSIS', 'CAI_REGION_HLCI', 'CAI_REGION_BOUNDARY', 'CAI_TRADING_POST',
    'CAI_FORT', 'CAI_SEA_GRID_CELL', 'CAI_TRADE_ROUTE', 'CAI_TRADE_ROUTE_SEGMENT', 'CAI_TRANSITION_AREA'))
# faction-keyed sub-lists inside components (entry key = first CAI faction id in the entry other than the list owner's
# faction): True = every other faction keyed (the template <-> new pair is filled from the proxy's entry), False =
# mirrored only (a list holding the template gets the new faction)
FACTION_LISTS = {'CAI_DIPLOMATIC_ANALYSIS_FACTIONINFO': True, 'CAI_RELATION_ANALYSIS_TIMELINES': True,
                 'CAI_FACTION_TRADE_ANALYSIS_STATUS': False}
# outside records whose body u32 arrays list template records get the clones too (THEATRE: [1] every mobile; the
# diplomatic analyses: faction lists, e.g. the rebels' [4] war list = every faction)
SHARED_LISTS = ('THEATRE', 'CAI_DIPLOMATIC_ANALYSIS')


def u32a(a):
    return Val(0x48, struct.pack(f'<{len(a)}I', *a))


def dedup(seq):
    seen, out = set(), []
    for v in seq:
        if v not in seen:
            seen.add(v); out.append(v)
    return out


def is_handle(v):
    return 6e8 <= v < 9e8 and v % 4 == 0


def _kids_of(r):
    return [r.children] if r.items is None else r.items


class Cai:
    """Index of every CAI BDI component under CAI_INTERFACE: by (id -> (item list, j)), unit (id -> the component
    whose items entry holds it: itself, or e.g. the CAI_FACTION for its inner component; None for CAI_INTERFACE /
    CAI_WORLD themselves), cont (unit -> the Rec whose items hold it), mgr (id -> CAI faction of the
    CAI_INTERFACE_MANAGERS item it sits in, None = world level)."""

    def __init__(self, sp):
        self.sp = sp
        self.ci = cm.first_rec(sp.root, 'CAI_INTERFACE')
        self.w = cm.first_rec(sp.root, 'CAI_WORLD')
        self.central = cm.first_rec(sp.root, 'CAI_CENTRAL_BDI_POOL')
        self.managers = self.ci.find('CAI_INTERFACE_MANAGERS')
        self.by, self.unit, self.cont, self.mgr = {}, {}, {}, {}
        self._arr, self._arrn = {}, 0     # id(Val) -> (Val, its bytes, its array()): checks read the same arrays over and over
        self.add(self.ci)

    def add(self, root, unit=None, mgr=None):
        for kids in _kids_of(root):
            self.add_kids(kids, root, unit, kids[2].children[0].value if root is self.managers else mgr)

    def touch(self):
        """An in-place edit: forget the read-only indexes (_index / check_faction's lists) built over the old tree."""
        self.__dict__.pop('_idx', None); self.__dict__.pop('_fk', None)

    def add_kids(self, kids, root, unit, mgr):
        self.touch()
        u = unit
        for j, c in enumerate(kids):
            if isinstance(c, Rec) and c.name == PS and j + 1 < len(kids) and isinstance(kids[j + 1], Val):
                x = kids[j + 1].value
                assert x not in self.by, ('duplicate CAI id', x)
                if root.items is not None:
                    u = x; self.cont[x] = root
                self.by[x], self.unit[x], self.mgr[x] = (kids, j), u, mgr
        for c in kids:
            if isinstance(c, Rec):
                self.add(c, u, mgr)

    def h(self, x, o):
        k, j = self.by[x]
        return k[j + o]

    def seth(self, x, o, v):
        k, j = self.by[x]
        k[j + o] = v
        self.touch()

    def arr(self, x, o):
        v = self.h(x, o)
        c = self._arr.get(id(v))
        if c is None or c[0] is not v or c[1] is not v.value:      # a replaced Val / an edited value misses
            a = v.array()
            if self._arrn > 1000000: self._arr.clear(); self._arrn = 0     # bounded by elements: a check visits ~1M components
            c = self._arr[id(v)] = (v, v.value, a); self._arrn += len(a) + 1
        return list(c[2])

    def rows(self, x):
        bo = self.h(x, 14)
        assert isinstance(bo, Rec) and bo.name == OWNS, x
        return bo.items

    def kind(self, x):
        return cai_kind(self.by, x)

    def body(self, x):
        b = self.by[x][0][-1]
        return b.children if isinstance(b, Rec) and b.items is None else None

    def body0(self, x):
        """The CAI record x is keyed by (its first body field), or None.  A CAI_SEA_GRID_CELL's first field is its
        sea_grids.esf cell index, not a CAI id: on the 1122-cell world grid cells 774..776 matched oldenburg's CAI
        ids, got cloned as its world beliefs with the index remapped, and the game crashed at load (0x6A3110, the
        cell's game grid cell [+0xFC] NULL)."""
        b = self.body(x)
        if not b or not isinstance(b[0], Val) or b[0].tag != 0x08 or self.kind(x) == 'CAI_SEA_GRID_CELL':
            return None
        return b[0].value

    def ana(self, x):
        a = next((c for c in self.by[x][0] if isinstance(c, Rec) and c.name == 'CAI_ANALYSER'), None)
        return a if a is not None and isinstance(a.children[0], Val) and a.children[0].tag == 0x48 else None

    def structural(self, x):
        return self.ana(x) is not None or 'MANAGER' in (self.kind(x) or '')

    def factions(self):
        """{game FACTION handle (CAI_FACTION body[6]): CAI faction id}"""
        return {it[-1].children[6].value: it[2].value for it in self.w.find('CAI_WORLD_FACTIONS').items}

    def manager_item(self, f):
        return next(it for it in self.managers.items if it[2].children[0].value == f)

    def group_of(self, r, owner):
        return [g for g, (k, j) in self.by.items() if isinstance(k[-1], Rec) and k[-1].name == 'CAI_BASIC_REGION_GROUP_ANALYSIS'
                and r in k[-1].children[0].array() and k[-1].children[3].value == owner]


def _walk_kids(kids, fn):
    fn(kids)
    for c in kids:
        if isinstance(c, Rec):
            for k2 in _kids_of(c):
                _walk_kids(k2, fn)


def _components(items):
    """{id: (item list, j)} of the components under these item lists."""
    out = {}

    def f(kids):
        for j, c in enumerate(kids):
            if isinstance(c, Rec) and c.name == PS and j + 1 < len(kids) and isinstance(kids[j + 1], Val):
                out[kids[j + 1].value] = (kids, j)
    for it in items:
        _walk_kids(it, f)
    return out


def _body_vals(kids, fn, hdr):
    """fn(kids, index, Val, path) for every Val under the item list kids except header slots j+1..j+20 of a component
    (hdr: {id(kids): j}) and the BLOCK_OWNS / CAI_ANALYSER contents (handled separately)."""
    def walk(kl, path):
        j0 = hdr.get(id(kl))
        for i, c in enumerate(kl):
            if isinstance(c, Rec):
                if c.name not in (OWNS, 'CAI_ANALYSER'):
                    for k2 in _kids_of(c):
                        walk(k2, path + '/' + c.name)
            elif j0 is None or not j0 < i <= j0 + 20:
                fn(kl, i, c, path)
    walk(kids, '')


def _scalars(cx, x):
    """u32 (0x08) values in x's item list outside headers / BLOCK_OWNS / analyser."""
    k, j = cx.by[x]
    out = set()
    _body_vals(k, lambda kl, i, v, p: out.add(v.value) if v.tag == 0x08 else None, {id(kk): jj for kk, jj in _components([k]).values()})
    return out


def _subst_all(kids, M, hm):
    """CAI ids (0x08 / 0x48 values) by M then game handles (0x04 / 0x08 / 0x44 / 0x48) by hm, everywhere under kids,
    headers too (j+1 renumbers the component).  Returns the number of values changed."""
    n = 0

    def f(kl):
        nonlocal n
        for i, c in enumerate(kl):
            if isinstance(c, Rec):
                continue
            if c.tag in (0x04, 0x08):
                v = c.value & 0xFFFFFFFF
                nv = M.get(v, v) if c.tag == 0x08 else v
                nv = hm.get(nv, nv)
                if nv != v:
                    kl[i] = Val(c.tag, nv); n += 1
            elif c.tag in (0x44, 0x48) and c.value:
                a = struct.unpack(f'<{len(c.value) // 4}I', c.value)
                b = [hm.get(M.get(v, v), M.get(v, v)) if c.tag == 0x48 else hm.get(v, v) for v in a]
                if list(a) != b:
                    kl[i] = Val(c.tag, struct.pack(f'<{len(b)}I', *b)); n += sum(x != y for x, y in zip(a, b))
    _walk_kids(kids, f)
    return n


def _add_pair(cx, y, o, r, A):
    """y gets the owner pair (o, r): A pairs first (j+10), B pairs after (j+11)."""
    p = cx.arr(y, 9)
    n10 = cx.h(y, 10).value
    if A:
        p[2 * n10:2 * n10] = [o, r]; cx.h(y, 10).value = n10 + 1
    else:
        p += [o, r]; cx.h(y, 11).value += 1
    cx.seth(y, 9, u32a(p))


def _add_row(cx, o, c, src, r, t, M):
    """Outside owner o gets a row for clone c, a copy of row r of src (o itself, or the template-side record o is
    mapped from) for template item t, in the same part (A: inserted before the B rows, whose items' pairs shift; B:
    appended).  Analyser: c appended to its owned list + (M[key], c) for each (key, t) pair of src; other kinds: c
    appended to each body u32 array of o at an index where src's holds t.  Returns c's row index."""
    rows = cx.rows(o)
    n15, n16 = cx.h(o, 15).value, cx.h(o, 16).value
    trow = cx.rows(src)[r]
    assert trow[0].value == t, (src, r, t)
    row = copy.deepcopy(trow)
    row[0] = Val(0x08, c)
    if row[1].tag == 0x08 and row[1].value == src:
        row[1] = Val(0x08, o)
    if r < cx.h(src, 15).value:
        pos = n15
        rows.insert(pos, row); cx.h(o, 15).value = n15 + 1
        for y in dedup(x[0].value for x in rows[pos + 1:]):
            if y in cx.by:
                p = cx.arr(y, 9)
                cx.seth(y, 9, u32a([v + 1 if i % 2 and p[i - 1] == o and v >= pos else v for i, v in enumerate(p)]))
    else:
        pos = n15 + n16
        rows.append(row); cx.h(o, 16).value = n16 + 1
    a, sa = cx.ana(o), cx.ana(src)
    if a is not None:
        own = a.children[0].array()
        assert len(own) == pos, ('analyser owned list = its rows', o, len(own), pos)
        a.children[0] = u32a(own + [c])
        p = sa.children[1].array()
        a.children[1] = u32a(a.children[1].array() + [v for key, b in zip(p[0::2], p[1::2]) if b == t for v in (M.get(key, key), c)])
    else:
        sb, ob = cx.body(src), cx.body(o)
        for i, v in enumerate(sb or []):
            if isinstance(v, Val) and v.tag == 0x48 and v.value and t in v.array() and c not in ob[i].array():
                ob[i] = u32a(ob[i].array() + [c])
    return pos


def _flat(cx, ys, f):
    return dedup(v for y in ys for v in [y] + (cx.arr(y, f) if y in cx.by else []))


def _owners(cx, z, t):
    """z's owners (pair order) linking it by a type t row."""
    p = cx.arr(z, 9)
    return [o for o, r in zip(p[0::2], p[1::2])
            if o in cx.by and r < len(cx.rows(o)) and cx.rows(o)[r][0].value == z and cx.rows(o)[r][4].value == t]


def _want(cx, z, f):
    """Recomputed cache f (12 / 13 / 17 / 18) of z (module docstring)."""
    t = int(f in (13, 18))
    if f in (12, 13):
        return _flat(cx, _owners(cx, z, t), f)
    return _flat(cx, [r[0].value for r in cx.rows(z) if r[4].value == t], f)


def _subseq(a, b):
    it = iter(b)
    return all(v in it for v in a)


def _refresh(cx, z, f, new):
    """Cache f of z after links to the ids in new were added: if the stored cache is a subsequence of the
    recomputation (exact before, or only missing entries) it is recomputed, else (stale with extra / reordered
    entries) the missing entries are appended.  Returns True if changed."""
    want, cur = _want(cx, z, f), cx.arr(z, f)
    if cur == want:
        return False
    nv = want if _subseq(cur, want) else dedup(cur + want)
    if nv == cur:
        return False
    cx.seth(z, f, u32a(nv))
    return True


def _bubble(cx, start, new, up):
    """Caches of the records around start after new ids joined start's descendants (up: its owners' j+17 / j+18) or
    ancestors (else: its owned items' j+12 / j+13), transitively: a cache that was exact stays exact (recomputed),
    a stale one (vanilla has ~10%) only gets the new ids appended."""
    todo, seen = [start], {start}
    while todo:
        y = todo.pop()
        if y not in cx.by:
            continue
        if up:
            p = cx.arr(y, 9)
            nxt = [(a, 17 + cx.rows(a)[r][4].value) for a, r in zip(p[0::2], p[1::2]) if a in cx.by]
        else:
            nxt = [(r[0].value, 12 + r[4].value) for r in cx.rows(y) if r[0].value in cx.by]
        for z, f in nxt:
            if _refresh(cx, z, f, new) and z not in seen:
                seen.add(z); todo.append(z)


def _relink(cx, tc, rowmap, M, omap, skip):
    """Header links of the clones tc [(template id, clone id)] (template headers as the source):
      owners   template pair (o, r): o cloned -> (o's clone, its pruned row); o in omap or structural -> a row is
               added to omap[o] / o (_add_row); o in skip (not cloned) or a non-structural outside owner (perception
               beliefs of other mobiles) -> dropped
      owned    each clone row whose item is outside the clones gives that item the back pair + ancestors
      caches   j+12 / 13 / 17 / 18 recomputed for the clones (dedup); touched outside owners get the clone appended
      subjects j+19 <-> j+20 made symmetric
    rowmap {template id: {template row: clone row}}.  Returns (report Counter, {outside owner: [clones]})."""
    cl = dict(tc)
    cset = set(cl.values())
    rep = collections.Counter()
    touched = collections.defaultdict(list)
    for t, c in tc:
        cx.seth(c, 9, u32a([])); cx.h(c, 10).value = cx.h(c, 11).value = 0
    for t, c in tc:
        p = cx.arr(t, 9)
        n10 = cx.h(t, 10).value
        for i, (o, r) in enumerate(zip(p[0::2], p[1::2])):
            A = i < n10
            if o in cl:
                ri = rowmap[o].get(r)
                assert ri is not None, ('owner row of a clone pruned', t, o, r)
                _add_pair(cx, c, cl[o], ri, A); rep['owner pairs clone -> clone'] += 1
            elif o in skip:
                rep['owner pairs from not-cloned owners dropped'] += 1
            elif o in omap or cx.structural(o):
                o2 = omap.get(o, o)
                ri = _add_row(cx, o2, c, o, r, t, M)
                _add_pair(cx, c, o2, ri, A)
                touched[o2].append(c); rep['rows added to outside owners'] += 1
            else:
                rep['owner pairs from outside perception beliefs dropped'] += 1
    memo = {}

    def links(x, o, own):                            # (A, B) ancestors (own=True) / descendants of x
        if x not in cset:
            return (cx.arr(x, o), cx.arr(x, o + 1)) if x in cx.by else ([], [])
        key = (x, own)
        if key not in memo:
            memo[key] = None
            if own:
                ys = [(z, t) for t in (0, 1) for z in _owners(cx, x, t)]
            else:
                ys = [(r[0].value, r[4].value) for r in cx.rows(x)]
            part = lambda t: dedup(v for y, u in ys if u == t for v in [y] + links(y, o, own)[t])
            memo[key] = (part(0), part(1))
        assert memo[key] is not None, ('ownership cycle', x)
        return memo[key]
    for t, c in tc:
        a, b = links(c, 12, True)
        cx.seth(c, 12, u32a(a)); cx.seth(c, 13, u32a(b))
    for t, c in tc:
        tr = {ri: r for r, ri in rowmap[t].items()}
        for ri, row in enumerate(cx.rows(c)):
            y = row[0].value
            if y in cset or y not in cx.by:
                continue
            ty = cx.rows(t)[tr[ri]][0].value                  # the template item's pair (t, row) gives the part (A / B)
            tp = cx.arr(ty, 9)
            _add_pair(cx, y, c, ri, list(zip(tp[0::2], tp[1::2])).index((t, tr[ri])) < cx.h(ty, 10).value)
            if _refresh(cx, y, 12 + row[4].value, cset):
                _bubble(cx, y, cset, False)
            rep['outside items owned by clones'] += 1
    for t, c in tc:
        a, b = links(c, 17, False)
        cx.seth(c, 17, u32a(a)); cx.seth(c, 18, u32a(b))
    for o in touched:
        if any([_refresh(cx, o, f, cset) for f in (17, 18)]):
            _bubble(cx, o, cset, True)
    for t, c in tc:
        for s, o in [(s, 20) for s in cx.arr(c, 19)] + [(r, 19) for r in cx.arr(c, 20)]:
            if s in cx.by and c not in cx.arr(s, o):
                cx.seth(s, o, u32a(cx.arr(s, o) + [c])); rep['subject / referenced-by back refs added'] += 1
    return rep, touched


def _drops(cx, S, D, foreign):
    """D grown to a fixpoint over the non-structural components of S: one owning (BLOCK_OWNS) or keyed by (body[0]) a
    D / foreign record, or holding a D id as a scalar, is not cloned.  Structural components (analysers, managers) are
    always cloned and only pruned."""
    bad = lambda y: y in D or foreign(y)
    cand = [x for x in S if not cx.structural(x)]
    sc = {x: _scalars(cx, x) for x in cand}
    while True:
        n = len(D)
        for x in cand:
            if x not in D and (any(bad(r[0].value) for r in cx.rows(x)) or (cx.body0(x) and bad(cx.body0(x))) or sc[x] & D):
                D.add(x)
        if len(D) == n:
            return D


def _stage(cx, S, D, foreign, M0, hm, new_id, mgr_from=None):
    """Clone the components S - D (template ids) next to their templates; mgr_from: that CAI faction's manager item is
    cloned as a whole (pools filtered of D) and appended to CAI_INTERFACE_MANAGERS.  In the copies: rows / analyser
    entries / j+19 / j+20 / body arrays drop D (and foreign row items), D scalars -> 0; then every value is substituted
    (fresh ids, M0, game handles hm) and the copies indexed.  Returns ([(template, clone)], M, rowmap, report)."""
    rep = collections.Counter()
    keep = [x for x in S if x not in D]
    units = dedup(cx.unit[x] for x in keep if mgr_from is None or cx.mgr[x] != mgr_from)
    ks = set(keep)
    assert all(u in ks for u in units), ('every cloned component sits in a cloned unit', [u for u in units if u not in ks][:5])
    new = []                                         # (container Rec, item list, manager)
    if mgr_from is not None:
        mi = copy.deepcopy(cx.manager_item(mgr_from))

        def filt(kids):
            for c in kids:
                if isinstance(c, Rec) and c.items is not None:
                    c.items = [it for it in c.items if not any(isinstance(v, Rec) and v.name == PS and i + 1 < len(it)
                                                              and it[i + 1].value in D for i, v in enumerate(it))]
        _walk_kids(mi, filt)
        new.append((cx.managers, mi, None))
    for u in units:
        new.append((cx.cont[u], copy.deepcopy(cx.by[u][0]), cx.mgr[u]))
    cl = _components([it for _, it, _ in new])
    assert sorted(cl) == sorted(keep), ('clone set', sorted(set(cl) ^ set(keep))[:8])
    bad = lambda y: y in D or foreign(y)
    rowmap = {}
    for t in keep:
        k, j = cl[t]
        bo = k[j + 14]
        assert isinstance(bo, Rec) and bo.name == OWNS
        n15 = k[j + 15].value
        kr = [(r, row) for r, row in enumerate(bo.items) if not bad(row[0].value)]
        rep['rows pruned'] += len(bo.items) - len(kr)
        rowmap[t] = {r: i for i, (r, _) in enumerate(kr)}
        bo.items = [row for _, row in kr]
        k[j + 15].value = sum(r < n15 for r, _ in kr)
        k[j + 16].value = len(kr) - k[j + 15].value
        a = next((c for c in k if isinstance(c, Rec) and c.name == 'CAI_ANALYSER'), None)
        if a is not None and isinstance(a.children[0], Val) and a.children[0].tag == 0x48:
            own = [row[0].value for row in bo.items]
            assert k[j + 15].value == 0 and set(own) <= set(a.children[0].array()), ('analyser rows', t)
            a.children[0] = u32a(own)
            if isinstance(a.children[1], Val) and a.children[1].tag == 0x48:
                p, so = a.children[1].array(), set(own)
                kp = [v for key, b in zip(p[0::2], p[1::2]) if b in so and key not in D for v in (key, b)]
                rep['analyser pairs pruned'] += (len(p) - len(kp)) // 2
                a.children[1] = u32a(kp)
        for o in (9, 12, 13, 17, 18):
            k[j + o] = u32a([])
        k[j + 10].value = k[j + 11].value = 0
        for o in (19, 20):
            v = k[j + o].array()
            k[j + o] = u32a([x for x in v if x not in D])
            rep['j+19/20 refs to not-cloned dropped'] += len(v) - len(k[j + o].array())
    paths = collections.Counter()
    hdr = {id(k): j for k, j in cl.values()}

    def fix(kl, i, v, path):
        if v.tag == 0x08 and v.value in D:
            kl[i] = Val(0x08, 0); paths['-> 0  ' + path] += 1
        elif v.tag == 0x48 and v.value and set(v.array()) & D:
            kl[i] = u32a([x for x in v.array() if x not in D]); paths['-> [] ' + path] += 1
    for _, it, _ in new:
        _body_vals(it, fix, hdr)
    m = {t: M0[t] if t in M0 else new_id() for t in keep}
    M = {**M0, **m}
    for _, it, _ in new:
        rep['values substituted'] += _subst_all(it, M, hm)
    for cont, it, mg in new:
        cont.items.append(it)
        cx.add_kids(it, cont, None, it[2].children[0].value if cont is cx.managers else mg)
    return [(t, m[t]) for t in keep], M, rowmap, rep, paths


def _omap(cx, rmap):
    """World analyser beliefs keyed by a mapped template region record -> the same analyser's belief of the same kind
    keyed by the new faction's record (e.g. the template region's CAI_REGION_OCCUPANCY_ANALYSIS -> the capital's)."""
    out = {}
    for a_id, (k, j) in cx.by.items():
        a = cx.ana(a_id)
        if a is None or cx.mgr[a_id] is not None or not (isinstance(a.children[1], Val) and a.children[1].tag == 0x48):
            continue
        p = a.children[1].array()
        bk = collections.defaultdict(list)
        for key, b in zip(p[0::2], p[1::2]):
            if key in rmap or key in rmap.values():
                bk[key].append(b)
        for tk, nk in rmap.items():
            for kind in dedup(cx.kind(b) for b in bk.get(tk, [])):
                out.update(zip([b for b in bk[tk] if cx.kind(b) == kind], [b for b in bk.get(nk, []) if cx.kind(b) == kind]))
    return out


def _entry_key(e, owner, fids):
    vals = []
    _walk_kids(e, lambda kl: vals.extend(v.value for v in kl if isinstance(v, Val) and v.tag == 0x08))
    return next((v for v in vals[:3] if v in fids and v != owner), None)


def _faction_lists(cx, T, U, P, M, D, cset):
    """FACTION_LISTS: a list (outside the clones) holding T gets a copy of T's entry for U (substituted by M, D -> 0);
    a complete list owned by T or U gets the missing T <-> U entry: the proxy P's entry with P -> T / U."""
    fids = set(cx.factions().values())
    rep = collections.Counter()
    for x in sorted(x for x in cx.by if cx.unit[x] == x):
        owner = cx.body0(x)
        lists = []
        _walk_kids(cx.by[x][0], lambda kl: lists.extend(c for c in kl if isinstance(c, Rec) and c.name in FACTION_LISTS))
        for L in lists:
            keys = [_entry_key(e, owner, fids) for e in L.items]

            def put(e, key):
                ks = [k for k in keys]
                pos = bisect.bisect(ks, key) if ks == sorted(ks) and None not in ks else len(ks)
                L.items.insert(pos, e); keys.insert(pos, key)
            if x not in cset and owner != U and T in keys and U not in keys:
                e = copy.deepcopy(L.items[keys.index(T)])
                _walk_kids(e, lambda kl: [kl.__setitem__(i, Val(0x08, 0)) for i, v in enumerate(kl)
                                          if isinstance(v, Val) and v.tag == 0x08 and v.value in D])
                _subst_all(e, M, {})
                put(e, U); rep['mirrored ' + L.name] += 1
            if FACTION_LISTS[L.name] and owner in (T, U) and P in keys:
                for X in (T, U):
                    if X != owner and X not in keys:
                        e = copy.deepcopy(L.items[keys.index(P)])
                        _subst_all(e, {P: X}, {})
                        put(e, X); rep['filled ' + L.name] += 1
    return rep


def _world_of(cx, f):
    """{kind: id} of the world components keyed by CAI faction f (body[0] == f, one per kind)."""
    c = collections.Counter(); out = {}
    for x in cx.by:
        if cx.mgr[x] is None and cx.body0(x) == f and cx.unit[x] == x:
            c[cx.kind(x)] += 1; out[cx.kind(x)] = x
    return {k: v for k, v in out.items() if c[k] == 1}


def _pair_views(cx, F, P, X, new_id):
    """Manager F gets views of faction X: its components keyed by the proxy faction P (body[0] == P: attitude analysis,
    attitude goal, friends-and-enemies, ..) cloned with P -> X (and P's world components -> X's), owned like P's."""
    S = [x for x in sorted(cx.by) if cx.mgr[x] == F and cx.body0(x) == P and cx.unit[x] == x]
    foreign = lambda y: cx.kind(y) in FOREIGN_KINDS
    D = _drops(cx, S, set(), foreign)
    wp, wx = _world_of(cx, P), _world_of(cx, X)
    M0 = {P: X, **{wp[k]: wx[k] for k in wp if k in wx}}
    tc, M, rowmap, rep, paths = _stage(cx, S, D, foreign, M0, {}, new_id)
    r2, _ = _relink(cx, tc, rowmap, M, {}, set(D))
    return dict(kinds=dict(collections.Counter(cx.kind(t) for t, _ in tc)), not_cloned=len(D), **rep, **r2)


def clone_cai_faction(sp, tpl_handle, new_handle, hm, regions, new_id, U=None, proxy_handle=None, cap_xy=None):
    """New CAI faction U for the game faction new_handle, cloned from the CAI faction of game faction tpl_handle (T).
      hm       template game handle -> new game handle (faction, governorship, characters, armies, tech manager, ..
               from the game-side clone); a CAI character / mobile / unit holding an unmapped template handle (the
               dropped garrison army, its colonel, its units) is not cloned
      regions  the new faction's CAI_REGION ids, capital first (built by the caller, settlements already owned by U,
               one region group owned by U); T's regions / settlements / building slots / HLCIs / group map onto
               them in order (rmap), and the world beliefs keyed by those onto the new records' (omap)
      new_id   CAI id allocator (CAI_CENTRAL_BDI_POOL counter); U: pre-allocated CAI_FACTION id
      proxy_handle  game faction whose views stand in for the T <-> U pair (a neutral minor); cap_xy: fixed-point
               capital position for the cloned mobiles' CAI_SITUATED
    Cloned (S): WT = T's CAI_FACTION (+ inner component), technology tree, governorships, characters, mobiles, units;
    T's manager (CAI_INTERFACE_MANAGERS item) with its 1000-odd components; the world components keyed by a WT record
    (diplomatic / relation / trade route / recruitment / strength analyses, mobile beliefs, ..); every other manager's
    components keyed by T (its attitude analysis, attitude goal, friends-and-enemies, the rebels' war).  Not cloned
    (_drops): non-structural components owning or keyed by foreign region-level records (perception of other
    factions' mobiles / regions, T's region-composite analyses, ..).  Then _relink, outside list back-refs
    (SHARED_LISTS, mapped records), pair views T <-> U, FACTION_LISTS, the CAI_INTERFACE (faction, 11) list, regions
    handed over (CAI_FACTION [0], governorship [3], CAI_REGION [12]).  Returns a report dict."""
    cx = Cai(sp)
    fh = cx.factions()
    T = fh[tpl_handle]
    assert new_handle not in fh, 'game faction already has a CAI faction'
    U = new_id() if U is None else U
    tb = cx.body(T)
    WT = dedup([T, tb[12].value, tb[9].value] + tb[10].array() + tb[3].array() + tb[4].array()
               + [u for x in tb[3].array() for u in cx.body(x)[5].array()])
    WTs = set(WT)
    # T's region records -> the new faction's
    rmap = {}
    for tr, nr in zip(tb[0].array(), regions):
        a, b = cx.body(tr), cx.body(nr)
        rmap[tr] = nr
        if a[2].value and b[2].value:
            rmap[a[2].value] = b[2].value
            rmap.update(zip(cx.body(a[2].value)[0].array(), cx.body(b[2].value)[0].array()))
        rmap.update(zip(a[1].array(), b[1].array()))
        tg, ng = cx.group_of(tr, T), cx.group_of(nr, U)
        if tg and ng:
            rmap[tg[0]] = ng[0]
    omap = _omap(cx, rmap)
    foreign = lambda y: cx.kind(y) in FOREIGN_KINDS and y not in WTs and y not in rmap
    ids = sorted(cx.by)
    S1 = [x for x in ids if cx.mgr[x] == T]
    S2w = [x for x in ids if cx.mgr[x] is None and x not in WTs and cx.body0(x) in WTs]
    S2m = [x for x in ids if cx.mgr[x] not in (None, T) and cx.body0(x) == T]
    S = dedup(WT + S1 + S2w + S2m)
    D = set()
    for x in WT[1:]:
        vals = set()
        _walk_kids(cx.by[x][0][-1].children if isinstance(cx.by[x][0][-1], Rec) else [], lambda kl: vals.update(
            v.value & 0xFFFFFFFF for v in kl if isinstance(v, Val) and v.tag in (0x04, 0x08)))
        if any(is_handle(v) and v not in hm for v in vals):
            D.add(x)
    seed = collections.Counter(cx.kind(x) for x in D)
    assert set(seed) <= {'CAI_CHARACTER', 'CAI_RESOURCE_MOBILE', 'CAI_UNIT'}, seed
    D = _drops(cx, S, D, foreign)
    assert T not in D
    tc, M, rowmap, rep1, paths = _stage(cx, S, D, foreign, {**rmap, **omap, T: U}, hm, new_id, mgr_from=T)
    rep2, touched = _relink(cx, tc, rowmap, M, omap, D)
    cl = dict(tc)
    cset, tset = set(cl.values()), set(cl)
    # outside records listing template records in body arrays
    back, unhandled = collections.Counter(), collections.Counter()
    for r in sorted(cx.by):
        if r in cset or r in tset or r in D or cx.mgr[r] == T or cx.ana(r) is not None:
            continue
        b = cx.body(r)
        for i, v in enumerate(b or []):
            if not (isinstance(v, Val) and v.tag == 0x48 and v.value):
                continue
            hit = [cl[x] for x in v.array() if x in cl]
            if not hit:
                continue
            tgt = rmap.get(r, omap.get(r, r if cx.kind(r) in SHARED_LISTS else None))
            if tgt is None:
                if not (r in touched and all(c in b[i].array() for c in hit)):
                    unhandled[f'{cx.kind(r)}[{i}]'] += len(hit)
                continue
            tb2 = cx.body(tgt)
            add = [c for c in hit if c not in tb2[i].array()]
            tb2[i] = u32a(tb2[i].array() + add)
            back[f'{cx.kind(r)}[{i}]'] += len(add)
    # T <-> U views, faction lists, the CAI_INTERFACE (CAI faction, 11) list
    P = fh[proxy_handle]
    pv = {'U views T': _pair_views(cx, U, P, T, new_id), 'T views U': _pair_views(cx, T, P, U, new_id)}
    fl = _faction_lists(cx, T, U, P, M, D, cset)
    k = cx.ci.children
    fp = next(i for i, v in enumerate(k) if isinstance(v, Val) and v.tag == 0x48 and v.value
              and v.array()[0::2] == [it[2].value for it in cx.w.find('CAI_WORLD_FACTIONS').items][:len(v.array()) // 2]
              and T in v.array()[0::2])
    a = k[fp].array()
    k[fp] = u32a(a + [U, a[a[0::2].index(T) * 2 + 1]])
    # hand the regions over
    ub = cx.body(U)
    ub[0] = u32a(list(regions))
    gov = cx.body(U)[10].array()
    assert len(gov) == 1
    gb = cx.body(gov[0])
    gb[3] = u32a(list(regions))
    for r in regions:
        rb = cx.body(r)
        old = rb[12].value
        if old and old != gov[0]:
            ob = cx.body(old)
            ob[3] = u32a([x for x in ob[3].array() if x != r])
        rb[12] = Val(0x08, gov[0])
    sit = 0
    if cap_xy is not None:
        for t, c in tc:
            s = next((v for v in cx.by[c][0][:cx.by[c][1]] if isinstance(v, Rec) and v.name == 'CAI_SITUATED'), None)
            if s is not None:
                s.children[0], s.children[1] = Val(0x04, cap_xy[0]), Val(0x04, cap_xy[1]); sit += 1
    return dict(cai_faction=U, template=T, proxy=P, cloned=len(tc), not_cloned=len(D),
                cloned_kinds_top=collections.Counter(cx.kind(t) for t, _ in tc).most_common(12),
                not_cloned_kinds=dict(collections.Counter(cx.kind(x) for x in D).most_common(14)),
                dropped_seed=dict(seed), wt=len(WT), region_map=len(rmap), belief_map=len(omap),
                stage=dict(rep1), relink=dict(rep2), pruned_body_refs=dict(paths), list_back_refs=dict(back),
                unhandled_back_refs=dict(unhandled), pair_views=pv, faction_lists=dict(fl), situated=sit,
                governorship=gov[0], governor=gb[2].value, characters=len(ub[4].array()), mobiles=len(ub[3].array()))


# ---------------------------------------------------------------- checks
def header_issues(cx, ids):
    """Counter of header-link issues over the components ids (+ up to 3 examples each): owner pairs <-> owner rows,
    owned rows <-> item pairs, counts, analyser owned list = rows / pair values owned, subjects <-> referenced-by,
    and the four caches against their dedup recomputation."""
    bad, ex = collections.Counter(), collections.defaultdict(list)

    def B(tag, x, info=''):
        bad[tag] += 1
        if len(ex[tag]) < 3:
            ex[tag].append((x, cx.kind(x), info))
    for x in ids:
        p = cx.arr(x, 9)
        pr = list(zip(p[0::2], p[1::2]))
        n10 = cx.h(x, 10).value
        if n10 + cx.h(x, 11).value != len(pr):
            B('j10 + j11 != owner pairs', x)
        for o, r in pr:
            if o not in cx.by or r >= len(cx.rows(o)) or cx.rows(o)[r][0].value != x:
                B('owner pair without its row', x, (o, r))
        rows = [r[0].value for r in cx.rows(x)]
        n15 = cx.h(x, 15).value
        if n15 + cx.h(x, 16).value != len(rows):
            B('j15 + j16 != rows', x)
        for y in rows:
            if y in cx.by and x not in cx.arr(y, 9)[0::2]:
                B('owned row without the item\'s owner pair', x, y)
        a = cx.ana(x)
        if a is not None:
            if a.children[0].array() != rows:
                B('analyser owned list != rows', x)
            if isinstance(a.children[1], Val) and a.children[1].tag == 0x48 and not set(a.children[1].array()[1::2]) <= set(rows):
                B('analyser pair value not owned', x)
        for s in cx.arr(x, 19):
            if s in cx.by and x not in cx.arr(s, 20):
                B('subject without back ref', x, s)
        for s in cx.arr(x, 20):
            if s in cx.by and x not in cx.arr(s, 19):
                B('referenced-by without subject', x, s)
        for o in (12, 13, 17, 18):
            if set(cx.arr(x, o)) != set(_want(cx, x, o)):
                B(f'j+{o} cache', x)
    return bad, ex


def _index(cx):
    """({x: body0(x)}, {(manager, body0): Counter of kinds}) over cx.by in its order; built on first use, so for a cx the
    checks only read (rebuilt if the component count changes)."""
    if getattr(cx, '_idx', (None,))[0] != len(cx.by):
        b0, kb = {}, collections.defaultdict(collections.Counter)
        for x in cx.by:
            b0[x] = cx.body0(x)
            kb[(cx.mgr[x], b0[x])][cx.kind(x)] += 1
        cx._idx = (len(cx.by), b0, kb)
    return cx._idx[1:]


def faction_components(cx, U):
    """The components of CAI faction U: its WT records, its manager, the world components keyed by a WT record and
    every component keyed by U."""
    b = cx.body(U)
    wt = {U, b[12].value, b[9].value, *b[10].array(), *b[3].array(), *b[4].array(),
          *[u for x in b[3].array() for u in cx.body(x)[5].array()]}
    b0 = _index(cx)[0]
    return sorted(x for x in cx.by if x in wt or cx.mgr[x] == U or b0[x] == U
                  or (cx.mgr[x] is None and b0[x] in wt))


def check_faction(sp, U, T, regions=None, cx=None):
    """[(name, ok, detail)]: generated CAI faction U against its template T."""
    cx = cx or Cai(sp)
    out = []
    C = faction_components(cx, U)
    bad, ex = header_issues(cx, C)
    out.append((f'CAI {U}: header links of its {len(C)} components exact (owner pairs <-> rows, analysers, subjects, caches)',
                not bad, dict(bad) or len(C), ))
    if bad:
        out[-1] = out[-1][:2] + ((dict(bad), dict(ex)),)
    kb = _index(cx)[1]
    kc = lambda f, key: collections.Counter(kb[(f, key)]) if (f, key) in kb else collections.Counter()
    fids = [it[2].value for it in cx.w.find('CAI_WORLD_FACTIONS').items]
    diff = {f: (dict(kc(f, U)), dict(kc(f, T))) for f in fids if f not in (U, T) and kc(f, U) != kc(f, T)}
    out.append((f'CAI {U}: every other manager keys {U} like {T} (attitude analysis / goal / friends-and-enemies / war)',
                not diff and all(any(it[2].children[0].value == f for it in cx.managers.items) for f in fids), diff or len(fids) - 2))
    wk = lambda f: kc(None, f)
    pv = (kc(U, T), kc(T, U), kc(T, fids[0] if fids[0] not in (U, T) else fids[1]))
    out.append((f'CAI {U}: world components keyed by it = {T}\'s; {U} <-> {T} views present',
                wk(U) == wk(T) and pv[0] == pv[1] and pv[0] and set(pv[0]) <= set(pv[2]) | set(pv[0]),
                (dict(wk(U)), dict(pv[0]), dict(pv[1]))))
    fs = set(fids)
    miss = []
    fk = cx.__dict__.get('_fk')                 # (fs, [(x, owner, [(list name, keys)])]) of the units that have faction lists:
    if fk is None or fk[0] != (fs, len(cx.by)):               # the same for every U, T (keys do not depend on them)
        ents = []
        for x in sorted(x for x in cx.by if cx.unit[x] == x):
            owner = cx.body0(x)
            lists = []
            _walk_kids(cx.by[x][0], lambda kl: lists.extend(c for c in kl if isinstance(c, Rec) and c.name in FACTION_LISTS))
            if lists:
                ents.append((x, owner, [(L.name, {_entry_key(e, owner, fs) for e in L.items}) for L in lists]))
        fk = cx._fk = ((fs, len(cx.by)), ents)
    for x, owner, lk in fk[1]:
        for name, keys in lk:
            if (owner != U and T in keys and U not in keys) or (owner != T and U in keys and T not in keys and owner not in (U, T)):
                miss.append((x, name))
            if FACTION_LISTS[name] and ((owner == U and T not in keys) or (owner == T and U not in keys)):
                miss.append((x, name, 'pair'))
    out.append((f'CAI {U}: faction-keyed lists ({", ".join(FACTION_LISTS)}) key {U} wherever they key {T}', not miss, miss[:6] or ''))
    fl = [v.array() for v in cx.ci.children if isinstance(v, Val) and v.tag == 0x48 and v.value and T in v.array()[0::2]]
    fl = fl[0] if len(fl) == 1 else []
    mi = [it for it in cx.managers.items if it[2].children[0].value == U]
    out.append((f'CAI {U}: one manager (CAI_FACTION_MANAGER {U}) and a CAI_INTERFACE (faction, n) entry; managers = factions',
                len(mi) == 1 and fl[0::2] == fids and len(cx.managers.items) == len(fids), (len(mi), len(fl) // 2, len(fids))))
    if regions is not None:
        b = cx.body(U)
        g = b[10].array()
        gb = cx.body(g[0]) if len(g) == 1 else None
        own = {x: v[0].children[0].value for x, (k, j) in cx.by.items() if cx.kind(x) == 'CAI_SETTLEMENT'
               for v in [k] if isinstance(v[0], Rec) and v[0].name == 'OWNED_DIRECT'}
        out.append((f'CAI {U}: owns its regions (body [0] / capital [5] [36], governorship [3] with a governor, CAI_REGION [12], '
                    'settlement owner)', b[0].array() == list(regions) and b[5].value == regions[0] == b[36].value
                    and gb is not None and gb[3].array() == list(regions) and gb[2].value in b[4].array()
                    and all(cx.body(r)[12].value == g[0] and own.get(cx.body(r)[2].value) == U for r in regions),
                    dict(regions=b[0].array(), governorship=g, governor=gb[2].value if gb else None)))
    return out


def fix_caches(sp):
    """Recompute the four caches of every component from the pairs and rows (module docstring: keyed by the row type).
    The clone helpers keep them right link by link; this runs once on the finished startpos as the guarantee, and
    repairs a save written before the fix (ids that are no component drop out).  A cache whose set is right keeps its
    order.  Returns {cache offset: components changed}."""
    by, _ = cai_index(sp)
    rows = {x: by[x][0][by[x][1] + 14].items for x in by}
    nb = {}                                          # (x, f) -> direct links, pair / row order
    for x, (k, j) in by.items():
        p = k[j + 9].array()
        for t in (0, 1):
            nb[x, 12 + t] = [o for o, r in zip(p[0::2], p[1::2])
                             if o in by and r < len(rows[o]) and rows[o][r][0].value == x and rows[o][r][4].value == t]
            nb[x, 17 + t] = [r[0].value for r in rows[x] if r[0].value in by and r[4].value == t]
    memo = {}

    def close(x, f):
        if (x, f) not in memo:
            memo[x, f] = None
            memo[x, f] = dedup(v for y in nb[x, f] for v in [y] + close(y, f))
        assert memo[x, f] is not None, ('ownership cycle', x, f)
        return memo[x, f]
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))
    n = collections.Counter()
    for x, (k, j) in by.items():
        for f in (12, 13, 17, 18):
            want = close(x, f)
            if set(k[j + f].array()) != set(want):
                k[j + f] = u32a(want); n[f] += 1
    return dict(n)


def game_factions(sp):
    """{game faction key: FACTION handle} (key = the FACTION's first string, the handle the value before it)."""
    out = {}
    for it in next(cm._iter_recs(sp.root, 'FACTION_ARRAY')).items:
        ch = it[0].children
        k = next(j for j, c in enumerate(ch) if isinstance(c, Val) and c.tag == 0x0e)
        out[ch[k].value] = ch[k - 1].value
    return out


if __name__ == '__main__':
    import esf
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if sys.argv[1] == 'fix':                             # fix IN OUT: repair a startpos or a save (fix_caches)
        sp = esf.load(sys.argv[2])
        print(fix_caches(sp))
        assert fix_caches(sp) == {}, 'a second pass changes nothing'
        open(sys.argv[3], 'wb').write(esf.dumps(sp))
        sys.exit(0)
    args = [a for a in sys.argv[1:] if not a.startswith('--template=')]
    tkey = next((a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--template=')), 'oldenburg')
    sp = esf.load(args[0])
    base = esf.load(args[1] if len(args) > 1 else os.path.join(root, 'work/world/probe5/startpos.esf'))
    cx, bx = Cai(sp), Cai(base)
    top = max(bx.by)
    fh = cx.factions()
    T = fh[game_factions(sp)[tkey]]
    gen = sorted(U for U in fh.values() if U > top)
    print(f'== {args[0]}: generated CAI factions {gen} (template {tkey} = {T})')
    ok = bool(gen)
    for U in gen:
        for name, good, det in check_faction(sp, U, T, cx=cx):
            ok &= bool(good)
            print(f"  {'ok  ' if good else 'FAIL'} {name}: {str(det)[:400]}")
    rest = sorted(set(x for x in cx.by if x > top) - {x for U in gen for x in faction_components(cx, U)})
    rb, rex = header_issues(cx, rest)
    print(f"  {'ok  ' if not rb else 'warn'} the {len(rest)} other new components (land_probe_b region records / beliefs): "
          f"header issues {dict(rb)} {dict(rex) if rb else ''}"[:600])
    nb, _ = header_issues(cx, sorted(x for x in cx.by if x <= top))
    ob, _ = header_issues(bx, sorted(bx.by))
    worse = {k: (ob[k], nb[k]) for k in sorted(set(nb) | set(ob)) if nb[k] > ob[k]}
    print(f"  {'ok  ' if not worse else 'FAIL'} the {len(bx.by)} base components: header issues not worse than in the base "
          f"{dict(sorted(ob.items()))}; worse: {worse}")
    ok &= not worse
    print('  PASS' if ok else '  FAIL')
    sys.exit(0 if ok else 1)
