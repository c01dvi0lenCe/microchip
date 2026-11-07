"""Explicit authorization boundary for the frozen S2 confirmatory batch.

This module changes neither prediction gates nor model/scoring semantics.
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import zipfile
import yaml

from ..batch import _write_json
from .spec import StudySpecS2, METHODS, CONDITIONS
from .study import _source_manifest, _run_paired, _audit_study, _digest

FORMAL_SEEDS=tuple(range(263000,263020))
CONFIG_TEXT='''schema: chapter2_s2_confirmatory_v1
mode: simulation
formal_seeds: [263000, 263001, 263002, 263003, 263004, 263005, 263006, 263007, 263008, 263009, 263010, 263011, 263012, 263013, 263014, 263015, 263016, 263017, 263018, 263019]
methods: [B_single_frame, BTQ, BTQ+S, BTQ+K, F_arrival]
conditions: [A_normal, B_flash_short, B_flash_window, C_jump_short, C_jump_persistent, D_tail_false, D_tail_true_cost, E_lowconf_false, E_lowconf_true, E_highconf_false, F_jitter, F_dropout, F_gap]
duration_s: 4.0
followup_s: 1.0
bootstrap_repeats: 2000
figure_example: A_normal_263000
'''


@dataclass(frozen=True)
class ConfirmatorySpecS2(StudySpecS2):
    version: str = 'chapter2_s2_single_task_confirmatory_v1'

    @property
    def study_phase(self):return 'confirmatory'

    def validate_seed(self,seed):
        if type(seed) is not int or seed not in FORMAL_SEEDS:
            raise ValueError('seed outside the frozen confirmatory range')


def load_confirmatory(path):
    content=Path(path).read_text(encoding='utf-8')
    if yaml.safe_load(content)!=yaml.safe_load(CONFIG_TEXT):
        raise ValueError('confirmatory contract changed; no implicit overrides')
    return ConfirmatorySpecS2()


def freeze(config,output):
    spec=load_confirmatory(config);output=Path(output)
    if output.exists():raise FileExistsError(output)
    manifest=_source_manifest(spec)
    manifest.update(config_file_sha256=hashlib.sha256(Path(config).read_bytes()).hexdigest(),
        computation_sha256={k:v for k,v in manifest['source_sha256'].items()
            if Path(k).as_posix()!='dmf/chapter2_sim/s2/plotting.py'},
        formal_seeds=list(FORMAL_SEEDS),conditions=list(CONDITIONS),
        statistics=dict(bootstrap_repeats=2000,unit='paired seed within condition',
            rate_interval='Wilson 95%',contrast_interval='paired percentile bootstrap 95%',
            no_cross_condition_pooling=True),figure_example='A_normal_263000',
        authorization='user requested completion of G1-G5 and S2 figures, 2026-10-25',
        limitations=['D_tail_true_cost does not isolate correct-confirmation loss',
                    'synthetic stress is not validated droplet deformation'])
    manifest['seal_sha256']=_digest(manifest)
    output.mkdir(parents=True)
    _write_json(output/'freeze_manifest.json',manifest)
    repo=Path(__file__).resolve().parents[3]
    with zipfile.ZipFile(output/'source_snapshot.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for path in manifest['source_sha256']:archive.write(repo/path,path)
        archive.write(config,'frozen_config.yaml')
    return manifest


def verify_seal(config,seal):
    spec=load_confirmatory(config)
    saved=json.loads((Path(seal)/'freeze_manifest.json').read_text(encoding='utf-8'))
    core={k:v for k,v in saved.items() if k!='seal_sha256'}
    if _digest(core)!=saved['seal_sha256']:raise ValueError('freeze manifest tampered')
    if hashlib.sha256(Path(config).read_bytes()).hexdigest()!=saved['config_file_sha256']:
        raise ValueError('configuration bytes changed after freeze')
    current=_source_manifest(spec)
    current_computation={k:v for k,v in current['source_sha256'].items()
        if Path(k).as_posix()!='dmf/chapter2_sim/s2/plotting.py'}
    if current_computation!=saved['computation_sha256']:raise ValueError('computation source changed after freeze')
    if _digest(current['config'])!=_digest(saved['config']):raise ValueError('effective configuration changed')
    return saved


def run_confirmatory(output,spec):
    if spec.study_phase!='confirmatory':raise ValueError('formal entry rejects development specification')
    return _run_paired(output,spec,conditions=CONDITIONS,seeds=FORMAL_SEEDS)


def audit_confirmatory(output):
    from collections import Counter
    from .study import _rows
    planned=_rows(Path(output)/'plan.csv')
    expected=Counter((f'{c}_{s}',c,str(s),m) for c in CONDITIONS for s in FORMAL_SEEDS for m in METHODS)
    if Counter((r['cache_id'],r['condition'],r['seed'],r['method']) for r in planned)!=expected:
        raise ValueError('formal plan differs from frozen full condition/seed/method product')
    aux=_rows(Path(output)/'diagnostic_scores.csv')
    if Counter((r['cache_id'],r['condition'],r['seed'],r['method']) for r in aux)!=Counter(
            (f'{c}_{s}',c,str(s),'BQ_single_frame') for c in CONDITIONS for s in FORMAL_SEEDS):
        raise ValueError('auxiliary diagnostic ledger incomplete or duplicated')
    result=_audit_study(output,'confirmatory',FORMAL_SEEDS)
    if result['planned_rows']!=1300 or result['independent_references_recomputed']!=260:
        raise ValueError('incomplete confirmatory plan')
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('freeze','run','audit','analyse'))
    parser.add_argument('--config',default='configs/chapter2_s2_confirmatory.yaml')
    parser.add_argument('--seal');parser.add_argument('--output',required=True)
    args=parser.parse_args()
    if args.action=='freeze':result=freeze(args.config,args.output)
    elif args.action=='run':
        if not args.seal:parser.error('--seal required for formal execution')
        seal=verify_seal(args.config,args.seal)
        result=run_confirmatory(args.output,load_confirmatory(args.config))
        _write_json(Path(args.output)/'seal_link.json',dict(seal_sha256=seal['seal_sha256'],
            freeze_manifest=str(Path(args.seal).resolve()/'freeze_manifest.json')))
        verify_seal(args.config,args.seal)
    elif args.action=='audit':
        result=audit_confirmatory(args.output)
        _write_json(Path(args.output)/'integrity_audit.json',result)
    else:
        from .statistics import analyse
        result=analyse(args.output)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
