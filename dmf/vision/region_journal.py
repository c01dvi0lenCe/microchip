"""Bounded off-inference-thread regional Mask and CSV persistence."""
from pathlib import Path
import queue
import threading

from dmf.recording import AsyncCsvLog
from .image_io import write_image


REGION_FIELDS=('sequence','region_id','epoch','kind','source_electrode','target_electrode','binding_sha256',
    'video_id','frame_id','capture_identity','source_timestamp_s','clock_domain','timing_json',
    'roi','source_shape','tile_count','backend','batch_size','submitted_perf_ns','started_perf_ns',
    'completed_perf_ns','processing_ms','pipeline_ms','source_age_ms','data_valid','reason',
    'identity_verified','control_eligible','needs_relocalization','quality_diagnostic','components',
    'foreground_px','mask_path','mask_pixels_sha256','error')


class RegionJournal:
    def __init__(self,output,save_masks=True):
        self.output=Path(output);self.save_masks=save_masks
        self.csv=AsyncCsvLog({'regions':(self.output/'regions.csv',REGION_FIELDS),
            'events':(self.output/'events.csv',('event','host_perf_counter_ns','region_id','capture_identity','detail'))})
        self.images=queue.Queue(maxsize=64);self.image_error=''
        self.writer=threading.Thread(target=self._write,name='region-mask-writer',daemon=True)
        self.writer.start()

    @property
    def error(self):return self.csv.error or self.image_error

    def mask(self,relative,mask):
        if not self.save_masks:return ''
        try:self.images.put_nowait((relative,mask.copy()))
        except queue.Full:self.image_error='regional mask queue overflow; data incomplete'
        return relative

    def _write(self):
        try:
            while True:
                item=self.images.get()
                if item is None:return
                relative,mask=item
                if not write_image(self.output/relative,mask):raise OSError('regional PNG write failed')
        except Exception as exc:self.image_error=f'{type(exc).__name__}: {exc}'

    def close(self):
        while self.writer.is_alive():
            try:self.images.put(None,timeout=.05);break
            except queue.Full:continue
        self.writer.join();self.csv.close()
