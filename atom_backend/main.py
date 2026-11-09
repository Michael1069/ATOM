import os
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime, timezone

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

BASE_DIR = os.path.dirname(__file__)
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

from fastapi.middleware.cors import CORSMiddleware
app = FastAPI()
detection_service = CameraService(FirebaseOccupancyPublisher(root_ref))

# Add CORS middleware to allow Flutter app access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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

@app.post('/mode')
async def set_mode(request: Request):
    body = await request.json()
    new_mode = body.get('mode')
    if new_mode not in ['automatic', 'human_override', 'hybrid']:
        raise HTTPException(status_code=400, detail='Invalid mode')
    db.reference('ATOM/classroom1/mode').set(new_mode)
    return {'mode': new_mode}

@app.get('/energy')
async def get_energy():
    en = db.reference('ATOM/classroom1/energy').get() or {'watts':0,'kwh':0,'cost':0}
    return en


@app.get('/health')
async def health():
    return {'status':'ok'}


@app.on_event('startup')
async def startup_event():
    await mqtt_client.connect()
    # Occupancy-driven relay automation is deliberately disabled pending
    # validation of the camera and person-detection pipeline.

class CommandRequest(BaseModel):
    appliance_id: str
    state: str  # "on" or "off"


class StartDetectionRequest(BaseModel):
    source: str | None = None  # "0", a local video path, or an MJPEG URL.
    confidence: float = float(os.getenv('YOLO_CONFIDENCE', '0.35'))


def require_api_key(request: Request) -> None:
    if request.headers.get('x-api-key') != API_KEY:
        raise HTTPException(status_code=401, detail='Unauthorized')


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
        return detection_service.start(source, model_name=os.getenv('YOLO_MODEL', DEFAULT_MODEL), confidence=req.confidence)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409 if isinstance(exc, RuntimeError) else 400, detail=str(exc)) from exc


@app.post('/detection/stop')
async def stop_detection(request: Request):
    require_api_key(request)
    return detection_service.stop()

@app.post('/api/command')
async def send_command(req: CommandRequest, request: Request):
    require_api_key(request)
    topic = f'atom/appliance/{req.appliance_id}/set'
    payload = json.dumps({'state': req.state})
    await mqtt_client.publish(topic, payload)
    # Update Firebase command log
    cmd_ref = db.reference(f'ATOM/classroom1/commands/{req.appliance_id}')
    cmd_ref.set({'state': req.state, 'timestamp': datetime.now(timezone.utc).isoformat()})
    return JSONResponse(content={'status':'sent','appliance_id':req.appliance_id,'state':req.state})
