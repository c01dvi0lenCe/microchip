"""One immutable replay bundle consumed by both the browser and video exporter."""
import base64
import bisect
import hashlib
import json
from pathlib import Path

from dmf.chapter2_sim.v2.replay import PersistedReplay


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tick_index(bundle,time_s):
    times=bundle['times']
    if not times[0]<=time_s<=times[-1]+1e-9:raise ValueError('outside recorded time')
    return bisect.bisect_right(times,time_s+1e-9)-1


def build_bundle(path):
    r=PersistedReplay(path);ticks=[];masks={}
    for c in r.captures:
        if c.get('mask_path'):
            p=r.path/c['mask_path'];raw=p.read_bytes()
            masks[str(c['frame_id'])]=dict(path=c['mask_path'],sha256=sha(p),data_url='data:image/png;base64,'+base64.b64encode(raw).decode('ascii'),capture=c)
    for i,t in enumerate(r.times):
        s=r.snapshot(t);f=s['frame'];cap=s['capture'];gate=s['trace']
        ticks.append(dict(index=i,time_s=t,truth=s['truth'],frame=f,capture=cap,gate=gate,
            state=s['state'],action=s['action'],events_now=s['events_now'],last_request=s['last_request'],
            reference=s['reference'],confirmation=s['confirmation'],mask_key=str(cap['frame_id']) if cap and cap.get('mask_path') else None,
            overlay_valid=s['overlay_mask'] is not None,
            observation_age_s=t-f['processing_s'] if f else None,
            observation_status=('valid_latest_processed' if s['overlay_mask'] is not None else 'rejected:'+str(gate.get('C0_reason') or f.get('reason') or 'no_valid_mask') if f else 'missing_current_epoch')))
    route=r.config['environment']['route'];ps=[p for key in route for p in r.geometry['polygons'][str(key)]]
    viewport=[min(p[0] for p in ps)-.18,max(p[0] for p in ps)+.18,min(p[1] for p in ps)-.18,max(p[1] for p in ps)+.18]
    source_hashes={str(p.relative_to(r.path)):sha(p) for p in r.path.rglob('*') if p.is_file()}
    return dict(schema='chapter2_readonly_player_v1',simulation=True,trial_id=r.trial_id,source_trial=str(r.path.resolve()),
        clock_domain='simulation',coordinate_unit='pitch',geometry=r.geometry,viewport=viewport,config=r.config,
        times=r.times,ticks=ticks,masks=masks,events=r.events,references=r.references,processed=r.processed,gates=r.gates,
        keyframes=r.keyframes(),source_sha256=source_hashes,no_interpolation=True,no_simulation_execution=True)


def audit_bundle(bundle,path):
    """Compare bundle to freshly decoded CSV/PNG, not to regenerated algorithms."""
    r=PersistedReplay(path);errors=[]
    for field,original in [('events',r.events),('references',r.references),('processed',r.processed),('gates',r.gates)]:
        if bundle[field]!=original:errors.append(field)
    for field,original in [('geometry',r.geometry),('config',r.config),('keyframes',r.keyframes())]:
        if bundle[field]!=original:errors.append(field)
    tick_errors=[]
    if bundle['times']!=r.times or len(bundle['ticks'])!=len(r.times):tick_errors.append('time_axis')
    for i,t in enumerate(r.times):
        if i>=len(bundle['ticks']):break
        actual=bundle['ticks'][i];s=r.snapshot(t)
        for field,expected in [('time_s',t),('truth',s['truth']),('frame',s['frame']),('capture',s['capture']),('state',s['state']),('action',s['action']),('events_now',s['events_now']),('gate',s['trace']),('last_request',s['last_request']),('reference',s['reference']),('confirmation',s['confirmation']),('mask_key',str(s['capture']['frame_id']) if s['capture'] and s['capture'].get('mask_path') else None),('overlay_valid',s['overlay_mask'] is not None)]:
            if actual[field]!=expected:tick_errors.append(f'{i}:{field}')
    mask_errors=[]
    for key,m in bundle['masks'].items():
        raw=base64.b64decode(m['data_url'].split(',',1)[1])
        capture=r.capture_by_id.get(int(key))
        if raw!=(r.path/m['path']).read_bytes() or hashlib.sha256(raw).hexdigest()!=m['sha256'] or not capture or capture!=m['capture'] or capture.get('mask_path')!=m['path'] or capture.get('mask_sha256')!=m['sha256']:mask_errors.append(key)
    if set(bundle['masks'])!={str(c['frame_id']) for c in r.captures if c.get('mask_path')}:mask_errors.append('mask_set')
    source_errors=[n for n,h in bundle['source_sha256'].items() if sha(r.path/n)!=h]
    event_rows=[dict(csv_line=e['csv_line'],time_s=e['time_s'],event=e['event'],matched=e==next((b for b in bundle['events'] if b['csv_line']==e['csv_line']),None)) for e in r.events]
    return dict(passed=not(errors or tick_errors or mask_errors or source_errors),trial_id=r.trial_id,checked_ticks=len(r.times),checked_masks=len(bundle['masks']),checked_events=len(r.events),checked_references=len(r.references),event_mismatches=errors,tick_mismatches=tick_errors,mask_mismatches=mask_errors,source_mismatches=source_errors,event_rows=event_rows,
        observed_states=sorted({s['state'] for s in bundle['ticks']}),observed_actions=sorted({s['action'] for s in bundle['ticks']}),new_simulation_runs=0)
