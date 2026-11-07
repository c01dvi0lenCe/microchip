"""Pre-run immutable provenance and a one-use batch claim; freezing performs no random draws."""
import csv
import hashlib
import json
import platform
from pathlib import Path
import shutil
import sys
import cv2
import numpy as np
import shapely
from .spec import ROOT,SEEDS,PLAN,VERSION,load_protocol,planned_identities,validate_formal_seeds

RESULTS_ROOT=Path('D:/Learn/ZJU/第二章 单液滴视觉闭环/仿真结果')
BATCH_REGISTRY=ROOT/'.planning/geometry_exp1b_formal_20261029/approved_batch_claim.json'


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,
        allow_nan=False).encode('utf-8')).hexdigest()


def js(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def environment():
    return dict(python=sys.version,python_executable=str(Path(sys.executable).resolve()),
        numpy=np.__version__,opencv=cv2.__version__,shapely=shapely.__version__,
        platform=platform.platform(),machine=platform.machine(),byteorder=sys.byteorder)


def source_inventory(config):
    # Include all local Python dependencies, not only the top-level runner imports.
    files=set((ROOT/'dmf').rglob('*.py'))
    files.update([ROOT/'run_chapter2_geometry_exp1b_formal.py',ROOT/'tests/test_geometry_exp1b_formal.py',
        Path(config['effective_config_path']),Path(config['development_wrapper_path']),Path(config['base_path']),
        Path(config['geometry']['map_path'])])
    shape=Path(config['geometry']['shape_source'])
    for relative in ('trial/world.csv','trial/world_polygons.json','trial/manifest.json',
        'shape_inputs/shape_library.json','visualization/render_manifest.json'):
        files.add(shape/relative)
    # Original shape inputs and the baseline manifest's code/artifact dependencies.
    library=json.loads((shape/'shape_inputs/shape_library.json').read_text(encoding='utf-8'))
    for item in library['inputs']:
        files.update(shape/'shape_inputs'/item[k] for k in ('image_path','mask_path'))
    baseline=json.loads((shape/'trial/manifest.json').read_text(encoding='utf-8'))
    files.update(Path(p) for p in baseline['source_code'])
    files.update(shape/'trial'/p for p in baseline['artifacts'])
    return {str(p.resolve()):sha(p) for p in sorted(files,key=lambda p:str(p.resolve()))}


def validate_verification(evidence):
    for key in ('protocol_approved','explicit_run_approval','spec_review_passed','quality_review_passed'):
        if evidence.get(key) is not True:raise ValueError('Missing positive verification evidence: '+key)
    tests=evidence.get('tests')
    if not isinstance(tests,list) or not tests or any(not isinstance(t,dict)
        or not isinstance(t.get('command'),str) or not t['command'].strip()
        or type(t.get('exit_code')) is not int or t['exit_code']!=0 for t in tests):
        raise ValueError('Successful named test commands with integer exit_code=0 required')


def scan_seed_use(root=RESULTS_ROOT):
    root=Path(root).resolve()
    if not root.is_dir():raise FileNotFoundError('Declared prior-results scope missing: '+str(root))
    files=[];used=set();findings=[]
    actual_keys=('actual_formal_seeds','actual_development_seeds','actual_seeds','executed_seeds','seed')
    for path in sorted(root.rglob('*')):
        if not path.is_file():continue
        relative=path.relative_to(root)
        # Provenance/code/config snapshots reserve identities, they are not actual execution evidence.
        if any(part.lower() in ('provenance','source_snapshots','source_snapshot','snapshots') for part in relative.parts):continue
        is_csv=path.suffix.lower()=='.csv'
        is_manifest=path.name.lower() in ('manifest.json','run_manifest.json','draw.json')
        if not (is_csv or is_manifest):continue
        found=set()
        try:
            if is_csv:
                with path.open(encoding='utf-8-sig',newline='') as stream:
                    rows=csv.DictReader(stream)
                    keys=[k for k in (rows.fieldnames or []) if k in ('seed','actual_seed','trial_seed')]
                    for row in rows:
                        for key in keys:
                            value=row.get(key,'')
                            if value and str(value).strip().isdigit() and int(value) in SEEDS:found.add(int(value))
            else:
                data=json.loads(path.read_text(encoding='utf-8-sig'))
                for key in actual_keys:
                    values=data.get(key,[]) if isinstance(data,dict) else []
                    if not isinstance(values,list):values=[values]
                    found.update(int(v) for v in values if type(v) is int and v in SEEDS)
        except (UnicodeError,csv.Error,json.JSONDecodeError) as error:
            raise ValueError('Cannot inspect declared actual-record candidate: '+str(path)) from error
        files.append(dict(path=relative.as_posix(),sha256=sha(path)))
        if found:findings.append(dict(path=relative.as_posix(),formal_seeds=sorted(found)))
        used.update(found)
    return dict(scope=str(root),scope_kind='all CSV seed fields and actual-run/draw manifests; not text reservations or source snapshots',
        used_formal_seeds=sorted(used),findings=findings,files=files,inventory_sha256=canonical_sha(files))


def create_freeze(output,verification_path,config_path=None,config=None):
    if BATCH_REGISTRY.exists():raise FileExistsError('Approved formal batch already claimed: '+str(BATCH_REGISTRY))
    config=config or load_protocol(config_path)
    output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    evidence_path=Path(verification_path).resolve()
    evidence=json.loads(evidence_path.read_text(encoding='utf-8'))
    validate_verification(evidence)
    inventory=source_inventory(config)
    scope=scan_seed_use()
    if scope['used_formal_seeds']:raise ValueError('Formal seeds already used in declared actual records')
    frozen=dict(schema='exp1b_formal_freeze_v1',version=VERSION,maximum_batches=1,
        seeds=list(SEEDS),plan=dict(PLAN),planned_identities=planned_identities(config),
        config=config,config_sha256=canonical_sha(config),environment=environment(),source_hashes=inventory,
        rng_contract=config['rng'],TF_revision=config['TF_revision'],
        verification=evidence,verification_source=str(evidence_path),verification_sha256=sha(evidence_path),
        prior_seed_scan=scope,formal_rng_initialized=False)
    output.mkdir(parents=True)
    shutil.copyfile(evidence_path,output/'verification.json')
    snapshots=[]
    for index,(source,digest) in enumerate(inventory.items()):
        dest=output/'source_snapshots'/f'{index:04d}_{Path(source).name}'
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
        snapshots.append(dict(source=source,relative=dest.relative_to(output).as_posix(),sha256=digest))
    frozen['snapshots']=snapshots
    frozen['freeze_payload_sha256']=canonical_sha(frozen)
    js(output/'freeze.json',frozen)
    return output/'freeze.json'


def verify_freeze_data(frozen,config):
    if frozen.get('schema')!='exp1b_formal_freeze_v1' or frozen.get('version')!=VERSION:
        raise ValueError('Unsupported formal freeze')
    validate_formal_seeds(frozen.get('seeds',[]));validate_verification(frozen.get('verification',{}))
    if (frozen.get('plan')!=PLAN or frozen.get('maximum_batches')!=1
        or frozen.get('config')!=config or frozen.get('config_sha256')!=canonical_sha(config)
        or frozen.get('planned_identities')!=[list(k) for k in planned_identities(config)]
        or frozen.get('environment')!=environment() or frozen.get('formal_rng_initialized') is not False
        or frozen.get('rng_contract')!=config['rng'] or frozen.get('TF_revision')!=config['TF_revision']):
        raise ValueError('Frozen code/config/environment/identity contract mismatch')
    expected=dict(frozen);digest=expected.pop('freeze_payload_sha256',None)
    if digest!=canonical_sha(expected):raise ValueError('Freeze payload was modified')


def verify_freeze(path,config_path=None,config=None,check_unused=True):
    if path is None:raise ValueError('A verified freeze file is mandatory')
    path=Path(path).resolve();frozen=json.loads(path.read_text(encoding='utf-8'))
    config=config or load_protocol(config_path)
    verify_freeze_data(frozen,config)
    if frozen['source_hashes']!=source_inventory(config):raise ValueError('Source/input/config inventory changed since freeze')
    for source,digest in frozen['source_hashes'].items():
        if sha(source)!=digest:raise ValueError('Frozen source/input changed: '+source)
    for item in frozen['snapshots']:
        if sha(path.parent/item['relative'])!=item['sha256']:raise ValueError('Frozen source snapshot changed')
    if sha(path.parent/'verification.json')!=frozen['verification_sha256']:
        raise ValueError('Verification evidence changed')
    if check_unused:
        if BATCH_REGISTRY.exists():raise FileExistsError('Approved formal batch already claimed: '+str(BATCH_REGISTRY))
        current=scan_seed_use(Path(frozen['prior_seed_scan']['scope']))
        if current['used_formal_seeds']:raise ValueError('Formal seeds already used; no repeat batch')
    return frozen


def claim_batch(freeze_path,output):
    freeze_path=Path(freeze_path).resolve();path=freeze_path.parent/'batch_claim.json'
    if path.exists():raise FileExistsError(path)
    frozen=json.loads(freeze_path.read_text(encoding='utf-8'))
    claim=dict(output=str(Path(output).resolve()),formal_seeds=list(SEEDS),no_rerun=True,
        freeze_path=str(freeze_path),freeze_sha256=sha(freeze_path),source_hashes=frozen['source_hashes'])
    # This exclusive claim is shared across every freeze and output directory.
    BATCH_REGISTRY.parent.mkdir(parents=True,exist_ok=True)
    with BATCH_REGISTRY.open('x',encoding='utf-8') as stream:json.dump(claim,stream,indent=2)
    with path.open('x',encoding='utf-8') as stream:json.dump(claim,stream,indent=2)
