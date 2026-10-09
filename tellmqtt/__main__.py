import logging
import asyncio
import os
import time
from collections import deque

from amqtt.client import MQTTClient
from amqtt.mqtt.constants import QOS_0, QOS_1, QOS_2

import tellmqtt
import tellmqtt.tellstickhandler
import tellmqtt.mqtthandler

import tellmqtt.fake.serial as fake_serial
import tellmqtt.serialport

import argparse

logger = logging.getLogger('tellmqtt')

def getopt():
    parser = argparse.ArgumentParser(add_help=False) # no add_help as we want -h for host
    parser.add_argument('--help', action="help", help="Show help message and exit.")
    parser.add_argument('-h', '--host',
                        dest="mqtthost", default=os.environ.get('TELLMQTT_HOST', 'localhost'),
                        help="MQTT broker host. Default: %(default)s")
    parser.add_argument('-p', '--port',
                        dest="mqttport", type=int, default=int(os.environ.get('TELLMQTT_PORT', '1883')),
                        help="MQTT broker port. Default: from TELLMQTT_PORT environment variable")
    parser.add_argument('-u', '--mqtt-user',
                        dest="mqttuser", default=os.environ.get('TELLMQTT_USER'),
                        help="MQTT username. Default: from TELLMQTT_USER environment variable")
    parser.add_argument('-P', '--mqtt-password',
                        dest="mqttpass", default=os.environ.get('TELLMQTT_PASSWORD'),
                        help="MQTT password. Default: from TELLMQTT_PASSWORD environment variable")

    parser.add_argument('-d', '--device',
                        dest="device", default="/dev/tellstickDuo",
                        help="Tellstick device. Default: %(default)s")

    args = parser.parse_args()
    return args

def serial_setup(args):
    if args.device != 'fake':
        return tellmqtt.serialport.open_serial(args.device, baudrate=9600)
    else:
        return fake_serial.open_serial_connection()

def mqtt_setup(args):
    client = MQTTClient(client_id="tellmqtt", config={
        'auto_reconnect': True,
        'reconnect_retries': -1,
        'reconnect_max_interval': 30,
        'keep_alive': 30,
        'ping_delay': 2,
    })
    if args.mqttuser and args.mqttpass:
        uri = 'mqtt://{}:{}@{}:{}/'.format(args.mqttuser, args.mqttpass, args.mqtthost, args.mqttport)
    else:
        uri = 'mqtt://{}:{}/'.format(args.mqtthost, args.mqttport)
    return client, client.connect(uri)

# in ms; 0 disables duplicate suppression
DEDUP_WINDOW_MS = int(os.environ.get('TELLMQTT_DEDUP_WINDOW_MS', '0'))


class DuplicateFilter:
    """Suppress identical outputs arriving within a short time window.

    Sensors often repeat a transmission; only the first identical result
    within the window is published. Repeats may differ at the raw line level
    (e.g. unused bits), so deduplication happens on key, which in the caller
    is the tuple of (topic, payload) to be published. Entries older than the
    window are forgotten.
    """

    def __init__(self, window_ms=0):
        self.window_s = window_ms / 1000 if window_ms > 0 else 0
        self._recent = deque()

    def suppress(self, key):
        if self.window_s <= 0:
            return False
        now = time.monotonic()
        while self._recent and now - self._recent[0][0] > self.window_s:
            self._recent.popleft()
        for ts, seen in self._recent:
            if seen == key:
                return True
        self._recent.append((now, key))
        return False


async def readproc(serialread, mqttclient, mqtt, stick, ready):
    duplicate_filter = DuplicateFilter(DEDUP_WINDOW_MS)
    while True:
        rawline = await serialread.readline()
        ret = stick.decode(rawline)
        if ret:
            outs = mqtt.createpost(ret)
            if duplicate_filter.suppress(tuple(outs)):
                logger.debug('duplicate output suppressed')
                continue
            for (path,data) in outs:
                logger.debug("{!r} -> {!r}".format(path,data))
            tasks = [
                asyncio.ensure_future(mqttclient.publish(path, data)) for (path,data) in outs
            ]
            await asyncio.wait(tasks)
            for task in tasks:
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc is not None:
                    logger.error('publish failed: %r', exc)
        else:
            ready.set()

# in s
_RECONNECT_POLL_INTERVAL = 1

async def subscribe_supervisor(mqttclient):
    reconnected = False
    while True:
        await mqttclient._connected_state.wait()
        if reconnected:
            logger.info("MQTT reconnected, re-subscribing")
        else:
            logger.info("MQTT connected, subscribing")
        await mqttclient.subscribe([('tellstick/out/#', QOS_0)])
        reconnected = True
        while mqttclient._connected_state.is_set():
            await asyncio.sleep(_RECONNECT_POLL_INTERVAL)

async def writeproc(serialwrite, mqttclient, mqtt, stick, ready):
    while True:
        try:
            message = await mqttclient.deliver_message()
            packet = message.publish_packet
            dec = mqtt.decodepost(packet.variable_header.topic_name, packet.payload.data)
            logger.debug('decoded to {!r}'.format(dec))
            out = stick.encode(*dec)
            if out:
                logger.debug('write {!r}'.format(out))
                await ready.wait()
                serialwrite.write(out + b'\n')
                ready.clear()
            else:
                logger.debug('no output')
        except ConnectionError as e:
            logger.warning('tellstick not connected, dropping command: %r', e)
        except Exception as e:
            logger.error('error handling outgoing message: %r', e)

async def main(opts):
    try:
        client, co = mqtt_setup(opts)
        await co
    except:
        logger.critical("Error connecting to MQTT broker")
        return

    try:
        r,w = await serial_setup(opts)
    except Exception as e:
        logger.critical("Error opening tellstick device: {!r}".format(e))
        await client.disconnect()
        return

    stickhandler = tellmqtt.tellstickhandler.TellstickHandler()
    mqtthandler = tellmqtt.mqtthandler.MqttHandler()

    # kludge: use ackevent to signal that the stick is ready for another command.
    # to be rewritten.
    ackevent = asyncio.Event()
    ackevent.set()

    try:
        await asyncio.gather(
            readproc(r, client, mqtthandler, stickhandler, ackevent),
            writeproc(w, client, mqtthandler, stickhandler, ackevent),
            subscribe_supervisor(client),
        )
    finally:
        await r.close()
        await client.disconnect()

def setup_logging():
    logging.disable(logging.NOTSET)
    logging.basicConfig(
        datefmt='[%Y-%m-%dT%H:%M:%S%z]',
        format='%(asctime)s %(levelname)-8s %(name)s: %(message)s',
    )
    level = os.environ.get('TELLMQTT_LOG_LEVEL', 'INFO').upper()
    if not hasattr(logging, level):
        logger.warning('Unknown TELLMQTT_LOG_LEVEL %r, defaulting to INFO', level)
        level = 'INFO'
    logger.setLevel(getattr(logging, level))

if __name__ == '__main__':
    setup_logging()
    opts = getopt()
    logger.debug("starting")
    asyncio.run(main(opts))
