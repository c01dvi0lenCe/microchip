"""Additive outputs with actual masks and separate truth/reference records."""
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
import cv2


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def write_json(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def write_csv(path,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def persist_trial(result,output):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True);(output/'masks').mkdir()
    captures=[]
    for item in result.captures:
        row={k:v for k,v in item.items() if k!='mask'};path=output/row['mask_path']
        ok,png=cv2.imencode('.png',item['mask'])
        if not ok:raise ValueError('Mask PNG encoding failed')
        path.write_bytes(png.tobytes());row['mask_sha256']=sha256(path);captures.append(row)
    for name,rows in (('world',result.world),('captures',captures),('deliveries',result.deliveries),
        ('frames',result.frames),('events',result.events),('arrivals',result.arrivals),('steps',result.steps),
        ('reference_marks',result.reference_marks)):
        write_csv(output/(name+'.csv'),rows)
    write_json(output/'world_polygons.json',result.polygons)
    write_json(output/'world_events.json',result.world_events)
    write_json(output/'reference_segments.json',result.reference_segments)
    write_json(output/'metrics.json',result.metrics);write_json(output/'raster.json',result.raster)
    write_json(output/'config.json',result.config.snapshot())
    sources={str(p.resolve()):sha256(p) for p in Path(__file__).parent.glob('*.py')}
    for rel in ('exp1b/gates.py','exp1b/spec.py','exp1b_closeout/replay.py','exp1b_closeout/run.py','observation.py','model.py'):
        p=Path(__file__).parents[1]/rel;sources[str(p.resolve())]=sha256(p)
    p=Path(__file__).parents[2]/'experiment/evidence.py';sources[str(p.resolve())]=sha256(p)
    p=Path(__file__).parents[3]/'run_chapter2_geometry_exp2.py';sources[str(p.resolve())]=sha256(p)
    write_json(output/'manifest.json',dict(config_sha256=sha256(output/'config.json'),inputs=result.inputs,
        source_code=sources,simulation=True,development_only=True,n=1,coordinate_unit='mm',formal=False,
        random_draws=0,tuning=False,old_world_compatible=False,
        artifacts={p.relative_to(output).as_posix():sha256(p) for p in output.rglob('*') if p.is_file()}))
    return output
