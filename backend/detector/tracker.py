import math


class Tracker:
    """
    Simple centroid-based multi-object tracker.

    Assigns a persistent ID to each tracked object by matching new detections
    to existing tracked centroids using Euclidean distance.

    Attributes:
        max_dist  -- max pixel distance to consider same object (default 50)
        max_lost  -- frames an object can be absent before being dropped (default 10)
    """

    def __init__(self, max_dist=50, max_lost=10):
        self.center_points = {}   # id → (cx, cy)
        self.lost_count    = {}   # id → frames since last seen
        self.id_count      = 0
        self.max_dist      = max_dist
        self.max_lost      = max_lost

    def update(self, objects_rect):
        """
        Match new detections to existing tracks; assign new IDs where needed.

        Args:
            objects_rect: list of [x1, y1, x2, y2]

        Returns:
            list of [x1, y1, x2, y2, track_id]
        """
        objects_bbs_ids = []
        matched_ids     = set()

        for rect in objects_rect:
            x1, y1, x2, y2 = rect
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2

            best_id   = None
            best_dist = float('inf')

            for tid, pt in self.center_points.items():
                dist = math.hypot(cx - pt[0], cy - pt[1])
                if dist < self.max_dist and dist < best_dist:
                    best_dist = dist
                    best_id   = tid

            if best_id is not None:
                self.center_points[best_id] = (cx, cy)
                self.lost_count[best_id]    = 0
                objects_bbs_ids.append([x1, y1, x2, y2, best_id])
                matched_ids.add(best_id)
            else:
                # New object — assign fresh ID
                self.center_points[self.id_count] = (cx, cy)
                self.lost_count[self.id_count]    = 0
                objects_bbs_ids.append([x1, y1, x2, y2, self.id_count])
                matched_ids.add(self.id_count)
                self.id_count += 1

        # Increment lost counter for unmatched tracks; remove stale ones
        stale = []
        for tid in list(self.center_points):
            if tid not in matched_ids:
                self.lost_count[tid] = self.lost_count.get(tid, 0) + 1
                if self.lost_count[tid] > self.max_lost:
                    stale.append(tid)

        for tid in stale:
            del self.center_points[tid]
            del self.lost_count[tid]

        return objects_bbs_ids