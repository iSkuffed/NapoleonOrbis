"""Patch Napoleon.exe's hard-coded campaign extents for the enlarged world map (research/00).

Groups:
  display  building + tree display boxes, x,z ±1000 -> ±2048 (quadtree roots VA 0x1363EE0 / 0x1363ED0 and their max-z
           immediates). A settlement outside crashes the building display. Verified in game.
  terrain  terrain display grid and draw/cull box, built at a fixed ±1280 x ±640 (grid init 0x11C0E00 called with
           256x128 cells of 10 u, draw box VA 0x1457F1C) -> ±1920 x ±1280, 384x256 cells. Past it nothing draws (black).
           Lane H static analysis; verified in game 2026-10-19 (Caribbean and Pacific render, camera pans past x=-1280).
  pfgrid   position -> pathfinding cell (FUN_00b44740 and its inlined copy in FUN_00b575a0): dx = p - grid origin in
           2^20-per-u fixed point is clamped with a signed max(0, dx), so past 2048 u from the origin (x >= 138 u on
           the world grid, origin -1910) dx overflows and maps to cell 0. An AI force rect crossing it gave an inverted
           cell rect and a crash (0xAED830, negative alloc). Patched to an unsigned clamp: dx <= 0xF8000000 (3968 u)
           else 0; the high word is 0 (EAX/EDX are reloaded before use at every site).
  zoom     campaign camera maximum distance (zoom-out cap) 100 -> 250 u.
  astar    the campaign A* on the pathfinding cells. A fleet whose goal is cut off floods the world's ~1M sea cells:
           the visited table, full before it grows and badly hashed, made it hang (AI turn 4 of pt_w11, 2026-10-28),
           and once fast it ran out of memory. Now the table grows at half load, the hash gets a mixing step and a
           search gives up ("no path") at 200k visited nodes. Verified in game on the hanging save.

  python tools/exe_patch.py status|patch|restore [GROUP...] [--exe PATH]     (patch default: all groups)
  python tools/exe_patch.py json      the table for the installer: {sha256, groups: {name: [[offset, orig, new]]}}

patch: only on the known Steam exe (sha256 below); backs up to Napoleon.exe.gn_backup first and always patches from
the backup, so groups can be changed by patching again. restore: copies the backup back. A Steam "verify files" also
restores the original, so patch again after one.
"""
import hashlib, os, shutil, sys

EXE = os.path.expanduser('~/.local/share/Steam/steamapps/common/Napoleon Total War/Napoleon.exe')
VANILLA_SHA256 = '44880ec1770f600163a336eec83b4366901484c5cceec83dc326e2932f02a054'
M1000, P1000, M2048, P2048 = '00007ac4', '00007a44', '000000c5', '00000045'   # -1000f, 1000f, -2048f, 2048f
GROUPS = {  # file offset, original hex, patched hex
    'display': [
        (0xF62CD0, M1000, M2048), (0xF62CD8, M1000, M2048), (0xF62CDC, P1000, P2048),   # tree box min x, min z, max x
        (0x502FC2, P1000, P2048),                                                        # tree max z (immediate)
        (0xF62CE0, M1000, M2048), (0xF62CE8, M1000, M2048), (0xF62CEC, P1000, P2048),   # building box min x, min z, max x
        (0x4FFDB0, P1000, P2048),                                                        # building max z (immediate)
    ],
    'terrain': [
        (0xDC579E, '0000a044', '00002045'), (0xDC57A5, '00002045', '00007045'),        # grid 1 h 1280->2560, w 2560->3840
        (0xDC57AA, '80000000', '00010000'), (0xDC57AF, '00010000', '80010000'),        # grid 1 rows 128->256, cols 256->384
        (0xDC718E, '0000a044', '00002045'), (0xDC7195, '00002045', '00007045'),        # grid 2 h, w
        (0xDC719A, '80000000', '00010000'), (0xDC719F, '00010000', '80010000'),        # grid 2 rows, cols
        (0x105611C, '0000a0c4', '0000f0c4'), (0x1056124, '000020c4', '0000a0c4'),      # draw box min x -1920, min z -1280
        (0x1056128, '0000a044', '0000f044'), (0x1056130, '00002044', '0000a044'),      # draw box max x 1920, max z 1280
    ],
    'pfgrid': [  # cmp esi,ecx; cmovl esi,ecx; mov eax,esi; cdq; mov esi,eax; mov ecx,edx
                 # -> cmp ecx,0xF8000000; cmovbe esi,ecx; xor ecx,ecx; nop   (esi = fixed 0.0 at every site)
        (o, '3bf10f4cf18bc6998bf08bca', '81f9000000f80f46f131c990')
        for o in (0x743BB4, 0x743C40, 0x756A8E, 0x756C74, 0x756D29)   # VA 0xB447B4 y, 0xB44840 x, 0xB5768E y, 0xB57874 x, 0xB57929 x
    ],
    'zoom': [  # tweaker CAMPAIGN_CAMERA_MAXIMUM_DISTANCE default (static init VA 0x41EB51, global 0x15C2FA0) 100 -> 250.
               # set_zoom_limit (VA 0x977CB0) takes fractions of the min..max distance range, so the scripts' 1.0 follows it.
        (0x1DF51, '0000c842', '00007a43'),
    ],
    'astar': [  # the campaign A* (FUN_00ac54c0) visited-cell hash insert (FUN_00b69130) grows 2n+1 only when a full scan
                # finds no empty slot, so it runs 100% full and every miss probes the whole table. A fleet whose goal is
                # cut off (Med behind an enemy force at Gibraltar, 2026-10-28) floods ~1M sea cells and the AI turn hangs.
                # Hook: the entry nop (VA 0xB69139) jumps to a cave (VA 0xA38B80, int3 padding) that sends the insert
                # to the existing grow path (VA 0xB69242, needs [esp+0x10] = capacity) when 2*count + 2 > capacity.
        (0x768539, '0f1f8000000000', 'e942faecff9090'),                        # jmp 0xA38B80; nop; nop
        (0x637F80, 'cc' * 27, '8b46048b5e088d44000239d8'                       # mov eax,[esi+4]; mov ebx,[esi+8]; lea eax,[2*eax+2]; cmp eax,ebx
                              '0f86ae051300'                                   # jbe 0xB69140 (the insert as before)
                              '895c2410e9a7061300'),                           # mov [esp+0x10],ebx; jmp 0xB69242 (grow)
                # The node hash (FUN_00b44f00: (ptr>>2) ^ byte-swapped (y*4095 + x)) falls in a narrow band, so a flood
                # filled one 295k-slot run even at 37% load. Its tail (VA 0xB44F49 pop ebx; pop ecx; ret) jumps to a
                # cave (VA 0xA38BA0) that adds a murmur3 finaliser step. Its 6 callers all reload EDX before use.
        (0x744349, '5b59c3cccc', 'e9523cefff'),                                # jmp 0xA38BA0
        (0x637FA0, 'cc' * 23, '5b5989c2c1ea1031d069c06bcaeb85'                 # pop ebx; pop ecx; h ^= h>>16; h *= 0x85ebca6b
                              '89c2c1ea0d31d0c3'),                             # h ^= h>>13; ret
                # Fast, the 1M-cell flood then ran the 32-bit process out of memory. Cap: the loop's own give-up test
                # (VA 0xAC5961, expansion counter +0xDC > limit +0xE0, which is always 0xFFFFFFFF and only reset by the
                # constructor) now gives up ("no path", as an exhausted open set) once the visited table (+0xC4, count
                # +0xC8, reset when the search source changes) holds 200k nodes. 243k ran without OOM.
        (0x6C4D61, '8b87dc0000003b87e0000000', '8b87c80000003d400d030090'),  # mov eax,[edi+0xc8]; cmp eax,200000; nop
    ],
}


def state(data, group):
    got = [data[o:o + len(bytes.fromhex(a))].hex() for o, a, _ in GROUPS[group]]
    if all(g == a for g, (_, a, _) in zip(got, GROUPS[group])): return 'original'
    if all(g == b for g, (_, _, b) in zip(got, GROUPS[group])): return 'patched'
    return 'unknown'


def patch(data, groups):
    out = bytearray(data)
    for g in groups:
        for o, _, b in GROUPS[g]: out[o:o + len(bytes.fromhex(b))] = bytes.fromhex(b)
    return bytes(out)


def main(argv):
    args = argv[1:]
    exe = EXE
    if '--exe' in args: i = args.index('--exe'); exe = args[i + 1]; del args[i:i + 2]
    cmd = args[0] if args else 'status'
    groups = args[1:] or list(GROUPS)
    if any(g not in GROUPS for g in groups): print('groups:', ', '.join(GROUPS)); return 2
    if cmd == 'json':
        import json; print(json.dumps({'sha256': VANILLA_SHA256, 'groups': {g: [list(e) for e in GROUPS[g]] for g in groups}})); return 0
    bak = exe + '.gn_backup'
    data = open(exe, 'rb').read()
    if cmd == 'status':
        vanilla = hashlib.sha256(data).hexdigest() == VANILLA_SHA256
        print(', '.join(f'{g} {state(data, g)}' for g in GROUPS), '| vanilla sha256' if vanilla else '', '| backup:', os.path.exists(bak))
    elif cmd == 'patch':
        src = open(bak, 'rb').read() if os.path.exists(bak) else data
        if hashlib.sha256(src).hexdigest() != VANILLA_SHA256: print('unknown Napoleon.exe version, not patching'); return 1
        if not os.path.exists(bak): shutil.copy2(exe, bak)
        open(exe, 'wb').write(patch(src, groups)); print('patched', ', '.join(groups), '| backup at', bak)
    elif cmd == 'restore':
        if not os.path.exists(bak): print('no backup'); return 1
        shutil.copy2(bak, exe); print('restored', hashlib.sha256(open(exe, 'rb').read()).hexdigest() == VANILLA_SHA256)
    else:
        print(__doc__); return 2
    return 0


def demo():
    import struct
    blank = bytearray(0x1056140)
    for g in GROUPS:
        for o, a, _ in GROUPS[g]: blank[o:o + len(bytes.fromhex(a))] = bytes.fromhex(a)
    assert all(state(bytes(blank), g) == 'original' for g in GROUPS)
    p = patch(bytes(blank), ['display'])
    assert state(p, 'display') == 'patched' and state(p, 'terrain') == 'original'
    p = patch(p, ['terrain']); assert state(p, 'terrain') == 'patched'
    f = lambda h: struct.unpack('<f', bytes.fromhex(h))[0]
    i = lambda h: struct.unpack('<I', bytes.fromhex(h))[0]
    assert (f(M2048), f(P1000), f('00002045'), f('00007045'), f('0000f0c4'), f('00007a43')) == (-2048, 1000, 2560, 3840, -1920, 250)
    assert (i('80010000'), i('00010000')) == (384, 256)
    p = bytearray(p); p[0x4FFDB0:0x4FFDB4] = b'\0\0\0\0'; assert state(bytes(p), 'display') == 'unknown'


if __name__ == '__main__':
    demo()
    sys.exit(main(sys.argv))
