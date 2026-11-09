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
  status           # starting, running, live, stopped, or error
  source           # webcam:0, a local path, or an MJPEG URL
  detected_at      # ISO-8601 UTC time of the latest analysed frame
  total            # sum of the nine zones
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
