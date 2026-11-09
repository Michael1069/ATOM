/// A telemetry value that distinguishes a true zero from unavailable data.
class TelemetryValue<T> {
  const TelemetryValue.available(this.value) : isAvailable = true;

  const TelemetryValue.unavailable() : value = null, isAvailable = false;

  final T? value;
  final bool isAvailable;
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
