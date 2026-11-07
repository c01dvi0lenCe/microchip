"""Load the hash-bound proposal with explicit development-only overrides."""
import copy
import hashlib
import json
from pathlib import Path
from ..exp1b.spec import GATES, METHODS

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / 'configs/chapter2_geometry_exp1b_random_dev_v1.json'
APPROVED = {268000: 0, 268001: 10}
APPROVED_BASE_SHA256 = '93d0de69c1c64c6772c4a46c97f1991489d34232136877be10747a4f824f4b03'
APPROVED_TF_REVISION = dict(
    start_rule='first capture at or after permanent_stall_started_s + fixed_offset_s',
    fixed_offset_s=.20, consecutive_frames=dict(low=[7,9],high=[10,12]), no_redraw=True,
    require_entire_episode_after_stall=True,
    persist_times=['permanent_stall_started_s','false_target_start_s','false_target_end_s','actual_false_frames'])


def validate_development_seeds(seeds, config):
    seeds = list(seeds)
    if (not seeds or len(seeds) > 2 or any(type(s) is not int for s in seeds)
            or len(set(seeds)) != len(seeds) or any(s not in APPROVED for s in seeds)):
        raise ValueError('Only unique approved development seeds 268000 and 268001 are permitted')
    slots = config.get('development_seed_slots')
    if slots != {str(s): slot for s, slot in APPROVED.items()} or any(type(v) is not int for v in slots.values()):
        raise ValueError('Approved seed slots cannot be changed')
    return seeds


def load_protocol(path=None):
    path = Path(path or DEFAULT_CONFIG).resolve()
    wrapper = json.loads(path.read_text(encoding='utf-8'))
    approved_keys = {'schema','extends','base_sha256','status','formal_execution_allowed',
        'development_seed_slots','development_max_unique_seeds','development_max_caches',
        'TF_revision','reference_revision','scope'}
    if set(wrapper)-approved_keys:
        raise ValueError('Development wrapper cannot override unapproved proposal parameters')
    if (wrapper.get('base_sha256') != APPROVED_BASE_SHA256
            or json.dumps(wrapper.get('TF_revision'),sort_keys=True) != json.dumps(APPROVED_TF_REVISION,sort_keys=True)
            or type(wrapper.get('development_max_unique_seeds')) is not int
            or wrapper['development_max_unique_seeds'] != 2
            or type(wrapper.get('development_max_caches')) is not int
            or wrapper['development_max_caches'] != 24
            or wrapper.get('formal_execution_allowed') is not False):
        raise ValueError('Only the approved proposal digest, TF revision and development limits are permitted')
    base_path = (path.parent / wrapper['extends']).resolve()
    digest = hashlib.sha256(base_path.read_bytes()).hexdigest()
    if digest != APPROVED_BASE_SHA256:
        raise ValueError('Base proposal hash mismatch')
    base = json.loads(base_path.read_text(encoding='utf-8'))
    result = copy.deepcopy(base)
    result.update(wrapper)
    result.update(formal_execution_allowed=False, execution_allowed=False,
                  effective_config_path=str(path), base_path=str(base_path))
    validate_development_seeds(APPROVED, result)
    if result.get('TF_revision', {}).get('fixed_offset_s') != .2:
        raise ValueError('TF fixed stall offset must remain 0.20 s')
    expected = dict(rho_target_min=GATES['rho_target'], eta_source_max=GATES['eta_source'],
        W_min_frames=GATES['min_frames'], W_min_span_s=GATES['min_span_s'],
        W_max_gap_s=GATES['max_gap_s'], S_target_distance_max_mm=GATES['target_distance_mm'],
        K_raw_history_speed_max_mm_s=GATES['max_history_speed_mm_s'])
    if any(result['shared_gates'][k] != v for k, v in expected.items()):
        raise ValueError('Existing gate thresholds must not change')
    for old, new in zip(METHODS, result['methods']):
        if old.name != new['name'] or any(getattr(old, k.lower()) != new[k] for k in 'QWSK'):
            raise ValueError('Existing method flags must not change')
    if len(result['methods']) != len(METHODS):
        raise ValueError('Exactly six unchanged methods required')
    return result
