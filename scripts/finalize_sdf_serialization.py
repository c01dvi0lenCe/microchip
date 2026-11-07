"""Repair only integer ID representation before first acceptance; retain raw."""
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.sdf_trial import OUT,canonical_ids,sha,js,audit_empirical
from dmf.chapter2_geometry_sim.audit import read_rows
from dmf.chapter2_geometry_sim.single_step import write_csv


def finalize():
    trial=OUT/'trial';qa=OUT/'preacceptance_serialization_record';qa.mkdir(exist_ok=False)
    for name in ('world.csv','events.csv','manifest.json'):shutil.copyfile(trial/name,qa/name)
    for name in ('world.csv','events.csv'):
        original=read_rows(trial/name);repaired=[canonical_ids(r) for r in original]
        for before,after in zip(original,repaired):
            for key in before:
                if key not in ('active','target','source','activation_segment','frame_id') and before[key]!=after[key]:
                    raise ValueError('unexpected non-ID change')
        write_csv(trial/name,repaired)
    manifest=json.loads((trial/'manifest.json').read_text(encoding='utf-8'))
    manifest['source_code']={p:sha(p) for p in manifest['source_code']}
    manifest['artifacts']={name:sha(trial/name) for name in manifest['artifacts']}
    manifest['preacceptance_serialization_fix']=dict(record_directory=str(qa),
        changed_fields=['world active/activation_segment','events target/frame_id integer representation'],
        trajectory_masks_features_predictions_reference_changed=False,new_simulation_runs=0)
    js(trial/'manifest.json',manifest)
    audit=audit_empirical(trial);js(OUT/'independent_audit.json',audit)
    print(json.dumps(audit,ensure_ascii=False,indent=2))
    if not audit['passed']:raise ValueError(audit)


if __name__=='__main__':finalize()
