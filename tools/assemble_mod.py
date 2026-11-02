"""Assemble work/mods/V and V_loc for a built world V: world_m1 base + work/world/V/overlay + flags + loc.  python tools/assemble_mod.py V..."""
import sys, os, csv, shutil, subprocess; sys.path.insert(0,'tools'); import world_build as wb
for v in sys.argv[1:]:
    m=f'work/mods/{v}'; shutil.rmtree(m, ignore_errors=True); shutil.rmtree(m+'_loc', ignore_errors=True)
    subprocess.run(['cp','-a','--reflink=auto','work/mods/world_m1',m],check=True)
    subprocess.run(['cp','-a','--reflink=auto',f'work/world/{v}/overlay/.',m+'/'],check=True)
    if os.path.isdir('work/mods/flags/ui'): subprocess.run(['cp','-a','--reflink=auto','work/mods/flags/.',m+'/'],check=True)
    rows = wb.loc_rows() + [(r['key'], r['text'], int(r['tooltip']=='true')) for r in csv.DictReader(open(f'work/world/{v}/loc_rows.tsv'), delimiter='\t')]
    os.makedirs(m+'_loc/text'); open(m+'_loc/text/localisation.loc','wb').write(wb.localisation(rows)); print(v, len(rows))
