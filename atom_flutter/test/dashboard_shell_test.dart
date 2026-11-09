import 'package:atom_flutter/dashboard.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('shows a compact 3 by 3 grid with unavailable zones', (
    WidgetTester tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(1440, 900));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      const MaterialApp(home: DashboardPage(listenToFirebase: false)),
    );

    expect(find.text('Occupancy map'), findsOneWidget);
    expect(find.text('Zone 1'), findsOneWidget);
    expect(find.text('Zone 9'), findsOneWidget);
    expect(find.text('N/A'), findsWidgets);
    expect(find.text('No occupancy readings received'), findsOneWidget);
  });

  testWidgets('selects each requested dashboard destination', (
    WidgetTester tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(1440, 900));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      const MaterialApp(home: DashboardPage(listenToFirebase: false)),
    );

    for (final destination in <String>[
      'Classroom Monitoring',
      'Appliance Controls',
      'Automation Rules',
      'Energy Analytics',
      'Activity Logs',
      'Settings',
      'Overview',
    ]) {
      await tester.tap(find.text(destination).first);
      await tester.pumpAndSettle();
      expect(find.text(destination).last, findsOneWidget);
    }
  });
}
