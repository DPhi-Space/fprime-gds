import logging
import struct
from typing import Tuple

from fprime_gds.common.communication.ground import GroundHandler
from fprime_gds.common.transport import (
    RoutingTag,
    ThreadedTransportClient,
    TransportationException,
)


class GrafanaGround(GroundHandler):
    def __init__(self):
        super().__init__()
        print("Using Grafana Ground Handler")

    def open(self):
        pass

    def close(self):
        pass

    def receive_all(self):
        messages = []
        data = None
        messages.append(data)
        return messages

    def send_all(self, frames):
        for packet in frames:
            size_bytes = struct.pack(
                ">I", len(packet)
            )  # Add in size bytes as it was stripped in the downlink protocol
