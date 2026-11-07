"""Dedicated OFFLINE all-droplet/exclusion review; no camera or hardware.

Instance lineage stays in the separate review table. Saving a binary mask does
not approve instances, actual train/val splits, grouping, state or calibration.
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox, ttk
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from dmf.segmentation_research.roi_pilot import all_foreground_draft
from dmf.vision.image_io import read_image, write_image
from dmf.vision.pilot_annotation import PilotWorkspace, sha256
from dmf.vision.pilot_annotation_gui import PilotAnnotationApp


def _binary(mask, shape, label):
    if (not isinstance(mask, np.ndarray) or mask.dtype != np.uint8 or
            mask.shape != shape or not np.isin(mask, [0, 255]).all()):
        raise ValueError(f'{label} must be native same-size uint8 binary 0/255')


def save_review_artifacts(workspace, index, semantic, exclusion, *,
                          mask_reviewed=False, boundary_reviewed=False,
                          exclusion_reviewed=False, notes=''):
    """Validate and save new mask revisions through existing Pilot persistence.

    No GUI interaction or automatic approval occurs here. Source drafts and
    prior revisions are retained. State approval is explicitly invalidated;
    source/target electrode records and all split/instance fields are preserved.
    """
    for label, value in [('mask_reviewed', mask_reviewed),
                         ('boundary_reviewed', boundary_reviewed),
                         ('exclusion_reviewed', exclusion_reviewed)]:
        if type(value) is not bool:
            raise ValueError(f'{label} must be a literal boolean')
    if type(index) is not int or not 0 <= index < len(workspace.rows):
        raise ValueError('Invalid sample index')
    if sha256(workspace.root / 'workspace.json') != workspace.loaded_hash:
        raise OSError('Workspace changed in another window; reopen before saving')
    row = workspace.rows[index]
    image = read_image(workspace.root / row['frame_path'], cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError('Cannot read native ROI image')
    _binary(semantic, image.shape[:2], 'Semantic mask')
    _binary(exclusion, image.shape[:2], 'Exclusion mask')
    old = copy.deepcopy(row)
    name = f'{index:04d}_{uuid.uuid4().hex}.png'
    relative = 'exclusion_revisions/' + name
    if not write_image(workspace.root / relative, exclusion):
        raise OSError('Cannot save exclusion revision')
    try:
        row.update(exclusion_mask_path=relative, boundary_reviewed=boundary_reviewed,
                   exclusion_reviewed=exclusion_reviewed)
        workspace.review(index, semantic, mask_reviewed=mask_reviewed,
            state_reviewed=False, source=old.get('source_electrode', ''),
            target=old.get('target_electrode', ''), state='Unknown', notes=str(notes))
    except Exception:
        row.clear(); row.update(old)
        raise
    return dict(row)


class RoiPilotReviewApp(PilotAnnotationApp):
    """Reuse the existing canvas, brush, tree navigation and dirty prompt."""

    def __init__(self, root, workspace):
        # Custom initialization prevents superclass virtual _draw_annotation from
        # running before both masks exist, and creates no calibration controls.
        self.root = root; self.workspace = workspace; self.index = None
        self.dirty = False; self.last_brush = None
        self.loaded_parent = None; self.calibration_dirty = False
        self.semantic = None; self.exclusion = None; self.mask = None
        self.mode = tk.StringVar(master=root, value='semantic')
        self.boundary_reviewed = tk.BooleanVar(master=root, value=False)
        self.exclusion_reviewed = tk.BooleanVar(master=root, value=False)
        self.status = tk.StringVar(master=root)
        width = min(1420, root.winfo_screenwidth() - 60)
        height = min(940, root.winfo_screenheight() - 80)
        root.title('真实液滴 ROI Pilot · 离线双掩膜审核')
        root.geometry(f'{width}x{height}')
        root.minsize(min(1080, width), min(720, height))
        root.option_add('*Font', ('Microsoft YaHei UI', 10))
        annotation = ttk.LabelFrame(root, text='所有实际液滴 Mask / 储液区排除域（非实例真值）')
        annotation.pack(fill='both', expand=True, padx=8, pady=8)
        super()._build_annotation(annotation)
        self._restrict_old_controls(annotation)
        self.table.heading('state', text='排除域')
        right = self.annotation_canvas.master
        bar = ttk.Frame(right)
        bar.pack(fill='x', before=self.annotation_canvas, pady=4)
        for value, label in [('semantic', '编辑：所有液滴前景（橙色）'),
                             ('exclusion', '编辑：储液区排除域（紫色）')]:
            ttk.Radiobutton(bar, text=label, value=value, variable=self.mode,
                            command=self._mode_changed).pack(side='left', padx=4)
        ttk.Checkbutton(bar, text='前景边界已核对', variable=self.boundary_reviewed,
                        command=self._review_edited).pack(side='left', padx=8)
        ttk.Checkbutton(bar, text='排除域已核对', variable=self.exclusion_reviewed,
                        command=self._review_edited).pack(side='left')
        ttk.Label(right, text='反光属于液滴；暗纹/污点不属于液滴。实例谱系另表审核；保存不会放行训练。',
                  foreground='#6c405c').pack(fill='x', before=self.annotation_canvas)
        ttk.Label(root, textvariable=self.status).pack(fill='x', padx=12, pady=(0, 8))
        self.refresh_table()
        if not workspace.rows:
            raise ValueError('No ROI candidates in workspace')
        self._load_frame(0)
        root.protocol('WM_DELETE_WINDOW', self.close)

    def _restrict_old_controls(self, parent):
        for widget in parent.winfo_children():
            if isinstance(widget, (ttk.Frame, ttk.LabelFrame)):
                self._restrict_old_controls(widget)
            text = str(widget.cget('text')) if 'text' in widget.keys() else ''
            if text in ('源电极', '目标电极', '状态已核对', '添加帧', '查看短片'):
                widget.configure(state='disabled')
            if text in ('草稿阈值', '补充短片帧号'):
                widget.pack_forget()
            if isinstance(widget, (ttk.Entry, ttk.Spinbox, ttk.Combobox)):
                variable = str(widget.cget('textvariable'))
                if variable in {str(self.source), str(self.target), str(self.state), str(self.extra_frame)}:
                    widget.configure(state='disabled')
                if variable == str(self.threshold):
                    widget.pack_forget()

    def _review_edited(self):
        self.dirty = True

    def refresh_table(self):
        self.table.delete(*self.table.get_children())
        for index, row in enumerate(self.workspace.rows):
            self.table.insert('', 'end', iid=str(index), text=row['sample_id'],
                values=(row['source_frame_id'], '已核对' if row['mask_reviewed'] is True else '草稿',
                        '已核对' if row.get('exclusion_reviewed') is True else '草稿'))
        if self.index is not None:
            self.table.selection_set(str(self.index)); self.table.see(str(self.index))
        rows = self.workspace.rows
        self.status.set(f'前景 {sum(r["mask_reviewed"] is True for r in rows)}/{len(rows)}；'
            f'边界 {sum(r.get("boundary_reviewed") is True for r in rows)}；'
            f'排除域 {sum(r.get("exclusion_reviewed") is True for r in rows)}；'
            '实例/划分/训练仍需独立审核')

    def _load_frame(self, index):
        if index == self.index:
            return
        if not self._allow_leave():
            if self.index is not None:
                self.table.selection_set(str(self.index))
            return
        image, semantic = self.workspace.images(index)
        row = self.workspace.rows[index]
        exclusion_path = row.get('exclusion_mask_path') or row.get('exclusion_draft_path', '')
        exclusion = (read_image(self.workspace.root / exclusion_path, cv2.IMREAD_UNCHANGED)
                     if exclusion_path else np.zeros(image.shape[:2], np.uint8))
        _binary(semantic, image.shape[:2], 'Semantic mask')
        _binary(exclusion, image.shape[:2], 'Exclusion mask')
        self.index = index; self.image = image
        self.semantic = semantic; self.exclusion = exclusion
        self.source.set(str(row.get('source_electrode', '')))
        self.target.set(str(row.get('target_electrode', '')))
        self.state.set('Unknown'); self.state_reviewed.set(False)
        self.mask_reviewed.set(row.get('mask_reviewed') is True)
        self.boundary_reviewed.set(row.get('boundary_reviewed') is True)
        self.exclusion_reviewed.set(row.get('exclusion_reviewed') is True)
        self.notes.set(row.get('notes', '')); self.extra_frame.set(str(row['frame_id']))
        self.frame_title.set(f'{row["sample_id"]} | 原帧 {row["source_frame_id"]} | '
            f'任务源/目标电极记录 {self.source.get() or "未知"} → {self.target.get() or "未知"}（非实例ID）')
        self.table.selection_set(str(index)); self.table.see(str(index))
        self.dirty = False; self.last_brush = None
        self._mode_changed()

    def _mode_changed(self):
        self.mask = self.semantic if self.mode.get() == 'semantic' else self.exclusion
        self.last_brush = None
        self._draw_annotation()

    def _draw_annotation(self):
        if self.index is None or self.semantic is None or self.exclusion is None:
            return
        preview = self.image.copy()
        for mask, color in [(self.semantic, [75, 170, 230]), (self.exclusion, [195, 65, 170])]:
            selected = mask > 0
            preview[selected] = (.6 * preview[selected] + .4 * np.array(color)).astype(np.uint8)
        self.annotation_canvas.show(preview)

    def _annotation_click(self, x, y, drag):
        if self.tool.get() not in ('补液滴', '擦除'):
            return
        point = (round(x), round(y)); radius = max(1, min(50, int(self.radius.get())))
        value = 255 if self.tool.get() == '补液滴' else 0
        if drag and self.last_brush is not None:
            cv2.line(self.mask, self.last_brush, point, value, radius * 2)
        else:
            cv2.circle(self.mask, point, radius, value, -1)
        self.last_brush = point
        self._mask_changed()

    def _mask_changed(self):
        if self.mode.get() == 'semantic':
            self.semantic = self.mask
            self.mask_reviewed.set(False); self.boundary_reviewed.set(False)
        else:
            self.exclusion = self.mask
            self.exclusion_reviewed.set(False)
        self.state_reviewed.set(False); self.dirty = True
        self._draw_annotation()

    def _draft(self):
        if self.mode.get() != 'semantic':
            messagebox.showinfo('排除域无自动真值', '请用笔刷核对储液区；重建草稿仅用于液滴前景。', parent=self.root)
            return
        self.mask = all_foreground_draft(self.image)
        self._mask_changed()

    def save_frame(self):
        try:
            save_review_artifacts(self.workspace, self.index, self.semantic, self.exclusion,
                mask_reviewed=self.mask_reviewed.get(), boundary_reviewed=self.boundary_reviewed.get(),
                exclusion_reviewed=self.exclusion_reviewed.get(), notes=self.notes.get())
        except (ValueError, OSError) as exc:
            messagebox.showerror('标注未保存', str(exc), parent=self.root)
            return False
        self.dirty = False; self.refresh_table()
        return True

    def _allow_calibration_leave(self):
        return True


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline all-droplet and reservoir-exclusion review')
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--smoke', action='store_true', help='Open for 250 ms, then destroy without saving')
    args = parser.parse_args(argv)
    workspace = PilotWorkspace(args.workspace)
    before = sha256(workspace.root / 'workspace.json')
    root = tk.Tk()
    try:
        RoiPilotReviewApp(root, workspace)
        if args.smoke:
            root.after(250, root.destroy)
        root.mainloop()
    finally:
        try:
            if root.winfo_exists():
                root.destroy()
        except tk.TclError:
            pass
    if args.smoke and sha256(workspace.root / 'workspace.json') != before:
        raise RuntimeError('Smoke mode unexpectedly modified workspace metadata')


if __name__ == '__main__':
    main()
