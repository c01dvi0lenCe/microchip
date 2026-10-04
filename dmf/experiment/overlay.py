"""Shared overlay used for optional recording and throttled GUI preview."""
import cv2
import numpy as np


def render_overlay(packet, result, electrode_map, source, target, state, action):
    overlay = packet.image_bgr.copy()
    for electrode, color in [(source, (190, 140, 80)), (target, (50, 150, 230))]:
        polygon = np.rint(electrode_map[electrode].polygon_px).astype(np.int32)
        cv2.polylines(overlay, [polygon], True, color, 1)
    if result.mask is not None:
        contours, _ = cv2.findContours(result.mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(overlay, contours, -1, (220, 120, 50), 1)
        moments = cv2.moments(result.mask, binaryImage=True)
        if moments['m00']:
            center = (int(moments['m10']/moments['m00']), int(moments['m01']/moments['m00']))
            cv2.circle(overlay, center, 3, (0, 0, 200), -1)
    cv2.putText(overlay, f'{state} / {action}', (8, 22), cv2.FONT_HERSHEY_SIMPLEX,
                .5, (50, 50, 200), 1)
    return overlay
