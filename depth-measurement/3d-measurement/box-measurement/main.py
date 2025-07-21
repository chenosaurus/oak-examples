import depthai as dai
import argparse

from host_box_measurement import BoxMeasurement

parser = argparse.ArgumentParser()
parser.add_argument(
    "-maxd",
    "--max-dist",
    type=float,
    default=2,
    help="maximum distance between camera and object in space in meters",
)
parser.add_argument(
    "-mins",
    "--min-box-size",
    type=float,
    default=0.003,
    help="minimum box size in cubic meters",
)
args = parser.parse_args()

# Higher resolution for example THE_720_P makes better results but drastically lowers FPS
RESOLUTION = dai.MonoCameraProperties.SensorResolution.THE_400_P

device = dai.Device()
with dai.Pipeline(device) as pipeline:
    print("Creating pipeline...")
    calib_data = device.readCalibration()
    device.setIrLaserDotProjectorIntensity(1)

    cam = pipeline.create(dai.node.ColorCamera)
    cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
    cam.setIspScale(1, 3)
    cam.setColorOrder(dai.ColorCameraProperties.ColorOrder.RGB)
    cam.initialControl.setManualFocus(130)

    left = pipeline.create(dai.node.MonoCamera)
    left.setResolution(RESOLUTION)
    left.setBoardSocket(dai.CameraBoardSocket.CAM_B)

    right = pipeline.create(dai.node.MonoCamera)
    right.setResolution(RESOLUTION)
    right.setBoardSocket(dai.CameraBoardSocket.CAM_C)

    stereo = pipeline.create(dai.node.StereoDepth).build(left=left.out, right=right.out)
    stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DETAIL)
    stereo.initialConfig.setMedianFilter(dai.MedianFilter.KERNEL_7x7)
    stereo.setLeftRightCheck(True)
    stereo.setExtendedDisparity(False)
    stereo.setSubpixel(True)
    stereo.setSubpixelFractionalBits(3)
    stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)

    align = p.create(dai.node.ImageAlign)
    stereo.depth.link(align.input)
    color_output.link(align.inputAlignTo)

    width, height = cam.getIspSize()
    intrinsics = calib_data.getCameraIntrinsics(
        dai.CameraBoardSocket.CAM_A, dai.Size2f(width, height)
    )

    box_measurement = pipeline.create(BoxMeasurement).build(
        color=cam.isp,
        depth=stereo.depth,
        cam_intrinsics=intrinsics,
        shape=(width, height),
        max_dist=args.max_dist,
        min_box_size=args.min_box_size,
    )
    box_measurement.inputs["color"].setBlocking(False)
    box_measurement.inputs["color"].setMaxSize(4)
    box_measurement.inputs["depth"].setBlocking(False)
    box_measurement.inputs["depth"].setMaxSize(4)

    print("Pipeline created.")
    pipeline.run()
