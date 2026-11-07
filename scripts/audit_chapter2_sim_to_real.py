"""Read-only source/resource audit; never imports controllers or simulation models."""
from pathlib import Path
import csv
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = Path('D:/Learn/ZJU/第二章 单液滴视觉闭环')
SIM = BASE / '仿真结果'
OUT = SIM / '2026-10-26_S3仿真与实物对应性审查_v1'

def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / '只读审查证据.json'
    if target.exists():
        raise FileExistsError(target)
    resource = BASE / '真实分割研究/2026-10-21_第一阶段与Pilot_v1/resource_manifest.json'
    snapshot = BASE / '真实分割研究/2026-10-21_Pilot分割基线_v2_同轮采集确认/reviewed_snapshot'
    videos = load(resource)['videos']
    samples = load(snapshot / 'snapshot_manifest.json')
    video_checks = []
    for r in videos:
        p = Path(r['source'])
        video_checks.append(dict(path=str(p), exists=p.is_file(), sha256=sha(p),
            expected=r['sha256'], hash_match=sha(p)==r['sha256'],
            exposure_timing_verified=r.get('exposure_timing_verified'),
            timing_sidecar_status=r.get('timing_sidecar_status')))
    mask_checks = []
    for r in samples:
        p = snapshot / r['mask_path']
        image = snapshot / r['frame_path']
        mask_checks.append(dict(path=str(p), reviewed=r['mask_reviewed'], state=r['state_gt'],
            split=r['split'], mask_hash_match=sha(p)==r['mask_path_sha256'],
            image_hash_match=sha(image)==r['frame_path_sha256']))
    map_path = BASE / '电极数字地图/2026-10-21_FBC6-3_真实轮廓_编号确认_v1/electrode_design_map.json'
    design = load(map_path)
    reg_root = BASE / '图像—电极配准/2026-10-23_清晰照片_配准预实验_v1'
    registration = []
    for p in reg_root.rglob('registration_result.json'):
        r = load(p)
        registration.append(dict(path=str(p), sha256=sha(p), **{k:r.get(k) for k in
            ('status','check_confirmed','rmse_px','p95_px','max_px','use_scope',
             'final_experiment_calibration_approved','transfer_to_old_videos_verified')}))
    repeat_path = BASE / '图像—电极配准/2026-10-23_粗范围辅助点选_v1/reports/20261023T102055_038372_6023ec/repeatability_result.json'
    repeat = load(repeat_path)
    weights = sorted(str(p) for top in (ROOT, BASE) for p in top.rglob('*')
        if p.is_file() and p.suffix.lower() in ('.onnx','.pt','.pth','.torchscript'))
    g3 = SIM / '2026-10-26_S3_G3协议冻结_v1'
    formal = SIM / '2026-10-26_S3正式仿真_v1'
    accept = SIM / '2026-10-26_S3正式验收与论文图_v1'
    index = load(accept / 'QA/formal_frozen_input_index.json')
    expected = {str(formal / name): h for name,h in index.items()}
    for name in index:
        if name.endswith('trial_manifest.json'):
            p = formal / name
            for rel,h in load(p)['files'].items():
                expected[str(p.parent / rel)] = h
    # Preserve original source, S1/S2 and all 120 development records.
    expected.update(load(g3 / 'QA/protected_before.json'))
    changed = []
    for i,(name,h) in enumerate(expected.items()):
        p = Path(name)
        if not p.is_file() or sha(p) != h:
            changed.append(name)
        if i % 25000 == 0:
            print('protected files checked:', i, flush=True)
    audit = load(accept / 'QA/independent_final_audit.json')
    g3audit = load(g3 / 'QA/g3_audit.json')
    source_paths = [p for top in ('dmf','controllers','configs','tests')
        for p in (ROOT / top).rglob('*') if p.is_file() and p.suffix in ('.py','.yaml','.json')]
    result = dict(schema='chapter2_s3_sim_to_real_read_only_audit_v1',
        new_trials=0, hardware_connections=0, inference_calls=0,
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        git_status=subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True,encoding='utf-8'),
        video_checks=video_checks, reviewed_mask_checks=mask_checks,
        map=dict(path=str(map_path),sha256=sha(map_path),electrode_count=design['electrode_count'],
            actual_rows=len(design['electrodes']),pitch_mm=design['pitch_mm'],binding=design['binding'],
            electrical_continuity_verified=design['electrical_continuity_verified'],
            as_manufactured_geometry_verified=design['as_manufactured_geometry_verified']),
        registrations=registration,
        assisted_repeatability=dict(path=str(repeat_path),sha256=sha(repeat_path),
            **{k:repeat[k] for k in ('strict_blind','observed_counts','confirmed_counts',
                'rmse_between_rounds_px','p95_distance_px','max_distance_px')}),
        weight_search=dict(roots=[str(ROOT),str(BASE)],paths=weights),
        configured_sdk_path_exists=Path('E:/工业相机驱动/setup/MVS/Development/Samples/Python/MvImport').exists(),
        previous_final_audit=dict(path=str(accept / 'QA/independent_final_audit.json'),
            sha256=sha(accept / 'QA/independent_final_audit.json'),keys=list(audit),
            passed=audit.get('passed')),previous_g3_audit_keys=list(g3audit),
        protected=dict(checked_files=len(expected),changed=changed,passed=not changed),
        current_source_sha256={str(p.relative_to(ROOT)):sha(p) for p in source_paths})
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(protected=result['protected'],videos=len(videos),masks=len(samples),
        weights=weights,registration_reports=len(registration)),ensure_ascii=True),flush=True)
    assert not changed
    assert all(r['hash_match'] for r in video_checks)
    assert all(r['mask_hash_match'] and r['image_hash_match'] for r in mask_checks)

if __name__ == '__main__':
    main()
