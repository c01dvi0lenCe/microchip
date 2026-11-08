"""Operator sensing display only. Never updates task/control perception fields."""
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import filedialog,ttk
import uuid

import cv2
from dmf.vision.config import load_yaml
from dmf.vision.g4_model import G4UNetPredictor
from dmf.vision.image_io import write_image
from dmf.vision.whole_chip import WholeChipDetector
from dmf.vision.priority_vision import PriorityVisionDetector
from dmf.vision.task_regions import TaskRegion
from .dual_vision_display import DualVisionDisplayMixin


class RealtimeVisionControllerMixin(DualVisionDisplayMixin):
    def _init_realtime_vision(self):
        repo=Path(__file__).resolve().parents[1]
        # This G4 package failed the 120-ROI batch audit. Preserve the audited
        # single-image setting across application restarts, not just one worker.
        defaults=dict(model_package='models/g4_unet',device='auto',batch_size=1,output_root='results/realtime_vision',
            native_single=False,task_period_s=.1,max_task_age_s=.25,max_inspection_age_s=1.,inspection_period_s=1.)
        self._vision_settings=dict(defaults)
        self._vision_config_error=''
        try:
            for name in ('realtime_vision.yaml','realtime_vision.local.yaml'):
                p=repo/'configs'/name
                if p.exists():self._vision_settings.update(load_yaml(p))
            if any(not isinstance(self._vision_settings[k],str) or not self._vision_settings[k]
                   for k in ('model_package','output_root')):raise ValueError('model_package/output_root须为非空路径')
            if self._vision_settings['device'] not in ('auto','cpu','cuda'):raise ValueError('device须为auto/cpu/cuda')
            if type(self._vision_settings['batch_size']) is not int or self._vision_settings['batch_size'] not in (1,4):
                raise ValueError('batch_size须为1或4')
            if type(self._vision_settings['native_single']) is not bool:raise ValueError('native_single须为布尔值')
            for key in ('task_period_s','max_task_age_s','max_inspection_age_s','inspection_period_s'):
                value=self._vision_settings[key]
                if type(value) not in (int,float) or value<0 or (key!='inspection_period_s' and value==0):
                    raise ValueError(f'{key}须为有效非负秒数')
                if value>60:raise ValueError(f'{key}不能超过60秒')
        except Exception as exc:
            self._vision_config_error=str(exc);self._vision_settings=dict(defaults)
        model=Path(self._vision_settings['model_package'])
        self.vision_package_var=tk.StringVar(value=str(model if model.is_absolute() else repo/model))
        self.vision_view_var=tk.StringVar(value='原图')
        self.vision_status_var=tk.StringVar(value='仅检测 · 未启动 · 未配准')
        output=Path(self._vision_settings['output_root'])
        self._vision_output_root=output if output.is_absolute() else repo/output
        self._vision_detector=None;self._vision_latest_result=None;self._vision_poll_id=None
        self._vision_accepting=False;self._vision_roi=None;self._vision_selecting=False
        self._vision_select_start=None;self._vision_display_frame_id=None
        self._latest_camera_packet=None;self._vision_snapshot_worker=None;self._vision_snapshot_error=''
        self._vision_snapshot_path=None;self._vision_previous_end=None;self._vision_fps=0.
        self._hardware_preview_overwrites=0
        self._init_dual_vision()

    def _build_realtime_vision_controls(self,parent):
        self._build_dual_vision_controls(parent)
        row=tk.Frame(parent,bg=self.colors['panel']);row.pack(fill='x',padx=8,pady=2)
        tk.Label(row,text='模型包',bg=self.colors['panel']).pack(side='left')
        tk.Entry(row,textvariable=self.vision_package_var,width=28).pack(side='left',fill='x',expand=True,padx=3)
        tk.Button(row,text='选择',command=self._choose_vision_package).pack(side='left')
        self.btn_detect_start=tk.Button(row,text='启动检测',command=self.start_realtime_detection)
        self.btn_detect_start.pack(side='left',padx=3)
        self.btn_detect_stop=tk.Button(row,text='停止检测',command=self.stop_realtime_detection,state='disabled')
        self.btn_detect_stop.pack(side='left')
        tools=tk.Frame(parent,bg=self.colors['panel']);tools.pack(fill='x',padx=8,pady=2)
        tk.Button(tools,text='整芯片范围',command=self._select_vision_roi).pack(side='left')
        tk.Button(tools,text='恢复全图',command=self._reset_vision_roi).pack(side='left',padx=3)
        view=ttk.Combobox(tools,textvariable=self.vision_view_var,state='readonly',values=('原图','叠加','Mask'),width=6)
        view.pack(side='left',padx=4);view.bind('<<ComboboxSelected>>',lambda _:self._vision_view_changed())
        self.btn_vision_save=tk.Button(tools,text='保存结果',command=self.save_vision_result,state='disabled')
        self.btn_vision_save.pack(side='left',padx=3)
        tk.Label(parent,textvariable=self.vision_status_var,bg=self.colors['panel'],fg=self.colors['muted'],
                 anchor='w',justify='left',wraplength=550).pack(fill='x',padx=8,pady=(0,3))
        if self._vision_config_error:self.vision_status_var.set('视觉配置错误：'+self._vision_config_error)

    def _choose_vision_package(self):
        if self._vision_detector is not None:return
        folder=filedialog.askdirectory(parent=self.root,title='选择G4推理模型包')
        if not folder:return
        self.vision_package_var.set(folder)
        # Machine-local path is never part of the shared template or Git.
        import yaml
        local=Path(__file__).resolve().parents[1]/'configs/realtime_vision.local.yaml'
        try:local.write_text(yaml.safe_dump(dict(model_package=folder),allow_unicode=True),encoding='utf-8')
        except OSError as exc:self.vision_status_var.set(f'模型路径已选择，本地配置未保存：{exc}')

    def start_realtime_detection(self):
        if not self._operator_only or self._experiment_active or self._vision_detector is not None:return False
        if not self.camera_running or self._latest_camera_packet is None:
            self.vision_status_var.set('请先开启相机预览并等待真实画面');return False
        if self._vision_config_error:
            self.vision_status_var.set('视觉配置错误：'+self._vision_config_error);return False
        package=Path(self.vision_package_var.get()).expanduser()
        if not package.is_dir():
            self.vision_status_var.set('模型包不存在，请复制模型包或重新选择');return False
        output=self._vision_output_root/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
        try:
            device=self._vision_settings['device'];batch=self._vision_settings['batch_size']
            factory=lambda:G4UNetPredictor(package,device=device,batch_size=batch)
            if self.vision_mode_var.get()=='双层优先':
                if self._vision_settings.get('native_single',False):
                    from dmf.vision.native_inference import NativeTileG4Predictor
                    factory=lambda:NativeTileG4Predictor(package,device=device,batch_size=1)
                regions=self._current_observation_regions()
                self._vision_last_regions=regions;self._vision_region_results.clear()
                self._vision_region_rates.clear();self._vision_region_previous.clear()
                self._vision_detector=PriorityVisionDetector(factory,output,regions,self._vision_roi,
                    task_period_s=self._vision_settings.get('task_period_s',.1),
                    max_task_age_s=self._vision_settings.get('max_task_age_s',.25),
                    max_inspection_age_s=self._vision_settings.get('max_inspection_age_s',1.),
                    inspection_period_s=self._vision_settings.get('inspection_period_s',1.),clock_policy='live')
                self._update_vision_region_choices()
            else:self._vision_detector=WholeChipDetector(factory,output,self._vision_roi)
        except Exception as exc:
            self.vision_status_var.set(f'检测未启动：{exc}');return False
        self._vision_selecting=False;self._vision_select_start=None
        self._vision_accepting=True;self._vision_latest_result=None
        self._vision_previous_end=None;self._vision_fps=0.
        if hasattr(self,'vision_mode_combo'):self.vision_mode_combo.config(state='disabled')
        self.btn_detect_start.config(state='disabled');self.btn_detect_stop.config(state='normal')
        self.vision_status_var.set('正在后台加载模型 · 仅检测，不控制电极')
        self._vision_detector.submit(self._latest_camera_packet)
        self._poll_realtime_vision();return True

    def _submit_realtime_packet(self,packet):
        # Called from camera worker; no Tk access or serial/control references.
        detector=self._vision_detector
        if detector is not None and self._vision_accepting:detector.submit(packet)

    def _poll_realtime_vision(self):
        if self._vision_poll_id is not None:
            self.root.after_cancel(self._vision_poll_id);self._vision_poll_id=None
        detector=self._vision_detector
        if detector is not None:
            self._refresh_dual_regions()
            for _ in range(PriorityVisionDetector.MAX_REGIONS+1):
                result=detector.poll_result()
                if result is None:break
                if self._vision_accepting and hasattr(result,'region_id'):
                    self._accept_region_result(result)
                    if self.vision_view_var.get()!='原图':self._vision_view_changed()
                    continue
                if not self._vision_accepting:continue
                if result.error:
                    self._vision_latest_result=None;self.btn_vision_save.config(state='disabled')
                    self.vision_status_var.set('本帧检测失败：'+result.error)
                else:
                    if self._vision_previous_end is not None:
                        self._vision_fps=1e9/max(1,result.completed_perf_ns-self._vision_previous_end)
                    else:self._vision_fps=1000/max(.001,result.processing_ms)
                    self._vision_previous_end=result.completed_perf_ns
                    self._vision_latest_result=result;self.btn_vision_save.config(state='normal')
                    if self.vision_view_var.get()!='原图':self._vision_view_changed()
            result=self._vision_latest_result
            if result is not None and self._vision_accepting:
                if hasattr(result,'region_id'):self.vision_status_var.set(self._dual_status(result,detector))
                else:
                    age=(time.perf_counter_ns()-result.submitted_perf_ns)/1e9
                    self.vision_status_var.set(f'{result.backend} · 接收 {detector.receive_fps:.1f}fps · 整帧检测 {self._vision_fps:.2f}fps · '
                    f'{result.processing_ms:.0f}ms · 输入年龄 {age:.1f}s · 源帧 {result.packet.capture_identity} · '
                    f'{len(result.components)}个候选 · 未配准'+
                    (f' · 诊断 {result.quality_diagnostic}' if result.quality_diagnostic else ''))
            if detector.error:
                self._vision_latest_result=None;self.btn_vision_save.config(state='disabled')
                self.vision_status_var.set('检测失败：'+detector.error)
            if not detector.worker.is_alive():
                self._vision_detector=None;self._vision_accepting=False
                self.btn_detect_start.config(state='normal');self.btn_detect_stop.config(state='disabled')
                if hasattr(self,'vision_mode_combo'):self.vision_mode_combo.config(state='readonly')
                if detector.log.error:self.vision_status_var.set('检测日志异常：'+detector.log.error)
        writer=self._vision_snapshot_worker
        if writer is not None and not writer.is_alive():
            self._vision_snapshot_worker=None
            self.log('检测结果保存失败：'+self._vision_snapshot_error if self._vision_snapshot_error else
                     f'检测结果已保存：{self._vision_snapshot_path}')
        if self._vision_detector is not None or self._vision_snapshot_worker is not None:
            self._vision_poll_id=self.root.after(50,self._poll_realtime_vision)

    def stop_realtime_detection(self):
        self._vision_selecting=False;self._vision_select_start=None
        self._vision_accepting=False;self._vision_latest_result=None;self.vision_view_var.set('原图')
        self._vision_region_results.clear()
        self._vision_region_previous.clear();self._vision_region_rates.clear();self._vision_last_regions=None
        if self._vision_detector is not None:self._vision_detector.stop()
        if hasattr(self,'btn_vision_save'):
            self.btn_vision_save.config(state='disabled');self.vision_status_var.set('检测停止 · 相机与开环任务独立运行')
        if hasattr(self,'vision_mode_combo'):self.vision_mode_combo.config(state='readonly')

    def _stop_realtime_for_close(self):
        self.stop_realtime_detection()
        detector=self._vision_detector;writer=self._vision_snapshot_worker
        waiting=bool((detector is not None and detector.worker.is_alive()) or (writer is not None and writer.is_alive()))
        if not waiting and self._vision_poll_id is not None:
            self.root.after_cancel(self._vision_poll_id);self._vision_poll_id=None
        return waiting

    @staticmethod
    def _vision_render_bgr(result,mode):
        if mode=='Mask':return cv2.cvtColor(result.mask,cv2.COLOR_GRAY2BGR)
        image=result.packet.image_bgr.copy()
        contours,_=cv2.findContours(result.mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        offset=result.roi[:2] if result.mask.shape!=result.packet.image_bgr.shape[:2] else (0,0)
        cv2.drawContours(image,contours,-1,(30,210,30),2,offset=offset)
        for part in result.components:
            x,y=(round(v) for v in part['centroid_px'])
            cv2.drawMarker(image,(x,y),(0,170,255),cv2.MARKER_CROSS,10,1)
        x,y,w,h=result.roi;cv2.rectangle(image,(x,y),(x+w-1,y+h-1),(255,150,0),2)
        return image

    def _vision_view_changed(self):
        if self.vision_view_var.get()=='原图':
            image=self.latest_camera_frame_bgr
            if image is not None:self._show_camera_frame(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
            return
        result=self._vision_latest_result
        if result is not None and result.mask is not None:
            self._vision_display_frame_id=result.packet.frame_id
            self._show_camera_frame(cv2.cvtColor(self._vision_render_bgr(result,self.vision_view_var.get()),cv2.COLOR_BGR2RGB))

    def _select_vision_roi(self):
        if self._vision_detector is not None:
            self.vision_status_var.set('请先停止检测再修改整芯片范围');return
        if self.latest_camera_frame_bgr is None:
            self.vision_status_var.set('请先开启相机预览');return
        self.vision_view_var.set('原图');self._vision_view_changed();self._vision_selecting=True
        self._vision_selection_role='inspection'
        self.vision_status_var.set('在图像上拖选包含核心及外围电极的完整芯片范围')

    def _reset_vision_roi(self):
        if self._vision_detector is not None:
            self.vision_status_var.set('请先停止检测再修改范围');return
        self._vision_roi=None;self._vision_selecting=False
        self.vision_status_var.set('完整原图检测范围 · 未配准')

    def _camera_native_point(self,event):
        geometry=getattr(self,'_camera_display_geometry',None)
        if geometry is None:return None
        width,height,shown_w,shown_h=geometry
        x0=(self.camera_label.winfo_width()-shown_w)/2; y0=(self.camera_label.winfo_height()-shown_h)/2
        if not (x0<=event.x<x0+shown_w and y0<=event.y<y0+shown_h):return None
        return min(width-1,int((event.x-x0)*width/shown_w)),min(height-1,int((event.y-y0)*height/shown_h))

    def _vision_roi_press(self,event):
        if self._vision_detector is not None:return
        if self._vision_selecting:self._vision_select_start=self._camera_native_point(event)

    def _vision_roi_release(self,event):
        if self._vision_detector is not None:return
        if not self._vision_selecting or self._vision_select_start is None:return
        end=self._camera_native_point(event)
        if end is None:return
        start=self._vision_select_start
        x,y=min(start[0],end[0]),min(start[1],end[1])
        roi=(x,y,abs(start[0]-end[0])+1,abs(start[1]-end[1])+1)
        if self._vision_selection_role=='watch':
            if len(self._vision_pixel_regions)>=PriorityVisionDetector.MAX_REGIONS:
                self._vision_selecting=False;self._vision_select_start=None
                self.vision_status_var.set('最多8个观察区，请先清空或加载新配置');return
            self._vision_watch_number+=1
            name=f'watch{self._vision_watch_number}'
            while any(r.region_id==name for r in self._vision_pixel_regions):
                self._vision_watch_number+=1;name=f'watch{self._vision_watch_number}'
            self._vision_pixel_regions.append(TaskRegion(name,roi));self.vision_region_var.set(name)
            self._update_vision_region_choices()
            message=f'观察区 {name} {roi} · 未配准，只检测记录'
        else:
            self._vision_roi=roi;message=f'整芯片范围 {roi} · 请确认包含全部电极 · 未配准'
        self._vision_selecting=False;self._vision_select_start=None
        self.vision_status_var.set(message)
        raw=self.latest_camera_frame_bgr.copy()
        x,y,w,h=roi;cv2.rectangle(raw,(x,y),(x+w-1,y+h-1),(255,150,0),3)
        self._show_camera_frame(cv2.cvtColor(raw,cv2.COLOR_BGR2RGB))

    def save_vision_result(self):
        result=self._vision_latest_result;detector=self._vision_detector
        if result is None or result.mask is None or detector is None or self._vision_snapshot_worker is not None:return False
        folder=detector.output/'snapshots'/str(time.time_ns())
        self._vision_snapshot_error='';self._vision_snapshot_path=folder
        def save():
            try:
                folder.mkdir(parents=True,exist_ok=False)
                for name,image in [('source.png',result.packet.image_bgr),('mask.png',result.mask),
                                   ('overlay.png',self._vision_render_bgr(result,'叠加'))]:
                    if not write_image(folder/name,image):raise OSError('PNG write failed: '+name)
                metadata=dict(frame_id=result.packet.frame_id,capture_identity=result.packet.capture_identity,
                    source_timestamp_s=result.packet.timestamp_s,timestamp_source=result.packet.timestamp_source,
                    timing=asdict(result.packet.timing) if result.packet.timing else None,roi=result.roi,
                    processing_ms=result.processing_ms,components=result.components,backend=result.backend,
                    source_frame_only=True,calibration_bound=False,control_output=False)
                if hasattr(result,'region_id'):
                    metadata.update(region_id=result.region_id,epoch=result.epoch,kind=result.kind,
                        data_valid=result.data_valid,identity_verified=False,control_eligible=False,
                        mask_coordinate_frame='roi_local',mask_offset_xy=result.roi[:2],
                        binding_sha256=result.binding_sha256,source_electrode=result.source_electrode,
                        target_electrode=result.target_electrode)
                (folder/'snapshot.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
            except Exception as exc:self._vision_snapshot_error=str(exc)
        self._vision_snapshot_worker=threading.Thread(target=save,name='vision-snapshot-writer',daemon=True)
        self._vision_snapshot_worker.start();self._poll_realtime_vision();return True
