from ultralytics import YOLO

# COCO vehicle class IDs
# VEHICLE_CLASSES = {
#     1: "bicycle",
#     2: "car",
#     3: "motorcycle",
#     5: "bus",
#     7: "truck",
# }
#Improvement 4 - 24/09/26 After changing detector to UVH - 26 s
VEHICLE_CLASSES = {
    0: "Hatchback",
    1: "Sedan",
    2: "SUV",
    3: "MUV",
    4: "Bus",
    5: "Truck",
    6: "Three-wheeler",
    7: "Two-wheeler",
    8: "LCV",
    9: "Mini-bus",
    10: "tempo-traveller",
    11: "bicycle",
    12: "Van",
    13: "Others"
}

import os

# ── Two models ────────────────────────────────────────────────────────────────
# nano  → fast (~60ms/frame on CPU) — used for live streaming
# medium → accurate (~400ms/frame on CPU) — used for batch analysis
_model_fast     = None   # yolov8n or best.pt — loaded on first stream request
_model_accurate = None   # yolov8m or best.pt — loaded on first batch request

def _get_best_model_path():
    """Returns path to fine-tuned best.pt if it exists, otherwise None."""
    best_path = os.path.join(os.path.dirname(__file__), '..', 'training', 'runs', 'traffic_model', 'weights', 'UVH26Ms.pt')
    if os.path.exists(best_path):
        return best_path
    
    fallback_path = os.path.join(os.path.dirname(__file__), '..', 'UVH26Ms.pt')
    if os.path.exists(fallback_path):
        return fallback_path
        
    return None

def _get_fast():
    global _model_fast
    if _model_fast is None:
        custom_model = _get_best_model_path()
        if custom_model:
            print(f"Loading custom fine-tuned model for fast detection: {custom_model}")
            _model_fast = YOLO(custom_model)
            print("YOLO device:", _model_fast.device)
            print("YOLO classes:", _model_fast.names)
        else:
            _model_fast = YOLO("yolov8n.pt")
    return _model_fast


def _get_accurate():
    global _model_accurate
    if _model_accurate is None:
        custom_model = _get_best_model_path()
        if custom_model:
            print(f"Loading custom fine-tuned model for accurate detection: {custom_model}")
            _model_accurate = YOLO(custom_model)
        else:
            _model_accurate = YOLO("yolov8m.pt")
    return _model_accurate


def _run(model, frame, conf):
    detections = []
    results = model(frame, verbose=False, conf=conf)
    #Improvement 3 - 24/9/26
    # results = model(
    #     frame,
    #     verbose=False,
    #     conf=conf,
    #     imgsz=640
    # )
    for r in results:
        for box in r.boxes:
            cls_id = int(box.cls[0])
            # If model has >10 classes, we assume it's general COCO and filter.
            # If it's fine-tuned on UA-DETRAC, it has 4 classes, all are vehicles.
            if len(r.names) > 10: 
                if cls_id in VEHICLE_CLASSES:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    detections.append([x1, y1, x2, y2])
            else:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                detections.append([x1, y1, x2, y2])
    return detections


def detect_fast(frame, conf=0.35):
    """
    YOLOv8n — optimised for real-time streaming (~60 ms/frame on CPU).
    Use in the MJPEG generator.
    """
    return _run(_get_fast(), frame, conf)


def detect_accurate(frame, conf=0.4):
    """
    YOLOv8m — optimised for accuracy in batch analysis (~400 ms/frame on CPU).
    Use in the /traffic/ batch endpoint.
    """
    return _run(_get_accurate(), frame, conf)


# Keep a generic alias so existing callers don't break
def detect(frame, verbose=False, conf=0.4):
    return _run(_get_accurate(), frame, conf)
