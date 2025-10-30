import argparse


def initialize_argparser():
    """Initialize the argument parser for the script."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "-d",
        "--device",
        help="Optional name, DeviceID or IP of the camera to connect to.",
        required=False,
        default=None,
        type=str,
    )

    parser.add_argument(
        "-fps",
        "--fps-limit",
        help="FPS limit.",
        required=False,
        default=30,
        type=int,
    )
   
    parser.add_argument(
        "-p",
        "--port",
        help="Port to open the TCP server on.",
        required=True,
        type=int,
    )

    args = parser.parse_args()

    return parser, args
