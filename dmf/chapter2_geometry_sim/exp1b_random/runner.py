"""Development-only runner. Outcomes never feed back into saved WORLD motion."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import shutil
import numpy as np
from dmf.experiment.evidence import StepContext
from ..model import DesignGeometry
from ..observation import Raster
from ..single_step import write_csv
from ..exp1b.generate import verify_baseline
from ..exp1b.gates import RawAssessor, GateRunner
from ..exp1b.spec import METHODS
from ..exp1b_closeout.run import saved_pool
from .spec import load_protocol, validate_development_seeds, APPROVED
from .draws import draw_motion, draw_observation
from .world import make_world
from .cache import create_cache
from .reference import build_reference
from .evaluation import score
from .statistics import summarize_development

VERSION = 'geometry_exp1b_random_development_v1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def js(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _save_draw(folder, draw):
    folder.mkdir(parents=True)
    metadata = {key: value for key, value in draw.items() if key != 'arrays'}
    if 'arrays' in draw:
        np.savez(folder/'raw_arrays.npz', **draw['arrays'])
        metadata['array_file_sha256'] = sha(folder/'raw_arrays.npz')
    js(folder/'draw.json', metadata)


def _recognize(folder, cache, context, horizon):
    assessor = RawAssessor(context); gates = [GateRunner(m, context) for m in METHODS]
    logs = {m.name: [] for m in METHODS}; raw_rows = []
    for delivery_id, delivery in enumerate(cache['deliveries']):
        if delivery['processed_s'] > horizon+1e-9: continue
        frame_id = delivery['frame_id']
        # Boundary: CameraFrame, Mask-only feature dict and task context only.
        frame = replace(cache['frames'][frame_id], processed_at_s=delivery['processed_s'])
        features = cache['features'][frame_id]
        if any(k.startswith(('world_', 'reference_', 'permanent_')) for k in features):
            raise ValueError('Internal WORLD/reference leaked into recognizer input')
        raw = assessor.observe(frame, features)
        common = dict(delivery_id=delivery_id, frame_id=frame_id, exposure_start_s=frame.exposure_start_s,
            exposure_end_s=frame.exposure_end_s, available_s=frame.available_s,
            processed_at_s=frame.processed_at_s, **features, **raw)
        raw_rows.append(common)
        for gate in gates: logs[gate.spec.name].append(dict(common, **gate.observe(frame, raw)))
    write_csv(folder/'raw_observations.csv', raw_rows)
    for gate in gates:
        write_csv(folder/(gate.spec.name+'_frames.csv'), logs[gate.spec.name])
        js(folder/(gate.spec.name+'_event.json'), gate.event)
    return gates, raw_rows


def run_development(output, config_path=None, seeds=(268000, 268001)):
    config = load_protocol(config_path)
    seeds = validate_development_seeds(seeds, config)
    output = Path(output).resolve()
    if output.exists(): raise FileExistsError(output)
    # No flag, config toggle, or seed substitution can open the formal path.
    verify_baseline()
    geometry_source = Path(config['geometry']['map_path'])
    if sha(geometry_source) != config['geometry']['map_sha256']:
        raise ValueError('Frozen design map hash mismatch')
    old_rows, pool, source_ticks = saved_pool()
    if len(pool.phases) != 430 or pool.max_phase_error_bound > config['geometry']['maximum_phase_error_bound']+1e-12:
        raise ValueError('Frozen saved-outline pool mismatch')
    output.mkdir(parents=True)
    config['actual_development_seeds'] = seeds
    config['actual_plan'] = dict(base_worlds=4*len(seeds), shared_caches=12*len(seeds), method_records=72*len(seeds),
        reference_scores=504*len(seeds), formal_execution_allowed=False)
    js(output/'effective_config.json', config)
    copies = []
    for source, relative in [(geometry_source, 'map_snapshot.json'),
            (Path(config['base_path']), 'provenance/base_proposal.json'),
            (Path(config['effective_config_path']), 'provenance/development_wrapper.json')]:
        dest = output/relative; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, dest)
        copies.append(dict(source=str(source.resolve()), relative=relative, sha256=sha(source)))
    shape_source = Path(config['geometry']['shape_source'])
    for relative in ('trial/world.csv', 'trial/world_polygons.json', 'trial/manifest.json', 'shape_inputs/shape_library.json'):
        source = shape_source/relative
        copies.append(dict(source=str(source.resolve()), relative=None, sha256=sha(source)))
    js(output/'source_inventory.json', copies)
    geometry = DesignGeometry(output/'map_snapshot.json'); raster = Raster(geometry, 190, 191, 40., 4.)
    js(output/'raster.json', raster.snapshot())
    # Draw every random stream for the entire approved plan before any algorithm.
    motion_draws = {}; observation_draws = {}
    for seed in seeds:
        motion_draws[seed] = draw_motion(seed, config)
        _save_draw(output/'draws'/str(seed)/'motion', motion_draws[seed])
        stratum = 'low' if APPROVED[seed] < 10 else 'high'
        for condition in config['conditions']:
            cid = condition['id']; draw = draw_observation(seed, cid, stratum, config)
            observation_draws[seed, cid] = draw
            _save_draw(output/'draws'/str(seed)/cid, draw)
    worlds = {}; references = {}; failures = []; results = []; sensitivity = []
    applied = config['time']['request_s']+config['time']['simulated_applied_delay_s']; horizon = config['time']['horizon_s']
    target_template = raster.mask(pool.at(1., geometry.center(191))[0])
    for seed in seeds:
        for kind in config['design']['motion_groups']:
            key = (seed, kind); folder = output/'worlds'/str(seed)/kind; folder.mkdir(parents=True)
            try:
                world = make_world(config, motion_draws[seed], kind, geometry, pool, source_ticks)
                worlds[key] = world
                write_csv(folder/'internal_world.csv', world['rows'])
                write_csv(folder/'outline_replay_diagnostics.csv', world['diagnostics'])
                js(folder/'internal_polygons.json', [dict(time_s=r['time_s'], polygon_mm=list(p.exterior.coords))
                    for r, p in zip(world['rows'], world['polygons'])])
                js(folder/'world_manifest.json', world['manifest'])
                refs = {s['id']: build_reference(world['rows'], geometry.center(191), target=191,
                    applied_s=applied, spec={k: v for k, v in s.items() if k != 'id'},
                    horizon=horizon, permanent_stall=kind == 'stall') for s in config['reference']['one_factor_sensitivity']}
                references[key] = refs; js(folder/'references.json', refs)
                js(folder/'control_events.json', [dict(time_s=.5,event='request',target=191),
                    dict(time_s=.54,event='simulated_applied',target=191)])
                print(f'World {seed}/{kind} saved', flush=True)
            except Exception as error:
                failure = dict(stage='world_generation', seed=seed, world=kind, error=repr(error))
                failures.append(failure); js(folder/'failure.json', failure)
    for seed in seeds:
        for condition in config['conditions']:
            cid = condition['id']; kind = condition['world']; key = (seed, kind)
            folder = output/'caches'/str(seed)/cid
            base = dict(seed=seed, seed_slot=APPROVED[seed], condition=cid, world_id=f'{seed}/{kind}',
                        stratum='base' if condition['strata']=='base' else 'low' if APPROVED[seed] < 10 else 'high')
            if key not in worlds:
                gates = None; error = 'world_generation_failed'
            else:
                try:
                    context = StepContext(f'{VERSION}:{seed}:{cid}', 1, 0, 1, 190, 191,
                        clock_domain='simulation', applied_timestamp_s=applied, applied_time_quality='simulation_exact')
                    cache = create_cache(folder, worlds[key], raster, observation_draws[seed, cid], config, context, target_template)
                    gates, raw = _recognize(folder, cache, context, horizon)
                    manifest = cache['manifest']; manifest.update(cache_sha256=sha(folder/'captures.csv'),
                        common_raw_history_sha256=sha(folder/'raw_observations.csv'))
                    js(folder/'manifest.json', manifest)
                    local_records = []
                    for gate in gates:
                        for rid, ref in references[key].items():
                            record = dict(base, method=gate.spec.name, reference_id=rid, status='executed',
                                cache_sha256=manifest['cache_sha256'], processed_frames=len(raw),
                                **score(gate.event, ref, horizon, manifest['pending_deliveries_at_H']))
                            local_records.append(record)
                    sensitivity.extend(local_records)
                    results.extend(dict(r) for r in local_records if r['reference_id']=='R0')
                    print(f'Cache {seed}/{cid}: six methods saved', flush=True)
                    continue
                except Exception as exc:
                    error = repr(exc); gates = None
            failure = dict(stage='cache_execution', **base, error=error); failures.append(failure)
            folder.mkdir(parents=True, exist_ok=True); js(folder/'failure.json', failure)
            empty_ref = dict(intervals=[], status='no_reference_by_H')
            for method in METHODS:
                for spec in config['reference']['one_factor_sensitivity']:
                    # Cache execution failure does not invalidate a saved WORLD reference.
                    known_reference = references.get(key, {}).get(spec['id'], empty_ref)
                    record = dict(base, method=method.name, reference_id=spec['id'], status='unattempted', error=error,
                                  **score(None, known_reference, horizon, status='unattempted'))
                    sensitivity.append(record)
                    if spec['id'] == 'R0': results.append(dict(record))
    write_csv(output/'planned_method_results.csv', results)
    write_csv(output/'reference_sensitivity_results.csv', sensitivity)
    js(output/'development_summary.json', summarize_development(results)); js(output/'failures.json', failures)
    sources = list(Path(__file__).parent.glob('*.py'))+[Path(__file__).parents[1]/p for p in
        ('exp1b/gates.py','exp1b/spec.py','exp1b_closeout/replay.py','exp1b_closeout/run.py','model.py','observation.py')]
    sources += [Path(__file__).parents[2]/'experiment/evidence.py', Path(__file__).parents[3]/'run_chapter2_geometry_exp1b_random.py']
    js(output/'manifest.json', dict(version=VERSION, actual_development_seeds=seeds, formal_execution_allowed=False,
        planned_base_worlds=len(seeds)*4, planned_caches=len(seeds)*12, planned_method_records=len(seeds)*72,
        planned_reference_scores=len(seeds)*504, failures=failures,
        source_code={str(p.resolve()): sha(p) for p in sources},
        artifacts={p.relative_to(output).as_posix(): sha(p) for p in output.rglob('*') if p.is_file()}))
    return results
