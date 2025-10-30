# LiveKit Streaming

This example project demonstrates how to stream from the `OAK-D Pro W PoE` to a LiveKit SFU using a pre-encoded stream from the camera.

## Usage

Here is a list of all available parameters:

```
-d DEVICE, --device DEVICE
					Optional name, DeviceID or IP of the camera to connect to. (default: None)
-fps FPS_LIMIT, --fps-limit FPS_LIMIT
					FPS limit. (default: 30)
-p PORT, --port PORT  Port to serve the stream on
```

To start OAK-D pipeline:
Camera at `192.168.2.24`, outputting H264 bytestream on port `5024`

```
python3 main.py --device 192.168.2.24 --fps 30 --port 5024

```

Install LiveKit CLI:
```
curl -sSL https://get.livekit.io/cli | bash
```


Then publish using the LiveKit CLI:
```
lk room join --identity <participant-identity> --api-key <api key> \
   --api-secret <secret> \
   --url "<livekit cloud url>" --publish h264://127.0.0.1:5024 <room name>
```

To view the stream, open in browser using LiveKit CLI:
```
lk token create --api-key <api key> \
  --api-secret <secret> \
  --url <url>\
   --identity=<viewer identity> --room=<room name> --join --open meet
```