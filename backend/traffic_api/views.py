import os
import cv2
import time
import threading

from django.http import StreamingHttpResponse, JsonResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser

from detector.yolo_detector import detect
from detector.tracker import Tracker
from detector.decision import get_signal_time

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR         = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
DEFAULT_VIDEO    = os.path.join(DATA_DIR, 'sample_video.mp4')

# ── Shared state ──────────────────────────────────────────────────────────────
_video_lock = threading.Lock()
_current_video_path = DEFAULT_VIDEO if os.path.exists(DEFAULT_VIDEO) else None

_stats_lock = threading.Lock()
_current_stats = {
    "zone_a_count":   0,
    "zone_b_count":   0,
    "total_unique":   0,
    "signal_a":       "Yellow",
    "signal_b":       "Yellow",
    "frame":          0,
    "video_name":     os.path.basename(_current_video_path) if _current_video_path else "None",
    "status":         "idle",
}

def _reset_stats(video_name=""):
    with _stats_lock:
        _current_stats.update({
            "zone_a_count":   0,
            "zone_b_count":   0,
            "total_unique":   0,
            "signal_a":       "Yellow",
            "signal_b":       "Yellow",
            "frame":          0,
            "video_name":     video_name,
            "status":         "running",
        })


# ── MJPEG Generator ───────────────────────────────────────────────────────────
def generate_frames():
    """
    Streams the current video as MJPEG.
    Automatically restarts when the video ends (loops) or when a new video
    is uploaded (_current_video_path changes).
    """
    DETECT_EVERY = 3
    STREAM_W, STREAM_H = 960, 540

    while True:
        # Grab current video path
        with _video_lock:
            video_path = _current_video_path

        if not video_path or not os.path.exists(video_path):
            # No video yet — yield a placeholder frame
            placeholder = _make_placeholder(STREAM_W, STREAM_H, "No video loaded")
            ok, buf = cv2.imencode('.jpg', placeholder)
            if ok:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                       + buf.tobytes() + b'\r\n')
            time.sleep(1)
            continue

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            time.sleep(1)
            continue

        native_fps   = cap.get(cv2.CAP_PROP_FPS) or 30
        frame_delay  = 1.0 / native_fps
        orig_w       = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Calculate aspect-ratio-preserving dimensions (max width 960)
        if orig_w > 0 and orig_h > 0:
            scale = min(960 / orig_w, 1.0)
            STREAM_W = int(orig_w * scale)
            STREAM_H = int(orig_h * scale)
        else:
            STREAM_W, STREAM_H = 960, 540

        tracker      = Tracker()
        _reset_stats(os.path.basename(video_path))
        frame_index  = 0
        last_tracked = []

        while True:
            # Check if the user uploaded a new video mid-stream
            with _video_lock:
                if _current_video_path != video_path:
                    break   # restart outer loop with new path

            t0 = time.time()
            ret, frame = cap.read()
            if not ret:
                break   # video ended → loop

            frame_resized = cv2.resize(frame, (STREAM_W, STREAM_H))

            # ── YOLO every N frames ────────────────────────────────────────
            if frame_index % DETECT_EVERY == 0:
                detections   = detect(frame_resized, verbose=False)
                last_tracked = tracker.update(detections)
                
                # Split counts based on center X coordinate
                zone_a, zone_b = 0, 0
                for obj in last_tracked:
                    x1, y1, x2, y2, obj_id = obj
                    cx = (x1 + x2) // 2
                    if cx < (STREAM_W // 2):
                        zone_a += 1
                    else:
                        zone_b += 1
                
                signals = get_signal_time(zone_a, zone_b)
                with _stats_lock:
                    _current_stats.update({
                        "zone_a_count": zone_a,
                        "zone_b_count": zone_b,
                        "total_unique": tracker.id_count,
                        "signal_a":     signals["zone_a"],
                        "signal_b":     signals["zone_b"],
                        "frame":        frame_index,
                        "status":       "running",
                    })

            # ── Draw boxes & ROI overlays ─────────────────────────────────
            overlay = frame_resized.copy()
            # Draw semi-transparent background for ROIs
            cv2.rectangle(overlay, (0, 0), (STREAM_W//2, STREAM_H), (0, 0, 50), -1)  # Zone A (Left)
            cv2.rectangle(overlay, (STREAM_W//2, 0), (STREAM_W, STREAM_H), (50, 0, 0), -1)  # Zone B (Right)
            cv2.addWeighted(overlay, 0.15, frame_resized, 0.85, 0, frame_resized)

            # Draw a highly visible splitting line down the middle
            cv2.line(frame_resized, (STREAM_W//2, 0), (STREAM_W//2, STREAM_H), (255, 255, 255), 2)

            # Clearly label the lanes physically in the video frame
            cv2.putText(frame_resized, "LANE A", (STREAM_W//4 - 60, 100), cv2.FONT_HERSHEY_DUPLEX, 1.2, (0, 165, 255), 2)
            cv2.putText(frame_resized, "LANE B", (STREAM_W*3//4 - 60, 100), cv2.FONT_HERSHEY_DUPLEX, 1.2, (255, 100, 0), 2)

            for obj in last_tracked:
                x1, y1, x2, y2, obj_id = obj
                cx = (x1 + x2) // 2
                color = (0, 165, 255) if cx < (STREAM_W // 2) else (255, 100, 0)
                cv2.rectangle(frame_resized, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame_resized, f"#{obj_id}", (x1, max(y1 - 6, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                # Draw center dot
                cv2.circle(frame_resized, (cx, (y1+y2)//2), 3, color, -1)

            # ── HUD overlay ───────────────────────────────────────────────
            with _stats_lock:
                s = _current_stats.copy()
            overlay = frame_resized.copy()
            cv2.rectangle(overlay, (0, 0), (STREAM_W, 62), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.5, frame_resized, 0.5, 0, frame_resized)
            cv2.putText(frame_resized,
                        f"Lane A: {s['zone_a_count']}   Lane B: {s['zone_b_count']}   "
                        f"Unique: {s['total_unique']}   {s['video_name']}",
                        (12, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 255, 80), 2)

            # ── Encode & yield ─────────────────────────────────────────────
            ok, buf = cv2.imencode('.jpg', frame_resized,
                                   [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                       + buf.tobytes() + b'\r\n')

            elapsed = time.time() - t0
            wait    = frame_delay - elapsed
            if wait > 0:
                time.sleep(wait)

            frame_index += 1

        cap.release()


def _make_placeholder(w, h, text):
    """Dark placeholder frame with centered text."""
    img = __import__('numpy').zeros((h, w, 3), dtype='uint8')
    img[:] = (20, 23, 32)
    cv2.putText(img, text, (w // 2 - 160, h // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (80, 80, 100), 2)
    return img


# ── Django views ──────────────────────────────────────────────────────────────

def video_feed(request):
    """MJPEG live stream — embed as <img src='/stream/'>."""
    response = StreamingHttpResponse(
        generate_frames(),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )
    response['Cache-Control']              = 'no-cache'
    response['Access-Control-Allow-Origin'] = '*'
    return response


def get_stats(request):
    """Returns current real-time detection stats as JSON."""
    with _stats_lock:
        stats = _current_stats.copy()
    response = JsonResponse(stats)
    response['Access-Control-Allow-Origin'] = '*'
    return response


@api_view(['POST'])
def upload_video(request):
    """
    Accepts a video file upload (multipart/form-data, field name = 'video').
    Saves it to backend/data/ and switches the live stream to it immediately.
    """
    global _current_video_path

    if 'video' not in request.FILES:
        return Response({'error': 'No video file. Use field name "video".'}, status=400)

    video_file = request.FILES['video']
    filename   = os.path.basename(video_file.name)   # strip any path traversal

    os.makedirs(DATA_DIR, exist_ok=True)
    save_path = os.path.join(DATA_DIR, filename)

    # Write chunks to disk (handles large files efficiently)
    with open(save_path, 'wb') as f:
        for chunk in video_file.chunks():
            f.write(chunk)

    # Verify it's a readable video
    cap = cv2.VideoCapture(save_path)
    if not cap.isOpened():
        os.remove(save_path)
        return Response({'error': 'Uploaded file is not a valid video.'}, status=400)

    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps    = cap.get(cv2.CAP_PROP_FPS)
    w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    # Switch the stream
    with _video_lock:
        _current_video_path = save_path

    return Response({
        'success':  True,
        'filename': filename,
        'frames':   frames,
        'fps':      round(fps, 2),
        'width':    w,
        'height':   h,
    })


@api_view(['GET'])
def traffic_status(request):
    """Full-video batch analysis endpoint (unchanged)."""
    with _video_lock:
        video_path = _current_video_path

    if not video_path or not os.path.exists(video_path):
        return Response({"error": "No video loaded."}, status=404)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return Response({"error": "Could not open video."}, status=500)

    tracker     = Tracker()
    frame_index = 0
    peak_count  = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_index % 15 == 0:
            detections = detect(frame, verbose=False)
            tracked    = tracker.update(detections)
            if len(tracked) > peak_count:
                peak_count = len(tracked)
        frame_index += 1

    cap.release()

    total = tracker.id_count
    return Response({
        "vehicle_count":    total,
        "peak_simultaneous": peak_count,
        "signal_time":      get_signal_time(total),
        "frames_analyzed":  frame_index // 15,
        "video":            os.path.basename(video_path),
    })