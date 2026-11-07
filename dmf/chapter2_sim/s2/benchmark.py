"""Thin GT-blind wrapper over the existing pure v2 arrival evaluator."""
from dataclasses import asdict
import json
from pathlib import Path

from ..v2.benchmark import run_arrival_variant
from .spec import flags_for


def predict_arrivals(cache_root, method, output_root, spec, *, diagnostic=False):
    flags=flags_for(method,diagnostic=diagnostic)
    report=run_arrival_variant(cache_root,method,output_root,spec,flags=flags)
    report.update(method_version=spec.version,role='auxiliary_diagnostic' if diagnostic else 'primary',
                  shared_quality_contract=asdict(spec.quality),C0_always_on=True,
                  effective_window=(asdict(spec.target.window) if flags.W else
                                    dict(frames=1,duration_s=0.,centroid_span_pitch=None,coverage_span=None)),
                  reference_visible=False)
    (Path(output_root)/'prediction_manifest.json').write_text(
        json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    return report
