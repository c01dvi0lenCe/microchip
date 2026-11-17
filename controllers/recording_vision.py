"""Recording/detection lifecycle only; never owns an electrode transaction."""
import json
from pathlib import Path
import time
import tkinter as tk
import uuid

from dmf.recording import sidecar_paths


class RecordingVisionMixin:
    def _init_recording_vision(self):
        self.recording_vision_var=tk.BooleanVar(value=True)
        self._recording_vision=None

    def _write_recording_vision(self,session):
        try:
            path=session['sidecar'];path.parent.mkdir(parents=True,exist_ok=True)
            temporary=path.with_suffix(path.suffix+'.tmp')
            temporary.write_text(json.dumps(session['data'],ensure_ascii=False,indent=2),encoding='utf-8')
            temporary.replace(path)
        except Exception as exc:
            self.log(f'录像检测索引保存失败：{exc}')
            session['data']['index_error']=str(exc)
            message='index_write_failed: '+str(exc)
            if message not in session['data']['errors']:session['data']['errors'].append(message)

    def _begin_linked_recording(self,path):
        if not getattr(self,'_operator_only',True):return False
        if self._recording_vision is not None:
            self.log('录像检测正在准备或保存，请稍候');return True
        if not self.recording_vision_var.get():return False
        path=Path(path)
        session=dict(sidecar=path.with_suffix('.vision-session.json'),video=path,detector=None,
            deadline=time.monotonic()+30,data=dict(schema='dmf_recording_vision_v1',
                experiment_id=uuid.uuid4().hex,video=str(path),status='preparing_detection',
                control_output=False,arrival_evaluated=False,errors=[],
                button_start_monotonic_ns=time.monotonic_ns(),
                recording_sidecars={k:str(v) for k,v in sidecar_paths(path).items()},
                boundary_semantics='host command acknowledgement; not exposure or physical AM output'))
        self._recording_vision=session
        self.btn_camera_record.config(state='disabled')
        detector=self._vision_detector
        if detector is None:
            if not self.start_realtime_detection(save_masks=True):
                session['data']['errors'].append('detection_start_failed: '+self.vision_status_var.get())
        elif not self._vision_accepting:
            session['data']['errors'].append('previous_detector_still_stopping')
            detector=None
        session['detector']=self._vision_detector if detector is not None or self._vision_accepting else None
        if session['detector'] is not None:
            session['detector'].save_masks=True
            session['data']['detection_directory']=str(session['detector'].output)
        self._write_recording_vision(session)
        self._wait_recording_vision(session)
        return True

    def _wait_recording_vision(self,session):
        if self._recording_vision is not session:return
        if session['data']['status']!='preparing_detection':return
        if not self.camera_running:
            self._abort_recording_vision('camera_closed_during_preparation');return
        detector=session['detector']
        if detector is not None and not detector.ready and detector.worker.is_alive() and time.monotonic()<session['deadline']:
            self.root.after(50,lambda:self._wait_recording_vision(session));return
        if detector is None or not detector.ready:
            reason='detector_not_ready' if detector is None else detector.error or 'detector_ready_timeout'
            session['data']['errors'].append(reason)
            if detector is not None:detector.stop();self._vision_accepting=False
            self.log('检测未就绪，仍保留原始录像；本次检测记录将标为不完整')
        session['data']['status']='recording_start_pending'
        session['data']['recording_request_monotonic_ns']=time.monotonic_ns()
        self._write_recording_vision(session)
        self._submit_camera_recording_command('start_recording',session['video'])

    def _recording_vision_started(self,path):
        session=self._recording_vision
        if session is None:return
        session['data'].update(status='recording',recording_start_ack_monotonic_ns=time.monotonic_ns())
        detector=session['detector']
        session['data']['detector_counts_at_recording_start']={
            k:getattr(detector,k,None) for k in ('completed','scan_completed','failed')}
        self._write_recording_vision(session)

    def _recording_vision_stopping(self):
        session=self._recording_vision
        if session is None:return
        session['data'].setdefault('detection_input_cutoff_monotonic_ns',time.monotonic_ns())
        self._vision_accepting=False
        detector=session['detector']
        if detector is not None:detector.finish()
        self._write_recording_vision(session)

    def _recording_vision_finished(self,path,error='',acknowledged=True):
        session=self._recording_vision
        if session is None:return
        self._recording_vision_stopping()
        if error:session['data']['errors'].append(error)
        session['data'].update(status='saving_detection',recording_end_observed_monotonic_ns=time.monotonic_ns())
        if acknowledged and not error:session['data']['recording_stop_ack_monotonic_ns']=time.monotonic_ns()
        self._write_recording_vision(session)
        self.btn_camera_record.config(state='disabled')
        self._poll_recording_vision_saved(session)

    def _poll_recording_vision_saved(self,session):
        if self._recording_vision is not session:return
        detector=session['detector']
        if detector is not None and detector.worker.is_alive():
            self.root.after(50,lambda:self._poll_recording_vision_saved(session));return
        if detector is not None:
            error=detector.error or detector.log.error
            if error:session['data']['errors'].append(error)
            session['data']['detector_counts_at_close']={
                k:getattr(detector,k,None) for k in ('completed','scan_completed','failed')}
            if getattr(detector,'failed',0):session['data']['errors'].append('detector_has_failed_frames; inspect detector CSV')
            if not (detector.output/'manifest.json').exists():
                session['data']['errors'].append('detector_final_manifest_missing')
        session['data'].update(status='incomplete' if session['data']['errors'] else 'saved',
            saved_monotonic_ns=time.monotonic_ns())
        self._write_recording_vision(session)
        self._recording_vision=None
        if self.camera_running:self.btn_camera_record.config(state='normal')
        self.log(f"录像及检测索引已保存：{session['sidecar']}"+
                 ('；检测/录像有缺失，请查看errors' if session['data']['errors'] else ''))

    def _abort_recording_vision(self,reason):
        session=self._recording_vision
        if session is None:return
        session['data']['errors'].append(reason)
        self._recording_vision_finished(session['video'],acknowledged=False)
