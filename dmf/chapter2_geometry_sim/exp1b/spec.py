"""Predeclared deterministic cases; no random performance batch."""
from dataclasses import dataclass,asdict


@dataclass(frozen=True)
class MethodSpec:
    name: str
    q: bool=False
    w: bool=False
    s: bool=False
    k: bool=False


METHODS=(MethodSpec('M1'),MethodSpec('GQ',q=True),MethodSpec('M2',q=True,w=True),
         MethodSpec('M2_S',q=True,w=True,s=True),MethodSpec('M2_K',q=True,w=True,k=True),
         MethodSpec('M3',q=True,w=True,s=True,k=True))


@dataclass(frozen=True)
class CaseSpec:
    name: str
    label: str
    world: str='normal'
    source_type: str='synthetic_stress'


CASES=(CaseSpec('A0','正常','normal','model_generated'),
       CaseSpec('B1','慢速','slow','model_generated'),CaseSpec('B2','暂停恢复','pause','model_generated'),
       CaseSpec('B3','最终卡滞','stall','model_generated'),CaseSpec('C1','小幅抖动'),
       CaseSpec('C2','位置偏移'),CaseSpec('C3','局部缺失'),CaseSpec('C4','破碎观测'),
       CaseSpec('C5','一帧伪目标'),CaseSpec('C6','七帧伪目标'),CaseSpec('D1','单帧丢失'),
       CaseSpec('D2','五帧丢失'),CaseSpec('D3','重复帧'),CaseSpec('D4','乱序延迟'),
       CaseSpec('D5','旧任务帧'),CaseSpec('D6','合法新帧突跳'))

VERSION='geometry_exp1b_mechanisms_v1'
HORIZON=10.
GATES=dict(rho_target=.9,eta_source=.08,min_frames=5,min_span_s=.25,max_gap_s=.18,
           target_distance_mm=.576,max_history_speed_mm_s=19.2)


def snapshot():
    return dict(version=VERSION,seed=264900,random_draws=0,horizon_s=HORIZON,
        source=190,target=191,request_s=.5,applied_s=.54,response_s=.72,dt_s=.01,
        camera_fps=20.,pixels_per_mm=40.,diameter_mm=4.,spacer_height_mm=.8,
        methods=[asdict(m) for m in METHODS],cases=[asdict(c) for c in CASES],gates=GATES,
        reference=dict(radius_mm=.288,max_speed_mm_s=.192,dwell_s=.15),
        observation_window_s=[4.2,4.5],false_target_window_s=[2.,2.3],
        case_parameters=dict(slow_peak_mm_s=.7,pause_progress=.55,pause_s=1.,stall_progress=.55,
            jitter_px=1,bias_px=8,missing_rear_bbox_fraction=.2,split_band_px=2,
            false_target_one_frame_s=2.,false_target_seven_exposures_s=[2.,2.05,2.1,2.15,2.2,2.25,2.3],
            drop_one_s=4.4,drop_five_exposures_s=[4.3,4.35,4.4,4.45,4.5],
            duplicate_exposure_s=4.4,duplicate_extra_process_delay_s=.001,
            delayed_exposure_s=4.4,extra_process_delay_s=.3,old_epoch_exposure_s=4.4,
            jump_exposure_s=4.4,jump_lateral_mm=1.2),
        status='fixed_development_mechanisms_not_random_performance')
