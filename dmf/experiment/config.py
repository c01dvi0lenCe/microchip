"""Central configuration and preflight checks for all experiment modes."""
from dataclasses import dataclass, asdict, fields
from pathlib import Path
import math

from dmf.vision.config import load_yaml, resolve_path


@dataclass(frozen=True)
class StateConfig:
    v_th_mm_s: float = .2
    eta_enter: float = .15
    eta_arr: float = .75
    eta_release: float = .1
    position_tolerance_mm: float = .5
    max_speed_mm_s: float = 20.
    prediction_tolerance_mm: float = 2.
    history_max_gap_s: float = 1.
    consistency_frames: int = 2
    arrival_frames: int = 5
    arrival_duration_s: float = .25
    min_area_px: float = 10.
    max_area_px: float = 100000.
    min_confidence: float = .2


@dataclass(frozen=True)
class ControlConfig:
    wait_s: float = 8.
    max_retries: int = 2
    recovery_timeout_s: float = 8.
    max_recoveries: int = 2
    no_detection_timeout_s: float = 2.
    source_timeout_s: float = 10.
    source_frames: int = 5
    source_duration_s: float = .25


def typed_config(cls, values):
    cfg=cls(**values)
    for field in fields(cfg):
        value=getattr(cfg,field.name)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
            raise ValueError(f'{cls.__name__}.{field.name} must be finite and nonnegative')
        if field.type is int and (not isinstance(value,int)):
            raise ValueError(f'{field.name} must be an integer')
    if cls is StateConfig:
        if not (0<=cfg.eta_release<cfg.eta_arr<=1 and 0<cfg.eta_enter<cfg.eta_arr):
            raise ValueError('require 0 <= eta_release < eta_arr <= 1 and 0 < eta_enter < eta_arr')
        if cfg.consistency_frames<1 or cfg.arrival_frames<1 or cfg.max_speed_mm_s<=0 or cfg.history_max_gap_s<=0:
            raise ValueError('positive state frame counts, history gap and max speed required')
        if cfg.max_area_px<=cfg.min_area_px or not 0<=cfg.min_confidence<=1:
            raise ValueError('invalid mask area/confidence limits')
    if cls is ControlConfig:
        if min(cfg.wait_s,cfg.recovery_timeout_s,cfg.no_detection_timeout_s,cfg.source_timeout_s)<=0 or cfg.source_frames<1:
            raise ValueError('control timeouts and source_frames must be positive')
    return cfg


def load_config(path,mode=None):
    path=Path(path).resolve();c=load_yaml(path)
    c['mode']=mode or c.get('mode','offline')
    if c['mode'] not in {'offline','dry_run','experiment'}:raise ValueError('invalid MODE')
    c['state']=asdict(typed_config(StateConfig,c.get('state',{})))
    c['control']=asdict(typed_config(ControlConfig,c.get('control',{})))
    route=c.get('route',[])
    if len(route)<2 or any(type(x) is not int or not 1<=x<=400 for x in route):
        raise ValueError('Chapter 2 route requires at least two core electrodes (IDs 1..400)')
    for a,b in zip(route,route[1:]):
        ra,ca=divmod(a-1,20);rb,cb=divmod(b-1,20)
        if abs(ra-rb)+abs(ca-cb)!=1:raise ValueError('route must specify adjacent single-electrode transfers')
    c.setdefault('candidate_electrodes',[])
    if any(type(x) is not int or not 1<=x<=420 for x in c['candidate_electrodes']):raise ValueError('invalid candidate electrodes')
    for key in ('electrode_map','output_dir'):
        if not c.get(key):raise ValueError(f'{key} is required')
        c[key]=str(resolve_path(path.parent,c[key]))
    source=c.setdefault('source',{})
    if c['mode']=='offline':
        if not source.get('video'):raise ValueError('source.video is required in offline mode')
        source['video']=str(resolve_path(path.parent,source['video']))
        if source.get('timestamps_csv'):
            source['timestamps_csv']=str(resolve_path(path.parent,source['timestamps_csv']))
    else:
        if source.get('backend') not in {'opencv','plugin'}:raise ValueError('live source.backend must be opencv or plugin')
    source.setdefault('frame_timeout_s',2.)
    if not math.isfinite(source['frame_timeout_s']) or source['frame_timeout_s']<=0:raise ValueError('positive frame timeout required')
    seg=c.setdefault('segmentation',{})
    if seg.get('name')=='unet':
        if not seg.get('model_path'):raise ValueError('segmentation.model_path required; supply an exported U-Net')
        seg['model_path']=str(resolve_path(path.parent,seg['model_path']))
    elif not (c['mode']=='offline' and c.get('synthetic_test_only') is True and seg.get('name')=='threshold'):
        raise ValueError('U-Net required; threshold is only allowed for explicit offline synthetic tests')
    serial=c.setdefault('serial',{})
    serial.setdefault('ack_timeout_s',.35);serial.setdefault('command_timeout_s',5.)
    serial.setdefault('max_retries',2);serial.setdefault('baudrate',115200)
    for key in ('ack_timeout_s','command_timeout_s'):
        if not math.isfinite(serial[key]) or serial[key]<=0:raise ValueError(f'positive serial.{key} required')
    if type(serial['max_retries']) is not int or not 0<=serial['max_retries']<=2:raise ValueError('serial retries must be 0..2')
    if c['mode']=='experiment':
        if c.get('enable_am_output') is not True or c.get('calibration_confirmed') is not True:
            raise ValueError('experiment requires enable_am_output and calibration_confirmed')
        if not serial.get('port'):raise ValueError('serial.port is required for experiment')
    if c.get('emergency_stop_file'):c['emergency_stop_file']=str(resolve_path(path.parent,c['emergency_stop_file']))
    c.setdefault('recording',{'raw':False,'mask':False,'overlay':False})
    c['config_path']=str(path)
    return c
