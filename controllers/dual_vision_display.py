"""Observation-only multi-region UI; automatic task context is strictly read-only."""
import json
import time
import tkinter as tk
from tkinter import filedialog,ttk

from dmf.vision.priority_vision import PriorityVisionDetector
from dmf.vision.task_regions import TaskRegion
from .vision_task_context import load_observation_setup,regions_from_open_loop


class DualVisionDisplayMixin:
    def _init_dual_vision(self):
        self.vision_mode_var=tk.StringVar(value='双层优先')
        self.vision_region_var=tk.StringVar(value='自动')
        self._vision_pixel_regions=[];self._vision_binding=None;self._vision_follow_open_loop=False
        self._vision_margin_px=64;self._vision_selection_role='inspection';self._vision_watch_number=0
        self._vision_region_results={};self._vision_region_rates={};self._vision_region_previous={}
        self._vision_last_regions=None;self._vision_context_signature=None;self._vision_context_epoch=0
        self._vision_binding_error=''

    def _build_dual_vision_controls(self,parent):
        row=tk.Frame(parent,bg=self.colors['panel']);row.pack(fill='x',padx=8,pady=2)
        self.vision_mode_combo=ttk.Combobox(row,textvariable=self.vision_mode_var,
            values=('双层优先','完整同帧'),state='readonly',width=9)
        self.vision_mode_combo.pack(side='left')
        for title,command in [('添加观察区',self._select_vision_watch),('清空观察区',self._clear_vision_watches),
                              ('区域配置',self._load_vision_setup)]:
            tk.Button(row,text=title,command=command).pack(side='left',padx=2)
        self.vision_region_combo=ttk.Combobox(row,textvariable=self.vision_region_var,
            values=('自动','巡检'),state='readonly',width=10)
        self.vision_region_combo.pack(side='left',padx=2)
        self.vision_region_combo.bind('<<ComboboxSelected>>',lambda _:self._vision_select_result())

    def _select_vision_watch(self):
        self._select_vision_roi()
        if self._vision_selecting:
            self._vision_selection_role='watch'
            self.vision_status_var.set('拖选液滴完整迁移范围 · 像素观察区 · 未配准，不判定到达')

    def _clear_vision_watches(self):
        if self._vision_detector is not None:
            self.vision_status_var.set('请先停止检测再修改观察区');return
        self._vision_pixel_regions=[];self.vision_region_var.set('自动');self._update_vision_region_choices()
        self.vision_status_var.set('像素观察区已清空 · 可继续整芯片巡检')

    def _load_vision_setup(self):
        if self._vision_detector is not None:
            self.vision_status_var.set('请先停止检测再加载区域配置');return
        packet=self._latest_camera_packet
        if packet is None:self.vision_status_var.set('请先开启预览，按当前采集域校验区域配置');return
        path=filedialog.askopenfilename(parent=self.root,title='加载检测区域配置',filetypes=[('JSON','*.json')])
        if not path:return
        try:setup=load_observation_setup(path,packet)
        except Exception as exc:self.vision_status_var.set('区域配置拒绝：'+str(exc));return
        self._vision_pixel_regions=list(setup['regions']);self._vision_binding=setup['binding']
        self._vision_follow_open_loop=setup['follow_open_loop'];self._vision_margin_px=setup['margin_px']
        self._vision_context_signature=None;self._vision_binding_error='';self._update_vision_region_choices()
        self.vision_status_var.set('区域配置已载入 · '+('合格配准仅用于观察区域' if self._vision_binding else '像素观察区未配准'))

    def _current_observation_regions(self):
        packet=self._latest_camera_packet
        regions=list(self._vision_pixel_regions)
        for region in regions:region.validate_packet(packet)
        self._vision_binding_error=''
        if self._vision_binding is not None and self._vision_follow_open_loop:
            plan=self._open_loop_plan
            sequence=getattr(self,'_timed_mix',None)
            if getattr(sequence,'plan',None) is not plan:sequence=None
            signature=(id(plan),getattr(sequence,'index',None),getattr(sequence,'pending',None) is not None,
                       packet.video_id,packet.image_bgr.shape)
            if signature!=self._vision_context_signature:
                self._vision_context_epoch+=1;self._vision_context_signature=signature
            try:regions.extend(regions_from_open_loop(plan,sequence,self._vision_binding,packet,
                epoch=self._vision_context_epoch,margin_px=self._vision_margin_px))
            except ValueError as exc:self._vision_binding_error='自动电极区域已拒绝：'+str(exc)
        if len(regions)>PriorityVisionDetector.MAX_REGIONS:raise ValueError('活动观察区超过本版8区容量')
        return tuple(regions)

    def _refresh_dual_regions(self):
        detector=self._vision_detector
        if not isinstance(detector,PriorityVisionDetector) or self._latest_camera_packet is None:return
        try:regions=self._current_observation_regions()
        except ValueError as exc:self._vision_binding_error=str(exc);regions=()
        if regions!=self._vision_last_regions:
            previous={r.region_id:r for r in (self._vision_last_regions or ())}
            detector.update_regions(regions);self._vision_last_regions=regions
            allowed={r.region_id for r in regions}|{'__inspection__'}
            current={r.region_id:r for r in regions}
            self._vision_region_results={k:v for k,v in self._vision_region_results.items()
                if k in allowed and k!='__inspection__' and previous.get(k)==current.get(k)}
            self._update_vision_region_choices()
            # A task epoch/binding change invalidates both the selected result and
            # any already rendered overlay until the new region completes.
            self._vision_select_result(render=False)
            if self.vision_view_var.get()!='原图' and self._vision_latest_result is None:
                self.vision_view_var.set('原图')
                if self.latest_camera_frame_bgr is not None:
                    self._show_camera_frame(self.latest_camera_frame_bgr[:,:,::-1].copy())

    def _update_vision_region_choices(self):
        if hasattr(self,'vision_region_combo'):
            ids=[r.region_id for r in (self._vision_last_regions or self._vision_pixel_regions)]
            self.vision_region_combo.config(values=('自动','巡检',*ids))

    def _accept_region_result(self,result):
        previous=self._vision_region_previous.get(result.region_id)
        valid=result.data_valid
        rate=0.
        if valid and previous is not None and previous[0]!=(result.packet.video_id,result.packet.capture_identity):
            rate=1e9/max(1,result.completed_perf_ns-previous[1])
        self._vision_region_rates[result.region_id]=rate
        if valid:self._vision_region_previous[result.region_id]=((result.packet.video_id,result.packet.capture_identity),result.completed_perf_ns)
        self._vision_region_results[result.region_id]=result
        self._vision_select_result(render=False)

    def _vision_select_result(self,render=True):
        choice=self.vision_region_var.get();cache=self._vision_region_results
        if choice=='巡检':result=cache.get('__inspection__')
        elif choice=='自动':result=next((r for key,r in cache.items() if key!='__inspection__'),cache.get('__inspection__'))
        else:result=cache.get(choice)
        packet=self._latest_camera_packet
        if result is not None and packet is not None and (result.packet.video_id!=packet.video_id
                or result.packet.image_bgr.shape!=packet.image_bgr.shape):result=None
        self._vision_latest_result=result
        self.btn_vision_save.config(state='normal' if result is not None and result.mask is not None else 'disabled')
        if render and self.vision_view_var.get()!='原图':self._vision_view_changed()

    def _dual_status(self,result,detector):
        age=result.source_age_ms/1000+(time.perf_counter_ns()-result.completed_perf_ns)/1e9
        limit=detector.max_inspection_age_s if result.kind=='rolling_inspection' else detector.max_task_age_s
        state='数据新鲜' if result.data_valid and age<=limit else '数据无效/过期'
        label='巡检分区' if result.kind=='rolling_inspection' else result.region_id
        rate=self._vision_region_rates.get(result.region_id,0.)
        self._vision_fps=rate
        return (f'{result.backend} · 接收 {detector.receive_fps:.1f}fps · {label} 有效新帧 {rate:.2f}fps · '
            f'{result.processing_ms:.0f}ms · 年龄 {age:.2f}s · 源帧 {result.packet.capture_identity} · {state} · '
            f'{len(result.components)}个候选 · '+('未配准' if result.kind=='pixel_observation' else '身份未核验')+
            (' · 需要重新定位' if result.needs_relocalization else '')+
            (' · '+result.error if result.error else '')+
            (' · '+self._vision_binding_error if self._vision_binding_error else ''))
