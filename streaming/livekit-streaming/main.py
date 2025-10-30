import depthai as dai
from utils.arguments import initialize_argparser
import socket
import threading

_, args = initialize_argparser()

device = dai.Device(dai.DeviceInfo(args.device)) if args.device else dai.Device()

# --- Simple TCP broadcaster for encoded frames ---
_server_socket = None
_client_sockets = []
_clients_lock = threading.Lock()
_server_running = False


def start_tcp_server(host: str = "0.0.0.0", port: int = 5000):
    global _server_socket, _server_running
    if _server_running:
        return
    _server_running = True
    _server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _server_socket.bind((host, port))
    _server_socket.listen(5)

    def _accept_loop():
        while _server_running:
            try:
                conn, addr = _server_socket.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                # Bound per-send latency; drop slow clients quickly
                conn.settimeout(0.005)
                with _clients_lock:
                    _client_sockets.append(conn)
                print(f"TCP client connected: {addr}")
            except OSError:
                break
            except Exception as e:
                print(f"TCP accept error: {e}")

    threading.Thread(target=_accept_loop, daemon=True).start()


def stop_tcp_server():
    global _server_running
    _server_running = False
    try:
        if _server_socket:
            _server_socket.close()
    except Exception:
        pass
    with _clients_lock:
        for s in list(_client_sockets):
            try:
                s.close()
            except Exception:
                pass
        _client_sockets.clear()


def _broadcast_to_clients(data: bytes):
    if not data:
        return
    # Snapshot clients to avoid holding the lock during network I/O
    with _clients_lock:
        clients = list(_client_sockets)
    drop_list = []
    for s in clients:
        try:
            s.sendall(data)
        except Exception:
            drop_list.append(s)
    if drop_list:
        with _clients_lock:
            for s in drop_list:
                try:
                    s.close()
                except Exception:
                    pass
                if s in _client_sockets:
                    _client_sockets.remove(s)

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

    ###
    # Create a host-side queue for the encoder bitstream and a per-frame callback
    enc_q = vid_enc.bitstream.createOutputQueue(blocking=False, maxSize=1)

    def on_encoded(packet: dai.EncodedFrame):
        try:
            data = packet.getData()
            _broadcast_to_clients(memoryview(data))
        except Exception as e:
            print(f"Error in encoded-frame callback: {e}")
    

    def custom_service(message):
        print("Received message:", message)

    # Start TCP server to emit encoded frames
    start_tcp_server("0.0.0.0", args.port)
    pipeline.start()
    print("Running pipeline... tcp server started on port ", args.port)

    while pipeline.isRunning():
        # Drain encoder output and invoke callback for every encoded frame
        while True:
            enc_msg = enc_q.tryGet()
            if enc_msg is None:
                break
            on_encoded(enc_msg)
    pipeline.stop()
    stop_tcp_server()
