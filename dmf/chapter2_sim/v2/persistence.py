"""Append-only trial directories. Observation Mask bytes and scoring are separate."""
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
import platform
import subprocess

import cv2
import numpy as np

from dmf.chapter2_sim.batch import _write_csv,_write_json


def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_trial(trial,output,spec):
    output=Path(output)
    if output.exists():raise FileExistsError('trial directory already exists; frozen outputs are never overwritten')
    output.mkdir(parents=True)
    obs=output/'observations';ev=output/'evaluation';masks=obs/'masks'
    masks.mkdir(parents=True);ev.mkdir()
    captures=[]
    for item in trial.captures:
        row={k:v for k,v in item.items() if k!='mask'}
        if item['mask'] is not None:
            relative=f"observations/masks/frame-{item['frame_id']:06d}.png";path=output/relative
            ok,encoded=cv2.imencode('.png',item['mask'])
            if not ok:raise OSError('Mask PNG encode failed')
            path.write_bytes(encoded.tobytes());row.update(mask_path=relative,mask_sha256=sha256(path))
        else:row.update(mask_path=None,mask_sha256=None)
        captures.append(row)
    _write_csv(obs/'captures.csv',captures);_write_csv(obs/'frames.csv',trial.frames);_write_csv(obs/'gate_trace.csv',trial.gates)
    _write_csv(obs/'events.csv',[e for e in trial.events if e['event'] not in ('TruthArrival',)])
    _write_csv(ev/'truth_ticks.csv',trial.truth);_write_csv(ev/'reference_intervals.csv',trial.references)
    _write_csv(ev/'event_evaluation.csv',trial.event_evaluation);_write_csv(ev/'step_outcomes.csv',trial.steps)
    _write_csv(output/'trials.csv',[trial.metrics]);_write_json(output/'electrode_map_snapshot.json',trial.geometry)
    _write_json(output/'config_snapshot.json',asdict(spec))
    # Preserve the exact legacy bridge view for semantic equality checks.
    _write_json(output/'legacy_view.json',dict(metrics=trial.legacy.metrics,frames=trial.legacy.frames,truth=trial.legacy.truth,events=trial.legacy.events))
    root=Path(__file__).resolve().parents[3]
    sources={str(p.relative_to(root)):sha256(p) for p in list(Path(__file__).parent.glob('*.py'))+[Path(__file__).parents[1]/n for n in ('world.py','vision.py','formal_adapter.py','formal_runner.py')]}
    repo=root
    manifest=dict(simulation=True,purpose='development_smoke_not_formal_performance',trial_id=trial.trial_id,method=trial.method,phase_mode=trial.phase_mode,
        source_hashes=sources,repository_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo).decode().strip(),
        config=asdict(spec),map_origin=trial.geometry['metadata'],python=platform.python_version(),numpy=np.__version__,opencv=cv2.__version__,
        mask_origin='actual_SyntheticCamera_output_in_this_independent_run',clock_domain='simulation',coordinate_unit='pitch',physical_timing_validated=False,
        files={str(p.relative_to(output)):sha256(p) for p in output.rglob('*') if p.is_file()})
    _write_json(output/'trial_manifest.json',manifest)
    return output


def load_trial(path):
    path=Path(path);manifest=json.loads((path/'trial_manifest.json').read_text(encoding='utf-8'))
    for name,h in manifest['files'].items():
        if sha256(path/name)!=h:raise ValueError('persisted input hash mismatch: '+name)
    def read(name):
        with (path/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
    return dict(manifest=manifest,captures=read('observations/captures.csv'),frames=read('observations/frames.csv'),gates=read('observations/gate_trace.csv'),
                events=read('observations/events.csv'),truth=read('evaluation/truth_ticks.csv'),references=read('evaluation/reference_intervals.csv'),path=path,
                geometry=json.loads((path/'electrode_map_snapshot.json').read_text(encoding='utf-8')))
