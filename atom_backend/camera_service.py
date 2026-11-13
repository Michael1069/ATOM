"""On-demand YOLO camera worker for ATOM occupancy telemetry.

Heavy camera and model imports intentionally occur only inside the worker.  This
keeps the FastAPI command service available when a camera or YOLO is absent.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from occupancy_detector import (
    ClassroomZoneCalibration,
    Detection,
    build_observation_update,
    frame_to_occupancy,
    frame_to_zone1_occupancy,
)


DEFAULT_MODEL = os.path.join(os.path.dirname(__file__), "yolo26n.pt")
LOCAL_VIDEO_ANALYSIS_FPS = 3


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_source(value: str | int) -> str | int:
    """Convert webcam indexes to integers while preserving file paths and URLs."""
    if isinstance(value, int):
        return value
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("a webcam index, local video path, or MJPEG URL is required")
    return int(cleaned) if cleaned.isdecimal() else cleaned


def source_label(source: str | int) -> str:
    return f"webcam:{source}" if isinstance(source, int) else str(source)


def frame_stride_for_source(source: str | int, source_fps: float) -> int:
    """Sample uploaded files at three real inferences per second of video.

    Cameras and network streams are never skipped. This keeps a short 30 FPS
    demo from taking several minutes while every published count still comes
    from an actual YOLO inference rather than interpolation.
    """
    if not isinstance(source, str) or source.lower().startswith(("http://", "https://", "rtsp://")):
        return 1
    return max(1, round(max(source_fps, 1) / LOCAL_VIDEO_ANALYSIS_FPS))


class FirebaseOccupancyPublisher:
    """Writes only ATOM/classroom1's dedicated occupancy nodes."""

    def __init__(self, classroom_reference: Any):
        self._root = classroom_reference
        self._observation_handler: Any | None = None
        self._session_root: Any | None = None

    def set_session_root(self, session_root: Any | None) -> None:
        self._session_root = session_root

    def set_observation_handler(self, handler: Any) -> None:
        self._observation_handler = handler

    def publish_observation(
        self,
        counts: dict[str, int],
        source: str,
        timestamp: str,
        *,
        model: str,
        calibration: str | None,
    ) -> None:
        self._root.update(
            build_observation_update(
                counts,
                source=source,
                detected_at=timestamp,
                model=model,
                calibration=calibration,
            )
        )
        if self._session_root is not None:
            self._session_root.update(
                build_observation_update(
                    counts, source=source, detected_at=timestamp,
                    model=model, calibration=calibration,
                )
            )
        if self._observation_handler is not None:
            self._observation_handler(counts, timestamp)

    def publish_status(
        self,
        *,
        status: str,
        source: str,
        timestamp: str,
        error: str | None = None,
        **details: object,
    ) -> None:
        payload: dict[str, object] = {
            "status": status,
            "source": source,
            "updated_at": timestamp,
        }
        if error:
            payload["error"] = error
        payload.update(details)
        # Do not write the occupancy node for lifecycle or error events. Merge
        # lifecycle information so a completed/stopped status retains the last
        # genuine detection's source, timestamp, total, and zone metadata.
        self._root.child("occupancy_status").update(payload)
        if self._session_root is not None:
            self._session_root.child("occupancy_status").update(payload)


class CameraService:
    """Single-worker camera service. It is manually started and stopped by API."""

    def __init__(self, publisher: FirebaseOccupancyPublisher):
        self._publisher = publisher
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture: Any | None = None
        self._status = "stopped"
        self._source: str | int | None = None
        self._display_source: str | None = None
        self._model_name: str | None = None
        self._calibration_name: str | None = None
        self._last_error: str | None = None
        self._last_jpeg: bytes | None = None
        self._frames_processed = 0

    def set_session_root(self, session_root: Any | None) -> None:
        """Route new worker output to the active browser demo session."""
        self._publisher.set_session_root(session_root)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self._status,
                "source": self._display_source,
                "last_error": self._last_error,
                "running": bool(self._thread and self._thread.is_alive()),
                "model": self._model_name,
                "calibration": self._calibration_name,
                "frames_processed": self._frames_processed,
                "has_annotated_frame": self._last_jpeg is not None,
            }

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._last_jpeg

    def set_observation_handler(self, handler: Any) -> None:
        self._publisher.set_observation_handler(handler)

    def start(
        self,
        source: str | int,
        model_name: str = DEFAULT_MODEL,
        confidence: float = 0.35,
        *,
        display_source: str | None = None,
        calibration: ClassroomZoneCalibration | None = None,
    ) -> dict[str, Any]:
        normalized_source = normalize_source(source)
        if not 0 < confidence <= 1:
            raise ValueError("confidence must be greater than 0 and no more than 1")
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("detection is already running; stop it before changing source")
            self._stop_event.clear()
            self._status = "starting"
            self._source = normalized_source
            self._display_source = display_source or source_label(normalized_source)
            self._model_name = Path(model_name).name
            self._calibration_name = calibration.name if calibration else None
            self._last_error = None
            self._last_jpeg = None
            self._frames_processed = 0
            self._thread = threading.Thread(
                target=self._run,
                args=(normalized_source, model_name, confidence, calibration),
                name="atom-yolo-camera",
                daemon=True,
            )
            self._thread.start()
        self._publisher.publish_status(
            status="starting",
            source=self._display_source,
            timestamp=utc_now(),
            model=self._model_name,
            calibration=self._calibration_name,
        )
        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        with self._lock:
            capture = self._capture
        if capture is not None:
            capture.release()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3)
        with self._lock:
            self._capture = None
            self._status = "stopped"
            # A new session must not render a frame produced for the previous
            # source while it is waiting for an explicitly started source.
            self._last_jpeg = None
        source = self._display_source or "not-configured"
        self._publisher.publish_status(status="stopped", source=source, timestamp=utc_now())
        return self.snapshot()

    def _run(
        self,
        source: str | int,
        model_name: str,
        confidence: float,
        calibration: ClassroomZoneCalibration | None,
    ) -> None:
        label = self._display_source or source_label(source)
        model_label = Path(model_name).name
        capture: Any | None = None
        try:
            # Keep Ultralytics settings and model cache with this backend rather
            # than relying on a writable user-profile directory.
            os.environ.setdefault("YOLO_CONFIG_DIR", os.path.join(os.path.dirname(__file__), ".ultralytics"))
            import cv2
            from ultralytics import YOLO

            model = YOLO(model_name)
            capture = cv2.VideoCapture(source)
            if not capture.isOpened():
                raise RuntimeError("could not open video source")
            with self._lock:
                self._capture = capture
                self._status = "running"
            self._publisher.publish_status(
                status="running",
                source=label,
                timestamp=utc_now(),
                model=model_label,
                calibration=calibration.name if calibration else None,
            )

            stride = frame_stride_for_source(source, capture.get(cv2.CAP_PROP_FPS))
            frame_number = 0

            while not self._stop_event.is_set():
                ok, frame = capture.read()
                if not ok or frame is None:
                    if isinstance(source, str) and not source.lower().startswith(("http://", "https://", "rtsp://")):
                        with self._lock:
                            self._status = "completed"
                        self._publisher.publish_status(
                            status="completed",
                            source=label,
                            timestamp=utc_now(),
                            model=model_label,
                            calibration=calibration.name if calibration else None,
                            frames_processed=self._frames_processed,
                        )
                        break
                    raise RuntimeError("video source stopped producing frames")
                frame_number += 1
                if frame_number % stride:
                    continue
                height, width = frame.shape[:2]
                results = model.predict(frame, classes=[0], conf=confidence, verbose=False)
                detections = self._detections_from_result(results[0])
                counts = (
                    frame_to_occupancy(detections, width, height, calibration=calibration)
                    if calibration is not None
                    else frame_to_zone1_occupancy(detections)
                )
                annotated = self._annotate_frame(frame, detections, counts, calibration)
                encoded, jpeg = cv2.imencode(".jpg", annotated)
                if not encoded:
                    raise RuntimeError("could not encode annotated frame")
                timestamp = utc_now()
                with self._lock:
                    self._last_jpeg = jpeg.tobytes()
                    self._frames_processed += 1
                # A zero count is published only after this real frame completed inference.
                self._publisher.publish_observation(
                    counts,
                    label,
                    timestamp,
                    model=model_label,
                    calibration=calibration.name if calibration else None,
                )
        except Exception as exc:
            if not self._stop_event.is_set():
                message = str(exc)
                with self._lock:
                    self._status = "error"
                    self._last_error = message
                self._publisher.publish_status(
                    status="error", source=label, timestamp=utc_now(), error=message
                )
        finally:
            if capture is not None:
                capture.release()
            with self._lock:
                self._capture = None
                if self._status == "running":
                    self._status = "stopped"

    @staticmethod
    def _annotate_frame(
        frame: Any,
        detections: list[Detection],
        counts: dict[str, int],
        calibration: ClassroomZoneCalibration | None,
    ) -> Any:
        """Overlay real detector boxes and the active occupancy map for viewing."""
        import cv2

        annotated = frame.copy()
        height, width = annotated.shape[:2]
        if calibration:
            for zone, points in calibration.pixels_for_frame(width, height).items():
                contour = __import__("numpy").array(points, dtype="int32")
                cv2.polylines(annotated, [contour], True, (0, 215, 255), 1)
                x, y = points[0]
                cv2.putText(
                    annotated,
                    f"{zone.upper()}: {counts[zone]}",
                    (x + 3, y + 16),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,
                    (0, 215, 255),
                    1,
                    cv2.LINE_AA,
                )
        for detection in detections:
            x1, y1, x2, y2 = (round(value) for value in (detection.x1, detection.y1, detection.x2, detection.y2))
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (68, 209, 154), 2)
            cv2.putText(
                annotated,
                f"person {detection.confidence:.2f}",
                (x1, max(18, y1 - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (68, 209, 154),
                1,
                cv2.LINE_AA,
            )
        return annotated

    @staticmethod
    def _detections_from_result(result: Any) -> list[Detection]:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []
        detections: list[Detection] = []
        for box in boxes:
            x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
            detections.append(
                Detection(
                    class_id=int(box.cls[0].item()),
                    confidence=float(box.conf[0].item()),
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                )
            )
        return detections
