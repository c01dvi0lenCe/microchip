"""Operator-drawn command routes. Camera preview is independent, never a gate."""
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk

from dmf.layout import cell_from_electrode_id, electrode_id, is_core_cell
from .open_loop_sequence import (FourCellTask, TimedPlanSequence, compile_four_cell_tasks,
                                 compile_routes, four_cell_missing_fields)
from .open_loop_journal import OpenLoopJournal


class OpenLoopControllerMixin:
    def _init_open_loop(self):
        self.open_loop_kind_var=tk.StringVar(value='规划移动路径')
        self.open_loop_pick_var=tk.StringVar(value='起点')
        self.open_loop_advance_var=tk.StringVar(value='定时')
        self.open_loop_dwell_var=tk.DoubleVar(value=1.)
        self.open_loop_cycles_var=tk.IntVar(value=2)
        self.open_loop_status_var=tk.StringVar(value='定时开环：仅按命令与停留推进，不判定液滴到达')
        self.open_loop_groups=[]
        self._open_loop_next_id=1
        self._open_loop_selected=None
        self._open_loop_plan=None
        self._open_loop_preview=False
        self._open_loop_journal=None
        self._open_loop_output_dir=None
        self._open_loop_release_required=False
        self._open_loop_hidden_rows={}
        self.open_loop_output_root=Path(__file__).resolve().parents[1]/'results/hardware_open_loop'

    def _build_open_loop_controls(self,parent):
        frame=tk.LabelFrame(parent,text='路径定时开环（实物／控制预演；不使用视觉判定）',bg=self.colors['panel'])
        self.open_loop_controls_frame=frame
        frame.pack(fill='x',padx=6,pady=(0,4))
        row=tk.Frame(frame,bg=self.colors['panel']);row.pack(fill='x')
        kind=ttk.Combobox(row,textvariable=self.open_loop_kind_var,state='readonly',
            values=('规划移动路径','多组四宫格'),width=13)
        kind.pack(side='left',padx=3);kind.bind('<<ComboboxSelected>>',self.on_open_loop_kind_changed)
        ttk.Combobox(row,textvariable=self.open_loop_advance_var,state='readonly',
            values=('定时','人工单步'),width=9).pack(side='left',padx=3)
        for label,var,low,high in [('停留/s',self.open_loop_dwell_var,.1,60),('圈数',self.open_loop_cycles_var,1,9999)]:
            tk.Label(row,text=label,bg=self.colors['panel']).pack(side='left',padx=(5,2))
            tk.Spinbox(row,textvariable=var,from_=low,to=high,increment=.1 if low==.1 else 1,width=5).pack(side='left')
        actions=tk.Frame(frame,bg=self.colors['panel']);actions.pack(fill='x',pady=2)
        for text,command in [('预检',self.precheck_open_loop),('开始开环',self.start_open_loop),
                ('单步',self.step_open_loop),('暂停/继续',self.pause_resume_open_loop),('停止',self.stop_timed_mixing)]:
            tk.Button(actions,text=text,command=command).pack(side='left',padx=3)
        tk.Label(frame,textvariable=self.open_loop_status_var,anchor='w',bg=self.colors['panel'],
                 fg=self.colors['muted'],wraplength=710).pack(fill='x',padx=3)
        self.open_loop_editor=tk.Frame(frame,bg=self.colors['panel'])
        toolbar=tk.Frame(self.open_loop_editor,bg=self.colors['panel']);toolbar.pack(fill='x')
        for text,command in [('添加组',self.open_loop_add_group),('删除组',self.open_loop_delete_group),
                ('清选四点',self.open_loop_clear_ring),('清空组',self.open_loop_clear_groups)]:
            tk.Button(toolbar,text=text,command=command).pack(side='left',padx=3)
        tk.Label(toolbar,text='画布选点',bg=self.colors['panel']).pack(side='left',padx=(8,2))
        self.open_loop_group_pick_combo=ttk.Combobox(toolbar,textvariable=self.open_loop_pick_var,state='readonly',
            values=('起点','四点','终点'),width=6)
        self.open_loop_group_pick_combo.pack(side='left')
        if self._operator_only:
            self.open_loop_group_pick_combo.bind('<<ComboboxSelected>>',
                lambda _event:self._operator_select_role(self.open_loop_pick_var.get()))
        self.open_loop_tree=ttk.Treeview(self.open_loop_editor,columns=('start','ring','target'),
            show='tree headings',height=2,selectmode='browse')
        for column,label,width in [('#0','组',55),('start','起点',60),('ring','四点顺序',300),('target','终点',60)]:
            self.open_loop_tree.heading(column,text=label);self.open_loop_tree.column(column,width=width,minwidth=45)
        self.open_loop_tree.pack(fill='x',padx=3,pady=2)
        self.open_loop_tree.bind('<<TreeviewSelect>>',self._open_loop_selection_changed)

    def on_open_loop_kind_changed(self,_event=None):
        if self._timed_mix_owned:
            self.open_loop_kind_var.set(getattr(self,'_open_loop_running_kind','规划移动路径'))
            return
        multi=self.open_loop_kind_var.get()=='多组四宫格'
        if multi:self.open_loop_editor.pack(fill='x')
        else:self.open_loop_editor.pack_forget()
        self._open_loop_preview=multi
        self._open_loop_plan=None
        if not self._operator_only:self._open_loop_set_legacy_visible(not multi)
        else:
            self.operator_pick_combo.config(values=('起点','四点','终点') if multi else ('起点','终点'))
            if not multi and self.open_loop_pick_var.get()=='四点':self.open_loop_pick_var.set('起点')
        self._refresh_matrix_legend(manual=False)
        self._draw_matrix_canvas()

    def _open_loop_set_legacy_visible(self,visible):
        # Keep the editor and canvas usable without deleting legacy controls.
        parent=self.open_loop_controls_frame.master
        if not visible:
            for widget in parent.winfo_children():
                if widget is not self.open_loop_controls_frame and widget.winfo_manager()=='pack':
                    self._open_loop_hidden_rows[widget]=widget.pack_info()
                    widget.pack_forget()
        else:
            for widget,info in self._open_loop_hidden_rows.items():widget.pack(**info)
            self._open_loop_hidden_rows.clear()

    def _refresh_open_loop_groups(self):
        tree=self.open_loop_tree
        tree.delete(*tree.get_children())
        for group in self.open_loop_groups:
            tree.insert('', 'end',iid=group['group_id'],text=group['group_id'],values=(
                group['start'] if group['start'] is not None else '—',
                ' → '.join(map(str,group['ring'])) or '待选四点',
                group['target'] if group['target'] is not None else '—'))
        if self._open_loop_selected and tree.exists(self._open_loop_selected):
            tree.selection_set(self._open_loop_selected)
        self._draw_matrix_canvas()

    def _open_loop_selection_changed(self,_event=None):
        if self.open_loop_tree.selection():self._open_loop_selected=self.open_loop_tree.selection()[0]

    def _open_loop_group(self):
        return next((g for g in self.open_loop_groups if g['group_id']==self._open_loop_selected),None)

    def open_loop_add_group(self):
        if self._timed_mix_owned:return None
        gid=f'G{self._open_loop_next_id}';self._open_loop_next_id+=1
        self.open_loop_groups.append(dict(group_id=gid,start=None,ring=[],target=None))
        self._open_loop_selected=gid;self._open_loop_plan=None
        if self._operator_only:self._operator_select_role('起点')
        self._refresh_open_loop_groups();return gid

    def open_loop_delete_group(self):
        if self._timed_mix_owned:return
        self.open_loop_groups[:]=[g for g in self.open_loop_groups if g['group_id']!=self._open_loop_selected]
        self._open_loop_selected=self.open_loop_groups[0]['group_id'] if self.open_loop_groups else None
        self._open_loop_plan=None;self._refresh_open_loop_groups()

    def open_loop_clear_groups(self):
        if self._timed_mix_owned:return
        self.open_loop_groups.clear();self._open_loop_selected=None;self._open_loop_plan=None
        self._refresh_open_loop_groups()

    def open_loop_clear_ring(self):
        if self._timed_mix_owned:return
        group=self._open_loop_group()
        if group is not None:group['ring'].clear()
        self._open_loop_plan=None;self._refresh_open_loop_groups()

    def open_loop_handle_cell(self,cell):
        if self._timed_mix_owned or self.auto_running or self._experiment_active:
            self.log('任务运行中，开环组选点已忽略');return
        if not is_core_cell(cell):
            self.open_loop_status_var.set('四宫格任务请选择核心1–400电极');return
        group=self._open_loop_group()
        if group is None:
            self.open_loop_status_var.set('请先添加并选择一个任务组');return
        eid=electrode_id(*cell,self.cols);role=self.open_loop_pick_var.get()
        if role=='四点':
            if eid in group['ring'] or len(group['ring'])==4:
                self.open_loop_status_var.set('四点须互异；重新选择请先“清选四点”');return
            group['ring'].append(eid)
        else:group['start' if role=='起点' else 'target']=eid
        self._open_loop_plan=None;self._refresh_open_loop_groups()
        self.open_loop_status_var.set(f'{group["group_id"]} 已设置{role}：{eid}；尚未执行')

    def _open_loop_view_active(self):
        return self._open_loop_preview or (self._timed_mix_owned and self._timed_mix_kind=='open_loop')

    def _open_loop_edit_active(self):
        return self.open_loop_kind_var.get()=='多组四宫格'

    def precheck_open_loop(self):
        if self._timed_mix_owned:
            self.open_loop_status_var.set('运行期间不能重新编译任务');return None
        try:
            cycles=self.open_loop_cycles_var.get()
            if self.open_loop_kind_var.get()=='多组四宫格':
                tasks=[FourCellTask(g['group_id'],g['start'],tuple(g['ring']),g['target']) for g in self.open_loop_groups]
                missing=four_cell_missing_fields(tasks)
                if missing:
                    self._open_loop_selected=next(iter(missing))
                    self._refresh_open_loop_groups()
                    self.open_loop_tree.see(self._open_loop_selected)
                    raise ValueError('；'.join(f'{group}未设置'+ '、'.join(fields) for group,fields in missing.items()))
                starts={g['start'] for g in self.open_loop_groups}
                holds=self._active_electrode_ids()-starts
                plan=compile_four_cell_tasks(tasks,cycles,hold_ids=holds)
            else:
                if self.operation_var.get()!=self.OP_MOVE:raise ValueError('规划移动路径入口仅执行“移动”；四宫格请选择多组入口')
                missing=[name for name,cell in (('起点',self.start_cell),('终点',self.goal_cell)) if cell is None]
                if missing:raise ValueError('移动任务未设置'+ '、'.join(missing))
                path=list(self.path)
                if not path or path[0]!=self.start_cell or path[-1]!=self.goal_cell:
                    path=self.planner.plan(self.start_cell,self.goal_cell,self._routing_obstacles(self.start_cell,self.goal_cell))
                if not path:raise ValueError('尚无可执行路径')
                ids=tuple(electrode_id(*cell,self.cols) for cell in path)
                plan=compile_routes({'移动':ids},hold_ids=self._active_electrode_ids()-{ids[0]})
            # Validate dwell now, before creating any journal or controlling outputs.
            TimedPlanSequence(plan,self.open_loop_dwell_var.get())
        except (ValueError,TypeError,tk.TclError) as exc:
            self._open_loop_plan=None;self.open_loop_status_var.set(f'预检拒绝：{exc}')
            self.log(f'开环预检拒绝：{exc}');return None
        self._open_loop_plan=plan;self._open_loop_preview=True
        self.open_loop_status_var.set(f'预检通过：{len(plan.routes)}组／{plan.length-1}同步步；额外保持{sorted(plan.hold_ids)}；不证明实际到达')
        self._draw_matrix_canvas();return plan

    def start_open_loop(self,manual=None):
        if (self._timed_mix_owned or self.auto_running or self._experiment_active
                or self.planning_jobs.is_active or self.hardware_auto_owned or self.hardware_state_uncertain):
            self.open_loop_status_var.set('启动拒绝：已有任务占用或硬件状态不明');return False
        if not self.is_simulation_mode() and not self.is_connected:
            self.open_loop_status_var.set('启动拒绝：串口未连接');return False
        with self.electrode_event_stream.lock:
            if not self.is_simulation_mode() and not self.electrode_event_stream.known:
                self.open_loop_status_var.set('启动拒绝：完整电极状态未知，请重新同步ALL_OFF')
                return False
            if self.electrode_event_stream.pending:
                self.open_loop_status_var.set('启动拒绝：已有在途电极事务');return False
        plan=self.precheck_open_loop()
        if plan is None:return False
        manual=self.open_loop_advance_var.get()=='人工单步' if manual is None else bool(manual)
        seq=TimedPlanSequence(plan,self.open_loop_dwell_var.get(),manual=manual)
        settings=dict(kind=self.open_loop_kind_var.get(),dwell_s=seq.dwell_s,manual=manual,
            cycles=self.open_loop_cycles_var.get(),groups=[dict(g,ring=list(g['ring'])) for g in self.open_loop_groups])
        try:
            self._open_loop_journal=OpenLoopJournal(self.open_loop_output_root,plan,settings,
                simulation=self.is_simulation_mode(),stream=self.electrode_event_stream)
        except OSError as exc:
            self.open_loop_status_var.set(f'日志创建失败，未执行：{exc}');return False
        self._open_loop_output_dir=self._open_loop_journal.output
        self._open_loop_running_kind=self.open_loop_kind_var.get()
        self._timed_mix=seq;self._timed_mix_mode=self.mode_var.get()
        self._timed_mix_kind='open_loop';self._timed_mix_owned=True
        self._init_open_loop_manual(plan)
        self._timed_mix_step_requested=False
        self._timed_mix_release_requested=False;self._timed_mix_disconnect_requested=False
        self.log(f'定时开环启动：{len(plan.routes)}组，共{plan.length-1}同步步；相机仅预览录像，不判定到达')
        self._timed_mix_tick();return True

    def pause_resume_open_loop(self):
        if not self._timed_mix_owned or self._timed_mix_kind!='open_loop':return
        if self._timed_mix.paused:
            self._timed_mix.resume(time.monotonic());text='已继续，重新等待当前停留时间'
        else:
            self._timed_mix.pause();self._timed_mix_step_requested=False;text='已暂停后续步进，保持电极'
        self.open_loop_status_var.set(text)

    def step_open_loop(self):
        if not self._timed_mix_owned:return self.start_open_loop(manual=True)
        if self._timed_mix_kind!='open_loop' or self._timed_mix.pending is not None:return False
        self._timed_mix.pause();self._timed_mix_step_requested=True
        self._timed_mix_tick();return True

    def _open_loop_on_request(self,target):
        phase=self._timed_mix.index
        self._open_loop_journal.step('request',phase,self._open_loop_composed_targets(phase),self._open_loop_plan.positions_at(phase))

    def _open_loop_on_applied(self,target,at):
        phase=self._timed_mix.index-1
        self._open_loop_journal.step('simulated_applied' if self._timed_mix_mode=='仿真' else 'applied_confirmed',
            phase,self._active_electrode_ids(),self._open_loop_plan.positions_at(phase),at)
        self.open_loop_status_var.set(f'命令步 {phase}/{self._open_loop_plan.length-1} 已确认；'+
            '，'.join(f'{g}→{eid}' for g,eid in self._open_loop_plan.positions_at(phase).items())+'；不是视觉到达')
        self._draw_matrix_canvas()

    def _open_loop_on_finish(self):
        if self._open_loop_journal is None:return
        status='state_unknown' if self.hardware_state_uncertain else 'command_sequence_complete' if self._timed_mix.complete else 'stopped'
        journal=self._open_loop_journal
        self._open_loop_journal=None
        try:
            journal.finish(status,self._active_electrode_ids())
        except OSError as exc:
            self.open_loop_status_var.set(f'已停止，日志未完整封存：{exc}')
            self.log(f'开环日志封存失败：{exc}')
            return
        if journal.error:
            self.open_loop_status_var.set(f'已停止，日志不完整：{journal.error}')
            return
        self.open_loop_status_var.set('电极序列执行完毕，未验证液滴到达' if status=='command_sequence_complete' else
            '电极状态未知，请核查并释放' if status=='state_unknown' else '已停止，保持最后确认电极')

    def _release_open_loop_hardware(self):
        if not self._open_loop_release_required:return True
        if not self.is_connected:
            self.hardware_state_uncertain=True
            self.log('开环释放未确认：串口已断开；请独立核查物理输出')
            return False
        if not self.electrode_transactions.all_off():
            self.hardware_state_uncertain=True;self.hardware_auto_owned=True
            self.log('开环释放ALL_OFF未确认，状态未知；持续导通故障仍需独立隔离')
            return False
        self._open_loop_release_required=False
        self.hardware_state_uncertain=False;self.hardware_auto_owned=False
        self._clear_local_electrode_display()
        return True

    def _draw_open_loop_overlay(self):
        plan=self._open_loop_plan
        if plan is not None:
            routes=plan.routes.items()
        else:
            routes=((g['group_id'],tuple(g['ring'])) for g in self.open_loop_groups)
        for i,(group,route) in enumerate(routes):
            color=self.multi_droplet_colors[i%len(self.multi_droplet_colors)]
            unique=list(dict.fromkeys(route))
            cells=[cell_from_electrode_id(eid) for eid in unique]
            for cell in cells:self._draw_cell(cell,fill='',outline=color,width=2)
            # Show a complete representative lap plus the explicit final dock.
            is_ring=self.open_loop_kind_var.get()=='多组四宫格' and len(cells)==4
            if len(cells)>1:self._draw_path_arrow(cells+cells[:1] if is_ring else cells,color)
            if plan is not None:
                end=cell_from_electrode_id(route[-1])
                if is_ring and route[-1]!=route[0]:
                    prefix=cells[:unique.index(route[-1])+1]
                    self._draw_path_arrow(prefix,self.colors['text'])
                self._draw_cell(end,fill='',outline=self.colors['text'],width=3)
                self._draw_cell_text(end,group+'终',fill=self.colors['text'])
            if cells:self._draw_cell_text(cells[0],group,fill=color)
        if self._timed_mix_owned and self._timed_mix_kind=='open_loop' and self._timed_mix.index:
            for group,eid in plan.positions_at(self._timed_mix.index-1).items():
                self._draw_cell_text(cell_from_electrode_id(eid),group,fill=self.colors['text'])
