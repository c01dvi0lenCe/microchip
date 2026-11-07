"""Two predeclared World-only timing interventions; not strategy trials."""
import argparse
from dataclasses import replace
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dmf.chapter2_geometry_sim.exp2.runner import load_inputs
from dmf.chapter2_geometry_sim.exp2.spec import Exp2Config
from dmf.chapter2_geometry_sim.exp2.world import CausalWorld
from dmf.chapter2_geometry_sim.exp2.persistence import write_json,write_csv,sha256


def run(output):
    output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    geometry,pool,inputs=load_inputs();cfg=replace(Exp2Config(),horizon_s=20.,control_budget_s=20.)
    output.mkdir(parents=True);summary=[]
    for name,request_s in [('early',.8),('late',8.)]:
        world=CausalWorld(geometry,pool,cfg);rows=[];polygons=[]
        folder=output/name;folder.mkdir()
        for tick in range(2001):
            t=round(tick*.01,10);world.advance(t)
            if abs(t-.5)<1e-9:world.request(191,'Start')
            if abs(t-request_s)<1e-9:world.request(192,'TimingIntervention')
            rows.append(world.snapshot());polygons.append(dict(time_s=t,polygon_mm=list(world.polygon.exterior.coords)))
        write_csv(folder/'world.csv',rows);write_json(folder/'world_polygons.json',polygons)
        write_json(folder/'events.json',world.events)
        write_json(folder/'config.json',cfg.snapshot())
        blocked=sum(r['world_status']=='blocked_no_overlap' for r in rows)
        summary.append(dict(case=name,request_192_s=request_s,blocked_ticks=blocked,
            final_distance_to_192_mm=float(((world.position-geometry.center(192))**2).sum()**.5)))
    write_json(output/'manifest.json',dict(simulation=True,development_only=True,world_only=True,algorithm_test=False,
        random_draws=0,seed=None,predeclared_request_192_s=[.8,8.],first_request_191_s=.5,
        inputs=inputs,config=cfg.snapshot(),cases=summary,
        script=str(Path(__file__).resolve()),script_sha256=sha256(__file__),
        source_code={str(p.resolve()):sha256(p) for p in (ROOT/'dmf/chapter2_geometry_sim/exp2').glob('*.py')},
        artifacts={p.relative_to(output).as_posix():sha256(p) for p in output.rglob('*') if p.is_file()}))
    print(summary)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output');a=p.parse_args();run(a.output)
