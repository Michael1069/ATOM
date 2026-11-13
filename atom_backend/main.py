import os
import json
import re
import time
import asyncio
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime, timezone

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIRECTORY = Path(BASE_DIR) / 'test_videos'
MAX_VIDEO_UPLOAD_BYTES = 300 * 1024 * 1024
FIREBASE_CRED_PATH = os.getenv('FIREBASE_CREDENTIALS') or os.path.join(BASE_DIR, 'serviceAccount.json')
FIREBASE_DB_URL = os.getenv('FIREBASE_DATABASE_URL')
MQTT_BROKER = os.getenv('MQTT_BROKER', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))
API_KEY = os.getenv('API_KEY', 'CHANGE_ME')

# Initialize Firebase Admin SDK
cred = credentials.Certificate(FIREBASE_CRED_PATH)
firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_DB_URL})

# Never initialize Firebase nodes with empty/default values here.  Doing so can
# erase live telemetry and appliance state whenever FastAPI restarts.
root_ref = db.reference('ATOM/classroom1')

# Import MQTT client for existing manual appliance commands.
from mqtt_client import mqtt_client
from camera_service import DEFAULT_MODEL, CameraService, FirebaseOccupancyPublisher
from automation_runtime import Zone1AutomationRuntime
from zone1_automation import apply_modeled_switch_state, apply_reported_switch_state

from fastapi.middleware.cors import CORSMiddleware
app = FastAPI()
detection_service = CameraService(FirebaseOccupancyPublisher(root_ref))
uploaded_video: Path | None = None
uploaded_video_name: str | None = None
automation_runtime: Zone1AutomationRuntime | None = None
application_loop: asyncio.AbstractEventLoop | None = None
active_session_id: str | None = None


def _session_ref():
    return root_ref.child('sessions').child(active_session_id) if active_session_id else None


def _activate_session(session_id: str | None) -> None:
    """Route a browser action and any worker it starts to its own demo session."""
    if not session_id:
        return
    candidate = session_id.strip()
    if not candidate:
        return
    session = root_ref.child('sessions').child(candidate)
    record = session.get() or {}
    if not isinstance(record, dict) or record.get('id') != candidate:
        raise HTTPException(status_code=409, detail='This demo session has expired. Refresh the dashboard and try again.')
    global active_session_id
    active_session_id = candidate
    detection_service.set_session_root(session)

# Add CORS middleware to allow Flutter app access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8080", "http://localhost:8080", "http://127.0.0.1:8081", "http://localhost:8081", "http://127.0.0.1:8090"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get('/occupancy')
async def get_occupancy():
    occ = db.reference('ATOM/classroom1/occupancy').get() or {}
    return occ

@app.get('/appliances')
async def get_appliances():
    apps = db.reference('ATOM/classroom1/appliances').get() or {}
    return apps

@app.get('/mode')
async def get_mode():
    mode = db.reference('ATOM/classroom1/mode').get() or 'automatic'
    return {'mode': mode}


def normalize_mode(value: object) -> str:
    normalized = str(value or '').strip().lower().replace(' ', '_')
    if normalized not in {'automatic', 'human_override', 'hybrid'}:
        raise ValueError('mode must be Automatic, Human Override, or Hybrid')
    return normalized


def _append_activity(kind: str, **details: object) -> None:
    entry = {'kind': kind, 'at': datetime.now(timezone.utc).isoformat(), **details}
    root_ref.child('activity_logs').push().set(entry)
    session = _session_ref()
    if session is not None:
        session.child('activity_logs').push().set(entry)


@app.post('/api/session/start')
async def start_demo_session(request: Request):
    require_api_key(request)
    global active_session_id, uploaded_video, uploaded_video_name
    # Stop the old owner before repointing session output; a stale worker can
    # therefore never publish into the new session branch.
    detection_service.stop()
    active_session_id = str(uuid.uuid4())
    uploaded_video = None
    uploaded_video_name = None
    db.reference('ATOM/classroom1/mode').set('automatic')
    session = _session_ref()
    appliance = root_ref.child('appliances').child('led1').get() or {}
    now = datetime.now(timezone.utc).isoformat()
    session.set({
        'id': active_session_id,
        'created_at': now,
        'mode': 'automatic',
        'occupancy_status': {'status': 'waiting_for_camera_input', 'updated_at': now},
        'energy': {'led1': {
            'reported_state': appliance.get('state'),
            'on_since': now if appliance.get('state') == 'on' else None,
            'cumulative_on_seconds': 0,
            'modeled_available': False,
        }},
    })
    detection_service.set_session_root(session)
    _append_activity('session_started', source='flutter_refresh', status='ready')
    return {'session_id': active_session_id, 'mode': 'automatic'}


@app.get('/api/session/{session_id}/snapshot')
async def get_demo_session_snapshot(session_id: str, request: Request):
    """Read one browser demo session for a reliable dashboard fallback."""
    require_api_key(request)
    session = root_ref.child('sessions').child(session_id).get() or {}
    if not isinstance(session, dict) or session.get('id') != session_id:
        raise HTTPException(status_code=404, detail='Demo session not found.')
    return session


@app.post('/mode')
async def set_mode(request: Request):
    require_api_key(request)
    _activate_session(request.headers.get('x-atom-session-id'))
    body = await request.json()
    try:
        new_mode = normalize_mode(body.get('mode'))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.reference('ATOM/classroom1/mode').set(new_mode)
    session = _session_ref()
    if session is not None:
        session.child('mode').set(new_mode)
    _append_activity('mode_changed', mode=new_mode, source='dashboard')
    return {'mode': new_mode}

@app.get('/energy')
async def get_energy():
    en = db.reference('ATOM/classroom1/energy').get() or {'watts':0,'kwh':0,'cost':0}
    return en


@app.get('/health')
async def health():
    return {'status':'ok'}


async def _connect_mqtt_optional(client) -> None:
    try:
        await client.connect()
    except RuntimeError:
        return


def schedule_optional_mqtt_connect(client=mqtt_client, task_creator=asyncio.create_task):
    """Start manual-control MQTT recovery without delaying the video service."""
    return task_creator(_connect_mqtt_optional(client), name='atom-optional-mqtt-connect')


async def _publish_led_command(state: str, reason: str, source: str) -> None:
    command_id = str(uuid.uuid4())
    payload = json.dumps({'state': state, 'command_id': command_id, 'source': source, 'reason': reason})
    await mqtt_client.publish('atom/appliance/led1/set', payload)
    root_ref.child('commands').child('led1').set({
        'state': state, 'command_id': command_id, 'source': source, 'reason': reason,
        'status': 'pending_ack', 'requested_at': datetime.now(timezone.utc).isoformat(),
    })
    if source == 'automatic':
        modeled_at = datetime.now(timezone.utc).isoformat()
        energy_ref = root_ref.child('energy').child('led1')
        energy_ref.set(apply_modeled_switch_state(
            energy_ref.get() or {}, modeled_state=state, modeled_at=modeled_at,
        ))
        session = _session_ref()
        if session is not None:
            session_energy = session.child('energy').child('led1')
            session_energy.set(apply_modeled_switch_state(
                session_energy.get() or {}, modeled_state=state, modeled_at=modeled_at,
            ))
        _append_activity(
            'energy_model_state', appliance_id='led1', state=state,
            source='automatic', reason=reason,
        )
    _append_activity('led_command_requested', appliance_id='led1', state=state, source=source, reason=reason)
    return True


async def _publish_automatic_led_command(state: str, reason: str) -> None:
    try:
        await _publish_led_command(state, reason, 'automatic')
    except RuntimeError as exc:
        _append_activity('led_command_failed', appliance_id='led1', state=state, source='automatic', reason=reason, error=str(exc))
        return False
    return True


def _record_reported_state(appliance_id: str, payload: dict) -> None:
    reported_at = datetime.now(timezone.utc).isoformat()
    state = payload['state']
    root_ref.child('appliances').child(appliance_id).set({
        'state': state, 'reported_at': reported_at, 'command_id': payload.get('command_id'),
    })
    command_ref = root_ref.child('commands').child(appliance_id)
    command = command_ref.get() or {}
    command_matches_id = command.get('command_id') and command.get('command_id') == payload.get('command_id')
    # Older flashed sketches report their real GPIO state without the command
    # ID. A matching state is still a genuine ESP32 acknowledgement, but it is
    # labelled so the dashboard does not pretend it had perfect correlation.
    legacy_state_match = (
        command.get('status') == 'pending_ack'
        and command.get('state') == state
        and not payload.get('command_id')
    )
    if command_matches_id or legacy_state_match:
        command.update({
            'status': 'acknowledged' if command_matches_id else 'acknowledged_state_match',
            'acknowledged_at': reported_at,
        })
        command_ref.set(command)
    if appliance_id == 'led1':
        energy_ref = root_ref.child('energy').child('led1')
        energy_ref.set(apply_reported_switch_state(
            energy_ref.get() or {}, reported_state=state, reported_at=reported_at,
        ))
        session = _session_ref()
        if session is not None:
            session_energy = session.child('energy').child('led1')
            session_energy.set(apply_reported_switch_state(
                session_energy.get() or {}, reported_state=state, reported_at=reported_at,
            ))
    _append_activity('device_state_reported', appliance_id=appliance_id, state=state, source='esp32')


def _schedule_observation(counts: dict[str, int], timestamp: str) -> None:
    if automation_runtime is not None and application_loop is not None:
        asyncio.run_coroutine_threadsafe(automation_runtime.observe(counts, timestamp), application_loop)


@app.on_event('startup')
async def startup_event():
    global automation_runtime, application_loop
    application_loop = asyncio.get_running_loop()
    mqtt_client.set_state_handler(_record_reported_state)
    automation_runtime = Zone1AutomationRuntime(
        root_ref, _publish_automatic_led_command,
    )
    await automation_runtime.load()
    detection_service.set_observation_handler(_schedule_observation)
    try:
        schedule_optional_mqtt_connect(mqtt_client)
    except RuntimeError:
        pass

    async def stale_feed_watchdog() -> None:
        while True:
            await asyncio.sleep(1)
            if automation_runtime is not None:
                await automation_runtime.check_stale()

    asyncio.create_task(stale_feed_watchdog(), name='atom-zone1-stale-watchdog')

class CommandRequest(BaseModel):
    appliance_id: str
    state: str  # "on" or "off"


class AutomationSettingsRequest(BaseModel):
    on_debounce_seconds: float
    off_debounce_seconds: float
    stale_after_seconds: float


class RatedWattsRequest(BaseModel):
    rated_watts: float


class StartDetectionRequest(BaseModel):
    source: str | None = None  # "0", a local video path, or an MJPEG URL.
    confidence: float = float(os.getenv('YOLO_CONFIDENCE', '0.35'))


class CameraStartRequest(BaseModel):
    source: str = 'uploaded'  # uploaded, webcam index, local path, or MJPEG URL
    confidence: float = float(os.getenv('YOLO_CONFIDENCE', '0.35'))


def require_api_key(request: Request) -> None:
    if request.headers.get('x-api-key') != API_KEY:
        raise HTTPException(status_code=401, detail='Unauthorized')


def _demo_video_path() -> Path | None:
    if uploaded_video and uploaded_video.is_file():
        return uploaded_video
    return None


def _resolve_camera_source(source: str) -> tuple[str | int, str, object | None]:
    """Resolve the user-facing source without leaking local upload paths."""
    if source == 'uploaded':
        video = _demo_video_path()
        if video is None:
            raise ValueError('Upload a classroom MP4 before starting uploaded-video detection.')
        name = uploaded_video_name or video.name
        calibration = (
            __import__('occupancy_detector').ClassroomZoneCalibration.for_uploaded_classroom_demo()
            if video.name == 'classroom_demo.mp4'
            else None
        )
        return str(video), f'uploaded:{name}', calibration
    return source, f'webcam:{source}' if source.isdecimal() else source, None


def _start_camera(source: str, confidence: float) -> dict:
    actual_source, display_source, calibration = _resolve_camera_source(source)
    return detection_service.start(
        actual_source,
        model_name=os.getenv('YOLO_MODEL', DEFAULT_MODEL),
        confidence=confidence,
        display_source=display_source,
        calibration=calibration,
    )


@app.get('/detection/status')
async def get_detection_status():
    """Return local worker state without reading or fabricating occupancy data."""
    return detection_service.snapshot()


@app.post('/detection/start')
async def start_detection(req: StartDetectionRequest, request: Request):
    require_api_key(request)
    source = req.source or os.getenv('DETECTION_SOURCE')
    if source is None:
        raise HTTPException(
            status_code=400,
            detail='Provide source (webcam index, local video path, or MJPEG URL).',
        )
    try:
        return _start_camera(source, req.confidence)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409 if isinstance(exc, RuntimeError) else 400, detail=str(exc)) from exc


@app.post('/detection/stop')
async def stop_detection(request: Request):
    require_api_key(request)
    return detection_service.stop()


@app.get('/api/camera/status')
async def get_camera_status():
    return {
        **detection_service.snapshot(),
        'uploaded_video_ready': _demo_video_path() is not None,
        'uploaded_video_name': uploaded_video_name or (_demo_video_path().name if _demo_video_path() else None),
        'virtual_lights_only': True,
    }


@app.post('/api/camera/upload')
async def upload_camera_video(request: Request):
    """Store a user-selected MP4 as the active private demo source."""
    require_api_key(request)
    _activate_session(request.headers.get('x-atom-session-id'))
    content_type = request.headers.get('content-type', '')
    filename = request.headers.get('x-file-name', 'classroom_demo.mp4')
    safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', Path(filename).name)
    if not safe_name.lower().endswith('.mp4') or 'video/' not in content_type:
        raise HTTPException(status_code=400, detail='Select an MP4 video file.')
    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=400, detail='The selected video is empty.')
    if len(payload) > MAX_VIDEO_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail='Video exceeds the 300 MB demo limit.')
    UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIRECTORY / 'classroom_demo.mp4'
    destination.write_bytes(payload)
    global uploaded_video, uploaded_video_name
    uploaded_video = destination
    uploaded_video_name = safe_name
    session = _session_ref()
    if session is not None:
        session.child('source').set({'name': safe_name, 'kind': 'uploaded', 'uploaded_at': datetime.now(timezone.utc).isoformat()})
    _append_activity('video_uploaded', source=f'uploaded:{safe_name}', bytes=len(payload))
    return {
        'status': 'uploaded',
        'source': f'uploaded:{safe_name}',
        'bytes': len(payload),
        'ready': True,
    }


@app.post('/api/camera/start')
async def start_camera(req: CameraStartRequest, request: Request):
    require_api_key(request)
    _activate_session(request.headers.get('x-atom-session-id'))
    try:
        started = _start_camera(req.source, req.confidence)
        _append_activity('detection_started', source=started.get('source'), confidence=req.confidence)
        return started
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409 if isinstance(exc, RuntimeError) else 400, detail=str(exc)) from exc


@app.post('/api/camera/stop')
async def stop_camera(request: Request):
    require_api_key(request)
    _activate_session(request.headers.get('x-atom-session-id'))
    stopped = detection_service.stop()
    _append_activity('detection_stopped', source=stopped.get('source'))
    return stopped


def _annotated_mjpeg_stream():
    """Yield the most recent annotated YOLO frame; no synthetic placeholder."""
    last_sent: bytes | None = None
    while True:
        current = detection_service.latest_jpeg()
        if current is not None and current != last_sent:
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + current + b'\r\n'
            last_sent = current
        time.sleep(0.1)


@app.get('/api/camera/stream')
async def stream_camera():
    return StreamingResponse(
        _annotated_mjpeg_stream(),
        media_type='multipart/x-mixed-replace; boundary=frame',
        headers={'Cache-Control': 'no-store'},
    )


@app.get('/api/camera/frame.jpg')
async def latest_camera_frame():
    """Return one annotated JPEG so Flutter web can refresh a real frame reliably."""
    frame = detection_service.latest_jpeg()
    if frame is None:
        raise HTTPException(status_code=404, detail='No annotated frame is available yet.')
    return Response(content=frame, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})

@app.post('/api/command')
async def send_command(req: CommandRequest, request: Request):
    require_api_key(request)
    _activate_session(request.headers.get('x-atom-session-id'))
    if req.appliance_id != 'led1' or req.state not in {'on', 'off'}:
        raise HTTPException(status_code=400, detail='Only the low-voltage led1 accepts on or off commands.')
    try:
        mode = normalize_mode(root_ref.child('mode').get() or 'automatic')
    except ValueError:
        mode = 'automatic'
    if mode == 'automatic':
        raise HTTPException(status_code=409, detail='Switch to Human Override or Hybrid before issuing a manual LED command.')
    if automation_runtime is not None:
        automation_runtime.note_manual_command(req.state)
    try:
        await _publish_led_command(req.state, 'manual_dashboard_command', 'manual')
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return JSONResponse(content={'status':'pending_ack', 'appliance_id':'led1', 'state':req.state})


@app.get('/api/automation/zone1')
async def get_zone1_automation(request: Request):
    require_api_key(request)
    if automation_runtime is None:
        return {'status': 'starting'}
    return {'status': 'ready', 'mode': automation_runtime.current_mode(), 'settings': automation_runtime.settings}


@app.put('/api/automation/zone1')
async def set_zone1_automation(req: AutomationSettingsRequest, request: Request):
    require_api_key(request)
    _activate_session(request.headers.get('x-atom-session-id'))
    if automation_runtime is None:
        raise HTTPException(status_code=503, detail='Automation service is starting.')
    try:
        settings = await automation_runtime.configure(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _append_activity('zone1_rule_updated', settings=settings)
    return {'mode': automation_runtime.current_mode(), 'settings': settings}


@app.put('/api/energy/led1/rated-watts')
async def set_led1_rated_watts(req: RatedWattsRequest, request: Request):
    require_api_key(request)
    _activate_session(request.headers.get('x-atom-session-id'))
    if req.rated_watts <= 0:
        raise HTTPException(status_code=400, detail='Rated watts must be greater than zero.')
    energy_ref = root_ref.child('energy').child('led1')
    energy = energy_ref.get() or {}
    energy['rated_watts'] = req.rated_watts
    if energy.get('reported_state') in {'on', 'off'} and isinstance(energy.get('last_changed_at'), str):
        energy = apply_reported_switch_state(
            energy, reported_state=energy['reported_state'], reported_at=energy['last_changed_at'],
        )
    energy['modeled_available'] = True
    energy_ref.set(energy)
    session = _session_ref()
    if session is not None:
        session_energy = session.child('energy').child('led1')
        session_value = session_energy.get() or {}
        session_value['rated_watts'] = req.rated_watts
        session_value['modeled_available'] = True
        session_energy.set(session_value)
    _append_activity('rated_watts_set', appliance_id='led1')
    return {'rated_watts': req.rated_watts, 'modeled': True}
