# ATOM YOLO person detection

The detector is intentionally **off by default**.  It does not send MQTT
commands and it does not enable occupancy-based appliance automation.  Manual
LED control through `POST /api/command` remains unchanged.

## What is published

After YOLO has successfully analysed a real frame, it writes only these
dedicated nodes below `ATOM/classroom1`:

```text
occupancy/
  zone1 ... zone9  # integer counts, row-major 3x3 map (Flutter's existing contract)
occupancy_status/
  status           # starting, running, live, completed, stopped, or error
  source           # e.g. uploaded:classroom_demo.mp4
  detected_at      # ISO-8601 UTC time of the latest analysed frame
  timestamp        # duplicate timestamp for dashboard consumers
  total            # sum of the nine zones
  model            # checkpoint used for this real inference
  calibration      # perspective map name, when configured
virtual_zone_lights/
  zone1 ... zone9  # virtual on/off display state only; never a relay command
```

Each person is assigned once using the bottom-center point of its bounding
box. `zone1` is top-left and `zone9` is bottom-right. A zero is published only
after a frame was read and analysed with no people. If the camera, model, or
network fails, the previous occupancy map is retained and only
`occupancy_status` changes to `error`.

The backend no longer clears `occupancy`, appliances, mode, energy, or commands
when it starts.

## Install (already completed on this machine)

```powershell
cd C:\ATOM\atom_backend
.\venv\Scripts\python.exe -m pip install -r .\requirements-yolo.txt
```

The first detection start downloads the pinned nano model (`yolo26n.pt`) if it
is missing. It is ignored by Git because it is a generated runtime asset.

### Current uploaded-video demo

The supplied classroom video is stored as `test_videos/classroom_demo.mp4`.
It runs the installed `yolo26n.pt` checkpoint—**not** YOLOv8n—and reports that
exact model name to Firebase. Its nine zones use the
`classroom_demo_perspective_v1` polygons, calibrated to the three desk columns,
their perspective, and the front/middle/rear seating bands. Board space and
walkways are intentionally outside every zone. Counts remain numerical YOLO
person detections, not manually supplied ground truth.

The Flutter web dashboard posts MP4 bytes to `/api/camera/upload`, starts the
source at `/api/camera/start`, and renders actual annotated frames from
`/api/camera/stream`. Uploaded files are sampled at three real inferences per
second of video so a short 30 FPS clip reaches the `completed` state promptly;
no values are interpolated between detections.

## Start the backend

```powershell
cd C:\ATOM\atom_backend
.\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Keep your existing Mosquitto and Firebase configuration as-is. The detector
loads lazily, so this command still starts without a camera.

## Start a local webcam test

Set the value below to the `API_KEY` from the existing `.env` file. Do not put
the key in source control.

```powershell
$headers = @{ "x-api-key" = "YOUR_API_KEY" }
$body = @{ source = "0"; confidence = 0.35 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/detection/start -Headers $headers -ContentType application/json -Body $body
Invoke-RestMethod http://127.0.0.1:8000/detection/status
```

For a local recorded video, change `source` to its full path, for example
`C:\ATOM\test-videos\classroom.mp4`. Stop safely with:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/detection/stop -Headers $headers
```

## ESP32-CAM later

When its MJPEG stream is known and reachable, use the same endpoint with its
stream URL instead of a webcam index:

```powershell
$body = @{ source = "http://ESP32_CAM_IP:81/stream"; confidence = 0.35 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/detection/start -Headers $headers -ContentType application/json -Body $body
```

Do not start a second source while one is running; stop it first. The status
endpoint reports source errors without replacing the last verified people
counts.
