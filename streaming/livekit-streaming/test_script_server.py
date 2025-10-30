#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "depthai",
# ]
# ///

import depthai as dai

SERVER_IP   = "192.168.1.50"   # your TCP server
SERVER_PORT = 5004

pipeline = dai.Pipeline()

# Color camera -> H.264 encoder
cam = pipeline.create(dai.node.ColorCamera)
cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
cam.setFps(30)
cam.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)  # input to encoder is NV12 internally

enc = pipeline.create(dai.node.VideoEncoder)
enc.setDefaultProfilePreset(30, dai.VideoEncoderProperties.Profile.H264_MAIN)
enc.setBitrateKbps(4000)           # tweak as needed
enc.setKeyframeFrequency(60)       # send SPS/PPS on IDR regularly

cam.video.link(enc.input)

# Script node will open a TCP socket and forward encoded bytes
script = pipeline.create(dai.node.Script)
enc.bitstream.link(script.inputs['h264'])

script.setScript(f"""
import socket
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", {SERVER_PORT})); srv.listen(1)
conn, _ = srv.accept()
while True:
    pkt = node.io['h264'].get()
    conn.sendall(pkt.getData())
""")

with dai.Device(pipeline) as device:
    print("Streaming H.264 to", SERVER_IP, SERVER_PORT)
    while True:
        device.getQueueEvents()  # k