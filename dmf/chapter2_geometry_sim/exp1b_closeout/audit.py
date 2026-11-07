"""Independent checks of replay, actual perturbations and exclusive denominators."""
import math
from pathlib import Path
from collections import Counter
import cv2
import numpy as np
from shapely import contains_xy
from shapely.geometry import Polygon
from shapely.affinity import translate
from ..exp1b.audit import read,load,sha,audit_development,flag


def expected_mask(case,original,t,target_template):
    mask=original.copy()
    if (case=='C5' and abs(t-2)<1e-9) or (case=='C6' and 2-1e-9<=t<=2.3+1e-9):
        return target_template.copy()
    offset=0
    if 4.2-1e-9<=t<=4.5+1e-9:
        if case=='C1':offset=1 if round(t*20)%2==0 else -1
        if case=='C2':offset=8
        if case=='C3':
            ys,xs=np.nonzero(mask)
            if len(xs):mask[:,:int(xs.min()+.2*(xs.max()-xs.min()+1))]=0
        if case=='C4':
            ys,xs=np.nonzero(mask)
            if len(ys):
                y=round(float(ys.mean()));mask[y:y+2,:]=0
    if case=='D6' and abs(t-4.4)<1e-9:offset=48
    if offset:
        moved=np.zeros_like(mask)
        if offset>0:moved[offset:]=mask[:-offset]
        else:moved[:offset]=mask[-offset:]
        mask=moved
    return mask


def expected_deliveries(case):
    result=[]
    for i in range(200):
        t=round(i*.05,10)
        if case=='D1' and i==88:continue
        if case=='D2' and 86<=i<=90:continue
        processed=round(t+.05,10)
        if case=='D4' and i==88:processed+=.3
        result.append(dict(frame_id=i,processed_s=processed,duplicate=False))
        if case=='D3' and i==88:result.append(dict(frame_id=i,processed_s=processed+.001,duplicate=True))
    return sorted(result,key=lambda r:(r['processed_s'],r['duplicate']))


def rasterize(p,raster):
    scale=raster['pixels_per_mm'];lower=np.array(raster['lower_mm']);shape=tuple(raster['shape'])
    result=np.zeros(shape,np.uint8);bounds=np.array(p.bounds)
    lo=np.maximum(np.floor((bounds[:2]-lower)*scale).astype(int)-1,0)
    hi=np.minimum(np.ceil((bounds[2:]-lower)*scale).astype(int)+1,np.array(shape[::-1]))
    xx=lower[0]+(np.arange(lo[0],hi[0])+.5)/scale
    yy=lower[1]+(np.arange(lo[1],hi[1])+.5)/scale
    result[lo[1]:hi[1],lo[0]:hi[0]]=contains_xy(p,xx[None,:],yy[:,None]).astype(np.uint8)*255
    return result


def audit_closeout(root):
    root=Path(root);base=audit_development(root);failures=list(base['failures'])
    def require(condition,label):
        if not condition:failures.append(label)
    manifest=load(root/'manifest.json');parent=Path(manifest['parent'])
    copy_inventory=load(root/'copy_inventory.json')
    for r in copy_inventory:
        require(sha(r['source'])==r['sha256'] and sha(root/r['relative'])==r['sha256'],'byte_copy:'+r['relative'])
    old_results={(r['case_id'],r['method']):r for r in read(parent/'planned_method_results.csv') if r['case_id']!='B1'}
    results=read(root/'planned_method_results.csv')
    for r in results:
        if r['case_id']=='B1':continue
        old=old_results[r['case_id'],r['method']]
        require(all(r.get(k)==v for k,v in old.items()),'unchanged_old_prediction:'+r['case_id']+r['method'])
    config=load(root/'config.json');raster=load(root/'raster.json')
    worlds={kind:load(root/f'worlds/{kind}/internal_polygons.json') for kind in ('normal','slow','pause','stall')}
    target_template=rasterize(Polygon(worlds['normal'][-1]['polygon_mm']),raster)
    perturbations=[]
    for case in config['cases']:
        name=case['name'];folder=root/'caches'/name;captures=read(folder/'captures.csv');mutations=0;bad=0
        for capture in captures:
            i=int(capture['frame_id']);t=float(capture['exposure_start_s'])
            original=rasterize(Polygon(worlds[case['world']][i*5]['polygon_mm']),raster)
            expected=expected_mask(name,original,t,target_template)
            actual=cv2.imdecode(np.fromfile(folder/capture['mask_path'],np.uint8),0)
            if not np.array_equal(actual,expected):bad+=1
            changed=int(np.count_nonzero(expected!=original));mutations+=int(changed>0)
            require(changed==int(capture['changed_pixels']),'actual_mutation_pixels:'+name+':'+str(i))
            expected_epoch='' if t<.54-1e-10 else '0' if name=='D5' and i==88 else '1'
            require(capture['captured_epoch']==expected_epoch,'actual_epoch:'+name+':'+str(i))
        require(bad==0,'actual_mask_injection:'+name)
        actual_plan=read(folder/'deliveries.csv');expected_plan=expected_deliveries(name)
        require(len(actual_plan)==len(expected_plan),'actual_delivery_count:'+name)
        for a,b in zip(actual_plan,expected_plan):
            require(int(a['frame_id'])==b['frame_id'] and abs(float(a['processed_s'])-b['processed_s'])<1e-9
                and flag(a['duplicate_delivery'])==b['duplicate'],'actual_delivery:'+name)
        perturbations.append(dict(case_id=name,checked_generated_masks=len(captures),actual_mutated_frames=mutations,
            mask_mismatches=bad,checked_deliveries=len(actual_plan)))
    source_baseline=Path(manifest['source_baseline']);source_rows=read(source_baseline/'trial/world.csv')
    source_polygons=load(source_baseline/'trial/world_polygons.json')
    phases=[]
    for row in source_rows:
        q=float(row['shape_phase'])
        if not phases or q!=phases[-1]:phases.append(q)
    bound=max(b-a for a,b in zip(phases,phases[1:]))/2
    diagnostics=read(root/'worlds/slow/outline_replay_diagnostics.csv');slow=read(root/'worlds/slow/internal_world.csv')
    max_error=area_error=centroid_error=0.
    for d,r,poly in zip(diagnostics,slow,worlds['slow']):
        q=float(d['query_phase']);chosen=float(d['selected_phase']);tick=int(d['source_tick'])
        nearest=min(phases,key=lambda x:(abs(x-q),x))
        require(abs(chosen-nearest)<1e-12,'nearest_phase')
        require(abs(chosen-float(source_rows[tick]['shape_phase']))<1e-12,'source_tick_phase')
        require(abs(float(d['phase_error'])-(chosen-q))<1e-12,'quantization_error')
        source_shape=Polygon(source_polygons[tick]['polygon_mm']);actual=Polygon(poly['polygon_mm'])
        center=source_shape.centroid;position=(float(r['x_mm']),float(r['y_mm']))
        expected=translate(source_shape,position[0]-center.x,position[1]-center.y)
        require(actual.is_valid and not actual.interiors,'valid_replay_outline')
        require(np.max(np.abs(np.array(actual.exterior.coords)-np.array(expected.exterior.coords)))<1e-10,'translation_only')
        max_error=max(max_error,abs(chosen-q));area_error=max(area_error,abs(actual.area/source_shape.area-1))
        centroid_error=max(centroid_error,math.dist(actual.centroid.coords[0],position))
    require(len(diagnostics)==1001 and max_error<=bound+1e-12,'phase_bound')
    outcomes=read(root/'exclusive_step_outcomes.csv');require(len(outcomes)==96,'exclusive_total')
    per_method={}
    for method in [m['name'] for m in config['methods']]:
        selected=[r for r in outcomes if r['method']==method]
        counts=dict(Counter(r['primary_outcome'] for r in selected))
        require(len(selected)==16 and sum(counts.values())==16 and all(int(r['primary_outcome_count'])==1 for r in selected),'exclusive_per_method:'+method)
        require(all(r['control_safety_evaluated']=='False' and r['actual_wrong_advance']=='' for r in selected),'no_invented_control_safety')
        per_method[method]=counts
    for r in outcomes:
        original=next(x for x in results if x['case_id']==r['case_id'] and x['method']==r['method'])
        category=original['category'];refs=int(original['reference_arrivals']);decision=original['decision_s']
        expected=('reference_supported' if category=='supported' else 'before_reference' if category=='premature' else
            'reference_not_confirmed' if not decision and refs else 'no_reference_no_confirmation' if not decision else
            'outside_reference_support' if refs else 'no_reference_confirmation')
        require(r['primary_outcome']==expected,'exclusive_category')
    return dict(passed=not failures,failures=sorted(set(failures)),core_audit=base,
        preserved_assets=len(copy_inventory),preserved_old_method_records=len(old_results),new_B1_method_records=6,
        checked_actual_perturbations=perturbations,replay=dict(pool_size=len(phases),checked_ticks=len(diagnostics),
            maximum_phase_error=max_error,theoretical_phase_error_bound=bound,
            equivalent_progress_distance_mm=max_error*3.2,maximum_area_relative_error=area_error,
            maximum_centroid_error_mm=centroid_error,no_new_contour_interpolation=True),
        primary_outcomes=per_method,control_safety_evaluated=False,formal_statistics_run=False,
        audit_code_sha256=sha(__file__))
