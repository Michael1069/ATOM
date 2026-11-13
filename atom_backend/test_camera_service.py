import unittest


class RecordingReference:
    def __init__(self):
        self.values = {}

    def child(self, name):
        return _ChildReference(self, name)

    def update(self, value):
        self.values.update(value)


class _ChildReference:
    def __init__(self, parent, name):
        self._parent = parent
        self._name = name

    def update(self, value):
        current = self._parent.values.setdefault(self._name, {})
        current.update(value)


class VideoPacingTests(unittest.TestCase):
    def test_local_video_is_sampled_at_a_demo_friendly_rate(self):
        from camera_service import frame_stride_for_source

        self.assertEqual(frame_stride_for_source('classroom_demo.mp4', 30), 10)
        self.assertEqual(frame_stride_for_source(0, 30), 1)
        self.assertEqual(frame_stride_for_source('http://camera/stream', 30), 1)


class SessionStatusPublishingTests(unittest.TestCase):
    def test_status_is_written_to_the_active_demo_session(self):
        from camera_service import FirebaseOccupancyPublisher

        root = RecordingReference()
        session = RecordingReference()
        publisher = FirebaseOccupancyPublisher(root)
        publisher.set_session_root(session)

        publisher.publish_status(
            status='running',
            source='uploaded:classroom.mp4',
            timestamp='2026-11-12T00:00:00+00:00',
        )

        self.assertEqual(session.values['occupancy_status']['status'], 'running')
        self.assertEqual(session.values['occupancy_status']['source'], 'uploaded:classroom.mp4')


class CameraStopTests(unittest.TestCase):
    def test_stop_discards_the_previous_session_preview(self):
        from camera_service import CameraService, FirebaseOccupancyPublisher

        service = CameraService(FirebaseOccupancyPublisher(RecordingReference()))
        service._last_jpeg = b'old annotated frame'

        service.stop()

        self.assertIsNone(service.latest_jpeg())
