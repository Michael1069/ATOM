import unittest
import os


class OccupancyMappingTests(unittest.TestCase):
    def test_calibrated_polygons_assign_people_to_actual_classroom_seating_areas(self):
        from occupancy_detector import ClassroomZoneCalibration, Detection, frame_to_occupancy

        calibration = ClassroomZoneCalibration.for_uploaded_classroom_demo()
        detections = [
            Detection(class_id=0, confidence=0.9, x1=80, y1=70, x2=130, y2=135),
            Detection(class_id=0, confidence=0.9, x1=310, y1=170, x2=360, y2=250),
            Detection(class_id=0, confidence=0.9, x1=590, y1=240, x2=650, y2=360),
        ]

        counts = frame_to_occupancy(
            detections, 718, 404, calibration=calibration
        )

        self.assertEqual(counts["zone1"], 1)
        self.assertEqual(counts["zone5"], 1)
        self.assertEqual(counts["zone9"], 1)
        self.assertEqual(sum(counts.values()), 3)

    def test_calibrated_polygons_do_not_treat_whiteboard_or_aisles_as_occupied_zones(self):
        from occupancy_detector import ClassroomZoneCalibration, Detection, frame_to_occupancy

        calibration = ClassroomZoneCalibration.for_uploaded_classroom_demo()
        detections = [
            Detection(class_id=0, confidence=0.9, x1=320, y1=20, x2=360, y2=80),
            Detection(class_id=0, confidence=0.9, x1=230, y1=180, x2=260, y2=250),
        ]

        counts = frame_to_occupancy(
            detections, 718, 404, calibration=calibration
        )

        self.assertEqual(sum(counts.values()), 0)
    def test_default_model_is_kept_with_the_backend(self):
        from camera_service import DEFAULT_MODEL

        self.assertEqual(os.path.dirname(DEFAULT_MODEL), os.path.dirname(__file__))
        self.assertEqual(os.path.basename(DEFAULT_MODEL), "yolo26n.pt")

    def test_zone_for_point_uses_bottom_center_and_covers_all_nine_zones(self):
        from occupancy_detector import zone_for_point

        self.assertEqual(zone_for_point(0, 0, 300, 300), "zone1")
        self.assertEqual(zone_for_point(299, 0, 300, 300), "zone3")
        self.assertEqual(zone_for_point(0, 299, 300, 300), "zone7")
        self.assertEqual(zone_for_point(299, 299, 300, 300), "zone9")


    def test_frame_to_occupancy_counts_only_people_by_bottom_center(self):
        from occupancy_detector import Detection, frame_to_occupancy

        detections = [
            Detection(class_id=0, confidence=0.9, x1=0, y1=0, x2=90, y2=90),
            Detection(class_id=0, confidence=0.8, x1=110, y1=20, x2=190, y2=170),
            Detection(class_id=2, confidence=0.99, x1=210, y1=210, x2=290, y2=290),
        ]

        counts = frame_to_occupancy(detections, frame_width=300, frame_height=300)

        self.assertEqual(counts, {
            "zone1": 1,
            "zone2": 0,
            "zone3": 0,
            "zone4": 0,
            "zone5": 1,
            "zone6": 0,
            "zone7": 0,
            "zone8": 0,
            "zone9": 0,
        })

    def test_uncalibrated_camera_reports_people_to_zone1_only(self):
        from occupancy_detector import Detection, frame_to_zone1_occupancy

        counts = frame_to_zone1_occupancy([
            Detection(class_id=0, confidence=.9, x1=0, y1=0, x2=20, y2=20),
            Detection(class_id=0, confidence=.9, x1=80, y1=80, x2=100, y2=100),
            Detection(class_id=2, confidence=.9, x1=20, y1=20, x2=40, y2=40),
        ])

        self.assertEqual(counts, {'zone1': 2})

    def test_observation_update_keeps_dashboard_occupancy_numeric_and_marks_source(self):
        from occupancy_detector import build_observation_update

        update = build_observation_update(
            {f"zone{number}": 0 for number in range(1, 10)},
            source="webcam:0",
            detected_at="2026-11-09T10:00:00+00:00",
        )

        self.assertEqual(set(update["occupancy"]), {f"zone{number}" for number in range(1, 10)})
        self.assertTrue(all(isinstance(count, int) for count in update["occupancy"].values()))
        self.assertEqual(update["occupancy_status"]["status"], "live")
        self.assertEqual(update["occupancy_status"]["source"], "webcam:0")
        self.assertEqual(update["occupancy_status"]["total"], 0)

    def test_error_status_does_not_replace_last_real_occupancy(self):
        from camera_service import FirebaseOccupancyPublisher

        class FakeStatusReference:
            def __init__(self):
                self.value = None

            def set(self, value):
                self.value = value

            def update(self, value):
                self.value = {**(self.value or {}), **value}

        class FakeRootReference:
            def __init__(self):
                self.update_value = None
                self.status = FakeStatusReference()

            def update(self, value):
                self.update_value = value

            def child(self, name):
                self.assertEqual(name, "occupancy_status")
                return self.status

            def assertEqual(self, actual, expected):
                if actual != expected:
                    raise AssertionError(f"{actual!r} != {expected!r}")

        root = FakeRootReference()
        publisher = FirebaseOccupancyPublisher(root)

        publisher.publish_status(
            status="error",
            source="webcam:0",
            timestamp="2026-11-09T10:00:00+00:00",
            error="camera unavailable",
        )

        self.assertIsNone(root.update_value)
        self.assertEqual(root.status.value["status"], "error")
        self.assertEqual(root.status.value["error"], "camera unavailable")

    def test_completion_status_retains_latest_real_detection_metadata(self):
        from camera_service import FirebaseOccupancyPublisher

        class FakeStatusReference:
            def __init__(self):
                self.value = {
                    "detected_at": "2026-11-12T07:44:00+00:00",
                    "total": 9,
                }

            def update(self, value):
                self.value.update(value)

        class FakeRootReference:
            def __init__(self):
                self.status = FakeStatusReference()

            def child(self, name):
                if name != "occupancy_status":
                    raise AssertionError(name)
                return self.status

        root = FakeRootReference()
        FirebaseOccupancyPublisher(root).publish_status(
            status="completed",
            source="uploaded:classroom_demo.mp4",
            timestamp="2026-11-12T07:45:00+00:00",
        )

        self.assertEqual(root.status.value["status"], "completed")
        self.assertEqual(root.status.value["total"], 9)
        self.assertEqual(root.status.value["detected_at"], "2026-11-12T07:44:00+00:00")
