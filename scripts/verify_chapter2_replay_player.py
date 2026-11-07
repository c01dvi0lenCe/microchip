"""Audit final replay artifacts, original fields and protected input inventory."""
import argparse
import csv
import json
from pathlib import Path
import subprocess

from dmf.chapter2_replay.data import sha,audit_bundle
from dmf.chapter2_replay.export import load_verified_bundle
from dmf.chapter2_sim.v2.replay import PersistedReplay


def csv_value(value,expected):
    if expected is None:return None if value=='' else value
    if isinstance(expected,(int,float)):return float(value)
    return value


def run(root,protected):
    root=Path(root);b=load_verified_bundle(root);r=PersistedReplay(b['source_trial']);a=audit_bundle(b,r.path)
    out=root/'检查结果';out.mkdir(exist_ok=True)
    def write(name,rows):
        with (out/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    field_checks=[]
    for e,shown in zip(r.events,b['events']):
        for key in e:field_checks.append(dict(csv_line=e['csv_line'],time_s=e['time_s'],event=e['event'],field=key,original=json.dumps(e[key],ensure_ascii=False),player=json.dumps(shown.get(key),ensure_ascii=False),matched=e[key]==shown.get(key)))
    write('event_field_checks.csv',field_checks)
    reference_checks=[]
    for e,shown in zip(r.references,b['references']):
        for key in e:reference_checks.append(dict(csv_line=e['csv_line'],field=key,original=json.dumps(e[key],ensure_ascii=False),player=json.dumps(shown.get(key),ensure_ascii=False),matched=e[key]==shown.get(key)))
    write('reference_field_checks.csv',reference_checks)
    m=json.loads((root/'source_manifest.json').read_text(encoding='utf-8'));e=json.loads((root/'视频与关键帧/export_manifest.json').read_text(encoding='utf-8'))
    artifact_changes=[name for name,h in e['files'].items() if sha(root/'视频与关键帧'/name)!=h]
    if sha(root/'DMF单液滴仿真播放器.html')!=m['html_sha256']:artifact_changes.append('html')
    code_changes=[name for name,h in m['code_sha256'].items() if sha(name)!=h]
    with (root/'视频与关键帧/frame_index.csv').open(encoding='utf-8-sig',newline='') as f:index=list(csv.DictReader(f))
    index_errors=[]
    for i,(row,t) in enumerate(zip(index,b['ticks'])):
        for field,expected in [('simulation_time_s',t['time_s']),('state',t['state']),('action',t['action']),('world_active',t['truth']['world_active']),('epoch',t['truth']['epoch'])]:
            value=csv_value(row[field],expected)
            if value!=expected:index_errors.append(f'{i}:{field}')
        if json.loads(row['events_now'])!=t['events_now']:index_errors.append(f'{i}:events_now')
    p=json.loads(Path(protected).read_text(encoding='utf-8'));old=json.loads(Path(p['inventory_source']).read_text(encoding='utf-8'))
    changed=[name for name,h in p['files'].items() if sha(name)!=h]
    inventory=[name for name,value in old['frozen_inventory'].items() if not Path(name).exists() or [Path(name).stat().st_size,Path(name).stat().st_mtime_ns]!=value]
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    report=dict(trial_id=b['trial_id'],audit=a,event_fields=len(field_checks),reference_fields=len(reference_checks),all_event_fields_match=all(x['matched'] for x in field_checks),all_reference_fields_match=all(x['matched'] for x in reference_checks),video_frames=e['decoded_frames'],video_index_rows=len(index),video_index_errors=index_errors,artifact_changes=artifact_changes,code_changes=code_changes,protected_files=len(p['files']),protected_changes=changed,frozen_v1_inventory_count=len(old['frozen_inventory']),inventory_check='size_and_mtime_ns_not_full_rehash',frozen_v1_changes=inventory,head_unchanged=head==p['git_head'],new_simulation_runs=0)
    report['passed']=a['passed'] and report['all_event_fields_match'] and report['all_reference_fields_match'] and not(index_errors or artifact_changes or code_changes or changed or inventory) and len(index)==len(b['ticks']) and e['bundle_sha256']==m['bundle_sha256'] and report['head_unchanged']
    (out/'final_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='audit'},ensure_ascii=False))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--player-root',type=Path,required=True);p.add_argument('--protected',type=Path,required=True);a=p.parse_args();run(a.player_root,a.protected)
