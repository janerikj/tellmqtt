import unittest
import asyncio
import contextlib
import logging
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from amqtt.broker import Broker
from amqtt.mqtt.constants import QOS_1

from tellmqtt.__main__ import mqtt_setup, subscribe_supervisor


def connect_client():
    """Create the real app MQTT client using tellmqtt's own config/cli logic."""
    args = SimpleNamespace(mqttuser=None, mqttpass=None, mqtthost='127.0.0.1', mqttport=1883)
    return mqtt_setup(args)


def force_disconnect(client):
    """Abort the client's current TCP connection to simulate the broker dying.

    amqtt's auto-reconnect can latch onto a connection accepted by the broker
    while it is shutting down; that orphaned connection is never closed, so
    without this the client would never notice the outage.
    """
    handler = getattr(client, '_handler', None)
    writer = getattr(handler, 'writer', None) if handler else None
    stream_writer = getattr(writer, '_writer', None)
    transport = getattr(stream_writer, 'transport', None)
    if transport is not None:
        transport.abort()


async def start_broker():
    broker = Broker()
    await broker.start()
    return broker


async def wait_until(predicate, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


class TestReconnectWithBroker(IsolatedAsyncioTestCase):
    @patch('tellmqtt.__main__._RECONNECT_POLL_INTERVAL', 0.01)
    async def testConnectPublishReconnectPublish(self):
        logging.getLogger('amqtt').setLevel(logging.CRITICAL)

        broker1 = await start_broker()
        client, connect_coro = connect_client()
        try:
            # amqtt Broker listens on the default port 1883
            await connect_coro

            with self.assertLogs('tellmqtt', level='INFO') as cm:
                super_task = asyncio.ensure_future(subscribe_supervisor(client))
                try:
                    # Initial connect and subscribe
                    self.assertTrue(await wait_until(
                        lambda: any('MQTT connected, subscribing' in line for line in cm.output)))

                    # Publish #1: a QOS_1 publish returns once the broker acks it
                    await asyncio.wait_for(
                        client.publish('tellstick/in/test/temperature', b'21.6', qos=QOS_1), timeout=5)

                    # Stop the broker; the client should notice the loss. amqtt's
                    # auto-reconnect may latch onto a connection accepted during
                    # the shutdown window, so force the connection down as well.
                    await broker1.shutdown()
                    force_disconnect(client)
                    self.assertTrue(await wait_until(lambda: not client._connected_state.is_set()))

                    # Start a new broker on the same port and wait for reconnect + re-subscribe
                    broker2 = await start_broker()
                    try:
                        self.assertTrue(await wait_until(lambda: client._connected_state.is_set()))
                        self.assertTrue(await wait_until(
                            lambda: any('MQTT reconnected, re-subscribing' in line for line in cm.output)))

                        # Publish #2 after reconnection
                        await asyncio.wait_for(
                            client.publish('tellstick/in/test/temperature', b'21.7', qos=QOS_1), timeout=5)
                    finally:
                        await broker2.shutdown()
                finally:
                    super_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await super_task
        finally:
            await client.disconnect()


if __name__ == '__main__':
    unittest.main()