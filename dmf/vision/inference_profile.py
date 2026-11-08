"""Independent instrumentation of frozen G4 inference, never a production path.

Host intervals partition one call; CUDA events describe the same work on a
different clock and must NEVER be added to host timings. No per-stage device
synchronization is inserted. The existing finite-logit check and blocking D2H
therefore charge their waits to postprocess_host_ms and d2h_host_ms respectively.
"""
from contextlib import nullcontext
from time import perf_counter_ns

import numpy as np

from dmf.segmentation_research.semantic_baselines import prepare_image, restore_mask


def profile_infer(predictor, images):
    """Return ``(native_masks, stages)`` with G4UNetPredictor._infer semantics.

The caller must supply a frozen/eval predictor. CUDA presynchronization and
event-query bookkeeping are reported separately, outside total_host_ms.
The GPU event intervals include stream idle gaps caused by host execution;
they are not isolated kernel profiler measurements. Batch size is caller-owned.
"""
    torch = predictor.torch
    cuda = predictor.device == 'cuda'
    events = {name: torch.cuda.Event(enable_timing=True)
              for name in ('start', 'h2d', 'model', 'postprocess', 'd2h')} if cuda else {}
    sync_started = perf_counter_ns()
    if cuda:
        torch.cuda.synchronize()
    presync_ms = (perf_counter_ns() - sync_started) / 1e6 if cuda else 0.0
    started = mark = perf_counter_ns()
    inputs = []; metas = []
    for image in images:
        prepared, meta = prepare_image(image); metas.append(meta)
        inputs.append(predictor.image_tensor(prepared[:, :, ::-1].astype(np.float32) / 255.))
    x = torch.stack(inputs)
    now = perf_counter_ns(); preprocess_ms = (now - mark) / 1e6; mark = now
    if cuda:
        events['start'].record()
    x = x.to(predictor.device)
    if cuda:
        events['h2d'].record()
    now = perf_counter_ns(); h2d_ms = (now - mark) / 1e6; mark = now
    context = torch.autocast('cuda', dtype=torch.float16) if cuda else nullcontext()
    with torch.inference_mode(), context:
        output = predictor.model(x)
    if cuda:
        events['model'].record()
    now = perf_counter_ns(); model_ms = (now - mark) / 1e6; mark = now
    if not torch.isfinite(output).all():
        raise ValueError('nonfinite U-Net logits')
    binary = (output.float().sigmoid() >= .5).to(torch.uint8)
    if cuda:
        events['postprocess'].record()
    now = perf_counter_ns(); postprocess_ms = (now - mark) / 1e6; mark = now
    masks = binary.cpu().numpy()[:, 0] * 255
    if cuda:
        events['d2h'].record()
    now = perf_counter_ns(); d2h_ms = (now - mark) / 1e6; mark = now
    restored = [restore_mask(mask, meta) for mask, meta in zip(masks, metas)]
    ended = perf_counter_ns()
    stages = dict(backend=str(predictor.device), image_count=len(inputs),
                  preprocess_host_ms=preprocess_ms, h2d_host_ms=h2d_ms,
                  model_host_ms=model_ms, postprocess_host_ms=postprocess_ms,
                  d2h_host_ms=d2h_ms, restore_host_ms=(ended - mark) / 1e6,
                  total_host_ms=(ended - started) / 1e6,
                  cuda_pre_sync_host_ms=presync_ms, cuda_event_query_host_ms=0.,
                  cuda_events_ms=None)
    if cuda:
        query_started = perf_counter_ns()
        events['d2h'].synchronize()
        stages['cuda_events_ms'] = {
            'h2d': events['start'].elapsed_time(events['h2d']),
            'model': events['h2d'].elapsed_time(events['model']),
            'postprocess': events['model'].elapsed_time(events['postprocess']),
            'd2h': events['postprocess'].elapsed_time(events['d2h']),
            'stream_span': events['start'].elapsed_time(events['d2h']),
        }
        stages['cuda_event_query_host_ms'] = (perf_counter_ns() - query_started) / 1e6
    return restored, stages
