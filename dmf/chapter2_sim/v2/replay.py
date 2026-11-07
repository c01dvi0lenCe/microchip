"""Replay persisted records only. No simulation/recognition calls or interpolation."""
import bisect
from functools import lru_cache
import json
from pathlib import Path
import cv2
import numpy as np

from .persistence import load_trial


def typed(value):
    if value=='':return None
    if value in ('True','False'):return value=='True'
    try:return json.loads(value)
    except (ValueError,TypeError):return value


class PersistedReplay:
    def __init__(self,path):
        self.path=Path(path);self.data=load_trial(path);self.trial_id=self.data['manifest']['trial_id']
        for name in ('truth','frames','captures','events','references','gates'):
            rows=[dict({k:typed(v) for k,v in row.items()},csv_line=i) for i,row in enumerate(self.data[name],2)]
            setattr(self,name,rows)
        self.truth.sort(key=lambda r:r['time_s']);self.times=[r['time_s'] for r in self.truth]
        if not self.times:raise ValueError('no persisted truth trajectory to replay')
        self.processed=sorted([r for r in self.frames if r.get('processing_s') is not None],key=lambda r:r['processing_s'])
        self.capture_by_id={r['frame_id']:r for r in self.captures};self.gate_by_id={r['frame_id']:r for r in self.gates}
        self.config=self.data['manifest']['config'];self.geometry=self.data['geometry']

    @lru_cache(maxsize=512)
    def mask(self,relative):
        if not relative:return None
        data=np.fromfile(self.path/relative,np.uint8);im=cv2.imdecode(data,cv2.IMREAD_GRAYSCALE)
        if im is None:raise ValueError('persisted Mask is not readable')
        im.setflags(write=False);return im

    @staticmethod
    def latest(rows,t,field='time_s'):
        eligible=[r for r in rows if r.get(field) is not None and r[field]<=t+1e-9]
        return max(eligible,key=lambda r:r[field]) if eligible else None

    def snapshot(self,t):
        if t<0 or t>self.times[-1]+1e-9:raise ValueError('no extrapolation outside recorded trial')
        truth=self.truth[bisect.bisect_right(self.times,t+1e-9)-1]
        frame=self.latest(self.processed,t,'processing_s')
        if frame and frame['epoch']!=truth['epoch']:frame=None
        capture=self.capture_by_id[frame['frame_id']] if frame else None
        mask=self.mask(capture['mask_path']) if capture and capture.get('mask_path') else None
        trace=self.gate_by_id.get(frame['frame_id'],{}) if frame else {}
        overlay=mask if (mask is not None and trace.get('C0_passed') and capture['capture_epoch']==truth['epoch']) else None
        step=truth['step']
        ref=next((r for r in self.references if r['step']==step and r['upper_s']<=t+1e-9),None)
        confirm=self.latest([e for e in self.events if e['event']=='ArrivalEvent' and e['step']==step],t)
        requests=[e for e in self.events if e['event'] in ('Prepare','Start','Update','Retry','Recovery','Complete','Stop')]
        exact=[e for e in self.events if abs(e['time_s']-t)<1e-8]
        return dict(time_s=t,truth=truth,frame=frame,capture=capture,mask=mask,overlay_mask=overlay,trace=trace,
            state=frame['state'] if frame else 'Unknown',action=next((e['event'] for e in exact if e['event'] in ('Start','Update','Retry','Recovery','Complete','Stop')),'Hold'),
            reference=ref,confirmation=confirm,last_request=self.latest(requests,t),events_now=exact)

    def keyframes(self):
        selected=[]
        start=next((e for e in self.events if e['event']=='Start'),None)
        if start:selected.append(('源区确认 / Start',start['time_s']))
        moving=next((f for f in self.processed if f.get('phase')=='transport' and f['state']=='Moving' and (f.get('progress_pitch') or 0)>.03),None)
        if moving:selected.append(('已观测运动 / Moving',moving['processing_s']))
        partial=next((f for f in self.processed if f['state']=='Partial'),None)
        if partial:selected.append(('跨电极 / Partial',partial['processing_s']))
        if self.references:selected.append(('独立参考到达',self.references[0]['upper_s']))
        update=next((e for e in self.events if e['event']=='Update'),None)
        if update:selected.append(('Arrived / Update请求',update['time_s']))
        applied=next((e for e in self.events if e['event']=='Applied' and e.get('action')=='Update'),None)
        if applied:selected.append(('下一目标模拟Applied',applied['time_s']))
        seen=set();out=[]
        for label,t in selected:
            if t in seen:continue
            seen.add(t);s=self.snapshot(t)
            out.append(dict(label=label,time_s=t,state=s['state'],action=s['action'],truth_csv_line=s['truth']['csv_line'],
                frame_id=s['frame']['frame_id'] if s['frame'] else None,frame_csv_line=s['frame']['csv_line'] if s['frame'] else None,
                mask_path=s['capture']['mask_path'] if s['capture'] else None,trial_id=self.trial_id))
        return out
