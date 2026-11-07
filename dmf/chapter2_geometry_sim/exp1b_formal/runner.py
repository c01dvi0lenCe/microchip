"""One hash-frozen formal batch, reusing the reviewed read-only world/cache/gate/scorer."""
import json
from pathlib import Path
import shutil
from dmf.experiment.evidence import StepContext
from ..model import DesignGeometry
from ..observation import Raster
from ..single_step import write_csv
from ..exp1b.generate import verify_baseline
from ..exp1b.spec import METHODS
from ..exp1b_closeout.run import saved_pool
from ..exp1b_random.world import make_world
from ..exp1b_random.cache import create_cache
from ..exp1b_random.reference import build_reference
from ..exp1b_random.evaluation import score
from ..exp1b_random.runner import _save_draw,_recognize
from .spec import SEEDS,SLOTS,PLAN,VERSION,load_protocol,validate_formal_seeds,planned_identities,validate_identities,stratum
from .draws import draw_motion,draw_observation
from .freeze import verify_freeze,claim_batch,sha,js
from .summary import write_statistics


def failure_score(reference,horizon):
    known=reference is not None
    reference=reference or dict(intervals=[],status='no_reference_by_H')
    result=score(None,reference,horizon,status='unattempted')
    result.update(reference_known=known,missed_references_by_H=None)
    if not known:
        result.update(reference_status='unknown_world_generation_failed',reference_arrivals=None,
            reference_confirmed_s=None,reference_right_censored=False)
    return result


def run_formal(output,freeze_path=None,config_path=None,seeds=SEEDS):
    validate_formal_seeds(seeds)
    config=load_protocol(config_path)
    frozen=verify_freeze(freeze_path,config=config)
    output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    # Prerequisites are read-only and run before consuming the one-use freeze.
    verify_baseline()
    geometry_source=Path(config['geometry']['map_path'])
    if sha(geometry_source)!=config['geometry']['map_sha256']:raise ValueError('Frozen design map changed')
    old_rows,pool,source_ticks=saved_pool()
    if len(pool.phases)!=430 or pool.max_phase_error_bound>config['geometry']['maximum_phase_error_bound']+1e-12:
        raise ValueError('Frozen saved-outline pool mismatch')
    claim_batch(freeze_path,output)
    output.mkdir(parents=True)
    js(output/'run_manifest.json',dict(version=VERSION,status='started',actual_formal_seeds=list(SEEDS),
        no_redraw=True,no_replacement_batch=True,freeze_sha256=sha(freeze_path)))
    js(output/'effective_config.json',config)
    provenance=output/'provenance';provenance.mkdir()
    shutil.copyfile(freeze_path,provenance/'freeze.json')
    shutil.copyfile(Path(freeze_path).parent/'verification.json',provenance/'verification.json')
    inventory=[]
    for item in frozen['snapshots']:
        source=Path(freeze_path).parent/item['relative'];destination=provenance/item['relative']
        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
        inventory.append(dict(source=item['source'],relative=destination.relative_to(output).as_posix(),sha256=item['sha256']))
    shutil.copyfile(geometry_source,output/'map_snapshot.json')
    js(output/'source_inventory.json',inventory)
    geometry=DesignGeometry(output/'map_snapshot.json');raster=Raster(geometry,190,191,40.,4.)
    js(output/'raster.json',raster.snapshot())
    # One shared raw motion stream per seed, persisted under each of 80 WORLD identities.
    motion_draws={};observation_draws={}
    for seed in SEEDS:
        motion_draws[seed]=draw_motion(seed,config)
        for kind in config['design']['motion_groups']:
            _save_draw(output/'draws'/str(seed)/'motion'/kind,motion_draws[seed])
        draw_stratum='low' if SLOTS[seed]<10 else 'high'
        for condition in config['conditions']:
            cid=condition['id'];draw=draw_observation(seed,cid,draw_stratum,config)
            observation_draws[seed,cid]=draw
            _save_draw(output/'draws'/str(seed)/cid,draw)
    js(output/'draws_complete.json',dict(motion_world_identities=80,unique_motion_streams=20,
        observation_stream_sets=240,all_persisted_before_any_algorithm=True))
    worlds={};references={};failures=[];results=[];sensitivity=[]
    applied=config['time']['request_s']+config['time']['simulated_applied_delay_s'];horizon=config['time']['horizon_s']
    target_template=raster.mask(pool.at(1.,geometry.center(191))[0])
    for seed in SEEDS:
        for kind in config['design']['motion_groups']:
            key=(seed,kind);folder=output/'worlds'/str(seed)/kind;folder.mkdir(parents=True)
            try:
                world=make_world(config,motion_draws[seed],kind,geometry,pool,source_ticks)
                write_csv(folder/'internal_world.csv',world['rows'])
                write_csv(folder/'outline_replay_diagnostics.csv',world['diagnostics'])
                js(folder/'internal_polygons.json',[dict(time_s=r['time_s'],polygon_mm=list(p.exterior.coords))
                    for r,p in zip(world['rows'],world['polygons'])])
                js(folder/'world_manifest.json',world['manifest'])
                refs={s['id']:build_reference(world['rows'],geometry.center(191),target=191,
                    applied_s=applied,spec={k:v for k,v in s.items() if k!='id'},horizon=horizon,
                    permanent_stall=kind=='stall') for s in config['reference']['one_factor_sensitivity']}
                js(folder/'references.json',refs);references[key]=refs;worlds[key]=world
                js(folder/'control_events.json',[dict(time_s=.5,event='request',target=191),
                    dict(time_s=.54,event='simulated_applied',target=191)])
                print(f'World {seed}/{kind} saved',flush=True)
            except Exception as error:
                failure=dict(stage='world_generation',seed=seed,world=kind,error=repr(error))
                failures.append(failure);js(folder/'failure.json',failure)
    for seed in SEEDS:
        for condition in config['conditions']:
            cid=condition['id'];kind=condition['world'];key=(seed,kind)
            folder=output/'caches'/str(seed)/cid
            base=dict(seed=seed,seed_slot=SLOTS[seed],condition=cid,world_id=f'{seed}/{kind}',stratum=stratum(seed,condition))
            if key not in worlds:error='world_generation_failed'
            else:
                try:
                    context=StepContext(f'{VERSION}:{seed}:{cid}',1,0,1,190,191,clock_domain='simulation',
                        applied_timestamp_s=applied,applied_time_quality='simulation_exact')
                    cache=create_cache(folder,worlds[key],raster,observation_draws[seed,cid],config,context,target_template)
                    gates,raw=_recognize(folder,cache,context,horizon)
                    manifest=cache['manifest'];manifest.update(cache_sha256=sha(folder/'captures.csv'),
                        common_raw_history_sha256=sha(folder/'raw_observations.csv'))
                    js(folder/'manifest.json',manifest)
                    local=[]
                    for gate in gates:
                        for rid,ref in references[key].items():
                            local.append(dict(base,method=gate.spec.name,reference_id=rid,status='executed',
                                reference_known=True,cache_sha256=manifest['cache_sha256'],processed_frames=len(raw),
                                **score(gate.event,ref,horizon,manifest['pending_deliveries_at_H'])))
                    sensitivity.extend(local);results.extend(dict(r) for r in local if r['reference_id']=='R0')
                    print(f'Cache {seed}/{cid}: six methods saved',flush=True)
                    continue
                except Exception as error_object:error=repr(error_object)
            failure=dict(stage='cache_execution',**base,error=error);failures.append(failure)
            folder.mkdir(parents=True,exist_ok=True);js(folder/'failure.json',failure)
            for method in METHODS:
                for reference in config['reference']['one_factor_sensitivity']:
                    rid=reference['id'];known=references.get(key,{}).get(rid)
                    record=dict(base,method=method.name,reference_id=rid,status='unattempted',error=error,
                        **failure_score(known,horizon))
                    sensitivity.append(record)
                    if rid=='R0':results.append(dict(record))
    validate_identities(results,planned_identities(config,primary=True))
    validate_identities(sensitivity,planned_identities(config))
    write_csv(output/'planned_method_results.csv',results)
    write_csv(output/'reference_sensitivity_results.csv',sensitivity)
    write_statistics(output,sensitivity,config);js(output/'failures.json',failures)
    js(output/'run_manifest.json',dict(version=VERSION,status='finished_with_failures' if failures else 'finished',
        actual_formal_seeds=list(SEEDS),no_redraw=True,no_replacement_batch=True,freeze_sha256=sha(freeze_path)))
    js(output/'manifest.json',dict(version=VERSION,actual_formal_seeds=list(SEEDS),planned=dict(PLAN),
        actual_base_worlds=len(worlds),actual_caches=240-sum(f['stage']=='cache_execution' for f in failures),
        formal_batch_count=1,freeze_sha256=sha(freeze_path),source_code=frozen['source_hashes'],
        failures=failures,artifacts={p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file()}))
    return results
