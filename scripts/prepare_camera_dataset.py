"""Review camera recordings and export explicitly accepted single-target ROI clips."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from dmf.vision.image_io import write_image

SCAN_W, SCAN_H, SCAN_FPS = 912, 608, 2


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def capture_date(path):
    match = re.fullmatch(r"camera_(\d{8})_\d{6}_\d+", Path(path).stem)
    if not match:
        raise ValueError(f"No explicit capture date in filename: {path}")
    return datetime.strptime(match[1], "%Y%m%d").strftime("%Y-%m-%d")


def probe(path):
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError(f"Cannot open {path}")
        rate = float(cap.get(cv2.CAP_PROP_FPS))
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not math.isfinite(rate) or rate <= 0 or count <= 0:
            raise ValueError(f"Invalid container timing: {path}")
        return dict(video_id=Path(path).stem, source=str(Path(path).resolve()),
                    batch_id=capture_date(path), fps=rate, frames=count,
                    width=int(cap.get(3)), height=int(cap.get(4)),
                    duration_s=count / rate, sha256=sha(path),
                    timestamp_source="container_fps", date_source="capture_filename")
    finally:
        cap.release()


def save_csv(path, rows, fields=None):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def detections(frame):
    # Pilot screening only; these dark components are not U-Net predictions or GT.
    mask = (frame.max(axis=2) <= 55).astype(np.uint8) * 255
    mask[:97] = 0
    mask[517:] = 0
    mask[:, :210] = 0
    mask[:, 575:] = 0
    count, _, stats, centers = cv2.connectedComponentsWithStats(mask)
    return [dict(x=float(centers[i, 0]), y=float(centers[i, 1]),
                 bbox=[int(v) for v in stats[i, :4]], area=int(stats[i, 4]))
            for i in range(1, count) if 10 <= stats[i, 4] <= 450]


def update_tracks(tracks, found, t):
    pairs = []
    for i, track in enumerate(tracks):
        previous = track[-1]
        if t - previous["t"] <= 0.76:
            for j, point in enumerate(found):
                distance = math.hypot(point["x"] - previous["x"], point["y"] - previous["y"])
                if distance <= 40:
                    pairs.append((distance, i, j))
    used_tracks, used_points = set(), set()
    for _, i, j in sorted(pairs):
        if i not in used_tracks and j not in used_points:
            tracks[i].append(dict(found[j], t=t))
            used_tracks.add(i)
            used_points.add(j)
    for j, point in enumerate(found):
        if j not in used_points:
            tracks.append([dict(point, t=t)])


def movement_windows(points):
    windows = []
    for previous, current in zip(points, points[1:]):
        distance = math.hypot(current["x"] - previous["x"], current["y"] - previous["y"])
        if current["t"] - previous["t"] <= 0.76 and distance >= 4:
            if windows and previous["t"] - windows[-1][1] <= 1.5:
                windows[-1][1] = current["t"]
            else:
                windows.append([previous["t"], current["t"]])
    return windows


def crop_for_points(points, width, height):
    sx, sy = width / SCAN_W, height / SCAN_H
    x = max(0, int((min(p["bbox"][0] for p in points) - 12) * sx) // 2 * 2)
    y = max(0, int((min(p["bbox"][1] for p in points) - 12) * sy) // 2 * 2)
    right = min(width, math.ceil((max(p["bbox"][0] + p["bbox"][2] for p in points) + 12) * sx / 2) * 2)
    bottom = min(height, math.ceil((max(p["bbox"][1] + p["bbox"][3] for p in points) + 12) * sy / 2) * 2)
    return [x, y, right - x, bottom - y]


def overlaps_crop(point, crop, width, height):
    x, y, w, h = point["bbox"]
    sx, sy = width / SCAN_W, height / SCAN_H
    left, top, cw, ch = crop
    return x * sx < left + cw and (x + w) * sx > left and y * sy < top + ch and (y + h) * sy > top


def lowres_frames(ffmpeg, source, log_path):
    command = [str(ffmpeg), "-hide_banner", "-nostdin", "-v", "warning", "-threads", "2",
               "-i", str(source), "-vf", f"fps={SCAN_FPS},scale={SCAN_W}:{SCAN_H}:flags=area",
               "-threads", "2", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    size = SCAN_W * SCAN_H * 3
    with Path(log_path).open("wb") as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        try:
            index = 0
            while True:
                chunks, received = [], 0
                while received < size:
                    chunk = process.stdout.read(size - received)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    received += len(chunk)
                if not received:
                    break
                if received != size:
                    raise ValueError("Incomplete screening frame")
                yield index / SCAN_FPS, np.frombuffer(b"".join(chunks), np.uint8).reshape(SCAN_H, SCAN_W, 3)
                index += 1
            if process.wait() != 0:
                raise RuntimeError(f"FFmpeg screening failed; see {log_path}")
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.terminate()
                process.wait()


def scan(media, output, ffmpeg):
    output.mkdir(parents=True, exist_ok=False)
    (output / "review").mkdir()
    (output / "logs").mkdir()
    inventory, candidates, tracking = [], [], []
    for path in sorted((media / "视频").rglob("*.avi")):
        metadata = probe(path)
        inventory.append(metadata)
        tracks, samples, disruptions = [], [], []
        previous = None
        for t, frame in lowres_frames(ffmpeg, path, output / "logs" / (path.stem + ".log")):
            roi = frame[97:517, 210:575]
            disruption = previous is not None and float((cv2.absdiff(roi, previous).max(axis=2) > 45).mean()) > 0.08
            previous = roi.copy()
            if disruption:
                disruptions.append(t)
            found = [] if disruption else detections(frame)
            update_tracks(tracks, found, t)
            samples.append(frame.copy())
        metadata["screened_samples"] = len(samples)
        metadata["decode_warning_log"] = str((output / "logs" / (path.stem + ".log")).resolve())
        serial = 0
        for track_id, points in enumerate(tracks):
            for point in points:
                tracking.append(dict(video_id=path.stem, track_id=track_id,
                                     scan_time_s=point["t"], x_px=point["x"] * metadata["width"] / SCAN_W,
                                     y_px=point["y"] * metadata["height"] / SCAN_H,
                                     estimate_only=True))
            for a, b in movement_windows(points):
                # Long episodes remain long-video context, rather than fake single steps.
                if b - a > 10:
                    continue
                start = max(0, a - 1)
                end = min((len(samples) - 1) / SCAN_FPS, b + 1)
                selected = [p for p in points if start <= p["t"] <= end]
                if end - start < 1 or len(selected) < 3:
                    continue
                crop = crop_for_points(selected, metadata["width"], metadata["height"])
                other = any(overlaps_crop(p, crop, metadata["width"], metadata["height"])
                            for other_id, trail in enumerate(tracks) if other_id != track_id
                            for p in trail if start <= p["t"] <= end)
                disrupted = any(start - 0.5 <= t <= end + 0.5 for t in disruptions)
                serial += 1
                clip_id = f"{path.stem}_t{track_id:03d}_c{serial:03d}"
                record = dict(clip_id=clip_id, video_id=path.stem, batch_id=metadata["batch_id"],
                              source=metadata["source"], source_sha256=metadata["sha256"],
                              start_frame=math.ceil(start * metadata["fps"]),
                              end_frame_exclusive=math.floor(end * metadata["fps"]),
                              fps=metadata["fps"], roi_xywh=crop,
                              review_status="rejected" if other or disrupted else "pending",
                              exclusion="other_component_in_roi" if other else "scene_disruption" if disrupted else "",
                              discovery="pilot_dark_component_motion; not trained model or ground truth")
                candidates.append(record)
                sheet = Image.new("RGB", (900, 300), "white")
                draw = ImageDraw.Draw(sheet)
                for column, t in enumerate((start, (a + b) / 2, end)):
                    frame = samples[min(len(samples) - 1, round(t * SCAN_FPS))]
                    x, y, w, h = crop
                    x, y, w, h = int(x / metadata["width"] * SCAN_W), int(y / metadata["height"] * SCAN_H), max(1, int(w / metadata["width"] * SCAN_W)), max(1, int(h / metadata["height"] * SCAN_H))
                    image = Image.fromarray(cv2.cvtColor(frame[y:y+h, x:x+w], cv2.COLOR_BGR2RGB))
                    image.thumbnail((290, 240))
                    sheet.paste(image, (column * 300 + 5, 45))
                    draw.text((column * 300 + 5, 5), f"{clip_id[-9:]} | {t:.2f}s", fill="black")
                sheet.save(output / "review" / (clip_id + ".png"))
        print(f"Screened {path.name}: {len(samples)} samples, {serial} candidates", flush=True)
        if sha(path) != metadata["sha256"]:
            raise RuntimeError("Source recording changed during screening")
    (output / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (output / "candidates.json").write_text(json.dumps(candidates, indent=2), encoding="utf-8")
    if tracking:
        save_csv(output / "tracking_estimates.csv", tracking)
    save_csv(output / "long_videos.csv", [{k: v for k, v in row.items() if k != "roi"} for row in inventory])
    print(f"Pending: {sum(c['review_status'] == 'pending' for c in candidates)}; rejected: {sum(c['review_status'] == 'rejected' for c in candidates)}", flush=True)


def export_clips(review, selection_path, ffmpeg):
    candidates = json.loads((review / "candidates.json").read_text())
    selection = json.loads(Path(selection_path).read_text())
    accepted = set(selection["accepted_clip_ids"])
    if len(accepted) != len(selection["accepted_clip_ids"]):
        raise ValueError("Duplicate clip IDs in selection")
    chosen = [c for c in candidates if c["clip_id"] in accepted]
    if len(chosen) != len(accepted) or any(c["review_status"] != "pending" for c in chosen):
        raise ValueError("Selection contains unknown or excluded candidates")
    clips, labels = [], []
    for item in chosen:
        source = Path(item["source"])
        if sha(source) != item["source_sha256"]:
            raise ValueError("Source changed after review")
        folder = review / "clips" / item["batch_id"]
        folder.mkdir(parents=True, exist_ok=True)
        clip = folder / (item["clip_id"] + ".mkv")
        if clip.exists():
            raise FileExistsError(clip)
        x, y, w, h = item["roi_xywh"]
        start, end, rate = item["start_frame"], item["end_frame_exclusive"], item["fps"]
        # Accurate input seeking with re-encoding; no streamcopy/keyframe approximation.
        command = [str(ffmpeg), "-hide_banner", "-nostdin", "-n", "-v", "warning", "-threads", "2",
                   "-ss", f"{start / rate:.12f}", "-i", str(source), "-frames:v", str(end - start),
                   "-vf", f"format=bgr0,crop={w}:{h}:{x}:{y}", "-an", "-c:v", "ffv1", "-level", "3",
                   "-pix_fmt", "bgr0", "-threads", "2", str(clip)]
        result = subprocess.run(command, capture_output=True, text=True, errors="replace")
        (review / "logs" / (item["clip_id"] + ".log")).write_text(result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(result.stderr)
        cap = cv2.VideoCapture(str(clip))
        count, extracted = 0, []
        desired = {0, (end - start) // 2, end - start - 1}
        try:
            if not cap.isOpened():
                raise RuntimeError("Exported clip cannot be read")
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if count in desired:
                    image = review / "annotation_frames" / item["batch_id"] / item["clip_id"] / f"frame_{count:05d}.png"
                    if not write_image(image, frame):
                        raise OSError("Annotation frame save failed")
                    extracted.append(str(image.resolve()))
                    labels.append(dict(video_id=item["clip_id"], batch_id=item["batch_id"],
                                      frame_id=count, timestamp_s=count / rate,
                                      mask_path="", source_electrode="", target_electrode="", state_gt="Unknown",
                                      image_path=str(image.resolve()), parent_video_id=item["video_id"],
                                      source_frame_id=start + count, roi_x=x, roi_y=y,
                                      annotation_status="unlabeled", split="unassigned"))
                count += 1
            if count != end - start:
                raise RuntimeError(f"Exported frame count mismatch: {count} != {end-start}")
            if int(cap.get(3)) != w or int(cap.get(4)) != h or abs(cap.get(5) - rate) > 0.01:
                raise RuntimeError("Export changed spatial size or nominal frame rate")
        finally:
            cap.release()
        record = dict(item, review_status="accepted_visual_review", path=str(clip.resolve()),
                      encoding="lossless_ffv1_bgr0", resize=False, color_adjustment=False,
                      decoded_frames=count, clip_sha256=sha(clip), annotation_frames=extracted,
                      split="unassigned", group_id=item["video_id"],
                      timing_note="Source container timing, not measured actuation timing")
        clips.append(record)
        if sha(source) != item["source_sha256"]:
            raise RuntimeError("Original recording changed")
        print(f"Exported {item['clip_id']}: {count} frames, {w}x{h}", flush=True)
    (review / "clips_manifest.json").write_text(json.dumps(clips, indent=2), encoding="utf-8")
    if labels:
        save_csv(review / "annotations_to_label.csv", labels)
    flat = [dict(clip_id=c["clip_id"], parent_video_id=c["video_id"], batch_id=c["batch_id"],
                 start_frame=c["start_frame"], end_frame_exclusive=c["end_frame_exclusive"],
                 start_s=c["start_frame"] / c["fps"], end_s=c["end_frame_exclusive"] / c["fps"],
                 fps=c["fps"], roi_xywh=json.dumps(c["roi_xywh"]), clip_path=c["path"],
                 source_path=c["source"], source_sha256=c["source_sha256"],
                 clip_sha256=c["clip_sha256"], group_id=c["group_id"], split=c["split"]) for c in clips]
    if flat:
        save_csv(review / "clips.csv", flat)


def export_previews(review, ffmpeg):
    clips = json.loads((review / "clips_manifest.json").read_text())
    previews = []
    for item in clips:
        source = Path(item["path"])
        if sha(source) != item["clip_sha256"]:
            raise ValueError("Lossless clip changed after export")
        folder = review / "preview_mp4" / item["batch_id"]
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (item["clip_id"] + ".mp4")
        if target.exists():
            raise FileExistsError(target)
        result = subprocess.run([str(ffmpeg), "-hide_banner", "-nostdin", "-n", "-v", "error",
                                 "-threads", "2", "-i", str(source), "-an", "-c:v", "libx264",
                                 "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                                 "-threads", "2", "-movflags", "+faststart", str(target)],
                                capture_output=True, text=True, errors="replace")
        if result.returncode:
            raise RuntimeError(result.stderr)
        cap = cv2.VideoCapture(str(target))
        count = 0
        try:
            while cap.read()[0]:
                count += 1
            if count != item["decoded_frames"] or abs(cap.get(5) - item["fps"]) > 0.01:
                raise ValueError("Preview frame count or FPS mismatch")
        finally:
            cap.release()
        previews.append(dict(clip_id=item["clip_id"], path=str(target.resolve()),
                             sha256=sha(target), lossless_source=str(source),
                             preview_only=True, encoding="lossy_h264_crf18_yuv420p",
                             decoded_frames=count))
    (review / "previews_manifest.json").write_text(json.dumps(previews, indent=2), encoding="utf-8")
    print(f"Validated {len(previews)} MP4 viewing previews", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("scan", "export", "preview"))
    parser.add_argument("--media", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--selection", type=Path)
    args = parser.parse_args()
    if args.mode == "scan":
        if args.media is None:
            parser.error("scan requires --media")
        scan(args.media, args.output, args.ffmpeg)
    elif args.mode == "export":
        if args.selection is None:
            parser.error("export requires --selection")
        export_clips(args.output, args.selection, args.ffmpeg)
    else:
        export_previews(args.output, args.ffmpeg)


if __name__ == "__main__":
    main()
