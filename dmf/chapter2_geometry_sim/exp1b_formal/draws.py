"""PCG64 draws with unchanged entropy, order and transformations; no DEV whitelist leak."""
import copy
import hashlib
import numpy as np
from .spec import SEEDS


def _draw(seed,stream,condition,size):
    entropy = [20261029,seed,0,stream,condition]
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence(entropy)))
    before = copy.deepcopy(rng.bit_generator.state)
    values = rng.random(size)
    return values,dict(entropy=entropy,NumPy_version=np.__version__,bit_generator='PCG64',
        state_before=before,state_after=copy.deepcopy(rng.bit_generator.state),
        array_sha256=hashlib.sha256(values.tobytes(order='C')).hexdigest(),dtype=str(values.dtype))


def _range(u,limits): return float(limits[0]+u*(limits[1]-limits[0]))
def _integer(u,limits): return min(limits[1],limits[0]+int(u*(limits[1]-limits[0]+1)))


def _motion(seed,config):
    spec=config['rng']['world_shared_raw_motion_stream']
    raw,meta=_draw(seed,spec['stream_code'],spec['condition_code'],5)
    motion=config['motion']
    params=dict(normal_peak_speed_mm_s=_range(raw[0],motion['normal_peak_speed_mm_s']['range']),
        slow_peak_speed_mm_s=_range(raw[0],motion['slow_peak_speed_mm_s']['range']),
        response_delay_s=_range(raw[1],motion['response_delay_s']['range']),
        pause_progress=_range(raw[2],motion['pause_progress']['range']),
        pause_duration_s=_range(raw[3],motion['pause_duration_s']['range']),
        stall_progress=_range(raw[4],motion['stall_progress']['range']))
    return dict(seed=seed,raw_uniforms=raw.tolist(),parameters=params,rng=meta)


def _observation(seed,condition,stratum,config):
    if stratum not in ('low','high'): raise ValueError('low/high draw stratum required')
    r=config['rng'];code=r['condition_codes'][condition]
    raw,meta=_draw(seed,r['observation_parameter_stream_code'],code,7)
    obs=config['observation']
    p=dict(start_progress=_range(raw[0],obs['ordinary_episode_start_progress_uniform']),
        false_start_progress=_range(raw[0],obs['false_episode_start_progress_uniform']),
        duration_s=_range(raw[1],obs['ordinary_episode_duration_s_uniform']),
        jitter_amplitude_mm=_range(raw[2],obs['jitter_coordinate_uniform_mm'][stratum+'_amplitude_range']),
        bias_magnitude_mm=_range(raw[2],obs['bias_magnitude_uniform_mm'][stratum]),
        bias_angle_rad=_range(raw[3],obs['bias_magnitude_uniform_mm']['angle_uniform_rad']),
        rear_cut_fraction=_range(raw[4],obs['rear_cut_bbox_fraction_uniform'][stratum]),
        false_frames=_integer(raw[5],obs['false_target_consecutive_frames_discrete_uniform'][stratum]),
        stall_false_frames=_integer(raw[6],config['TF_revision']['consecutive_frames'][stratum]),
        fragment_band_pixels=obs['fragment_band_pixels'][stratum],
        drop_probability=obs['drop_each_post_applied_capture_probability'][stratum],
        delay_probability=obs['delay_each_post_applied_capture_probability'],
        extra_delay_range_s=obs['extra_delivery_delay_s_uniform'][stratum])
    arrays={};states=dict(parameters=meta)
    for name,stream,shape in [('spatial_uniform',r['per_frame_spatial_stream_code'],(200,2)),
            ('drop_uniform',r['drop_stream_code'],(200,)),
            ('delay_probability_and_magnitude_uniform',r['delivery_delay_stream_code'],(200,2))]:
        arrays[name],states[name]=_draw(seed,stream,code,shape)
    return dict(seed=seed,condition=condition,stratum=stratum,parameters=p,
        raw_parameter_uniforms=raw.tolist(),arrays=arrays,rng=states)


def _formal_seed(seed):
    if type(seed) is not int or seed not in SEEDS: raise ValueError('A declared formal seed required')


def draw_motion(seed,config):
    _formal_seed(seed)
    return _motion(seed,config)


def draw_observation(seed,condition,stratum,config):
    _formal_seed(seed)
    return _observation(seed,condition,stratum,config)


def fixture_motion(seed,config):
    if seed != 268000: raise ValueError('Only the approved pure-formula DEV fixture 268000')
    return _motion(seed,config)


def fixture_observation(seed,condition,stratum,config):
    if seed != 268000: raise ValueError('Only the approved pure-formula DEV fixture 268000')
    return _observation(seed,condition,stratum,config)
