#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "depthai",
# ]
# ///
import depthai as dai
import time
from utils.arguments import initialize_argparser

_, args = initialize_argparser()

device = dai.Device(dai.DeviceInfo(args.device)) if args.device else dai.Device()

with dai.Pipeline(device) as pipeline:
    cam = pipeline.create(dai.node.Camera).build()
    fps = args.fps_limit or 30
    raw_stream = cam.requestOutput(
        (1280, 720), dai.ImgFrame.Type.NV12, fps=fps
    )

    vid_enc = pipeline.create(dai.node.VideoEncoder)
    vid_enc.setDefaultProfilePreset(
        fps, dai.VideoEncoderProperties.Profile.H264_BASELINE
    )
    vid_enc.setBitrateKbps(1000)
    # Shorter GOP for faster viewer startup
    gop = min(30, fps) if fps else 30
    vid_enc.setKeyframeFrequency(gop)
    raw_stream.link(vid_enc.input)

   # Script node will open a TCP socket and forward encoded bytes
    script = pipeline.create(dai.node.Script)
    vid_enc.bitstream.link(script.inputs['h264'])

    script.setScript(f"""
    import socket
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", {args.port})); srv.listen(1)
    conn, _ = srv.accept()
    while True:
        pkt = node.io['h264'].get()
        conn.sendall(pkt.getData())
    """)

    # Start TCP server to emit encoded frames
    pipeline.start()
    print("Running pipeline...")

    while pipeline.isRunning():
        # Keep the host process alive while the on-device Script streams H264
        time.sleep(0.1)
    pipeline.stop()
