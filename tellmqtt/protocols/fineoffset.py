from tellmqtt.common import env_flag, protocoldata as pd
import functools
import logging

logger = logging.getLogger(__name__)

# With TELLMQTT_FINEOFFSET_CHANNEL_IN_TOPIC set, the topic gets dual levels to match other sensors.
# tellstick/in/fineoffset/8/intern/temperature instead of
# tellstick/in/fineoffset/247/temperature
CHANNEL_IN_TOPIC = 'TELLMQTT_FINEOFFSET_CHANNEL_IN_TOPIC'
# The id the probes report holds the channel in the high nibble, as the
# channel + 7, and the probe in the low nibble, 7 for the internal and 8 for
# the external one. The internal probe of a sensor on channel 2 thus reports
# 151 and the external one 152, so the ids of the two probes interleave, from
# 135/136 on channel 1 to 247/248 on channel 8.
CHANNEL_OFFSET = 7
PROBE_INT = 7
PROBE_EXT = 8

# the dipswitches set channel 1-8
CHANNELS = 8


def probe_channel(vid):
    """The probe and the channel the id reports, None if the id is unknown."""
    probe = vid % 16
    channel = vid // 16 - CHANNEL_OFFSET
    if probe not in (PROBE_INT, PROBE_EXT) or not 1 <= channel <= CHANNELS:
        return None
    return ('intern' if probe == PROBE_INT else 'extern', channel)


def topic_path(vid, res):
    if not env_flag(CHANNEL_IN_TOPIC):
        return (vid,)

    probe = probe_channel(vid)
    if probe is None:
        logger.warning('Unknown fineoffset id %s, using it as the only topic level', vid)
        return (vid,)

    name, channel = probe
    # the internal probe has a humidity sensor, the external one reports 0xFF
    if (name == 'intern') != ('humidity' in res):
        logger.warning('Id %s reports %s but %s in the values', vid, name, list(res))
    return (channel, name)


# CRC method is deduced from sample data gather from Telldus sensors using
# https://reveng.sourceforge.io/
#
# width=8 poly=0x31 init=0x00 refin=false refout=false xorout=0x00 check=0xa2
# residue=0x00 name=(none)

@functools.cache
def get_crc_tbl():
    tbl = []

    for crc in range(256):
        for _ in range(8):
            msb_set = crc & 0x80
            crc = (crc << 1) & 0xff
            if msb_set:
                crc ^= 0x31
        tbl.append(crc)

    return tbl


def calc_crc(data: bytes) -> int:
    tbl = get_crc_tbl()
    crc = 0
    for byte in data:
        idx = crc ^ byte
        crc = (crc << 8) & 0xff
        crc ^= tbl[idx]

    return crc


class fineoffset:
    def name(self):
        return 'fineoffset'

    def decode(self, msg):
        data = msg.get('data')
        if data is None:
                return None

        if len(data) != 10:
            # telldus reads the fields from the end of the message, see
            # https://github.com/telldus/telldus/blob/master/telldus-core/service/ProtocolFineoffset.cpp
            # It ignores the last digit, the checksum, which we do verify. The
            # three first digits are the id, see probe_channel, and start with
            # a nibble that is 4 in the data we have seen.
            logger.warning("Expected 10 hex digits, ID[0:3], TEMP[3:6], HUMIDITY[6:8], CRC[8:10], got %s", data)
            return None

        data_bytes = bytes.fromhex(data)
        crc = data_bytes[-1]
        if calc_crc(data_bytes[:-1]) != crc:
            logger.warning("Got corrupted data, skipping: '%s'", data)
            return None

        vid, temp, hum = int(data[:3], 16) & 0xff, int(data[3:6], 16), int(data[6:8], 16)

        res = {
            "temperature": (temp & 0x7ff) / (-10.0 if temp & 0x800 else 10.0),
        }
        if hum <= 100:
            res['humidity'] = hum

        return pd(topic_path(vid, res), res)
