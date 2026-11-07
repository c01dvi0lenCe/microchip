"""Synthetic mechanism fixtures, never formal ground truth or random results."""
from dataclasses import asdict
import itertools
import json

import cv2
import numpy as np

from dmf.experiment.mask_cache import write_cache
from ..geometry import SimulationMap
from ..formal_adapter import state_config
from .adapter import ResearchAdapter
from .observation import ObservedFrame
from .spec import FactorFlags

CASES=('stable','transient','motion_jump','spatial_tail','low_confidence','small_area','two_components','high_confidence_indistinguishable')


def build_probe_case(name,spec,geometry=None):
    if name not in CASES:raise ValueError('unknown mechanism fixture')
    geometry=geometry or SimulationMap(spec.environment)
    target=geometry.center(191);center=np.rint(geometry.to_pixel(target)).astype(int)
    frames=[];n=2 if name=='transient' else 7 if name=='motion_jump' else 6
    for i in range(n):
        mask=np.zeros(geometry.shape,np.uint8);confidence=.1 if name=='low_confidence' else 1.
        if name=='spatial_tail':
            # Hand-countable 90 target pixels and 15 far, individually small
            # artifacts. Significant-component Q deliberately cannot see them.
            mask[84:129,83:85]=255;mask[145:148,0:3]=255;mask[155:157,0:3]=255
        elif name=='small_area':mask[center[1],center[0]]=255
        elif name=='two_components':
            for shift in (-5,5):cv2.circle(mask,(int(center[0]+shift),int(center[1])),3,255,-1)
        else:
            point=geometry.center(190) if name=='motion_jump' and i==0 else target
            pixel=np.rint(geometry.to_pixel(point)).astype(int);cv2.circle(mask,tuple(pixel),12,255,-1)
        start=.1+i*.05
        frames.append(ObservedFrame(i,start,start+.008,start+.05,mask,confidence=confidence))
    return frames


def write_probe_cache(path,name,spec):
    geometry=SimulationMap(spec.environment);snapshot=geometry.snapshot()
    snapshot.update(lower=geometry.lower.tolist(),scale=geometry.scale,shape=[int(v) for v in geometry.shape])
    params=asdict(state_config(spec.environment))
    params.update(eta_arr=spec.target.coverage,eta_release=spec.target.source_release,arrival_frames=spec.target.window.frames,
        arrival_duration_s=spec.target.window.duration_s,evidence_max_gap_s=spec.target.window.max_gap_s,
        arrival_max_centroid_span_mm=spec.target.window.centroid_span_pitch,arrival_max_coverage_span=spec.target.window.coverage_span)
    return write_cache(path,map_snapshot=snapshot,tasks=[dict(step_id=0,source=190,target=191,start_s=0.,end_s=1.,applied_s=.04)],parameters=params,
        frames=[dict(frame_id=f.frame_id,exposure_start_s=f.exposure_start_s,exposure_s=f.exposure_end_s,available_s=f.available_s,mask=f.mask,confidence=f.confidence) for f in build_probe_case(name,spec,geometry)],
        clock_domain='simulation',coordinate_unit='pitch')


def run_probe_matrix(spec):
    geometry=SimulationMap(spec.environment);records=[]
    for case in CASES:
        raw_sequences=[];case_records=[]
        for bits in itertools.product((False,True),repeat=4):
            flags=FactorFlags(*bits);adapter=ResearchAdapter(spec,geometry,'F',flags=flags,run_id='mechanism:'+case)
            adapter.begin_transport(.04);raw=[];count=0;reasons=[]
            for frame in build_probe_case(case,spec,geometry):
                out=adapter.observe(frame,frame.available_s);count+=int(out.arrival_event is not None)
                raw.append(adapter.last_trace['raw']);reasons.extend(adapter.last_trace.get('rejection_reasons',[]))
            raw_sequences.append(json.dumps(raw,sort_keys=True))
            case_records.append(dict(case=case,flags=asdict(flags),arrival_events=count,rejection_reasons=sorted(set(reasons)),
                C0_always_on=True,synthetic_stress=True,not_formal_gt=True,observability_boundary=case=='high_confidence_indistinguishable'))
        invariant=len(set(raw_sequences))==1
        if not invariant:raise AssertionError('module switches changed raw feature history')
        for row in case_records:row['raw_invariant']=invariant
        records.extend(case_records)
    return records
