"""Exactly ten approved cases; no seed, draw, search or adaptive injection."""
from dataclasses import asdict, dataclass
from ..exp2.spec import Exp2Config

VERSION = 'geometry_exp2_fault_mechanisms_development_v1'


@dataclass(frozen=True)
class FaultCase:
    case_id: str
    method: str
    stall_at_s: float | None = None
    fake_exposures_s: tuple = ()
    fake_electrode: int | None = None
    # Saved pool endpoint 1 is compact (about 3.894 x 3.777 mm); endpoint 0
    # is elongated (about 4.675 x 3.112 mm). Fixed before any algorithm run.
    fake_phase: float = 1.
    drop_frame_ids: tuple = ()
    delayed_frame_id: int | None = None
    extra_delay_s: float = 0.
    duplicate_frame_id: int | None = None
    duplicate_offset_s: float = .02
    applied_delay_s: float | None = None

    def snapshot(self):
        return asdict(self)


_FALSE_WINDOW = tuple(round(2.2 + i*.05, 2) for i in range(12))
CASES = (
    FaultCase('early_M1','M1',fake_exposures_s=(2.05,),fake_electrode=191),
    FaultCase('early_M2','M2',fake_exposures_s=(2.05,),fake_electrode=191),
    FaultCase('stall_false_M2','M2',stall_at_s=2.,fake_exposures_s=_FALSE_WINDOW,fake_electrode=191),
    FaultCase('stall_false_M3','M3',stall_at_s=2.,fake_exposures_s=_FALSE_WINDOW,fake_electrode=191),
    FaultCase('camera_gap_M2','M2',drop_frame_ids=tuple(range(20,33))),
    FaultCase('late_duplicate_M2','M2',delayed_frame_id=68,extra_delay_s=1.,duplicate_frame_id=69),
    FaultCase('applied_delay_M2','M2',applied_delay_s=.30),
    FaultCase('stall_timeout_M2','M2',stall_at_s=2.),
    FaultCase('turn_early_M1','M1',fake_exposures_s=(4.8,),fake_electrode=192),
    FaultCase('turn_early_M2','M2',fake_exposures_s=(4.8,),fake_electrode=192),
)

