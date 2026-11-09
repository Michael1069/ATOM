"""Pure helpers for mapping YOLO detections to the dashboard's 3x3 zones."""

from dataclasses import dataclass
from typing import Iterable


PERSON_CLASS_ID = 0  # COCO's person class.
ZONE_NAMES = tuple(f"zone{number}" for number in range(1, 10))


@dataclass(frozen=True)
class Detection:
    class_id: int
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def bottom_center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, self.y2)


def zone_for_point(x: float, y: float, frame_width: int, frame_height: int) -> str:
    """Return the row-major 3x3 zone for a point, clamped to the frame."""
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("frame dimensions must be positive")

    x = min(max(x, 0), frame_width - 1)
    y = min(max(y, 0), frame_height - 1)
    column = min(2, int(x * 3 / frame_width))
    row = min(2, int(y * 3 / frame_height))
    return f"zone{row * 3 + column + 1}"


def empty_zone_counts() -> dict[str, int]:
    return {zone: 0 for zone in ZONE_NAMES}


def frame_to_occupancy(
    detections: Iterable[Detection], frame_width: int, frame_height: int
) -> dict[str, int]:
    """Count only COCO person detections using each bounding box's bottom center."""
    counts = empty_zone_counts()
    for detection in detections:
        if detection.class_id != PERSON_CLASS_ID:
            continue
        x, y = detection.bottom_center
        counts[zone_for_point(x, y, frame_width, frame_height)] += 1
    return counts


def build_observation_update(
    counts: dict[str, int], *, source: str, detected_at: str
) -> dict[str, dict[str, object]]:
    """Build the isolated Firebase update used only after a frame was analysed."""
    normalized_counts = {zone: int(counts.get(zone, 0)) for zone in ZONE_NAMES}
    return {
        # Flutter reads this node as a map of numeric `zone1`...`zone9` values.
        "occupancy": normalized_counts,
        # Metadata is intentionally separate so it cannot be mistaken for a zone count.
        "occupancy_status": {
            "status": "live",
            "source": source,
            "detected_at": detected_at,
            "total": sum(normalized_counts.values()),
        },
    }
