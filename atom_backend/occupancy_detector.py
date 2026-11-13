"""Pure helpers for mapping YOLO detections to the dashboard's 3x3 zones."""

from dataclasses import dataclass
from typing import Iterable, Mapping


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


NormalizedPoint = tuple[float, float]


@dataclass(frozen=True)
class ClassroomZoneCalibration:
    """Perspective-aware seating polygons for a known fixed classroom view.

    Points are stored as fractions of frame width and height so the map stays
    valid if an uploaded MP4 is decoded at a different resolution. Areas not
    covered by a polygon are board, walkways, or non-seating foreground and do
    not contribute to occupancy.
    """

    name: str
    polygons: Mapping[str, tuple[NormalizedPoint, ...]]

    @classmethod
    def for_uploaded_classroom_demo(cls) -> "ClassroomZoneCalibration":
        # Calibrated against "WhatsApp Video 2026-11-12 at 12.48.25 PM.mp4"
        # (718x404): three desk columns, with perspective-adjusted front,
        # middle, and rear seating bands. These are deliberately not screen
        # thirds; the gaps preserve the two aisles and whiteboard foreground.
        return cls(
            name="classroom_demo_perspective_v1",
            polygons={
                "zone1": ((.05, .19), (.33, .19), (.32, .37), (.08, .37)),
                "zone2": ((.39, .28), (.63, .28), (.64, .47), (.36, .47)),
                "zone3": ((.70, .27), (.99, .27), (1.0, .47), (.67, .47)),
                "zone4": ((.06, .37), (.32, .37), (.31, .63), (0.0, .63)),
                "zone5": ((.36, .47), (.64, .47), (.67, .71), (.34, .71)),
                "zone6": ((.67, .47), (1.0, .47), (1.0, .71), (.66, .71)),
                "zone7": ((0.0, .63), (.31, .63), (.30, 1.0), (0.0, 1.0)),
                "zone8": ((.34, .71), (.67, .71), (.70, 1.0), (.30, 1.0)),
                "zone9": ((.66, .71), (1.0, .71), (1.0, 1.0), (.70, 1.0)),
            },
        )

    def zone_for_point(self, x: float, y: float, frame_width: int, frame_height: int) -> str | None:
        if frame_width <= 0 or frame_height <= 0:
            raise ValueError("frame dimensions must be positive")
        point = (x / frame_width, y / frame_height)
        for zone in ZONE_NAMES:
            polygon = self.polygons.get(zone)
            if polygon and _point_in_polygon(point, polygon):
                return zone
        return None

    def pixels_for_frame(self, frame_width: int, frame_height: int) -> dict[str, list[tuple[int, int]]]:
        return {
            zone: [
                (round(x * frame_width), round(y * frame_height))
                for x, y in polygon
            ]
            for zone, polygon in self.polygons.items()
        }


def _point_in_polygon(point: NormalizedPoint, polygon: tuple[NormalizedPoint, ...]) -> bool:
    """Return whether a point is inside a polygon, including its boundary."""
    x, y = point
    inside = False
    previous_x, previous_y = polygon[-1]
    for current_x, current_y in polygon:
        if _point_on_segment(x, y, previous_x, previous_y, current_x, current_y):
            return True
        crosses = (current_y > y) != (previous_y > y)
        if crosses:
            intersection_x = (previous_x - current_x) * (y - current_y) / (previous_y - current_y) + current_x
            if x < intersection_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


def _point_on_segment(x: float, y: float, x1: float, y1: float, x2: float, y2: float) -> bool:
    cross_product = (y - y1) * (x2 - x1) - (x - x1) * (y2 - y1)
    if abs(cross_product) > 1e-9:
        return False
    return min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2)


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
    detections: Iterable[Detection],
    frame_width: int,
    frame_height: int,
    calibration: ClassroomZoneCalibration | None = None,
) -> dict[str, int]:
    """Count only COCO people using a calibrated seating map when supplied."""
    counts = empty_zone_counts()
    for detection in detections:
        if detection.class_id != PERSON_CLASS_ID:
            continue
        x, y = detection.bottom_center
        zone = (
            calibration.zone_for_point(x, y, frame_width, frame_height)
            if calibration
            else zone_for_point(x, y, frame_width, frame_height)
        )
        if zone is not None:
            counts[zone] += 1
    return counts


def frame_to_zone1_occupancy(detections: Iterable[Detection]) -> dict[str, int]:
    """Map an uncalibrated single camera to the sole physical LED zone."""
    return {
        "zone1": sum(1 for detection in detections if detection.class_id == PERSON_CLASS_ID)
    }


def build_observation_update(
    counts: dict[str, int],
    *,
    source: str,
    detected_at: str,
    model: str | None = None,
    calibration: str | None = None,
) -> dict[str, dict[str, object]]:
    """Build the isolated Firebase update used only after a frame was analysed."""
    # A calibrated classroom source reports all nine zones. An uncalibrated
    # laptop or future ESP32 camera reports only Zone 1 instead of inventing
    # occupancy for areas it cannot be calibrated to see.
    normalized_counts = {
        zone: int(count)
        for zone, count in counts.items()
        if zone in ZONE_NAMES
    }
    status: dict[str, object] = {
        "status": "live",
        "source": source,
        "detected_at": detected_at,
        "timestamp": detected_at,
        "total": sum(normalized_counts.values()),
    }
    if model:
        status["model"] = model
    if calibration:
        status["calibration"] = calibration
    return {
        # Flutter reads this node as a map of numeric `zone1`...`zone9` values.
        "occupancy": normalized_counts,
        # Metadata is intentionally separate so it cannot be mistaken for a zone count.
        "occupancy_status": status,
        # This is an explicitly virtual display state. It never targets MQTT,
        # relays, or mains-powered appliances.
        "virtual_zone_lights": {
            zone: {"state": "on" if count > 0 else "off", "virtual": True}
            for zone, count in normalized_counts.items()
        },
    }
