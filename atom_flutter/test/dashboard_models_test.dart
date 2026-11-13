import 'package:atom_flutter/dashboard_models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('classroom telemetry parsing', () {
    test('keeps unknown zones unavailable instead of inventing a zero', () {
      final occupancy = parseOccupancy(<Object?, Object?>{
        'zone1': 3,
        'zone3': '2',
      });

      expect(occupancy['zone1'], 3);
      expect(occupancy['zone3'], 2);
      expect(occupancy.containsKey('zone2'), isFalse);
    });

    test('ignores malformed occupancy values', () {
      final occupancy = parseOccupancy(<Object?, Object?>{
        'zone1': 'not-a-number',
        'zone2': null,
      });

      expect(occupancy, isEmpty);
    });

    test('marks a missing energy reading as unavailable', () {
      expect(parseEnergy(null).isAvailable, isFalse);
      expect(parseEnergy('1.75').value, 1.75);
    });

    test('includes the acknowledged current ON interval in modeled energy', () {
      final wh = modeledEnergyWh(
        <String, Object?>{
          'rated_watts': 5,
          'cumulative_on_seconds': 10,
          'reported_state': 'on',
          'on_since': '2026-11-12T17:00:00Z',
        },
        DateTime.utc(2026, 11, 12, 17, 1),
      );

      expect(wh, closeTo(5 * 70 / 3600, 0.000001));
    });

    test('uses an automation model interval when hardware acknowledgement is unavailable', () {
      final wh = modeledEnergyWh(
        <String, Object?>{
          'rated_watts': 5,
          'cumulative_on_seconds': 0,
          'modeled_state': 'on',
          'modeled_on_since': '2026-11-12T17:00:00Z',
        },
        DateTime.utc(2026, 11, 12, 17, 1),
      );

      expect(wh, closeTo(5 * 60 / 3600, 0.000001));
    });

    test('reports the live modeled run duration to the second', () {
      final seconds = modeledRunSeconds(
        <String, Object?>{
          'modeled_cumulative_on_seconds': 4,
          'modeled_state': 'on',
          'modeled_on_since': '2026-11-12T17:00:00Z',
        },
        DateTime.utc(2026, 11, 12, 17, 1),
      );

      expect(seconds, 64);
    });

    test('parses a backend session snapshot for dashboard fallback', () {
      final snapshot = parseDemoSessionSnapshot(<String, Object?>{
        'occupancy': <String, Object?>{'zone1': 2},
        'occupancy_status': <String, Object?>{'status': 'live'},
        'energy': <String, Object?>{
          'led1': <String, Object?>{'rated_watts': 5},
        },
        'activity_logs': <String, Object?>{
          'event-1': <String, Object?>{'kind': 'detection_started'},
        },
      });

      expect(snapshot.zones, <String, int>{'zone1': 2});
      expect(snapshot.status['status'], 'live');
      expect(snapshot.energy['rated_watts'], 5);
      expect(snapshot.logs.single['kind'], 'detection_started');
    });
  });
}
