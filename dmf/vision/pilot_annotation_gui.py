"""Standalone offline annotation UI; has no camera or electrode ownership."""
from __future__ import annotations

import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

from .contracts import DropletState
from .pilot_annotation import PilotWorkspace, _image, draft_mask, translated_map


class ImageCanvas(ttk.Frame):
    def __init__(self, parent, clicked):
        super().__init__(parent)
        self.clicked=clicked;self.image=None;self.scale=1.;self.draw_overlay=None
        self.zoom=tk.StringVar(value='Fit')
        bar=ttk.Frame(self);bar.grid(row=0,column=0,columnspan=2,sticky='ew')
        ttk.Label(bar,text='缩放').pack(side='left')
        control=ttk.Combobox(bar,textvariable=self.zoom,values=('Fit','100%','200%','400%'),width=8,state='readonly')
        control.pack(side='left',padx=6);control.bind('<<ComboboxSelected>>',lambda event:self.redraw())
        self.canvas=tk.Canvas(self,bg='#eef1f3',highlightthickness=0)
        self.canvas.grid(row=1,column=0,sticky='nsew')
        horizontal=ttk.Scrollbar(self,orient='horizontal',command=lambda *args:self._scroll('x',*args))
        vertical=ttk.Scrollbar(self,orient='vertical',command=lambda *args:self._scroll('y',*args))
        horizontal.grid(row=2,column=0,sticky='ew');vertical.grid(row=1,column=1,sticky='ns')
        self.canvas.config(xscrollcommand=horizontal.set,yscrollcommand=vertical.set)
        self.rowconfigure(1,weight=1);self.columnconfigure(0,weight=1)
        self.canvas.bind('<Button-1>',lambda event:self._click(event,False))
        self.canvas.bind('<B1-Motion>',lambda event:self._click(event,True))
        self.canvas.bind('<Configure>',lambda event:self.redraw())
        self.canvas.bind('<MouseWheel>',lambda event:self._scroll('y','scroll',-int(event.delta/120)*3,'units'))

    def _scroll(self,axis,*args):
        (self.canvas.xview if axis=='x' else self.canvas.yview)(*args)
        self.redraw()

    def _click(self,event,drag):
        if self.image is not None:
            x=self.canvas.canvasx(event.x)/self.scale;y=self.canvas.canvasy(event.y)/self.scale
            if 0<=x<self.image.shape[1] and 0<=y<self.image.shape[0]:self.clicked(x,y,drag)

    def show(self,image,overlay=None):
        self.image=image;self.draw_overlay=overlay;self.redraw()

    def redraw(self):
        if self.image is None:return
        h,w=self.image.shape[:2]
        self.scale=(min(max(1,self.canvas.winfo_width())/w,max(1,self.canvas.winfo_height())/h)
            if self.zoom.get()=='Fit' else float(self.zoom.get().rstrip('%'))/100)
        size=(max(1,round(w*self.scale)),max(1,round(h*self.scale)))
        self.canvas.config(scrollregion=(0,0,*size))
        # Only rasterize the visible viewport, even at 400% on a 20 MP image.
        x0=max(0,min(w-1,int(self.canvas.canvasx(0)/self.scale)))
        y0=max(0,min(h-1,int(self.canvas.canvasy(0)/self.scale)))
        x1=min(w,x0+max(1,int(np.ceil(self.canvas.winfo_width()/self.scale))+2))
        y1=min(h,y0+max(1,int(np.ceil(self.canvas.winfo_height()/self.scale))+2))
        size=(max(1,round((x1-x0)*self.scale)),max(1,round((y1-y0)*self.scale)))
        interpolation=cv2.INTER_AREA if self.scale<1 else cv2.INTER_NEAREST
        preview=cv2.resize(self.image[y0:y1,x0:x1],size,interpolation=interpolation)
        self.photo=ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(preview,cv2.COLOR_BGR2RGB)),master=self.canvas)
        self.canvas.delete('all');self.canvas.create_image(x0*self.scale,y0*self.scale,image=self.photo,anchor='nw')
        if self.draw_overlay:self.draw_overlay(self.canvas,self.scale)


class PilotAnnotationApp:
    def __init__(self, root, workspace):
        self.root=root;self.workspace=workspace;self.index=None;self.dirty=False;self.last_brush=None
        self.loaded_parent=None;self.calibration_dirty=False
        width=min(1320,root.winfo_screenwidth()-80);height=min(900,root.winfo_screenheight()-100)
        root.title('第二章离线标注');root.geometry(f'{width}x{height}');root.minsize(min(1040,width),min(700,height))
        root.option_add('*Font',('Microsoft YaHei UI',10))
        book=ttk.Notebook(root);book.pack(fill='both',expand=True,padx=8,pady=8)
        calibration=ttk.Frame(book);annotation=ttk.Frame(book)
        book.add(calibration,text='电极地图');book.add(annotation,text='Mask与状态')
        self.status=tk.StringVar();ttk.Label(root,textvariable=self.status).pack(fill='x',padx=12,pady=(0,8))
        self._build_calibration(calibration);self._build_annotation(annotation)
        self._load_reference();self.refresh_table();self._load_frame(0)
        root.protocol('WM_DELETE_WINDOW',self.close)

    def _build_calibration(self,parent):
        bar=ttk.Frame(parent);bar.pack(fill='x',padx=8,pady=6)
        self.parent_video=tk.StringVar(value=next(iter(self.workspace.data['references'])))
        choice=ttk.Combobox(bar,textvariable=self.parent_video,values=list(self.workspace.data['references']),width=36,state='readonly')
        choice.pack(side='left');choice.bind('<<ComboboxSelected>>',self._select_reference)
        ttk.Label(bar,text='中心间距 / mm').pack(side='left',padx=(12,4))
        self.pitch=tk.StringVar(value='3.2');pitch_entry=ttk.Entry(bar,textvariable=self.pitch,width=7)
        pitch_entry.pack(side='left');pitch_entry.bind('<KeyRelease>',self._calibration_edited)
        ttk.Button(bar,text='撤销点',command=self._undo_corner).pack(side='left',padx=8)
        ttk.Button(bar,text='清空点',command=self._clear_corners).pack(side='left')
        ttk.Button(bar,text='原始录像',command=self._open_original).pack(side='right')
        row=ttk.Frame(parent);row.pack(fill='x',padx=8,pady=(0,6))
        self.map_confirmed=tk.BooleanVar(value=False)
        ttk.Checkbutton(row,text='已核对编号方向、间距及网格',variable=self.map_confirmed,
            command=lambda:setattr(self,'calibration_dirty',True)).pack(side='left')
        self.corner_status=tk.StringVar();ttk.Label(row,textvariable=self.corner_status).pack(side='left',padx=16)
        ttk.Button(row,text='保存地图',command=self.save_calibration).pack(side='right')
        self.calibration_canvas=ImageCanvas(parent,self._corner_click);self.calibration_canvas.pack(fill='both',expand=True)

    def _load_reference(self):
        self.loaded_parent=self.parent_video.get()
        reference=self.workspace.data['references'][self.parent_video.get()]
        self.reference_image=_image(self.workspace.root/reference['image'])
        config=self.workspace.map_config(self.parent_video.get())
        self.corners=[tuple(point) for point in config['core_corners_px']] if config else []
        self.pitch.set(str(config['pitch_mm']) if config else str(self.workspace.data.get('physical_layout',{}).get('pitch_mm',3.2)))
        self.map_confirmed.set(bool(config and config.get('calibration_confirmed')))
        self.calibration_dirty=False
        self._draw_calibration()

    def _select_reference(self,event=None):
        requested=self.parent_video.get();self.parent_video.set(self.loaded_parent)
        if not self._allow_calibration_leave():return
        self.parent_video.set(requested);self._load_reference()

    def _allow_calibration_leave(self):
        if not self.calibration_dirty:return True
        choice=messagebox.askyesnocancel('未保存地图','保存当前视频的地图修改？',parent=self.root)
        return False if choice is None else self.save_calibration() if choice else True

    def _calibration_edited(self,event=None):
        self.calibration_dirty=True;self.map_confirmed.set(False);self._draw_calibration()

    def _corner_click(self,x,y,drag):
        if drag or len(self.corners)>=4:return
        self.corners.append((x,y));self._calibration_edited()

    def _undo_corner(self):
        if self.corners:self.corners.pop()
        self._calibration_edited()

    def _clear_corners(self):
        self.corners=[];self._calibration_edited()

    def _draw_calibration(self):
        labels=('ID1 外角','ID20 外角','ID400 外角','ID381 外角')
        self.corner_status.set(f'下一点：{labels[len(self.corners)]}' if len(self.corners)<4 else '四角齐全')
        def overlay(canvas,scale):
            if len(self.corners)==4:
                try:
                    electrode_map=translated_map(dict(core_corners_px=self.corners,pitch_mm=float(self.pitch.get())),0,0)
                    self._draw_map(canvas,scale,electrode_map,labels=False)
                except ValueError:pass
            for number,(x,y) in enumerate(self.corners):
                x*=scale;y*=scale
                canvas.create_oval(x-4,y-4,x+4,y+4,fill='#bb3f53',outline='white')
                canvas.create_text(x+8,y+8,text=labels[number],fill='#9b2539',anchor='nw')
        self.calibration_canvas.show(self.reference_image,overlay)

    @staticmethod
    def _draw_map(canvas,scale,electrode_map,labels=True):
        left,top=canvas.canvasx(0),canvas.canvasy(0)
        right,bottom=left+canvas.winfo_width(),top+canvas.winfo_height()
        for region in electrode_map:
            if region.electrode_id>400:continue
            points=[coordinate*scale for point in region.polygon_px for coordinate in point]
            if max(points[::2])<left or min(points[::2])>right or max(points[1::2])<top or min(points[1::2])>bottom:continue
            canvas.create_polygon(*points,fill='',outline='#57947c',width=1)
            x,y=region.center_px
            if labels or region.electrode_id in (1,20,381,400):
                canvas.create_text(x*scale,y*scale,text=str(region.electrode_id),fill='#304a40',font=('Arial',9))

    def save_calibration(self):
        try:
            path=self.workspace.save_calibration(self.loaded_parent,self.corners,float(self.pitch.get()),
                confirmed=self.map_confirmed.get())
        except (ValueError,OSError) as exc:messagebox.showerror('地图未保存',str(exc),parent=self.root);return False
        self.calibration_dirty=False
        self.refresh_table()
        if self.index is not None:
            self.state_reviewed.set(False);self._draw_annotation()
        self.status.set(f'地图已保存：{path.name}');return True

    def _build_annotation(self,parent):
        left=ttk.Frame(parent);left.pack(side='left',fill='y',padx=(0,8))
        self.table=ttk.Treeview(left,columns=('frame','mask','state'),show='tree headings',selectmode='browse',height=28)
        self.table.heading('#0',text='片段');self.table.column('#0',width=155,stretch=False)
        for key,label in (('frame','帧'),('mask','Mask'),('state','状态')):
            self.table.heading(key,text=label);self.table.column(key,width=65,stretch=False)
        scrollbar=ttk.Scrollbar(left,orient='vertical',command=self.table.yview)
        self.table.config(yscrollcommand=scrollbar.set);self.table.pack(side='left',fill='y');scrollbar.pack(side='left',fill='y')
        self.table.bind('<<TreeviewSelect>>',self._selected)
        right=ttk.Frame(parent);right.pack(side='left',fill='both',expand=True)
        self.frame_title=tk.StringVar();ttk.Label(right,textvariable=self.frame_title).pack(fill='x',pady=(4,0))
        toolbar=ttk.Frame(right);toolbar.pack(fill='x',pady=4)
        self.tool=tk.StringVar(value='补液滴')
        for value in ('补液滴','擦除','源电极','目标电极'):
            ttk.Radiobutton(toolbar,text=value,value=value,variable=self.tool).pack(side='left',padx=3)
        self.radius=tk.IntVar(value=5)
        ttk.Label(toolbar,text='笔刷').pack(side='left',padx=(10,2))
        ttk.Spinbox(toolbar,from_=1,to=50,textvariable=self.radius,width=4).pack(side='left')
        controls=ttk.Frame(right);controls.pack(fill='x',pady=4)
        self.source=tk.StringVar();self.target=tk.StringVar();self.state=tk.StringVar(value='Unknown')
        for label,variable in (('源ID',self.source),('目标ID',self.target)):
            ttk.Label(controls,text=label).pack(side='left',padx=(0,4))
            entry=ttk.Entry(controls,textvariable=variable,width=5);entry.pack(side='left',padx=(0,10))
            entry.bind('<KeyRelease>',self._label_edited)
        state=ttk.Combobox(controls,textvariable=self.state,values=[s.value for s in DropletState],state='readonly',width=11)
        state.pack(side='left');state.bind('<<ComboboxSelected>>',self._label_edited)
        self.mask_reviewed=tk.BooleanVar(value=False);self.state_reviewed=tk.BooleanVar(value=False)
        ttk.Checkbutton(controls,text='Mask已核对',variable=self.mask_reviewed,
            command=lambda:setattr(self,'dirty',True)).pack(side='left',padx=8)
        ttk.Checkbutton(controls,text='状态已核对',variable=self.state_reviewed,
            command=lambda:setattr(self,'dirty',True)).pack(side='left')
        row=ttk.Frame(right);row.pack(fill='x',pady=4)
        self.threshold=tk.IntVar(value=55)
        ttk.Label(row,text='草稿阈值').pack(side='left');ttk.Spinbox(row,from_=0,to=255,textvariable=self.threshold,width=5).pack(side='left')
        ttk.Button(row,text='重建草稿',command=self._draft).pack(side='left',padx=6)
        ttk.Button(row,text='清空Mask',command=self._clear_mask).pack(side='left')
        ttk.Button(row,text='查看短片',command=self._open_clip).pack(side='left',padx=8)
        ttk.Button(row,text='保存标注',command=self.save_frame).pack(side='right')
        row=ttk.Frame(right);row.pack(fill='x',pady=4)
        ttk.Label(row,text='补充短片帧号').pack(side='left')
        self.extra_frame=tk.StringVar(value='0');ttk.Entry(row,textvariable=self.extra_frame,width=6).pack(side='left',padx=6)
        ttk.Button(row,text='添加帧',command=self._add_frame).pack(side='left')
        ttk.Label(row,text='备注').pack(side='left',padx=(12,4));self.notes=tk.StringVar()
        entry=ttk.Entry(row,textvariable=self.notes);entry.pack(side='left',fill='x',expand=True)
        entry.bind('<KeyRelease>',lambda event:setattr(self,'dirty',True))
        self.annotation_canvas=ImageCanvas(right,self._annotation_click);self.annotation_canvas.pack(fill='both',expand=True)
        self.annotation_canvas.canvas.bind('<ButtonRelease-1>',lambda event:setattr(self,'last_brush',None))

    def refresh_table(self):
        self.table.delete(*self.table.get_children())
        for index,row in enumerate(self.workspace.rows):
            effective=self.workspace._effective(row)
            self.table.insert('', 'end',iid=str(index),text=row['video_id'][-18:],
                values=(row['frame_id'],'已核对' if row['mask_reviewed'] else '草稿',effective['state_gt']))
        if self.index is not None:
            self.table.selection_set(str(self.index));self.table.see(str(self.index))
        report=self.workspace.report()
        self.status.set(f'Mask {report["mask_reviewed_frames"]}/{report["frames"]}；状态 {report["state_reviewed_frames"]}；地图 {report["confirmed_maps"]}/{report["reference_videos"]}')

    def _selected(self,event=None):
        selection=self.table.selection()
        if selection:self._load_frame(int(selection[0]))

    def _allow_leave(self):
        if not self.dirty:return True
        choice=messagebox.askyesnocancel('未保存标注','保存当前帧的修改？',parent=self.root)
        return False if choice is None else self.save_frame() if choice else True

    def _load_frame(self,index):
        if index==self.index:return
        if not self._allow_leave():return
        self.index=index;self.image,self.mask=self.workspace.images(index);row=self.workspace.rows[index]
        self.frame_title.set(f'{row["video_id"][-18:]} | 帧 {row["frame_id"]} | 原视频帧 {row["source_frame_id"]}')
        self.table.selection_set(str(index));self.table.see(str(index))
        self.source.set(str(row['source_electrode']));self.target.set(str(row['target_electrode']))
        self.state.set(row['state_draft']);self.notes.set(row['notes'])
        self.mask_reviewed.set(row['mask_reviewed']);self.state_reviewed.set(self.workspace._effective(row)['state_reviewed'])
        self.dirty=False;self.last_brush=None;self.extra_frame.set(str(row['frame_id']))
        self._draw_annotation()

    def _draw_annotation(self):
        if self.index is None:return
        preview=self.image.copy();selected=self.mask>0
        preview[selected]=(.6*self.image[selected]+.4*np.array([75,170,230])).astype(np.uint8)
        electrode_map=self.workspace.crop_map(self.index)
        def overlay(canvas,scale):
            if electrode_map is None:return
            self._draw_map(canvas,scale,electrode_map)
            for variable,color in ((self.source,'#3673a2'),(self.target,'#bc7640')):
                if variable.get().isdigit() and 1<=int(variable.get())<=420:
                    region=electrode_map[int(variable.get())]
                    canvas.create_polygon(*[v*scale for p in region.polygon_px for v in p],fill='',outline=color,width=3)
        self.annotation_canvas.show(preview,overlay)

    def _label_edited(self,event=None):
        self.state_reviewed.set(False);self.dirty=True;self._draw_annotation()

    def _annotation_click(self,x,y,drag):
        mode=self.tool.get()
        if mode in ('源电极','目标电极'):
            if drag:return
            electrode_map=self.workspace.crop_map(self.index)
            if electrode_map is None:messagebox.showwarning('尚无地图','请先保存该原视频的电极地图',parent=self.root);return
            for region in electrode_map:
                if region.electrode_id<=400 and cv2.pointPolygonTest(np.array(region.polygon_px,np.float32),(x,y),False)>=0:
                    (self.source if mode=='源电极' else self.target).set(str(region.electrode_id))
                    self._label_edited();return
            return
        point=(round(x),round(y));radius=max(1,min(50,int(self.radius.get())))
        value=255 if mode=='补液滴' else 0
        if drag and self.last_brush is not None:cv2.line(self.mask,self.last_brush,point,value,radius*2)
        else:cv2.circle(self.mask,point,radius,value,-1)
        self.last_brush=point;self.dirty=True;self.mask_reviewed.set(False);self.state_reviewed.set(False)
        self._draw_annotation()

    def _draft(self):
        self.mask=draft_mask(self.image,self.threshold.get());self._mask_changed()

    def _clear_mask(self):
        self.mask=np.zeros(self.image.shape[:2],np.uint8);self._mask_changed()

    def _mask_changed(self):
        self.mask_reviewed.set(False);self.state_reviewed.set(False);self.dirty=True;self._draw_annotation()

    def save_frame(self):
        try:
            if self.state_reviewed.get() and self.calibration_dirty and \
                    self.workspace.rows[self.index]['parent_video_id']==self.loaded_parent:
                raise ValueError('Save the modified calibration before confirming state GT')
            self.workspace.review(self.index,self.mask,mask_reviewed=self.mask_reviewed.get(),
                state_reviewed=self.state_reviewed.get(),source=self.source.get(),target=self.target.get(),
                state=self.state.get(),notes=self.notes.get())
        except (ValueError,OSError) as exc:messagebox.showerror('标注未保存',str(exc),parent=self.root);return False
        self.dirty=False;self.refresh_table();return True

    def _add_frame(self):
        if not self._allow_leave():return
        try:index=self.workspace.add_frame(self.workspace.rows[self.index]['video_id'],int(self.extra_frame.get()))
        except (ValueError,OSError) as exc:messagebox.showerror('未添加',str(exc),parent=self.root);return
        self.dirty=False;self.refresh_table();self._load_frame(index)

    def _open_original(self):
        os.startfile(self.workspace.data['references'][self.parent_video.get()]['source_video'])

    def _open_clip(self):
        row=self.workspace.rows[self.index]
        preview=Path(self.workspace.data['dataset'])/'preview_mp4'/row['batch_id']/(row['video_id']+'.mp4')
        os.startfile(str(preview if preview.exists() else Path(self.workspace.clips[row['video_id']]['path'])))

    def close(self):
        if self._allow_leave() and self._allow_calibration_leave():self.root.destroy()


def launch(workspace):
    root=tk.Tk();PilotAnnotationApp(root,PilotWorkspace(workspace));root.mainloop()
