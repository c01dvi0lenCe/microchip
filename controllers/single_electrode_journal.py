"""Command provenance for a single-electrode cycle, not scope synchronization."""
from datetime import datetime
import json
from pathlib import Path
import uuid

from dmf.recording import AsyncCsvLog, EVENT_FIELDS, clock_stamp, event_row


class SingleElectrodeJournal:
    def __init__(self, root, electrode_id, stream):
        self.output = Path(root) / (datetime.now().strftime('%Y%m%d_%H%M%S')
                                    + '_' + uuid.uuid4().hex[:8])
        self.output.mkdir(parents=True, exist_ok=False)
        self.stream = stream
        self.closed = False
        self.manifest = dict(schema='dmf_single_electrode_cycle_v1',
            electrode_id=electrode_id, dwell_s=.25, state_frequency_nominal_hz=2,
            scheduling='250ms_after_APPLIED_receive',
            timestamp_domain='host_receive_not_physical_OFF_write',
            high_voltage_source_controlled=False, physical_off_verified=False,
            status='running', started_stamp=clock_stamp())
        self.log = AsyncCsvLog({'events': (self.output / 'electrode_events.csv', EVENT_FIELDS)})
        self.listener = lambda event: self.log.append('events', event_row(event))
        try:
            self.stream.subscribe(self.listener)
            self._write_manifest()
            if self.log.error:
                raise OSError(self.log.error)
        except Exception:
            self.stream.unsubscribe(self.listener)
            self.log.close()
            raise

    @property
    def error(self):
        return self.log.error

    def _write_manifest(self):
        target = self.output / 'manifest.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(target)

    def finish(self, released, error):
        if self.closed:
            return
        self.closed = True
        self.stream.unsubscribe(self.listener)
        self.log.close()
        self.manifest.update(status='released_buffer_only' if released else 'state_unknown',
            error=error, log_error=self.log.error, ended_stamp=clock_stamp(),
            written_rows=dict(self.log.counts))
        self._write_manifest()
