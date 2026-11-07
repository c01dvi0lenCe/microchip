"""Real operator pages; no simulated observations or implicit actuation."""
import tkinter as tk
from tkinter import ttk

from dmf.layout import electrode_id, is_core_cell


class OperatorProfileMixin:
    def _build_operator_manual_controls(self, parent):
        card=tk.Frame(parent,bg=self.colors['panel'])
        card.pack(fill='x',pady=(0,4))
        self._build_open_loop_controls(card)
        self.open_loop_controls_frame.config(text='定时开环')
        self.open_loop_input_var=tk.StringVar(value='电极开关')
        row=tk.Frame(self.open_loop_controls_frame,bg=self.colors['panel'])
        row.pack(fill='x',padx=3,pady=3)
        tk.Label(row,text='画布用途',bg=self.colors['panel']).pack(side='left')
        ttk.Combobox(row,textvariable=self.open_loop_input_var,state='readonly',
            values=('电极开关','任务选点'),width=10).pack(side='left',padx=4)
        tk.Label(row,text='选点项目',bg=self.colors['panel']).pack(side='left')
        self.operator_pick_combo=ttk.Combobox(row,textvariable=self.open_loop_pick_var,
            state='readonly',values=('起点','终点'),width=7)
        self.operator_pick_combo.pack(side='left',padx=4)
        self.operator_pick_combo.bind('<<ComboboxSelected>>',
            lambda _event:self._operator_select_role(self.open_loop_pick_var.get()))
        tk.Button(row,text='设置起点',command=lambda:self._operator_select_role('起点')).pack(side='left',padx=2)
        tk.Button(row,text='设置终点',command=lambda:self._operator_select_role('终点')).pack(side='left',padx=2)
        tk.Button(row,text='恢复电极开关',command=lambda:self.open_loop_input_var.set('电极开关')).pack(side='left',padx=2)
        # Reuse the existing status line rather than adding another cramped row.
        self.operator_pick_hint_var=self.open_loop_status_var
        self.operator_pick_hint_var.set('选点只编辑任务，不点亮电极；执行前请预检。')

    def _operator_select_role(self, role):
        self.open_loop_pick_var.set(role)
        self.open_loop_input_var.set('任务选点')

    def _build_operator_visual_controls(self, parent):
        frame=tk.LabelFrame(parent,text='真实视觉反馈任务',bg=self.colors['panel'])
        frame.pack(fill='x',pady=(0,5))
        self.visual_status_var=tk.StringVar(value='未就绪：模型适配、本次装夹配准、真实到达核对及无输出联调尚待验收')
        self.auto_status_label=tk.Label(frame,textvariable=self.visual_status_var,
            bg=self.colors['panel'],fg=self.colors['muted'],wraplength=710,justify='left')
        self.auto_status_label.pack(fill='x',padx=8,pady=6)
        self.visual_start_button=tk.Button(frame,text='启动视觉闭环',state='disabled')
        self.visual_start_button.pack(anchor='w',padx=8,pady=(0,6))
        tk.Label(frame,text='相机预览和录像可以独立使用；当前无视觉结果参与电极切换。',
            bg=self.colors['panel'],fg=self.colors['text']).pack(anchor='w',padx=8,pady=(0,5))

    def _operator_pick_cell(self, cell):
        if self._timed_mix_owned or self.auto_running or self._experiment_active:
            self.log('任务运行中，不接受选点修改');return
        if self.open_loop_kind_var.get()=='多组四宫格':
            self.open_loop_handle_cell(cell);return
        if not is_core_cell(cell):
            self.open_loop_status_var.set('移动路径起终点请选择核心1–400电极');return
        role=self.open_loop_pick_var.get()
        if role not in ('起点','终点'):
            self.open_loop_status_var.set('普通移动请选择起点或终点');return
        if role=='起点':self.start_cell=cell
        else:self.goal_cell=cell
        self.path=[];self._open_loop_plan=None;self._open_loop_preview=True
        def label(value):return '未设置' if value is None else str(electrode_id(*value))
        self.operator_pick_hint_var.set(f'起点 {label(self.start_cell)} → 终点 {label(self.goal_cell)}；选点不发电极命令')
        self._draw_matrix_canvas()

    def _draw_operator_command_overlay(self, manual):
        for cell in self._active_cells():self._draw_cell(cell,fill=self.colors['btn_on'],outline='')
        self._draw_hardware_reminders()
        if manual:
            self._draw_manual_electrode_ids()
            if self._open_loop_view_active():self._draw_open_loop_overlay()
            if self.open_loop_kind_var.get()=='规划移动路径':
                for cell,color in ((self.start_cell,self.colors['droplet_a']),
                                   (self.goal_cell,self.colors['target_edge'])):
                    if cell is not None:self._draw_cell(cell,fill='',outline=color,width=3)
        self._draw_open_loop_pending()
        self._draw_hardware_reminders(outline_only=True)
        if self.hover_cell is not None:self._draw_cell(self.hover_cell,fill='',outline='#1F2A33',width=2)
