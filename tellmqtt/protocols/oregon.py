"""
Protocol for oregon

Tested models:
 - THGN132N

With TELLMQTT_OREGON_CHECKSUM set, the checksum is calculated and used to
detect whether a reported 0x1A2D really is a 1D20. If the variable is not
set, tellmqtt runs in telldus-compatible mode: the model reported by the
Tellstick is used as-is, which allows more models to work.
"""

import logging
import os

from tellmqtt.common import protocoldata as pd

logger = logging.getLogger(__name__)

class oregon:
    """
    Oregon Protocol v2.1
    """

    def __init__(self):
        self.protocol = 'oregon'

    def name(self):
        """
        Name of protocol
        """
        return self.protocol

    @staticmethod
    def checksum_enabled() -> bool:
        """
        With checksum enabled a 0x1A2D reported by the Tellstick is
        checked whether it really is a 1D20. If TELLMQTT_OREGON_CHECKSUM
        is not set, the model the Tellstick reports is used as-is
        (telldus-compatible mode).
        """
        return os.getenv("TELLMQTT_OREGON_CHECKSUM", "").strip().lower() not in ("", "0", "false", "no", "off")

    @staticmethod
    def check_checksum(data: str, model: str) -> bool:
        """
        Check checksum for Oregon Protocol v2.1.
        Strips the last four characters from data and prepends model.
        Calculates checksum as sum of nibbles & 0xFF and compares
        to the checksum in data.
        """
        if not data or len(data) < 4:
            return False
        if model.startswith(('0x', '0X')):
            model = model[2:]
        payload = model + data[:-4]
        try:
            calculated_checksum = sum(int(char, 16) for char in payload) & 0xFF
            message_checksum = int(data[-4:-2], 16)
            return calculated_checksum == message_checksum
        except ValueError:
            return False

    @staticmethod
    def decode(msg):
        """
        Decode data and return temperature, humidity and battery status.
        With TELLMQTT_OREGON_CHECKSUM set the checksum is validated and used
        to detect whether a reported 0x1A2D really is a 1D20.
        """
        if not 'model' in msg:
            return None
        model = str(msg['model'])
        if not 'data' in msg:
            return None

        data = str(msg['data'])

        if len(data) < 12:
            # see https://github.com/telldus/telldus/blob/master/telldus-core/service/ProtocolOregon.cpp
            logger.warning("Expected format is Ch[0], Flags[1], Type[2:4], T[4,6,7,9], H[8,11], CRC[-4:], got %s", data)
            return None

        model = model[2:] if model.startswith(('0x', '0X')) else model
        # Model 1D20 (THGN132N) is renamed 1A2D by the Tellstick Duo
        if oregon.checksum_enabled():
            if oregon.check_checksum(data, "1D20"):
                model = "1D20"
            elif oregon.check_checksum(data, model):
                pass
            else:
                logger.warning("Got corrupted data, skipping: '%s'", data)
                return None

        # Channel
        channel = int(data[0])

        # Battery status, bit 2 (0x04) indicates low battery (0 = ok, 1 = low)
        battery = 1 if (int(data[1], 16) & 0x04) else 0

        # Negative temperature flag is bit 3 (0x08)
        is_negative = bool(int(data[9], 16) & 0x08)
        temperature = f"{'-' if is_negative else ''}{data[6]}{data[7]}.{data[4]}"

        humidity = f"{data[11]}{data[8]}"

        # set values
        vals = {}
        vals['temperature'] = float(temperature)
        vals['humidity'] = float(humidity)
        vals['battery'] = battery

        return pd((model, channel), vals)
