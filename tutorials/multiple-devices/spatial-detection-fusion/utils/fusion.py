import depthai as dai
import time
import pickle
import collections
import numpy as np
from typing import Dict, List, Any

from .detection_object import WorldDetection

class FusionManager(dai.node.ThreadedHostNode):
    def __init__(self, all_cam_extrinsics: Dict[str, Dict[str, Any]]) -> None:
        super().__init__()

        self.inputs: Dict[str, dai.Node.Input] = {}

        self.output = self.createOutput(
            possibleDatatypes=[
                dai.Node.DatatypeHierarchy(dai.DatatypeEnum.Buffer, True)
            ]
        )

        self.all_cam_extrinsics = all_cam_extrinsics
        for mxid in all_cam_extrinsics.keys():
            inp = self.createInput(
                name=mxid,
                group=mxid,
                queueSize=4, 
                blocking=False,
                types=[dai.Node.DatatypeHierarchy(
                    dai.DatatypeEnum.SpatialImgDetections, True
                )]
            )
            self.inputs[mxid] = inp

    def run(self):
        while True:
            for mxid, inp in self.inputs.items():
                msg = inp.get() 
                if msg is None:
                    continue
                self._handle(mxid, msg)
            time.sleep(0.002)

    def _handle(self, mxid: str, detections_msg: dai.ADatatype):
        assert isinstance(detections_msg, dai.SpatialImgDetections)
        extrinsics = self.all_cam_extrinsics.get(mxid)
        if not extrinsics:
            return

        world_dets = self._transform_detections_to_world(
            detections_msg.detections,
            extrinsics['cam_to_world'],
            extrinsics['friendly_id']
        )

        groups = self._group_detections(world_dets)
        data_bytes = pickle.dumps(groups)
        arr_uint8 = bytearray(data_bytes)

        groups_buffer = dai.Buffer()
        groups_buffer.setData(arr_uint8) # type: ignore
        groups_buffer.setTimestamp(detections_msg.getTimestamp())
        groups_buffer.setSequenceNum(detections_msg.getSequenceNum())
        self.output.send(groups_buffer)

    def _transform_detections_to_world(
        self,
        detections: List[dai.SpatialImgDetection],
        cam_to_world: np.ndarray,
        friendly_id: int
    ) -> List[WorldDetection]:
        world_detections: List[WorldDetection] = []
        for det in detections:
            coords = det.spatialCoordinates

            # Convert from mm to m and add homogeneous w=1
            pos_cam = np.array([
                coords.x / 1000.0, 
                -coords.y / 1000.0, 
                coords.z / 1000.0, 
                1.0
            ])
            pos_world = cam_to_world @ pos_cam.reshape(4, 1)

            world_detections.append(
                WorldDetection(
                    label=det.name,
                    confidence=det.confidence,
                    pos_world_homogeneous=pos_world,
                    camera_friendly_id=friendly_id,
                )
            )
        return world_detections

    def _group_detections(self, detections: List[WorldDetection]) -> List[List[WorldDetection]]:
        distance_threshold = 1.5
        for i in range(len(detections)):
            for j in range(i + 1, len(detections)):
                det1, det2 = detections[i], detections[j]
                if det1.label == det2.label:
                    dist = np.linalg.norm(det1.pos_world_homogeneous[:2] - det2.pos_world_homogeneous[:2])
                    if dist < distance_threshold:
                        det1.corresponding_world_detections.append(det2)
                        det2.corresponding_world_detections.append(det1)

        groups, visited = [], set()
        for det in detections:
            if det not in visited:
                current_group, q = [], collections.deque([det])
                visited.add(det)
                while q:
                    current_det = q.popleft()
                    current_group.append(current_det)
                    for neighbor in current_det.corresponding_world_detections:
                        if neighbor not in visited:
                            visited.add(neighbor)
                            q.append(neighbor)
                groups.append(current_group)
        return groups
