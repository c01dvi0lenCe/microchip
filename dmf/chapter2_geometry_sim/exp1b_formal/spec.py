"""Immutable formal wrapper around the reviewed proposal and DEV amendments."""
import copy
import hashlib
import json
from pathlib import Path
from ..exp1b_random.spec import load_protocol as load_development, APPROVED_BASE_SHA256

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT/'configs/chapter2_geometry_exp1b_formal_v1.json'
DEV_SHA256 = '290c54e965dc5124355efae63e12fba8ac6f71ae6cf3afe89fee9ac4841a05b0'
SEEDS = tuple(range(266000,266020))
SLOTS = {seed: index for index,seed in enumerate(SEEDS)}
VERSION = 'geometry_exp1b_formal_v1'
STATISTICS_VERSION = 'exp1b_formal_stratified_v1'
PLAN = dict(base_worlds=80, shared_caches=240, method_records=1440, reference_scores=10080)
LATENCY_POLICY = 'combined descriptive median only; inferential latency confined to base and individual low/high strata'


def validate_formal_seeds(seeds):
    seeds = list(seeds)
    if any(type(s) is not int for s in seeds) or seeds != list(SEEDS):
        raise ValueError('Exactly the ordered formal seeds 266000..266019 required; no subset or replacement')
    return seeds


def load_protocol(path=None):
    path = Path(path or DEFAULT_CONFIG).resolve()
    wrapper = json.loads(path.read_text(encoding='utf-8'))
    expected = dict(schema='chapter2_geometry_exp1b_formal_v1',
        extends_development='chapter2_geometry_exp1b_random_dev_v1.json',
        development_wrapper_sha256=DEV_SHA256, base_sha256=APPROVED_BASE_SHA256,
        formal_seed_slots={str(s):i for s,i in SLOTS.items()}, maximum_batches=1,
        execution_requires_verified_freeze=True, statistics_version=STATISTICS_VERSION,
        latency_mixture_policy=LATENCY_POLICY,
        scope='One approved 20-seed paired batch only after verification freeze; no new model, thresholds, distribution or development seeds.')
    if wrapper != expected or any(type(v) is not int for v in wrapper['formal_seed_slots'].values()):
        raise ValueError('Formal wrapper may not override approved identities, algorithms, statistics or protocol')
    dev_path = (path.parent/wrapper['extends_development']).resolve()
    if hashlib.sha256(dev_path.read_bytes()).hexdigest() != DEV_SHA256:
        raise ValueError('DEV wrapper hash mismatch')
    config = copy.deepcopy(load_development(dev_path))
    config.update(wrapper)
    config.update(effective_config_path=str(path), development_wrapper_path=str(dev_path),
        execution_allowed=False, formal_execution_allowed=False, actual_plan=dict(PLAN))
    validate_formal_seeds(SEEDS)
    return config


def planned_identities(config, primary=False):
    references = ['R0'] if primary else [r['id'] for r in config['reference']['one_factor_sensitivity']]
    return [(str(seed), c['id'], m['name'], rid) for seed in SEEDS for c in config['conditions']
        for m in config['methods'] for rid in references]


def identity(row):
    return tuple(str(row[k]) for k in ('seed','condition','method','reference_id'))


def validate_identities(rows, expected):
    actual = [identity(row) for row in rows]
    if len(set(actual)) != len(actual) or set(actual) != set(expected) or len(actual) != len(expected):
        raise ValueError('Duplicate or missing planned record identities')


def stratum(seed, condition):
    return 'base' if condition['strata']=='base' else 'low' if SLOTS[seed] < 10 else 'high'
