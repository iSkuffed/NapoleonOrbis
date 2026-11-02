"""Release payload for the installer (installer/README.md "Payload"): work/mods/world_m1 + work/world/V/overlay + flags as
zz_gn_world.pack, V's startpos, our loc rows only (the installer merges them on the player's machine), exe patch json.

    python tools/make_payload.py V VERSION [OUT=installer/payload]
"""
import csv, json, os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
import packtool, world_build as wb

ROOT = os.path.join(os.path.dirname(__file__), '..')


def esc(s):
    return s.replace('\\', '\\\\').replace('\t', '\\t').replace('\n', '\\n').replace('\r', '\\r')


def tsv(rows):
    keys = [k for k, _, _ in rows]
    assert len(keys) == len(set(keys)), 'duplicate loc keys'
    return 'key\ttext\ttooltip\n' + ''.join(f'{esc(k)}\t{esc(t)}\t{"true" if tip else "false"}\n' for k, t, tip in rows)


def main(v, version, out=os.path.join(ROOT, 'installer/payload')):
    src = os.path.join(ROOT, 'work/world', v)
    rows = dict((k, (k, t, tip)) for k, t, tip in wb.loc_rows())
    if os.path.exists(src + '/loc_rows.tsv'):
        for r in csv.DictReader(open(src + '/loc_rows.tsv', encoding='utf-8'), delimiter='\t'):
            rows[r['key']] = (r['key'], r['text'], r['tooltip'] == 'true')
    shutil.rmtree(out, ignore_errors=True); os.makedirs(out)
    with tempfile.TemporaryDirectory(dir=os.path.join(ROOT, 'work')) as t:   # not /tmp: tmpfs is RAM
        subprocess.run(['cp', '-a', '--reflink=auto', os.path.join(ROOT, 'work/mods/world_m1/.'), t], check=True)
        if os.path.isdir(src + '/overlay'):
            subprocess.run(['cp', '-a', '--reflink=auto', src + '/overlay/.', t], check=True)
        if os.path.isdir(os.path.join(ROOT, 'work/mods/flags/ui')):        # tools/flags.py output (our own art)
            subprocess.run(['cp', '-a', '--reflink=auto', os.path.join(ROOT, 'work/mods/flags/.'), t], check=True)
        packtool.build(out + '/zz_gn_world.pack', t)
    shutil.copy(src + '/startpos.esf', out + '/startpos.esf')
    open(out + '/loc_rows.tsv', 'w', encoding='utf-8', newline='').write(tsv(list(rows.values())))
    open(out + '/exe_patch.json', 'wb').write(subprocess.run(
        [sys.executable, os.path.join(ROOT, 'tools/exe_patch.py'), 'json'], check=True, capture_output=True).stdout)
    json.dump({'version': version, 'mod_packs': ['zz_gn_world.pack'], 'startpos': 'startpos.esf',
               'loc_rows': 'loc_rows.tsv', 'exe_patch': 'exe_patch.json'}, open(out + '/manifest.json', 'w'), indent=1)
    print(out, len(rows), 'loc rows')


if __name__ == '__main__':
    assert tsv([('a\tb', 'x\\y\n', 1)]) == 'key\ttext\ttooltip\na\\tb\tx\\\\y\\n\ttrue\n'
    main(*sys.argv[1:])
