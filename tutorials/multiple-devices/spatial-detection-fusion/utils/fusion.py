import depthai as dai
import time
import datetime
import pickle
import collections
import numpy as np
from typing import Dict, List, Any, Deque

from .detection_object import WorldDetection

class FusionManager(dai.node.ThreadedHostNode):
    def __init__(self, all_cam_extrinsics: Dict[str, Dict[str, Any]], fps: int) -> None:
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

        self.detection_buffer: Dict[int, List[WorldDetection]] = collections.defaultdict(list)
        self.timestamp_queue: Deque[int] = collections.deque()

        frame_time_ms = 1000 / fps # time for one frame in milliseconds
        self.time_window_ms = frame_time_ms * 0.8  # time window for grouping near-simultaneous detections
        self.timeout = frame_time_ms / 1000 # timeout for fusion in seconds
        self.latest_device_timestamp_ms = 0

    def run(self):
        while True:
            self._read_inputs()
            self._process_buffer()
            time.sleep(0.002)

    def _read_inputs(self):
        """Read all available detections from input queues and buffer them."""
        for mxid, inp in self.inputs.items():
            msg = inp.tryGet()
            if msg is None:
                continue

            assert isinstance(msg, dai.SpatialImgDetections)
            extrinsics = self.all_cam_extrinsics.get(mxid)
            if not extrinsics:
                continue

            world_dets = self._transform_detections_to_world(
                msg.detections,
                extrinsics['cam_to_world'],
                extrinsics['friendly_id']
            )

            ts_ms = int(msg.getTimestamp().total_seconds() * 1000)
            self.latest_device_timestamp_ms = max(self.latest_device_timestamp_ms, ts_ms)
            
            self.detection_buffer[ts_ms].extend(world_dets)
            if ts_ms not in self.timestamp_queue:
                self.timestamp_queue.append(ts_ms)
                self.timestamp_queue = collections.deque(sorted(self.timestamp_queue))

    def _process_buffer(self):
        """
        Process timestamps that are older than the fusion timeout,
        ensuring all relevant cameras have reported.
        """
        if not self.timestamp_queue:
            return

        oldest_ts_ms = self.timestamp_queue[0]

        if (self.latest_device_timestamp_ms - oldest_ts_ms) / 1000 > self.timeout:
            start_ts = self.timestamp_queue[0]
            end_ts = start_ts + self.time_window_ms 

            all_detections_in_window = []

            while self.timestamp_queue and self.timestamp_queue[0] <= end_ts:
                ts_to_pop = self.timestamp_queue.popleft()
                all_detections_in_window.extend(self.detection_buffer.pop(ts_to_pop, []))

            if not all_detections_in_window:
                return

            groups = self._group_detections(all_detections_in_window)
            pruned_groups = self._prune_redundant_detections(groups)

            data_bytes = pickle.dumps(pruned_groups)
            buffer = dai.Buffer()
            buffer.setData(bytearray(data_bytes)) # type: ignore 
            buffer.setTimestamp(datetime.timedelta(milliseconds=start_ts))
            self.output.send(buffer)

    def _prune_redundant_detections(self, groups: List[List[WorldDetection]]) -> List[List[WorldDetection]]:
        """
        For each group, ensure that each camera is represented by at most one detection
        (the one with the highest confidence).
        """
        pruned_groups = []
        for group in groups:
            # dictionary to track the best detection for each device within this group
            best_det_per_cam: Dict[int, WorldDetection] = {}
            
            for det in group:
                cam_id = det.camera_friendly_id
                if cam_id not in best_det_per_cam or det.confidence > best_det_per_cam[cam_id].confidence:
                    best_det_per_cam[cam_id] = det
            
            pruned_groups.append(list(best_det_per_cam.values()))
            
        return pruned_groups

    def _transform_detections_to_world(
        self,
        detections: List[dai.SpatialImgDetection],
        cam_to_world: np.ndarray,
        friendly_id: int
    ) -> List[WorldDetection]:
        world_detections: List[WorldDetection] = []
        for det in detections:
            coords = det.spatialCoordinates

            # filter out ghost detections with z=0
            if coords.z == 0:
                continue

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
