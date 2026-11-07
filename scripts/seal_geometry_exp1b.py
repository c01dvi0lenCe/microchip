"""Archive direct research sources and model inputs; never changes raw outputs."""
import json
from pathlib import Path
import platform
import shutil
import sys
import zipfile
import cv2
import numpy
import shapely
import matplotlib

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.exp1b.audit import load,sha
from dmf.chapter2_geometry_sim.sdf_trial import js,OUT as BASE

CH=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
DATA=CH/'仿真结果/2026-10-29_实验一B_固定机制核查_r2'
REPORT=CH/'审查材料/2026-10-29_实验一B固定机制_Chat审查包_v1'


if __name__=='__main__':
    snapshot=REPORT/'source_snapshot';snapshot.mkdir(exist_ok=False)
    files=list((ROOT/'dmf/chapter2_geometry_sim').rglob('*.py'))
    files += [ROOT/p for p in ['dmf/experiment/evidence.py','dmf/vision/design_registration.py',
        'run_chapter2_geometry_exp1b.py','scripts/check_geometry_exp1b.py','scripts/plot_geometry_exp1b.py',
        'scripts/verify_geometry_exp1b.py','scripts/package_geometry_exp1b_review.py','scripts/seal_geometry_exp1b.py',
        'tests/test_geometry_exp1b.py','docs/chapter2-geometry-exp1b-baseline-audit-2026-10-29.md',
        'docs/chapter2-geometry-exp1b-implementation-2026-10-29.md',
        'docs/superpowers/specs/2026-10-29-geometry-arrival-exp1b-design.md',
        'docs/superpowers/plans/2026-10-29-geometry-exp1b-execution.md']]
    records=[]
    for source in files:
        dest=snapshot/'repository'/source.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,dest);records.append(dict(source=str(source),snapshot=str(dest.relative_to(snapshot)),sha256=sha(dest)))
    for source in (BASE/'shape_inputs').rglob('*'):
        if source.is_file():
            dest=snapshot/'frozen_shape_inputs'/source.relative_to(BASE/'shape_inputs')
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
            records.append(dict(source=str(source),snapshot=str(dest.relative_to(snapshot)),sha256=sha(dest)))
    for rel in ['config.json','map_snapshot.json','baseline_entries.json','manifest.json']:
        dest=snapshot/'run_metadata'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(DATA/rel,dest)
        records.append(dict(source=str(DATA/rel),snapshot=str(dest.relative_to(snapshot)),sha256=sha(dest)))
    environment=dict(python=platform.python_version(),platform=platform.platform(),numpy=numpy.__version__,
        opencv=cv2.__version__,shapely=shapely.__version__,matplotlib=matplotlib.__version__,
        code_is_direct_research_sources_not_complete_repository=True,
        note='Raw datasets remain at traceability-index paths; no original file moved or overwritten.')
    js(snapshot/'environment.json',environment);js(snapshot/'source_inventory.json',records)
    archive=REPORT/'源码与协议快照.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in snapshot.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(snapshot).as_posix())
    js(REPORT/'封存补充索引.json',dict(archive=str(archive),sha256=sha(archive),
        report_manifest_sha256=sha(REPORT/'交付manifest.json'),raw_manifest_sha256=sha(DATA/'manifest.json'),
        source_records=len(records),environment=environment,original_results_changed=False))
    print(archive)
