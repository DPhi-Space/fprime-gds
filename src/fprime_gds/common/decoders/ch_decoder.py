"""
@brief Channel Decoder class used to parse binary channel telemetry data

Decoders are responsible for taking in serialized data and parsing it into
objects. Decoders receive serialized data (that had a specific descriptor) from
a distributer that it has been registered to. The distributer will send the
binary data after removing any length and descriptor headers.

Example data that would be sent to a decoder that parses channels:
    +-------------------+---------------------+------------ - - -
    | ID (4 bytes) | Time Tag (11 bytes) | Data....
    +-------------------+---------------------+------------ - - -

@date Created July 11, 2018
@author R. Joseph Paetz

@bug No known bugs
"""

from fprime.common.models.serialize.time_type import TimeType
from datetime import datetime, timezone
from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.decoders.decoder import Decoder, DecodingException
from fprime_gds.common.utils import config_manager
import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS
from enum import IntEnum


MSB_NODE_MAP = {
    0x5C: "MSPSWITCH",
    0x5B: "MSPFPGA",
    0x5D: "VORAGO",
}

HIGH_LEVEL = ["MPU1", "MPU2", "FPGA", "GPU"]


INFLUXDB_BUCKET = "CG2-QM"
INFLUXDB_ORG = "dphi-space"
INFLUXDB_URL = "http://192.168.11.11:8086/"
INFLUXDB_TOKEN = "V7RxoUQ9KffLTjsVSWPAp6yo8dupHWtWLaTQCImo2FwxEgUoV7i1ZNusydFLGzebfB_BOJsei2lrWMDhbtlpgw=="

client = influxdb_client.InfluxDBClient(
    url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG, timeout=10000, gzip=True
)
write_api = client.write_api(write_options=SYNCHRONOUS)


from datetime import datetime, timezone


def fprime_time_to_datetime(t):
    return datetime.fromtimestamp(
        t.seconds,
        tz=timezone.utc,
    )


def find_node(tlm_id: int, channel_name: str) -> str:
    # 1) MSB-based resolution (authoritative)
    msb = (tlm_id >> 8) & 0xFF

    node = MSB_NODE_MAP.get(msb)
    if node:
        return node

    # 2) Fallback: infer from channel name (case-insensitive)
    name_upper = channel_name.upper()
    for hl_node in HIGH_LEVEL:
        if hl_node in name_upper:
            return hl_node

    return "UNKNOWN"


class ChDecoder(Decoder):
    """Decoder class for Channel data"""

    def __init__(self, ch_dict, config):
        """
        ChDecoder class constructor

        Args:
            ch_dict: Channel telemetry dictionary. Channel IDs should be keys
                     and ChTemplate objects should be values

        Returns:
            An initialized channel decoder object.
        """
        super().__init__()

        if config is None:
            # Retrieve singleton for the configs
            config = config_manager.ConfigManager.get_instance()

        self.__dict = ch_dict
        self.id_obj = config.get_type("FwChanIdType")

    def decode_api(self, data):
        """
        Decodes the given data and returns the result.

        This function allows for non-registered code to call the same decoding
        code as is used to parse data passed to the data_callback function.

        Args:
            data: Binary telemetry channel data to decode

        Returns:
            Parsed version of the channel telemetry data in the form of a
            ChData object or None if the data is not decodable
        """
        ptr = 0

        # list for decoded channel values
        ch_list = []

        while ptr < len(data):
            # Decode Ch ID here...
            self.id_obj.deserialize(data, ptr)
            ptr += self.id_obj.getSize()
            ch_id = self.id_obj.val

            # Decode time...
            ch_time = TimeType()
            ch_time.deserialize(data, ptr)
            ptr += ch_time.getSize()

            if ch_id not in self.__dict:
                msg = f"Channel {ch_id} not found in dictionary"
                raise DecodingException(msg)
            # Retrieve the template instance for this channel
            ch_temp = self.__dict[ch_id]

            try:
                val_obj = self.decode_ch_val(data, ptr, ch_temp)
            except Exception as exc:
                msg = f"Channel {ch_temp.name} failed to decode: {exc}"
                raise DecodingException(msg)
            ch_list.append(ChData(val_obj, ch_time, ch_temp))
            # todo here we put the data into the influxdb

            node = find_node(ch_id, ch_temp.name)
            # print("Channel data: ", node, ch_temp.name, val_obj.val, ch_id)

            ts = fprime_time_to_datetime(ch_time)

            point = (
                influxdb_client.Point(ch_temp.name)
                .tag("id", str(ch_id))
                .tag("node", node)
                .time(ts)
            )

            value = val_obj.val

            if isinstance(value, (list, tuple)):
                for i, v in enumerate(value):
                    point.field(f"value_{i}", int(v))
            else:
                point.field("value", int(value))

            write_api.write(
                bucket=INFLUXDB_BUCKET,
                org=INFLUXDB_ORG,
                record=point,
            )
            ptr += val_obj.getSize()
        return ch_list

    @staticmethod
    def decode_ch_val(val_data, offset, template):
        """
        Decodes the given channel's value from the given data

        Args:
            val_data: Data to parse the value out of
            offset: Location in val_data to start the parsing
            template: Channel Template object for the channel

        Returns:
            The channel's value as an instance of a class derived from
            the BaseType class. The val_data has been deserialized using this
            object, and so the channel value can be retrieved from the obj's
            val field.
        """
        val_obj = template.get_type_obj()()
        val_obj.deserialize(val_data, offset)
        return val_obj
