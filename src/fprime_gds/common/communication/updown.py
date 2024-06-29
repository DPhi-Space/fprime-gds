""" Uplink and Downlink handling for communications layer

Downlink needs to happen in several stages. First, raw data is read from the adapter. This data is collected in a pool
and the pool is passed to a deframer that extracts frames from this pool. Frames are queued and sent to the ground
side where they are and passed into the ground side handler and onto the other GDS processes. Downlink handles multiple
streams of data the FSW downlink, and loopback data from the uplink adapter.

Uplink is the reverse, it pulls data in from the ground handler, frames it, and sends it up to the waiting FSW. Uplink
is represented by a single thread, as it is not dealing with multiple streams of data that need to be multiplexed.

"""
import logging
import threading
from queue import Empty, Full, Queue

from fprime.common.models.serialize.numerical_types import U32Type

from fprime_gds.common.communication.adapters.base import BaseAdapter
from fprime_gds.common.communication.framing import FramerDeframer
from fprime_gds.common.communication.ground import GroundHandler
from fprime_gds.common.utils.data_desc_type import DataDescType

from cg_protocol import resend_unacked


DW_LOGGER = logging.getLogger("downlink")
UP_LOGGER = logging.getLogger("uplink")

acks = []
rets = []

class Downlinker:
    """Encapsulates communication downlink functions

    Handles downlink creating two threads, one to read and deframe, and the other to send data out to the ground side
    of the system. It is composed of an adapter used to read from the interface, a deframer that is used to deframe
    incoming data, and a ground handler that is used to interact with the ground side of the system.

    Two threaded stages are used to multiplex between loopback data and FSW downlink data without the need to busy spin
    waiting for data.
    """

    def __init__(
        self,
        adapter: BaseAdapter,
        ground: GroundHandler,
        deframer: FramerDeframer,
        discarded=None,
    ):
        """Initialize the downlinker

        Constructs a new downlinker object used to run the downlink and deframing operation. This downlinker will log
        discarded (unframed) data when discarded is a writable data object. When discarded is None the discarded data is
        dropped.

        Args:
            adapter: adapter used to read raw data from the hardware connection
            ground: handles the ground side connection
            deframer: deframer used to deframe data from the communication format
            discarded: file to write discarded data to. None to drop the data.
        """
        self.running = True
        self.th_ground = None
        self.th_data = None
        self.adapter = adapter
        self.ground = ground
        self.deframer = deframer
        self.outgoing = Queue()
        self.discarded = discarded

    def start(self):
        """Starts the downlink pipeline"""
        self.th_ground = threading.Thread(
            target=self.sending, name="DownlinkTTSGroundThread"
        )
        self.th_ground.daemon = True
        self.th_ground.start()
        self.th_data = threading.Thread(
            target=self.deframing, name="DownLinkDeframingThread"
        )
        self.th_data.daemon = True
        self.th_data.start()

    def deframing(self):
        global acks, rets
        """Deframing stage of downlink

        Reads in data from the raw adapter and runs the deframing. Collects data in a pool and continually runs
        deframing against it where possible. Then appends new frames into the outgoing queue.
        """
        pool = b""
        while self.running:
            # Blocks until data is available, but may still return b"" if timeout
            pool += self.adapter.read()
            frames, pool, discarded_data, new_acks, new_rets = self.deframer.deframe_all(pool, no_copy=True)
            if new_acks:
                for ack in new_acks:
                    if ack is not None:
                        acks.append(ack)
            if new_rets:
                for ret in new_rets:
                    if ret is not None:
                        rets.append(ret)
                
            try:
                for frame in frames:
                    self.outgoing.put_nowait(frame)
            except Full:
                DW_LOGGER.warning("GDS ground queue full, dropping frame")
            try:
                if self.discarded is not None:
                    self.discarded.write(discarded_data)
                    self.discarded.flush()
            # Failure to write discarded data should never stop the GDS. Log it and move on.
            except Exception as exc:
                DW_LOGGER.warning("Cannot write discarded data %s", exc)
                self.discarded = None  # Give up on logging further data

    def sending(self):
        """Outgoing stage of downlink

        Adapts the downlink adapter to the rest of the GDS system by draining the outgoing queue and sending those
        packets to the rest of the GDS. This uses the ground send_all method.
        """
        while self.running:
            frames = []
            try:
                # Blocking read of at least one frame, then drain the entire queue
                frames.append(self.outgoing.get(timeout=0.500))
                while not self.outgoing.empty():
                    frames.append(self.outgoing.get_nowait())
            except Empty:
                pass
            self.ground.send_all(frames)

    def stop(self):
        """Stop the thread depends will close the ground resource which may be blocking"""
        self.running = False

    def join(self):
        """Join on the ending threads"""
        for thread in [self.th_data, self.th_ground]:
            if thread is not None:
                thread.join()
        self.discarded = None

    def add_loopback_frame(self, frame):
        """Adds a frame to loopback to ground

        Some uplink processes are virtualized on the ground, and thus must loopback packets. This is used for data
        handshaking that the FSW may not support.

        Args:
            frame: frame to loopback to ground
        """
        try:
            self.outgoing.put_nowait(frame)
        except Full:
            DW_LOGGER.warning("GDS ground queue full, dropping loopback frame")


class Uplinker:
    """Uplinker used to pull data out of the ground layer and send to FSW

    Handles uplink by creating a single thread to read data from the ground layer, frame it, and pass it to the adapter
    to the hardware link to flight software. It is composed of an adapter used to write to the interface, a framer
    that is used to frame outgoing data, and a ground handler that is used to interact with the ground side of the
    system.

    Since there is one stream of data the uplink requires only one thread to run.

    """

    RETRY_COUNT = 3

    def __init__(
        self,
        adapter: BaseAdapter,
        ground: GroundHandler,
        framer: FramerDeframer,
        loopback: Downlinker,
    ):
        """Initializes the uplink class

        Initialize the uplink class using a hardware adapter, ground handler, and framer.
        loopback is used to virtualize the return packet handshake as FSW does not handle that.

        Args:
            adapter: hardware adapter used to write raw outgoing data bytes
            ground: ground handler receiving data from the ground system
            framer: framer used to frame wire bytes
            loopback: used to return handshake packets
        """
        self.th_uplink = None
        self.running = True
        self.ground = ground
        self.adapter = adapter
        self.loopback = loopback
        self.framer = framer

    def start(self):
        """Starts the uplink pipeline"""
        self.th_uplink = threading.Thread(target=self.uplink, name="UplinkThread")
        self.th_uplink.daemon = True
        self.th_uplink.start()

    def uplink(self):
        from cg_protocol import get_unacked_full
        global acks, rets
        """Runs uplink of data from ground to FSW

        Primary stage of the uplink process, reads data from the ground adapter, and passes the rest of the data to the
        framer, and then onto the adapter to send to FSW. Uplink also generates handshake packets as the current FSW
        does not generate handshake packets.
        """
        queued_packets = []
        try:
            while self.running:
                packets = self.ground.receive_all()
                # send packets from gds
                
                for packet in [
                    packet
                    for packet in packets
                    if packet is not None and len(packet) > 0
                ]:
                    queued_packets.append(packet)
                    
                    
                """ for packet in [
                    packet
                    for packet in packets
                    if packet is not None and len(packet) > 0
                ]: """
                if not  get_unacked_full():
                    for packet in list(queued_packets):
                        framed = self.framer.frame(packet)
                        # Uplink handles synchronous retries
                        for retry in range(Uplinker.RETRY_COUNT):
                            if self.adapter.write(framed):
                                self.loopback.add_loopback_frame(
                                    Uplinker.get_handshake(packet)
                                )
                                queued_packets.remove(packet)
                                break
                        else:
                            UP_LOGGER.warning(
                                "Uplink failed to send %d bytes of data after %d retries",
                                len(framed),
                                Uplinker.RETRY_COUNT,
                        )
                # send acks
                if acks is not None and len(acks) > 0:
                    for ack in acks:
                        print(f'[Uplinker] Uplinking ACK {ack}')
                        for retry in range(Uplinker.RETRY_COUNT):
                            if self.adapter.write(ack):
                                self.loopback.add_loopback_frame(
                                    Uplinker.get_handshake(ack)
                                )
                                break
                        else:
                            UP_LOGGER.warning(
                                "Uplink failed to send %d bytes of data after %d retries",
                                len(ack),
                                Uplinker.RETRY_COUNT,
                            )
                    acks = []
                
                # send rets
                if rets is not None and len(rets) > 0:
                    for ret in rets:
                        #print(f'[Uplinker] Uplinking RET {ret}')
                        print(f"[Uplinker] Uplinking RET: {''.join(f'{x:02x}' for x in ret)}")
                        for retry in range(Uplinker.RETRY_COUNT):
                            if self.adapter.write(ret):
                                self.loopback.add_loopback_frame(
                                    Uplinker.get_handshake(ret)
                                )
                                break
                        else:
                            UP_LOGGER.warning(
                                "Uplink failed to send %d bytes of data after %d retries",
                                len(ret),
                                Uplinker.RETRY_COUNT,
                            )
                    rets = []
                    
                #resend packets
                resends = resend_unacked()
                if resends is not None and len(resends) > 0:
                    for resend in resends:
                        #print(f'[Uplinker] Resending Packet {resend}')
                        print(f"[Uplinker] Resending Packet: {''.join(f'{x:02x}' for x in resend)}")
                        for retry in range(Uplinker.RETRY_COUNT):
                            if self.adapter.write(resend):
                                self.loopback.add_loopback_frame(
                                    Uplinker.get_handshake(resend)
                                )
                                break
                        else:
                            UP_LOGGER.warning(
                                "Uplink failed to send %d bytes of data after %d retries",
                                len(resend),
                                Uplinker.RETRY_COUNT,
                            )

                        


                    
                    
                
                        
        # An OSError might occur during shutdown and is harmless. If we are not shutting down, this error should be
        # propagated up the stack.
        except OSError:
            if self.running:
                raise

    def stop(self):
        """Stop the thread depends will close the ground resource which may be blocking"""
        self.running = False

    def join(self):
        """Join on the ending threads"""
        if self.th_uplink is not None:
            self.th_uplink.join()

    @staticmethod
    def get_handshake(packet: bytes) -> bytes:
        """Gets a handshake raw frame from the last packet

        Creates a handshake raw-frame by repeating the contents of the last packet with a handshake descriptor at the
        front.

        Args:
            packet: packet to repeat back out as handshake

        Returns:
            handshake packet
        """
        return U32Type(DataDescType["FW_PACKET_HAND"].value).serialize() + packet
