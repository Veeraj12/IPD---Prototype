from django.urls import path
from .views import video_feed, get_stats, snapshot, save_polygons, traffic_status, upload_video

urlpatterns = [
    path('stream/',      video_feed),      # MJPEG live video
    path('api/stats/',   get_stats),       # Real-time JSON stats (polling)
    path('upload/',      upload_video),    # Upload any video
    path('traffic/',     traffic_status),  # Full batch analysis
    path("snapshot/",    snapshot),
    path("save-polygons/", save_polygons),
]