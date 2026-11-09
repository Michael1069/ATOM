import unittest
import os


class OccupancyMappingTests(unittest.TestCase):
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
