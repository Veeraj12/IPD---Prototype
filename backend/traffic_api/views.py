import os
import cv2
import time
import json
import threading
import numpy as np

from django.http import StreamingHttpResponse, JsonResponse, HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from detector.yolo_detector import detect_fast, detect
from detector.tracker import Tracker
from detector.decision import get_signal_state, init_lanes

# ==========================================================
# PATHS
# ==========================================================
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")
DEFAULT_VIDEO = os.path.join(DATA_DIR, "sample_video.mp4")

# ==========================================================
# SHARED STATE
# ==========================================================
_video_lock = threading.Lock()
_current_video_path = DEFAULT_VIDEO if os.path.exists(DEFAULT_VIDEO) else None

_stats_lock = threading.Lock()
_current_stats = {
    "frame": 0,
    "video_name": os.path.basename(_current_video_path) if _current_video_path else "None",
    "status": "idle",
    "total_unique": 0,
    "green_lane": None,
    "signal_state": "Idle",
    "lanes": {},
    "density": {}
}

latest_clean_frame = None

# ==========================================================
# VEHICLE WEIGHTS
# ==========================================================
VEHICLE_WEIGHTS = {
    2: 2,   # car
    3: 1,   # motorcycle
    5: 5,   # bus
    7: 6    # truck
}

# ==========================================================
# HELPERS
# ==========================================================
def load_polygons():
    """
    Loads polygons from road_polygons.json
    """
    path = os.path.join(DATA_DIR, "road_polygons.json")

    if not os.path.exists(path):
        return []

    with open(path, "r") as f:
        data = json.load(f)

    return [np.array(item["points"], np.int32) for item in data]


def _make_placeholder(w, h, text):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = (20, 23, 32)

    cv2.putText(
        img,
        text,
        (w // 2 - 170, h // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (100, 100, 100),
        2
    )
    return img


# ==========================================================
# STREAM GENERATOR
# ==========================================================
def generate_frames():
    global latest_clean_frame

    DETECT_EVERY = 3

    while True:

        with _video_lock:
            video_path = _current_video_path

        # -----------------------------------------------
        # If no video exists
        # -----------------------------------------------
        if not video_path or not os.path.exists(video_path):

            placeholder = _make_placeholder(960, 540, "No video loaded")

            ok, buf = cv2.imencode(".jpg", placeholder)

            if ok:
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' +
                    buf.tobytes() +
                    b'\r\n'
                )

            time.sleep(1)
            continue

        cap = cv2.VideoCapture(video_path)

        if not cap.isOpened():
            time.sleep(1)
            continue

        # -----------------------------------------------
        # Video metadata
        # -----------------------------------------------
        native_fps = cap.get(cv2.CAP_PROP_FPS) or 30
        frame_delay = 1.0 / native_fps

        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # Preserve aspect ratio
        if orig_w > 0 and orig_h > 0:
            scale = min(960 / orig_w, 1.0)
            STREAM_W = int(orig_w * scale)
            STREAM_H = int(orig_h * scale)
        else:
            STREAM_W, STREAM_H = 960, 540

        # -----------------------------------------------
        # Init trackers
        # -----------------------------------------------
        tracker = Tracker()
        polygons = load_polygons()
        init_lanes(len(polygons))

        frame_index = 0
        last_tracked = []

        # ==================================================
        # FRAME LOOP
        # ==================================================
        while True:

            with _video_lock:
                if _current_video_path != video_path:
                    break

            start = time.time()

            ret, frame = cap.read()

            if not ret:
                break

            frame = cv2.resize(frame, (STREAM_W, STREAM_H))

            # save clean frame for snapshot
            latest_clean_frame = frame.copy()

            # -----------------------------------------------
            # Detection every N frames
            # -----------------------------------------------
            if frame_index % DETECT_EVERY == 0:

                detections = detect_fast(frame)
                last_tracked = tracker.update(detections)

                lane_fill = {
                    i: 0 for i in range(len(polygons))
                }

                for obj in last_tracked:
                    x1, y1, x2, y2, obj_id = obj

                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2

                    weight = 2

                    for i, poly in enumerate(polygons):

                        inside = cv2.pointPolygonTest(
                            poly,
                            (cx, cy),
                            False
                        )

                        if inside >= 0:
                            box_area = (x2 - x1) * (y2 - y1)
                            lane_fill[i] += box_area
                            break

                # -------------------------------------------
                # Normalize by polygon area
                # -------------------------------------------
                lane_areas = [
                    max(cv2.contourArea(poly), 1)
                    for poly in polygons
                ]

                normalized_density = {
                    i: min(lane_fill[i] / lane_areas[i], 1.0)
                    for i in lane_fill
                }

                # -------------------------------------------
                # Smart signal logic
                # -------------------------------------------
                if polygons:
                    green_lane, signal_state, timer = get_signal_state(
                        normalized_density
                    )
                else:
                    green_lane = None
                    signal_state = "No ROI"

                with _stats_lock:
                    _current_stats.update({
                        "frame": frame_index,
                        "video_name": os.path.basename(video_path),
                        "status": "running",
                        "total_unique": tracker.id_count,
                        "green_lane": green_lane,
                        "signal_state": signal_state,
                        "lanes": lane_fill,
                        "density": normalized_density,
                        "timer": timer
                    })

            # ==================================================
            # DRAW POLYGONS
            # ==================================================
            with _stats_lock:
                stats = _current_stats.copy()

            active_lane = stats["green_lane"]

            for i, poly in enumerate(polygons):

                color = (0, 0, 255)

                if i == active_lane:
                    color = (0, 255, 0)

                cv2.polylines(frame, [poly], True, color, 3)

                x, y = poly[0]

                cv2.putText(
                    frame,
                    f"Lane {i+1}",
                    (x, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    color,
                    2
                )

            # ==================================================
            # DRAW DETECTIONS
            # ==================================================
            for obj in last_tracked:
                x1, y1, x2, y2, obj_id = obj

                cv2.rectangle(
                    frame,
                    (x1, y1),
                    (x2, y2),
                    (255, 180, 0),
                    2
                )

                cv2.putText(
                    frame,
                    f"#{obj_id}",
                    (x1, max(20, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (255, 180, 0),
                    2
                )

            # ==================================================
            # HUD TOP BAR
            # ==================================================
            overlay = frame.copy()

            cv2.rectangle(
                overlay,
                (0, 0),
                (STREAM_W, 65),
                (0, 0, 0),
                -1
            )

            cv2.addWeighted(
                overlay,
                0.45,
                frame,
                0.55,
                0,
                frame
            )

            green_text = (
                "None"
                if stats["green_lane"] is None
                else str(stats["green_lane"] + 1)
            )

            cv2.putText(
                frame,
                f"Vehicles:{stats['total_unique']}  "
                f"Active Green Lane:{green_text}  "
                f"{stats['signal_state']}",
                (15, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 120),
                2
            )

            # ==================================================
            # DENSITY DISPLAY
            # ==================================================
            y_pos = 95

            for i, d in stats["density"].items():
                cv2.putText(
                    frame,
                    f"D{i+1}: {round(d*100,1)}%",
                    (15, y_pos),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (255, 255, 255),
                    2
                )
                y_pos += 28

            # ==================================================
            # ENCODE FRAME
            # ==================================================
            ok, buf = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, 75]
            )

            if ok:
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' +
                    buf.tobytes() +
                    b'\r\n'
                )

            elapsed = time.time() - start
            wait = frame_delay - elapsed

            if wait > 0:
                time.sleep(wait)

            frame_index += 1

        cap.release()


# ==========================================================
# DJANGO VIEWS
# ==========================================================
def video_feed(request):
    response = StreamingHttpResponse(
        generate_frames(),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )

    response["Cache-Control"] = "no-cache"
    response["Access-Control-Allow-Origin"] = "*"

    return response


def get_stats(request):
    with _stats_lock:
        data = _current_stats.copy()

    response = JsonResponse(data)
    response["Access-Control-Allow-Origin"] = "*"

    return response


def snapshot(request):
    global latest_clean_frame

    if latest_clean_frame is None:
        return JsonResponse(
            {"error": "No frame available"},
            status=404
        )

    ok, buffer = cv2.imencode(".jpg", latest_clean_frame)

    if not ok:
        return JsonResponse(
            {"error": "Encoding failed"},
            status=500
        )

    response = HttpResponse(
        buffer.tobytes(),
        content_type="image/jpeg"
    )

    response["Access-Control-Allow-Origin"] = "*"
    return response


@api_view(["POST"])
def upload_video(request):
    global _current_video_path

    if "video" not in request.FILES:
        return Response(
            {"error": "No video uploaded"},
            status=400
        )

    file = request.FILES["video"]

    os.makedirs(DATA_DIR, exist_ok=True)

    save_path = os.path.join(DATA_DIR, file.name)

    with open(save_path, "wb") as f:
        for chunk in file.chunks():
            f.write(chunk)

    cap = cv2.VideoCapture(save_path)

    if not cap.isOpened():
        os.remove(save_path)

        return Response(
            {"error": "Invalid video"},
            status=400
        )

    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    cap.release()

    with _video_lock:
        _current_video_path = save_path

    return Response({
        "success": True,
        "filename": file.name,
        "frames": frames,
        "fps": round(fps, 2),
        "width": width,
        "height": height
    })


@api_view(["POST"])
def save_polygons(request):
    try:
        data = request.data

        os.makedirs(DATA_DIR, exist_ok=True)

        path = os.path.join(DATA_DIR, "road_polygons.json")

        with open(path, "w") as f:
            json.dump(data, f, indent=4)

        return Response({
            "success": True,
            "message": "Polygons saved successfully"
        })

    except Exception as e:
        return Response({
            "success": False,
            "error": str(e)
        }, status=500)


@api_view(["GET"])
def traffic_status(request):
    """
    Batch analysis endpoint
    """
    with _video_lock:
        video_path = _current_video_path

    if not video_path or not os.path.exists(video_path):
        return Response({"error": "No video loaded"}, status=404)

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        return Response({"error": "Could not open video"}, status=500)

    tracker = Tracker()
    frame_index = 0
    peak_count = 0

    while True:
        ret, frame = cap.read()

        if not ret:
            break

        if frame_index % 15 == 0:
            detections = detect(frame)
            tracked = tracker.update(detections)

            if len(tracked) > peak_count:
                peak_count = len(tracked)

        frame_index += 1

    cap.release()

    return Response({
        "vehicle_count": tracker.id_count,
        "peak_simultaneous": peak_count,
        "frames_analyzed": frame_index // 15,
        "video": os.path.basename(video_path)
    })