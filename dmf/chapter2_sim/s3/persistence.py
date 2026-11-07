"""Reuse lossless Mask/CSV writer; add S3 source and schema provenance."""
from pathlib import Path
import json
import shutil
from ..v2.persistence import save_trial as save_v2,load_trial,sha256
from ..batch import _write_json

def save_trial(trial,output,spec):
    output=save_v2(trial,output,spec)
    manifest=json.loads((output/'trial_manifest.json').read_text(encoding='utf-8'))
    root=Path(__file__).resolve().parents[3];sources=output/'source_code';sources.mkdir()
    files={root/name for name in manifest['source_hashes']}
    for folder in ('dmf/experiment','dmf/vision','dmf/chapter2_sim/s3'):
        files.update((root/folder).glob('*.py'))
    files.update(root/'dmf/chapter2_sim'/name for name in ('config.py','geometry.py','runner.py','batch.py'))
    files.update((root/'dmf/chapter2_sim/s2/spec.py',root/'run_chapter2_s3.py'))
    manifest['source_hashes']={}
    for p in sorted(files):
        relative=p.relative_to(root);target=sources/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,target);manifest['source_hashes'][relative.as_posix()]=sha256(p)
    manifest.update(schema='chapter2_s3_development_v1',method_version=trial.metrics['method_version'],
        cohort=trial.metrics['cohort'],protection=trial.metrics['protection'],exogenous=trial.metrics['exogenous'],
        common_source_prefix_sha256=trial.metrics['p0_prefix_hash'],
        boundary='SIMULATION; 2D point motion, synthetic circular Mask, pitch units; not CFD, U-Net or physical EWOD',
        reference_version='s3_activation_position_speed_contiguous_dwell_v1',formal_seed_runs=0)
    manifest['files']={str(p.relative_to(output)).replace('\\','/'):sha256(p) for p in output.rglob('*') if p.is_file() and p.name!='trial_manifest.json'}
    _write_json(output/'trial_manifest.json',manifest);return output
