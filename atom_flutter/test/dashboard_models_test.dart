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
  });
}
