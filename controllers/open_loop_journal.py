"""Per-session command provenance using the existing nonblocking CSV writer."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import uuid

from dmf.recording import AsyncCsvLog, EVENT_FIELDS, clock_stamp, event_row


class OpenLoopJournal:
    def __init__(self, root, plan, settings, *, simulation, stream):
        self.output = Path(root)/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
        self.output.mkdir(parents=True, exist_ok=False)
        self.stream = stream
        self.simulation = bool(simulation)
        self.closed = False
        self.manifest = dict(schema='dmf_open_loop_session_v1', control_mode='timed_open_loop',
            simulation=self.simulation, vision_used_for_advancement=False,
            physical_transport_verified=False, physical_isolation_verified=False,
            timestamp_domain='host_monotonic_not_camera_exposure',
            settings=settings, routes={k:list(v) for k,v in plan.routes.items()},
            hold_ids=sorted(plan.hold_ids), global_frames=plan.length,
            status='running', completion_means='command_sequence_only_not_droplet_arrival')
        files=[Path(__file__),Path(__file__).with_name('open_loop_sequence.py'),
               Path(__file__).with_name('open_loop_controller.py'),
               Path(__file__).with_name('open_loop_manual.py'),
               Path(__file__).with_name('open_loop_manual_controller.py'),
               Path(__file__).with_name('timed_mixing_controller.py')]
        self.manifest['source_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        self.log=AsyncCsvLog({'events':(self.output/'electrode_events.csv',EVENT_FIELDS),
            'steps':(self.output/'steps.csv',('event','host_monotonic_ns','host_perf_counter_ns',
                'host_utc_ns','phase','active_ids','positions','confirmed_at_monotonic_s')),
            'manual':(self.output/'manual_commands.csv',('event','host_monotonic_ns',
                'host_perf_counter_ns','host_utc_ns','intent_id','changes','phase',
                'sequence','reason','confirmed_at_monotonic_s'))})
        self.listener=lambda event:self.log.append('events',event_row(event))
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
        target=self.output/'manifest.json'
        tmp=target.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        tmp.replace(target)

    def step(self,event,phase,active,positions,at=''):
        self.log.append('steps',dict(event=event,**clock_stamp(),phase=phase,
            active_ids=json.dumps(sorted(active)),positions=json.dumps(positions,ensure_ascii=False),
            confirmed_at_monotonic_s=at))

    def finish(self,status,active):
        if self.closed:return
        self.closed=True
        self.stream.unsubscribe(self.listener)
        self.log.close()
        self.manifest.update(status=status,last_commanded_active_ids=sorted(active),
            log_error=self.log.error,ended_stamp=clock_stamp(),written_rows=dict(self.log.counts))
        self._write_manifest()

    def manual(self,event,intent_id,changes,phase,*,sequence='',reason='',at=''):
        self.log.append('manual',dict(event=event,**clock_stamp(),intent_id=intent_id,
            changes=json.dumps(changes,sort_keys=True),phase=phase,sequence=sequence,
            reason=reason,confirmed_at_monotonic_s=at))
