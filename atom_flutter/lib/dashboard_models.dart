/// A telemetry value that distinguishes a true zero from unavailable data.
class TelemetryValue<T> {
  const TelemetryValue.available(this.value) : isAvailable = true;

  const TelemetryValue.unavailable() : value = null, isAvailable = false;

  final T? value;
  final bool isAvailable;
}

class DemoSessionSnapshot {
  const DemoSessionSnapshot({
    required this.zones,
    required this.status,
    required this.energy,
    required this.logs,
  });

  final Map<String, int> zones;
  final Map<String, Object?> status;
  final Map<String, Object?> energy;
  final List<Map<String, Object?>> logs;
}

Map<String, Object?> _asStringMap(Object? value) {
  if (value is! Map) return <String, Object?>{};
  return <String, Object?>{
    for (final entry in value.entries) entry.key.toString(): entry.value,
  };
}

DemoSessionSnapshot parseDemoSessionSnapshot(Object? raw) {
  final session = _asStringMap(raw);
  final energyRoot = _asStringMap(session['energy']);
  final logRoot = _asStringMap(session['activity_logs']);
  return DemoSessionSnapshot(
    zones: parseOccupancy(session['occupancy']),
    status: _asStringMap(session['occupancy_status']),
    energy: _asStringMap(energyRoot['led1']),
    logs: logRoot.values
        .whereType<Map>()
        .map(_asStringMap)
        .toList(),
  );
}

Map<String, int> parseOccupancy(Object? raw) {
  if (raw is! Map) {
    return <String, int>{};
  }

  final zones = <String, int>{};
  raw.forEach((key, value) {
    final parsed = value is int ? value : int.tryParse(value?.toString() ?? '');
    if (parsed != null) {
      zones[key.toString()] = parsed;
    }
  });
  return zones;
}

TelemetryValue<double> parseEnergy(Object? raw) {
  if (raw == null) {
    return const TelemetryValue<double>.unavailable();
  }
  final value = raw is num ? raw.toDouble() : double.tryParse(raw.toString());
  return value == null
      ? const TelemetryValue<double>.unavailable()
      : TelemetryValue<double>.available(value);
}

/// Computes modeled LED energy from acknowledged state timestamps only.
/// The current ON interval is included without writing speculative readings.
double? modeledEnergyWh(Map<String, Object?> model, DateTime now) {
  final watts = model['rated_watts'] is num
      ? (model['rated_watts'] as num).toDouble()
      : double.tryParse(model['rated_watts']?.toString() ?? '');
  if (watts == null || watts <= 0) return null;

  final usingAutomationModel = model.containsKey('modeled_state');
  final cumulativeKey = usingAutomationModel
      ? 'modeled_cumulative_on_seconds'
      : 'cumulative_on_seconds';
  final stateKey = usingAutomationModel ? 'modeled_state' : 'reported_state';
  final onSinceKey = usingAutomationModel ? 'modeled_on_since' : 'on_since';
  var onSeconds = model[cumulativeKey] is num
      ? (model[cumulativeKey] as num).toDouble()
      : double.tryParse(model[cumulativeKey]?.toString() ?? '') ?? 0;
  if (model[stateKey] == 'on' && model[onSinceKey] is String) {
    final onSince = DateTime.tryParse(model[onSinceKey] as String);
    if (onSince != null) {
      onSeconds += now.toUtc().difference(onSince.toUtc()).inMilliseconds.clamp(0, 1 << 53) / 1000;
    }
  }
  return watts * onSeconds / 3600;
}

int modeledRunSeconds(Map<String, Object?> model, DateTime now) {
  final usingAutomationModel = model.containsKey('modeled_state');
  final cumulativeKey = usingAutomationModel
      ? 'modeled_cumulative_on_seconds'
      : 'cumulative_on_seconds';
  final stateKey = usingAutomationModel ? 'modeled_state' : 'reported_state';
  final onSinceKey = usingAutomationModel ? 'modeled_on_since' : 'on_since';
  var seconds = model[cumulativeKey] is num
      ? (model[cumulativeKey] as num).toInt()
      : int.tryParse(model[cumulativeKey]?.toString() ?? '') ?? 0;
  if (model[stateKey] == 'on' && model[onSinceKey] is String) {
    final onSince = DateTime.tryParse(model[onSinceKey] as String);
    if (onSince != null) {
      seconds += now.toUtc().difference(onSince.toUtc()).inSeconds.clamp(0, 1 << 53);
    }
  }
  return seconds;
}
