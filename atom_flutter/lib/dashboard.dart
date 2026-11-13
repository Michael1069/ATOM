// ATOM classroom operations dashboard. The Firebase and FastAPI contracts
// deliberately remain behind this presentation shell.
import 'dart:async';
import 'dart:convert';

import 'package:firebase_database/firebase_database.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'dashboard_models.dart';
import 'video_upload_picker.dart';

const _canvas = Color(0xFF06111F);
const _sidebarColor = Color(0xFF081827);
const _surface = Color(0xFF0D2133);
const _raised = Color(0xFF112A3E);
const _line = Color(0xFF1D3A50);
const _ink = Color(0xFFE6F4F7);
const _muted = Color(0xFF92ABB9);
const _cyan = Color(0xFF24D5E8);
const _cyanDim = Color(0xFF0B6575);
const _good = Color(0xFF45D19A);
const _warning = Color(0xFFF5B84A);
const _backendBase = 'http://127.0.0.1:8000';
const _apiKey = String.fromEnvironment('ATOM_API_KEY');

Map<String, String> _apiHeaders({bool json = false}) => <String, String>{
  if (json) 'Content-Type': 'application/json',
  if (_apiKey.isNotEmpty) 'x-api-key': _apiKey,
};

const _modeLabels = <String, String>{
  'automatic': 'Automatic',
  'human_override': 'Human Override',
  'hybrid': 'Hybrid',
};

enum DashboardNavigation {
  overview('Overview', Icons.grid_view_rounded),
  monitoring('Classroom Monitoring', Icons.sensors_rounded),
  appliances('Appliance Controls', Icons.tune_rounded),
  energy('Energy Analytics', Icons.bolt_rounded),
  logs('Activity Logs', Icons.receipt_long_rounded),
  settings('Settings', Icons.settings_outlined);

  const DashboardNavigation(this.label, this.icon);
  final String label;
  final IconData icon;
}

class DashboardPage extends StatefulWidget {
  const DashboardPage({this.listenToFirebase = true, super.key});
  final bool listenToFirebase;

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  DatabaseReference? _rootRef;
  final _zones = <String, int>{};
  final _appliances = <String, String>{};
  final _pending = <String, bool>{};
  final _desiredStates = <String, String>{};
  List<String> _logs = <String>[];
  int _totalCount = 0;
  String? _mode;
  TelemetryValue<double> _energy = const TelemetryValue<double>.unavailable();
  Map<String, Object?> _energyModel = <String, Object?>{};
  String _connection = 'Waiting for live data';
  String? _sessionId;
  DashboardNavigation _selected = DashboardNavigation.overview;
  StreamSubscription<DatabaseEvent>? _occupancySub;
  StreamSubscription<DatabaseEvent>? _applianceSub;
  StreamSubscription<DatabaseEvent>? _modeSub;
  StreamSubscription<DatabaseEvent>? _energySub;
  StreamSubscription<DatabaseEvent>? _logSub;
  StreamSubscription<DatabaseEvent>? _occupancyStatusSub;
  Map<String, Object?> _occupancyStatus = <String, Object?>{};
  String _selectedVideoSource = 'uploaded';
  String _cameraStatus = 'Not started';
  bool _cameraRequestInFlight = false;
  bool _sessionSnapshotInFlight = false;
  bool _uploadedReady = false;
  int _streamVersion = 0;
  late final Timer _previewTimer;
  final _ratedWattsController = TextEditingController();

  @override
  void initState() {
    super.initState();
    if (widget.listenToFirebase) {
      _startSession();
    }
    _previewTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      _refreshSessionSnapshot();
      if (mounted && (_cameraStatus == 'starting' || _cameraStatus == 'running' || _cameraStatus == 'live' || _cameraStatus == 'completed' || _energyModel['reported_state'] == 'on' || _energyModel['modeled_state'] == 'on')) {
        setState(() => _streamVersion++);
      }
    });
  }

  Future<void> _startSession() async {
    try {
      final response = await http.post(
        Uri.parse('$_backendBase/api/session/start'),
        headers: _apiHeaders(),
      );
      if (response.statusCode != 200) throw Exception(response.body);
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      if (!mounted) return;
      _sessionId = body['session_id'] as String;
      _rootRef = FirebaseDatabase.instance.ref('ATOM/classroom1/sessions/$_sessionId');
      setState(() {
        _zones.clear();
        _logs = <String>[];
        _energyModel = <String, Object?>{};
        _mode = 'automatic';
        _cameraStatus = 'Waiting for camera input';
        _uploadedReady = false;
        _connection = 'Session ready';
      });
      _listen();
    } catch (_) {
      if (mounted) setState(() => _connection = 'Could not start a new demo session');
    }
  }

  Map<String, String> _sessionHeaders({bool json = false}) => <String, String>{
    ..._apiHeaders(json: json),
    'x-atom-session-id': ?_sessionId,
  };

  double? get _modeledWh => modeledEnergyWh(_energyModel, DateTime.now().toUtc());

  int get _modeledRunSeconds => modeledRunSeconds(_energyModel, DateTime.now().toUtc());

  String get _modeledRunLabel {
    final total = _modeledRunSeconds;
    final minutes = total ~/ 60;
    final seconds = total % 60;
    return '${minutes.toString().padLeft(2, '0')}:${seconds.toString().padLeft(2, '0')} modeled LED-on time';
  }

  String _formatActivity(Map<String, Object?> event) {
    final when = DateTime.tryParse(event['at']?.toString() ?? '')?.toLocal();
    final time = when == null
        ? 'Just now'
        : '${when.hour.toString().padLeft(2, '0')}:${when.minute.toString().padLeft(2, '0')}:${when.second.toString().padLeft(2, '0')}';
    final state = event['state']?.toString().toUpperCase();
    final reason = event['reason']?.toString().replaceAll('_', ' ');
    final detail = reason == null || reason.isEmpty ? '' : ' — $reason';
    final message = switch (event['kind']) {
      'session_started' => 'New demo session ready',
      'video_uploaded' => 'Video uploaded',
      'detection_started' => 'Detection started',
      'detection_stopped' => 'Detection stopped',
      'mode_changed' => 'Operating mode changed to ${event['mode']?.toString().replaceAll('_', ' ')}',
      'led_command_requested' => 'LED 1 requested $state$detail',
      'device_state_reported' => 'LED 1 confirmed $state by ESP32',
      'energy_model_state' => 'Energy estimate is tracking LED $state$detail',
      'rated_watts_set' => 'LED 1 rated watts saved',
      _ => event['kind']?.toString().replaceAll('_', ' ') ?? 'System update',
    };
    return '$time  $message';
  }

  Future<void> _refreshSessionSnapshot() async {
    final sessionId = _sessionId;
    if (sessionId == null || _sessionSnapshotInFlight) return;
    _sessionSnapshotInFlight = true;
    try {
      final response = await http.get(
        Uri.parse('$_backendBase/api/session/$sessionId/snapshot'),
        headers: _sessionHeaders(),
      );
      if (response.statusCode != 200 || !mounted || sessionId != _sessionId) return;
      final snapshot = parseDemoSessionSnapshot(jsonDecode(response.body));
      final logs = snapshot.logs..sort(
        (a, b) => (b['at']?.toString() ?? '').compareTo(a['at']?.toString() ?? ''),
      );
      setState(() {
        _zones
          ..clear()
          ..addAll(snapshot.zones);
        _totalCount = _zones.values.fold(0, (sum, value) => sum + value);
        _occupancyStatus = snapshot.status;
        _energyModel = snapshot.energy;
        final ratedWatts = _energyModel['rated_watts'];
        if (ratedWatts != null) _ratedWattsController.text = ratedWatts.toString();
        _logs = logs.map((event) {
          final reason = event['reason'] ?? event['status'] ?? event['state'] ?? '';
          return '${event['at'] ?? ''} â€¢ ${event['kind'] ?? 'event'}${reason == '' ? '' : ' â€¢ $reason'}';
        }).toList();
        _logs = logs.map(_formatActivity).toList();
        if (snapshot.status['status'] != null) {
          _cameraStatus = snapshot.status['status'] == 'waiting_for_camera_input'
              ? 'Waiting for camera input'
              : snapshot.status['status'].toString();
        }
        if (snapshot.zones.isNotEmpty || logs.isNotEmpty || snapshot.energy.isNotEmpty) {
          _connection = 'Live data received';
        }
      });
    } catch (_) {
      // Firebase remains the preferred live feed; the fallback is best effort.
    } finally {
      _sessionSnapshotInFlight = false;
    }
  }

  @override
  void dispose() {
    _occupancySub?.cancel();
    _applianceSub?.cancel();
    _modeSub?.cancel();
    _energySub?.cancel();
    _logSub?.cancel();
    _occupancyStatusSub?.cancel();
    _previewTimer.cancel();
    _ratedWattsController.dispose();
    super.dispose();
  }

  void _listen() {
    _occupancySub = _rootRef!.child('occupancy').onValue.listen((event) {
      final zones = parseOccupancy(event.snapshot.value);
      if (!mounted) return;
      setState(() {
        _zones
          ..clear()
          ..addAll(zones);
        _totalCount = zones.values.fold(0, (sum, value) => sum + value);
        _connection = zones.isEmpty
            ? 'No occupancy readings received'
            : 'Live data received';
      });
    }, onError: (_) => _markUnavailable());
    // ESP32 state is physical classroom state and deliberately survives a
    // browser demo-session refresh.
    _applianceSub = FirebaseDatabase.instance.ref('ATOM/classroom1/appliances').onValue.listen((event) {
      final states = <String, String>{};
      final raw = event.snapshot.value;
      if (raw is Map) {
        raw.forEach((id, payload) {
          if (payload is Map && payload['state'] != null) {
            states[id.toString()] = payload['state'].toString();
          }
        });
      }
      if (!mounted) return;
      setState(() {
        _appliances
          ..clear()
          ..addAll(states);
        _pending.removeWhere(
          (id, isPending) => isPending && states[id] == _desiredStates[id],
        );
        if (states.isNotEmpty) _connection = 'Live data received';
      });
    }, onError: (_) => _markUnavailable());
    // Mode is a classroom-wide control, not a per-session telemetry value.
    _modeSub = FirebaseDatabase.instance.ref('ATOM/classroom1/mode').onValue.listen((event) {
      if (!mounted) return;
      setState(() {
        _mode = event.snapshot.value?.toString();
        if (_mode != null) _connection = 'Live data received';
      });
    }, onError: (_) => _markUnavailable());
    _energySub = _rootRef!.child('energy').onValue.listen((event) {
      if (!mounted) return;
      final raw = event.snapshot.value;
      final model = <String, Object?>{};
      if (raw is Map && raw['led1'] is Map) {
        (raw['led1'] as Map).forEach((key, value) => model[key.toString()] = value);
      }
      setState(() {
        _energy = parseEnergy(raw);
        _energyModel = model;
        final ratedWatts = model['rated_watts'];
        if (ratedWatts != null) _ratedWattsController.text = ratedWatts.toString();
        if (_energy.isAvailable || model.isNotEmpty) _connection = 'Live data received';
      });
    }, onError: (_) => _markUnavailable());
    _logSub = _rootRef!.child('activity_logs').onValue.listen((event) {
      final raw = event.snapshot.value;
      final events = raw is Map
          ? raw.values.whereType<Map>().map((item) => Map<String, Object?>.from(item)).toList()
          : <Map<String, Object?>>[];
      events.sort((a, b) => (b['at']?.toString() ?? '').compareTo(a['at']?.toString() ?? ''));
      final entries = events.map((event) {
        final reason = event['reason'] ?? event['status'] ?? event['state'] ?? '';
        return '${event['at'] ?? ''} • ${event['kind'] ?? 'event'}${reason == '' ? '' : ' • $reason'}';
      }).toList();
      final cleanEntries = entries.isEmpty ? <String>[] : events.map(_formatActivity).toList();
      if (!mounted) return;
      setState(() {
        _logs = cleanEntries;
        if (cleanEntries.isNotEmpty) _connection = 'Live data received';
      });
    }, onError: (_) => _markUnavailable());
    _occupancyStatusSub = _rootRef!.child('occupancy_status').onValue.listen((event) {
      final raw = event.snapshot.value;
      final status = <String, Object?>{};
      if (raw is Map) {
        raw.forEach((key, value) => status[key.toString()] = value);
      }
      if (!mounted) return;
      setState(() {
        _occupancyStatus = status;
        if (status['status'] != null) {
          _cameraStatus = status['status'] == 'waiting_for_camera_input'
              ? 'Waiting for camera input'
              : status['status'].toString();
          _connection = 'Live data received';
        }
      });
    }, onError: (_) => _markUnavailable());
  }

  void _markUnavailable() {
    if (mounted) setState(() => _connection = 'Live connection unavailable');
  }

  Future<void> _sendLedCommand(String id, bool turnOn) async {
    final requestedState = turnOn ? 'on' : 'off';
    setState(() {
      _pending[id] = true;
      _desiredStates[id] = requestedState;
    });
    try {
      final response = await http.post(
        Uri.parse('$_backendBase/api/command'),
        headers: _sessionHeaders(json: true),
        body: jsonEncode({'appliance_id': id, 'state': requestedState}),
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        _message('${turnOn ? 'Turn-on' : 'Turn-off'} request is pending ESP32 acknowledgement');
      } else {
        setState(() => _pending.remove(id));
        _message(
          'Command rejected (${response.statusCode}): ${response.body}',
        );
      }
    } catch (_) {
      if (mounted) setState(() => _pending.remove(id));
      if (mounted) _message('Command service is unavailable');
    }
  }

  Future<void> _setMode(String mode) async {
    try {
      final response = await http.post(
        Uri.parse('$_backendBase/mode'),
        headers: _sessionHeaders(json: true),
        body: jsonEncode({'mode': mode}),
      );
      if (response.statusCode != 200) throw Exception(response.body);
      if (mounted) setState(() => _mode = mode);
      _message('Mode set to ${_modeLabels[mode]}.');
    } catch (_) {
      if (mounted) _message('Could not update automation mode. Start Flutter with ATOM_API_KEY.');
    }
  }

  void _message(String text) {
    ScaffoldMessenger.of(context).hideCurrentSnackBar();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(text), behavior: SnackBarBehavior.floating),
    );
  }

  Future<void> _uploadAndStartVideo() async {
    final selection = await pickVideoForUpload();
    if (selection == null) {
      _message('Choose an MP4 video to upload.');
      return;
    }
    setState(() => _cameraRequestInFlight = true);
    try {
      final response = await http.post(
        Uri.parse('$_backendBase/api/camera/upload'),
        headers: {
          'Content-Type': 'video/mp4',
          ..._sessionHeaders(),
          'x-file-name': selection.name,
        },
        body: selection.bytes,
      );
      if (response.statusCode != 200) {
        throw Exception('Upload rejected (${response.statusCode})');
      }
      if (!mounted) return;
      final upload = jsonDecode(response.body) as Map<String, dynamic>;
      setState(() => _uploadedReady = true);
      _message('Uploaded ${upload['source']} (${upload['bytes']} bytes). Press Start to begin detection.');
    } catch (error) {
      if (mounted) _message('Could not upload the selected MP4: $error');
    } finally {
      if (mounted) setState(() => _cameraRequestInFlight = false);
    }
  }

  Future<void> _startCamera() async {
    if (_cameraRequestInFlight && _cameraStatus == 'starting') return;
    setState(() => _cameraRequestInFlight = true);
    try {
      final response = await http.post(
        Uri.parse('$_backendBase/api/camera/start'),
        headers: _sessionHeaders(json: true),
        body: jsonEncode({'source': _selectedVideoSource}),
      );
      if (response.statusCode != 200) {
        throw Exception('Start rejected (${response.statusCode})');
      }
      if (!mounted) return;
      setState(() {
        _cameraStatus = 'starting';
        _streamVersion++;
      });
    } catch (_) {
      if (mounted) _message('Detection could not start. Upload a video first.');
    } finally {
      if (mounted) setState(() => _cameraRequestInFlight = false);
    }
  }

  Future<void> _stopCamera() async {
    setState(() => _cameraRequestInFlight = true);
    try {
      final response = await http.post(
        Uri.parse('$_backendBase/api/camera/stop'),
        headers: _sessionHeaders(),
      );
      if (response.statusCode != 200) throw Exception('Stop rejected');
      if (mounted) setState(() => _cameraStatus = 'stopped');
    } catch (_) {
      if (mounted) _message('Detection service is unavailable.');
    } finally {
      if (mounted) setState(() => _cameraRequestInFlight = false);
    }
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final showRail = constraints.maxWidth >= 760;
      final extended = constraints.maxWidth >= 1160;
      final content = Container(
        color: _canvas,
        child: SafeArea(
          child: Padding(
            padding: EdgeInsets.fromLTRB(showRail ? 30 : 18, 22, 30, 30),
            child: _page(),
          ),
        ),
      );
      if (!showRail) {
        return Scaffold(
          backgroundColor: _canvas,
          body: Column(
            children: [
              _mobileNav(),
              Expanded(child: content),
            ],
          ),
        );
      }
      return Scaffold(
        backgroundColor: _canvas,
        body: Row(
          children: [
            _sidebar(extended),
            Expanded(child: content),
          ],
        ),
      );
    },
  );

  Widget _sidebar(bool extended) => Container(
    width: extended ? 264 : 82,
    color: _sidebarColor,
    child: SafeArea(
      child: Column(
        children: [
          Padding(
            padding: EdgeInsets.fromLTRB(extended ? 24 : 16, 24, 16, 30),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _mark(),
                if (extended) ...[
                  const SizedBox(width: 12),
                  const Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'ATOM',
                          style: TextStyle(
                            color: _ink,
                            fontSize: 19,
                            fontWeight: FontWeight.w800,
                            letterSpacing: 1.4,
                          ),
                        ),
                        Text(
                          'CLASSROOM OPERATIONS',
                          style: TextStyle(
                            color: _muted,
                            fontSize: 9,
                            fontWeight: FontWeight.w700,
                            letterSpacing: .8,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              children: DashboardNavigation.values
                  .map((item) => _navItem(item, extended))
                  .toList(),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: _livePill(compact: !extended),
          ),
        ],
      ),
    ),
  );

  Widget _mobileNav() => Container(
    color: _sidebarColor,
    padding: const EdgeInsets.fromLTRB(16, 12, 16, 10),
    child: SafeArea(
      bottom: false,
      child: SizedBox(
        height: 42,
        child: ListView(
          scrollDirection: Axis.horizontal,
          children: DashboardNavigation.values
              .map(
                (item) => Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(item.label),
                    selected: _selected == item,
                    onSelected: (_) => setState(() => _selected = item),
                    selectedColor: _cyanDim,
                    backgroundColor: _surface,
                    labelStyle: TextStyle(
                      color: _selected == item ? _ink : _muted,
                      fontWeight: FontWeight.w700,
                    ),
                    side: const BorderSide(color: _line),
                  ),
                ),
              )
              .toList(),
        ),
      ),
    ),
  );

  Widget _navItem(DashboardNavigation item, bool extended) {
    final selected = _selected == item;
    return Padding(
      padding: const EdgeInsets.only(bottom: 5),
      child: Material(
        color: selected ? _cyanDim : Colors.transparent,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => setState(() => _selected = item),
          child: Padding(
            padding: EdgeInsets.symmetric(
              horizontal: extended ? 13 : 16,
              vertical: 12,
            ),
            child: Row(
              mainAxisAlignment: extended
                  ? MainAxisAlignment.start
                  : MainAxisAlignment.center,
              children: [
                Icon(item.icon, color: selected ? _cyan : _muted, size: 21),
                if (extended) ...[
                  const SizedBox(width: 13),
                  Expanded(
                    child: Text(
                      item.label,
                      style: TextStyle(
                        color: selected ? _ink : _muted,
                        fontSize: 13,
                        fontWeight: selected
                            ? FontWeight.w700
                            : FontWeight.w500,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _page() => switch (_selected) {
    DashboardNavigation.overview => _overview(),
    DashboardNavigation.monitoring => _monitoring(),
    DashboardNavigation.appliances => _appliancePage(),
    DashboardNavigation.energy => _energyPage(),
    DashboardNavigation.logs => _logsPage(),
    DashboardNavigation.settings => _settings(),
  };

  Widget _overview() => _screen(
    'Overview',
    'A live view of classroom signals and device actions.',
    [
      Wrap(
        spacing: 14,
        runSpacing: 14,
        children: [
          _metric(
            'People detected',
            _zones.isEmpty ? 'N/A' : '$_totalCount',
            _zones.isEmpty
                ? 'No occupancy feed'
                : '${_zones.length} reporting zones',
            Icons.groups_rounded,
            _cyan,
          ),
          _metric(
            'Automation mode',
            _mode ?? 'N/A',
            _mode == null ? 'No mode reported' : 'Live configuration',
            Icons.auto_awesome_rounded,
            _good,
          ),
          _metric(
            'Modeled LED energy',
            _modeledWh != null
                ? '${_modeledWh!.toStringAsFixed(3)} Wh'
                : 'N/A',
            _modeledWh != null
                ? 'Estimated LED 1 run time'
                : 'Set rated watts to begin',
            Icons.bolt_rounded,
            _warning,
          ),
          _metric(
            'Device states',
            _appliances.isEmpty ? 'N/A' : '${_appliances.length}',
            _appliances.isEmpty ? 'No appliance feed' : 'Reporting appliances',
            Icons.power_rounded,
            _cyan,
          ),
        ],
      ),
      const SizedBox(height: 18),
      _pair(_occupancyPanel(), _quickPanel()),
      const SizedBox(height: 18),
      _pair(_activityPanel(4), _systemPanel()),
    ],
  );

  Widget _monitoring() => _screen(
    'Classroom Monitoring',
    'Zone-level presence appears only after a sensor reports it.',
    [
      _videoControlPanel(),
      const SizedBox(height: 18),
      _occupancyPanel(),
      const SizedBox(height: 18),
      _virtualLightsPanel(),
      const SizedBox(height: 18),
      _panel(
        'Zone detail',
        Column(
          children: List.generate(9, (index) {
            final count = _zones['zone${index + 1}'];
            return Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              decoration: BoxDecoration(
                color: _raised,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Row(
                children: [
                  _zoneNumber(index + 1),
                  const SizedBox(width: 12),
                  Text(
                    'Zone ${index + 1}',
                    style: const TextStyle(
                      color: _ink,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const Spacer(),
                  Text(
                    count == null ? 'N/A' : '$count detected',
                    style: TextStyle(
                      color: count == null ? _muted : _cyan,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            );
          }),
        ),
        trailing: _small(
          _zones.isEmpty ? 'No feed' : '${_zones.length} reporting',
          _zones.isEmpty ? _warning : _good,
        ),
      ),
    ],
  );

  Widget _videoControlPanel() => _panel(
    'Video source',
    Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: DropdownButtonFormField<String>(
                initialValue: _selectedVideoSource,
                dropdownColor: _raised,
                style: const TextStyle(color: _ink, fontWeight: FontWeight.w700),
                decoration: const InputDecoration(
                  labelText: 'Source',
                  labelStyle: TextStyle(color: _muted),
                ),
                items: const [
                  DropdownMenuItem(value: 'uploaded', child: Text('Uploaded video')),
                  DropdownMenuItem(value: '0', child: Text('Laptop camera')),
                ],
                onChanged: _cameraRequestInFlight
                    ? null
                    : (value) => value == null
                        ? null
                        : setState(() => _selectedVideoSource = value),
              ),
            ),
            const SizedBox(width: 12),
            OutlinedButton.icon(
              onPressed: _cameraRequestInFlight || _selectedVideoSource != 'uploaded'
                  ? null
                  : _uploadAndStartVideo,
              icon: const Icon(Icons.upload_file_rounded),
              label: const Text('Upload MP4'),
            ),
            const SizedBox(width: 8),
            FilledButton.icon(
              onPressed: _cameraRequestInFlight || (_selectedVideoSource == 'uploaded' && !_uploadedReady) ? null : _startCamera,
              icon: const Icon(Icons.play_arrow_rounded),
              label: const Text('Start'),
            ),
            const SizedBox(width: 8),
            TextButton.icon(
              onPressed: _cameraRequestInFlight ? null : _stopCamera,
              icon: const Icon(Icons.stop_circle_outlined),
              label: const Text('Stop'),
            ),
          ],
        ),
        const SizedBox(height: 14),
        Text(
          'Status: $_cameraStatus${_occupancyStatus['source'] == null ? '' : ' • ${_occupancyStatus['source']}'}',
          style: const TextStyle(color: _muted, fontSize: 12),
        ),
        const SizedBox(height: 14),
        AspectRatio(
          aspectRatio: 16 / 9,
          child: Container(
            clipBehavior: Clip.antiAlias,
            decoration: BoxDecoration(
              color: _canvas,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: _line),
            ),
            child: Image.network(
              '$_backendBase/api/camera/frame.jpg?v=$_streamVersion',
              fit: BoxFit.cover,
              errorBuilder: (_, _, _) => const Center(
                child: Text('Start detection to view real annotated frames.', style: TextStyle(color: _muted)),
              ),
              loadingBuilder: (context, child, progress) => progress == null
                  ? child
                  : const Center(child: CircularProgressIndicator(color: _cyan)),
            ),
          ),
        ),
        const SizedBox(height: 8),
        const Text(
          'The overlay uses the calibrated classroom seating polygons and real YOLO person detections.',
          style: TextStyle(color: _muted, fontSize: 11),
        ),
      ],
    ),
    trailing: _small(_cameraStatus, _cameraStatus == 'running' ? _good : _warning),
  );

  Widget _virtualLightsPanel() => _panel(
    'Virtual light indicators only',
    Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'These are on-screen occupancy indicators. They do not send MQTT commands or control relays.',
          style: TextStyle(color: _muted, fontSize: 12),
        ),
        const SizedBox(height: 14),
        GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          itemCount: 9,
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 3,
            childAspectRatio: 2.5,
            mainAxisSpacing: 8,
            crossAxisSpacing: 8,
          ),
          itemBuilder: (context, index) {
            final zone = index + 1;
            final reported = _zones.containsKey('zone$zone');
            final on = (_zones['zone$zone'] ?? 0) > 0;
            return Container(
              padding: const EdgeInsets.symmetric(horizontal: 10),
              decoration: BoxDecoration(
                color: (reported && on ? _good : _raised).withValues(alpha: reported && on ? .14 : 1),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: reported && on ? _good : _line),
              ),
              child: Row(
                children: [
                  Icon(Icons.lightbulb_outline_rounded, color: reported && on ? _good : _muted, size: 18),
                  const SizedBox(width: 7),
                  Text(
                    'Z$zone ${reported ? (on ? 'ON' : 'OFF') : 'N/A'}',
                    style: TextStyle(color: reported && on ? _good : _muted, fontWeight: FontWeight.w800),
                  ),
                ],
              ),
            );
          },
        ),
      ],
    ),
    trailing: _small('No relay control', _warning),
  );

  Widget _appliancePage() {
    final ids = <String>{'led1', ..._appliances.keys}.toList()..sort();
    return _screen(
      'Appliance Controls',
      'Commands use the existing local control service and wait for a live acknowledgement.',
      [
        _panel(
          'Connected controls',
          Column(children: ids.map(_control).toList()),
          trailing: _small(
            _appliances.isEmpty
                ? 'State unavailable'
                : '${_appliances.length} reporting',
            _appliances.isEmpty ? _warning : _good,
          ),
        ),
      ],
    );
  }

  Future<void> _saveRatedWatts() async {
    final watts = double.tryParse(_ratedWattsController.text);
    if (watts == null || watts <= 0) return _message('Enter the LED’s rated watts from its label or datasheet.');
    try {
      final response = await http.put(
        Uri.parse('$_backendBase/api/energy/led1/rated-watts'),
        headers: _sessionHeaders(json: true),
        body: jsonEncode({'rated_watts': watts}),
      );
      if (response.statusCode != 200) throw Exception(response.body);
      _message('Rated watts saved; future consumption is modeled from LED ON time.');
    } catch (_) {
      _message('Could not save rated watts. Start Flutter with ATOM_API_KEY.');
    }
  }

  Widget _energyPage() => _screen(
    'Energy Analytics',
    'LED 1 estimate from automation run time and confirmed switch state. It is not a meter reading.',
    [
      _panel(
        'Latest reading',
        Row(
          children: [
            Container(
              width: 52,
              height: 52,
              decoration: BoxDecoration(
                color: _warning.withValues(alpha: .13),
                borderRadius: BorderRadius.circular(14),
              ),
              child: const Icon(Icons.bolt_rounded, color: _warning),
            ),
            const SizedBox(width: 16),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _modeledWh != null
                      ? '${_modeledWh!.toStringAsFixed(4)} Wh'
                      : 'N/A',
                  style: const TextStyle(
                    color: _ink,
                    fontSize: 28,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                Text(
                  _energyModel['modeled_state'] == 'on'
                      ? 'Automation estimate is running'
                      : 'Modeled consumption (not measured)',
                  style: const TextStyle(color: _muted),
                ),
                const SizedBox(height: 3),
                Text(
                  _modeledRunLabel,
                  style: const TextStyle(color: _cyan, fontSize: 12, fontWeight: FontWeight.w700),
                ),
              ],
            ),
          ],
        ),
        trailing: _small(
          _energyModel['modeled_available'] == true ? 'Modeled' : 'Needs watts',
          _energyModel['modeled_available'] == true ? _good : _warning,
        ),
      ),
      const SizedBox(height: 18),
      _panel(
        'LED 1 model settings',
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Enter the LED’s rated watts. Until then consumption remains N/A.', style: TextStyle(color: _muted, fontSize: 12)),
            const SizedBox(height: 10),
            SizedBox(
              width: 220,
              child: TextField(
                controller: _ratedWattsController,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                style: const TextStyle(color: _ink),
                decoration: const InputDecoration(labelText: 'Rated watts', labelStyle: TextStyle(color: _muted)),
              ),
            ),
            const SizedBox(height: 10),
            FilledButton(onPressed: _saveRatedWatts, child: const Text('Save rated watts')),
          ],
        ),
      ),
    ],
  );

  Widget _logsPage() => _screen(
    'Activity',
    'Events from this demo session, newest first.',
    [_activityPanel(null)],
  );

  Widget _settings() => _screen(
    'Settings',
    'Connection details are shown for clarity; credentials and backend configuration stay unchanged.',
    [
      _panel(
        'Data sources',
        Column(
          children: [
            _setting(
              Icons.cloud_outlined,
              'Firebase Realtime Database',
              'ATOM/classroom1',
              _connection,
            ),
            const Divider(color: _line, height: 28),
            _setting(
              Icons.lan_outlined,
              'Local command service',
              '127.0.0.1:8000/api/command',
              'Used for appliance commands',
            ),
            const Divider(color: _line, height: 28),
            _setting(
              Icons.memory_rounded,
              'ESP32 MQTT controls',
              'Command path preserved',
              'Hardware response is confirmed by its live state feed',
            ),
          ],
        ),
      ),
    ],
  );

  Widget _screen(String title, String subtitle, List<Widget> children) =>
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        color: _ink,
                        fontSize: 26,
                        fontWeight: FontWeight.w800,
                        letterSpacing: -.5,
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      subtitle,
                      style: const TextStyle(color: _muted, fontSize: 13),
                    ),
                  ],
                ),
              ),
              _livePill(),
            ],
          ),
          const SizedBox(height: 22),
          Expanded(
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: children,
              ),
            ),
          ),
        ],
      );

  Widget _metric(
    String label,
    String value,
    String detail,
    IconData icon,
    Color accent,
  ) => Container(
    width: 236,
    padding: const EdgeInsets.all(17),
    decoration: BoxDecoration(
      color: _surface,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: _line),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: accent.withValues(alpha: .13),
                borderRadius: BorderRadius.circular(9),
              ),
              child: Icon(icon, color: accent, size: 18),
            ),
            const Spacer(),
            Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(
                color: value == 'N/A' ? _warning : accent,
                shape: BoxShape.circle,
              ),
            ),
          ],
        ),
        const SizedBox(height: 18),
        Text(
          value,
          style: const TextStyle(
            color: _ink,
            fontSize: 24,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 3),
        Text(
          label,
          style: const TextStyle(
            color: _ink,
            fontSize: 13,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 4),
        Text(detail, style: const TextStyle(color: _muted, fontSize: 11)),
      ],
    ),
  );

  Widget _pair(Widget first, Widget second) => LayoutBuilder(
    builder: (context, constraints) => constraints.maxWidth < 860
        ? Column(children: [first, const SizedBox(height: 18), second])
        : Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: first),
              const SizedBox(width: 18),
              Expanded(child: second),
            ],
          ),
  );

  Widget _occupancyPanel() => _panel(
    'Occupancy map',
    Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          _zones.isEmpty
              ? 'No occupancy readings received'
              : 'Each tile reflects the latest sensor report.',
          style: const TextStyle(color: _muted, fontSize: 12),
        ),
        const SizedBox(height: 16),
        GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          itemCount: 9,
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 3,
            mainAxisSpacing: 8,
            crossAxisSpacing: 8,
            childAspectRatio: 1.55,
          ),
          itemBuilder: (context, index) => _zoneTile(index + 1),
        ),
      ],
    ),
    trailing: _small(
      _zones.isEmpty ? 'No live feed' : '$_totalCount detected',
      _zones.isEmpty ? _warning : _good,
    ),
  );

  Widget _zoneTile(int number) {
    final count = _zones['zone$number'];
    final reported = count != null;
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: reported ? _cyanDim.withValues(alpha: .28) : _raised,
        borderRadius: BorderRadius.circular(11),
        border: Border.all(color: reported ? _cyanDim : _line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(
            'Zone $number',
            style: const TextStyle(
              color: _muted,
              fontSize: 10,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 3),
          Text(
            reported ? '$count' : 'N/A',
            style: TextStyle(
              color: reported ? _cyan : _muted,
              fontSize: 20,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }

  Widget _quickPanel() => _panel(
    'Quick controls',
    Column(
      children: [
        _control('led1'),
        const SizedBox(height: 12),
        Align(
          alignment: Alignment.centerLeft,
          child: _modePicker(compact: true),
        ),
      ],
    ),
    trailing: _small(
      _mode ?? 'Mode unavailable',
      _mode == null ? _warning : _good,
    ),
  );

  Widget _control(String id) {
    final state = _appliances[id];
    final pending = _pending[id] ?? false;
    final label = id == 'led1'
        ? 'LED 1'
        : id.replaceAll('_', ' ').toUpperCase();
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        color: _raised,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: _cyan.withValues(alpha: .13),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: const Icon(
                  Icons.lightbulb_outline_rounded,
                  color: _cyan,
                  size: 20,
                ),
              ),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      label,
                      style: const TextStyle(
                        color: _ink,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    Text(
                      pending
                          ? 'Awaiting acknowledgement: ${_desiredStates[id]}'
                          : state == null
                          ? 'State unavailable'
                          : 'Actual state: $state',
                      style: const TextStyle(color: _muted, fontSize: 11),
                    ),
                  ],
                ),
              ),
              _small(
                pending ? 'Pending' : state ?? 'N/A',
                pending
                    ? _warning
                    : state == 'on'
                    ? _good
                    : _muted,
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: pending ? null : () => _sendLedCommand(id, true),
                  icon: const Icon(Icons.power_settings_new_rounded, size: 16),
                  label: const Text('Turn on'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: TextButton.icon(
                  onPressed: pending ? null : () => _sendLedCommand(id, false),
                  icon: const Icon(Icons.power_off_rounded, size: 16),
                  label: const Text('Turn off'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _modePicker({bool compact = false}) {
    return SizedBox(
      width: compact ? double.infinity : 280,
      child: DropdownButtonFormField<String>(
        key: ValueKey<String?>(_mode),
        initialValue: _modeLabels.containsKey(_mode) ? _mode : null,
        dropdownColor: _raised,
        style: const TextStyle(
          color: _ink,
          fontSize: 13,
          fontWeight: FontWeight.w700,
        ),
        decoration: InputDecoration(
          labelText: 'Operating mode',
          labelStyle: const TextStyle(color: _muted),
          filled: true,
          fillColor: _raised,
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(11),
            borderSide: const BorderSide(color: _line),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(11),
            borderSide: const BorderSide(color: _cyan),
          ),
        ),
        hint: const Text('Mode unavailable', style: TextStyle(color: _muted)),
        items: _modeLabels.entries
            .map((entry) => DropdownMenuItem(value: entry.key, child: Text(entry.value)))
            .toList(),
        onChanged: _rootRef == null
            ? null
            : (mode) => mode == null ? null : _setMode(mode),
      ),
    );
  }

  Widget _activityPanel(int? limit) {
    final entries = limit == null ? _logs : _logs.take(limit).toList();
    return _panel(
      'Activity',
      entries.isEmpty
          ? _empty(
              'No activity logs available',
              'Upload a video, start detection, or change LED state to create an event.',
            )
          : Column(
              children: entries
                  .map(
                    (entry) => Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Container(
                            margin: const EdgeInsets.only(top: 5),
                            width: 7,
                            height: 7,
                            decoration: const BoxDecoration(
                              color: _cyan,
                              shape: BoxShape.circle,
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              entry,
                              style: const TextStyle(
                                color: _ink,
                                fontSize: 12,
                                height: 1.35,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  )
                  .toList(),
            ),
      trailing: _small(
        _logs.isEmpty ? 'No logs' : '${_logs.length} events',
        _logs.isEmpty ? _muted : _good,
      ),
    );
  }

  Widget _systemPanel() => _panel(
    'System status',
    Column(
      children: [
        _status(
          'Live data',
          _connection,
          _connection == 'Live data received' ? _good : _warning,
        ),
        const Divider(color: _line, height: 26),
        _status(
          'Occupancy feed',
          _zones.isEmpty ? 'Unavailable' : 'Reporting',
          _zones.isEmpty ? _warning : _good,
        ),
        const Divider(color: _line, height: 26),
        _status('Command pathway', 'Local FastAPI service', _cyan),
      ],
    ),
  );

  Widget _status(String label, String value, Color color) => Row(
    children: [
      Container(
        width: 9,
        height: 9,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      ),
      const SizedBox(width: 10),
      Expanded(
        child: Text(
          label,
          style: const TextStyle(
            color: _ink,
            fontWeight: FontWeight.w700,
            fontSize: 12,
          ),
        ),
      ),
      Flexible(
        child: Text(
          value,
          textAlign: TextAlign.right,
          style: const TextStyle(color: _muted, fontSize: 11),
        ),
      ),
    ],
  );

  Widget _setting(
    IconData icon,
    String title,
    String detail,
    String status,
  ) => Row(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Icon(icon, color: _cyan, size: 20),
      const SizedBox(width: 12),
      Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: const TextStyle(color: _ink, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 3),
            Text(detail, style: const TextStyle(color: _muted, fontSize: 11)),
          ],
        ),
      ),
      Flexible(
        child: Text(
          status,
          textAlign: TextAlign.right,
          style: const TextStyle(color: _muted, fontSize: 11),
        ),
      ),
    ],
  );

  Widget _panel(String title, Widget child, {Widget? trailing}) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(18),
    decoration: BoxDecoration(
      color: _surface,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: _line),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                title,
                style: const TextStyle(
                  color: _ink,
                  fontSize: 15,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            if (trailing != null) ...<Widget>[trailing],
          ],
        ),
        const SizedBox(height: 16),
        child,
      ],
    ),
  );

  Widget _empty(String title, String detail) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: _raised,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Icon(Icons.info_outline_rounded, color: _muted, size: 20),
        const SizedBox(width: 11),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  color: _ink,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 3),
              Text(
                detail,
                style: const TextStyle(
                  color: _muted,
                  fontSize: 12,
                  height: 1.35,
                ),
              ),
            ],
          ),
        ),
      ],
    ),
  );

  Widget _livePill({bool compact = false}) {
    final live = _connection == 'Live data received';
    return Container(
      padding: EdgeInsets.symmetric(horizontal: compact ? 8 : 10, vertical: 7),
      decoration: BoxDecoration(
        color: (live ? _good : _warning).withValues(alpha: .12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(
              color: live ? _good : _warning,
              shape: BoxShape.circle,
            ),
          ),
          if (!compact) ...[
            const SizedBox(width: 7),
            Text(
              live ? 'LIVE' : 'WAITING',
              style: TextStyle(
                color: live ? _good : _warning,
                fontSize: 10,
                fontWeight: FontWeight.w800,
                letterSpacing: .7,
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _small(String label, Color color) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .12),
      borderRadius: BorderRadius.circular(99),
    ),
    child: Text(
      label,
      style: TextStyle(color: color, fontSize: 10, fontWeight: FontWeight.w800),
    ),
  );
  Widget _zoneNumber(int number) => Container(
    width: 30,
    height: 30,
    alignment: Alignment.center,
    decoration: BoxDecoration(
      color: _cyanDim,
      borderRadius: BorderRadius.circular(8),
    ),
    child: Text(
      '$number',
      style: const TextStyle(color: _cyan, fontWeight: FontWeight.w800),
    ),
  );
  Widget _mark() => Container(
    width: 34,
    height: 34,
    alignment: Alignment.center,
    decoration: BoxDecoration(
      color: _cyan,
      borderRadius: BorderRadius.circular(10),
    ),
    child: const Text(
      'A',
      style: TextStyle(
        color: _canvas,
        fontWeight: FontWeight.w900,
        fontSize: 20,
      ),
    ),
  );
}
