import depthai as dai
from frontend_server import FrontendServer
from pathlib import Path
from utils.arguments import initialize_argparser
import asyncio
import logging
import os
import threading
from typing import Optional

import cv2
import numpy as np
from livekit import api, rtc
from dotenv import load_dotenv, find_dotenv


_, args = initialize_argparser()

# Load env vars from .env if present (searches up the directory tree)
load_dotenv(find_dotenv(), override=False)

# Configure basic logging
logging.basicConfig(level=logging.INFO)

FRONTEND_DIRECTORY = Path(__file__).parent / "frontend" / "dist"
IP = args.ip or "localhost"
PORT = args.port or 8082

frontend_server = FrontendServer(IP, PORT, FRONTEND_DIRECTORY)
print(f"Serving frontend at http://{IP}:{PORT}")
frontend_server.start()

device = dai.Device(dai.DeviceInfo(args.device)) if args.device else dai.Device()
visualizer = dai.RemoteConnection(serveFrontend=False)

# LiveKit globals
LIVEKIT_WIDTH = 1280
LIVEKIT_HEIGHT = 720
LIVEKIT_FPS = 30

_lk_loop: Optional[asyncio.AbstractEventLoop] = None
_lk_room: Optional[rtc.Room] = None
_lk_video_source: Optional[rtc.VideoSource] = None
_lk_connected = False


def _ensure_event_loop_in_thread() -> asyncio.AbstractEventLoop:
    global _lk_loop
    if _lk_loop is not None and _lk_loop.is_running():
        return _lk_loop

    _lk_loop = asyncio.new_event_loop()

    def _run_loop(loop: asyncio.AbstractEventLoop):
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_run_loop, args=(_lk_loop,), daemon=True)
    thread.start()
    return _lk_loop


async def _lk_connect_and_publish(width: int, height: int, fps: int) -> None:
    global _lk_room, _lk_video_source, _lk_connected

    if _lk_room is None:
        _lk_room = rtc.Room(loop=asyncio.get_event_loop())

    token = (
        api.AccessToken()
        .with_identity("oak-python-publisher")
        .with_name("OAK Python Publisher")
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=os.getenv("LIVEKIT_ROOM", "cavalla"),
            )
        )
        .to_jwt()
    )

    url = os.getenv("LIVEKIT_URL")
    logging.info("Connecting to LiveKit at %s", url)
    try:
        await _lk_room.connect(url, token)
        logging.info("Connected to room %s", _lk_room.name)
    except rtc.ConnectError as e:
        logging.error("Failed to connect to the room: %s", e)
        return

    # Create source and publish track
    _lk_video_source = rtc.VideoSource(width, height)
    track = rtc.LocalVideoTrack.create_video_track("oak-raw", _lk_video_source)
    options = rtc.TrackPublishOptions(
        source=rtc.TrackSource.SOURCE_CAMERA,
        simulcast=True,
        video_encoding=rtc.VideoEncoding(
            max_framerate=fps,
            max_bitrate=3_000_000,
        ),
    )
    publication = await _lk_room.local_participant.publish_track(track, options)
    logging.info("Published LiveKit video track %s", publication.sid)
    _lk_connected = True


def start_livekit(width: int, height: int, fps: int) -> None:
    loop = _ensure_event_loop_in_thread()
    asyncio.run_coroutine_threadsafe(_lk_connect_and_publish(width, height, fps), loop)


def stop_livekit() -> None:
    global _lk_connected, _lk_room
    if _lk_loop is None:
        return
    if _lk_room is not None:
        async def _cleanup():
            try:
                await _lk_room.disconnect()
            finally:
                pass

        asyncio.run_coroutine_threadsafe(_cleanup(), _lk_loop)
    _lk_connected = False

with dai.Pipeline(device) as pipeline:
    cam = pipeline.create(dai.node.Camera).build()
    raw_stream = cam.requestOutput(
        (1280, 720), dai.ImgFrame.Type.NV12, fps=30 or args.fps_limit
    )
    visualizer.addTopic("Raw Stream", raw_stream)

    # Create a host-side queue to consume frames from the raw stream
    raw_q = raw_stream.createOutputQueue(blocking=False, maxSize=1)

    # Start LiveKit publisher in background
    try:
        # Use args.fps_limit if provided
        fps = int(args.fps_limit) if getattr(args, "fps_limit", None) else LIVEKIT_FPS
        start_livekit(LIVEKIT_WIDTH, LIVEKIT_HEIGHT, fps)
    except Exception as e:
        logging.error("Failed to start LiveKit publisher: %s", e)

    # Per-frame callback: receives dai.ImgFrame
    def on_frame(img_frame: dai.ImgFrame):
        # Example: access timestamp/shape
        ts = img_frame.getTimestamp()
        w, h = img_frame.getWidth(), img_frame.getHeight()
        # print(f"Frame {w}x{h} @ {ts}")

        # Publish to LiveKit if connected
        if _lk_video_source is not None and _lk_loop is not None:
            # Convert to RGBA for LiveKit
            bgr = img_frame.getCvFrame()
            rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
            # Ensure contiguous bytes
            buffer = np.ascontiguousarray(rgba).tobytes()
            frame = rtc.VideoFrame(w, h, rtc.VideoBufferType.RGBA, buffer)
            # Capture on LiveKit loop thread
            _lk_loop.call_soon_threadsafe(_lk_video_source.capture_frame, frame)

    def custom_service(message):
        print("Received message:", message)

    visualizer.registerService("Custom Service", custom_service)
    pipeline.start()
    print("Running pipeline...")

    while pipeline.isRunning():
        # Drain latest frame (if any) and invoke callback
        if raw_q.has():
            frame_msg = raw_q.get()
            on_frame(frame_msg)
        key_pressed = visualizer.waitKey(1)
        if key_pressed == ord("q"):
            break

    pipeline.stop()
    stop_livekit()
