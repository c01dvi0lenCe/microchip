"""Additive experiment2-compatible files plus original-mask intervention audit."""
import hashlib
from pathlib import Path
import cv2
from ..exp2.persistence import sha256, write_csv, write_json


def mask_png(mask):
    ok,png=cv2.imencode('.png',mask)
    if not ok:
        raise ValueError('Mask PNG encoding failed')
    return png.tobytes()


def mask_sha256(mask):
    return hashlib.sha256(mask_png(mask)).hexdigest()


def persist_case(result,output):
    output=Path(output)
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    (output/'masks').mkdir()
    (output/'unmodified_source_masks').mkdir()
    captures=[]
    for item in result.captures:
        row={k:v for k,v in item.items() if k not in ('mask','source_mask')}
        path=output/row['mask_path']
        path.write_bytes(mask_png(item['mask']))
        row['mask_sha256']=sha256(path)
        if row['mask_sha256']!=row['visible_mask_sha256']:
            raise ValueError('visible Mask hash changed since capture')
        if item.get('source_mask') is not None:
            source_path=output/row['source_mask_path']
            source_path.write_bytes(mask_png(item['source_mask']))
            if sha256(source_path)!=row['source_mask_sha256']:
                raise ValueError('source Mask hash changed since capture')
        captures.append(row)
    for name,rows in (('world',result.world),('captures',captures),('deliveries',result.deliveries),
        ('frames',result.frames),('events',result.events),('arrivals',result.arrivals),('steps',result.steps),
        ('reference_marks',result.reference_marks),('interventions',result.interventions)):
        write_csv(output/(name+'.csv'),rows)
    for name,value in (('world_polygons',result.polygons),('world_events',result.world_events),
        ('reference_segments',result.reference_segments),('metrics',result.metrics),
        ('raster',result.raster),('config',result.config.snapshot()),('case',result.fault_case)):
        write_json(output/(name+'.json'),value)
    package=Path(__file__).parent
    sources={str(p.resolve()):sha256(p) for p in package.glob('*.py')}
    for p in (package.parent/'exp2').glob('*.py'):
        sources[str(p.resolve())]=sha256(p)
    for rel in ('exp1b/gates.py','exp1b/spec.py','exp1b_closeout/replay.py',
                'exp1b_closeout/run.py','observation.py','model.py'):
        p=package.parent/rel
        sources[str(p.resolve())]=sha256(p)
    for p in (package.parents[1]/'experiment/evidence.py',
              package.parents[2]/'run_chapter2_geometry_exp2_faults.py'):
        sources[str(p.resolve())]=sha256(p)
    write_json(output/'manifest.json',dict(config_sha256=sha256(output/'config.json'),
        case=result.fault_case,inputs=result.inputs,source_code=sources,
        simulation=True,development_only=True,n=1,coordinate_unit='mm',formal=False,
        random_draws=0,tuning=False,old_world_compatible=False,
        mask_hash_encoding='PNG OpenCV default lossless',
        artifacts={p.relative_to(output).as_posix():sha256(p) for p in output.rglob('*') if p.is_file()}))
    return output

