import asyncio
import os
import unittest
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import serial

from tellmqtt import serialport


def open_pty():
    """Create a pty pair, return (master_fd, slave_name)."""
    master, slave = os.openpty()
    return master, os.ttyname(slave)


def dead_port():
    """A port that fails every read, as a tellstick does when unplugged."""
    class DeadPort:
        def readline(self):
            raise serial.SerialException('device disconnected')

        def write(self, data):
            pass

        def close(self):
            pass

    return DeadPort()


def opens_as(*items):
    """Side effect for serial.Serial() handing out one item per call.

    An item that is an exception is raised instead of returned, which is how
    opening a port that is not there fails.
    """
    items = list(items)
    def open_port(*args, **kwargs):
        item = items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    return open_port


async def wait_until(predicate, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


class TestOpenSerial(IsolatedAsyncioTestCase):
    async def testMissingDeviceRaises(self):
        with self.assertRaises(serial.SerialException):
            await serialport.open_serial('/dev/tellmqtt-no-such-device')

    async def testReadAndWrite(self):
        master, slave = open_pty()
        self.addCleanup(os.close, master)
        port, _ = await serialport.open_serial(slave)
        self.addAsyncCleanup(port.close)

        os.write(master, b'+Wclass:sensor;protocol:fineoffset;data:4970D82884;\r\n')
        self.assertEqual(
            await asyncio.wait_for(port.readline(), timeout=5),
            b'+Wclass:sensor;protocol:fineoffset;data:4970D82884;\r\n')

        port.write(b'+S1\n')
        self.assertTrue(await wait_until(lambda: os.read(master, 64) == b'+S1\n'))

    async def testIncompleteLineHeldUntilComplete(self):
        master, slave = open_pty()
        self.addCleanup(os.close, master)
        port, _ = await serialport.open_serial(slave)
        self.addAsyncCleanup(port.close)

        os.write(master, b'+Wprotocol:orego')
        await asyncio.sleep(0.2)
        self.assertTrue(await wait_until(lambda: port._queue.empty()))

        os.write(master, b'n;model:0x1A2D;data:405F741310063EAA;\r\n')
        self.assertEqual(
            await asyncio.wait_for(port.readline(), timeout=5),
            b'+Wprotocol:oregon;model:0x1A2D;data:405F741310063EAA;\r\n')

    async def testWriteAfterCloseRaises(self):
        master, slave = open_pty()
        self.addCleanup(os.close, master)
        port, _ = await serialport.open_serial(slave)
        self.addAsyncCleanup(port.close)

        await port.close()
        self.assertFalse(port.connected)
        with self.assertRaises(ConnectionError):
            port.write(b'+S1\n')


class TestReconnect(IsolatedAsyncioTestCase):
    async def testResumesReadingWhenPortReopened(self):
        master, slave = open_pty()
        self.addCleanup(os.close, master)

        class OneLinePort:
            """Delivers one line, then fails every read like an unplugged stick."""

            def __init__(self):
                self.closed = False
                self.reads = 0

            def readline(self):
                self.reads += 1
                if self.reads == 1:
                    return b'+T1\n'
                raise serial.SerialException('device disconnected')

            def write(self, data):
                pass

            def close(self):
                self.closed = True

        first = OneLinePort()
        with patch.object(serialport.serial, 'Serial',
                          side_effect=opens_as(first, serial.Serial(slave, 9600, timeout=1.0))):
            port, _ = await serialport.open_serial(slave)
            self.addAsyncCleanup(port.close)

            self.assertEqual(await asyncio.wait_for(port.readline(), timeout=5), b'+T1\n')

            # the reader keeps retrying until the device is back
            os.write(master, b'+T2\n')
            self.assertEqual(await asyncio.wait_for(port.readline(), timeout=5), b'+T2\n')
            self.assertTrue(port.connected)

        self.assertTrue(first.closed)

    async def testRetriesUntilDeviceReturns(self):
        master, slave = open_pty()
        self.addCleanup(os.close, master)

        with patch.object(serialport.serial, 'Serial',
                          side_effect=opens_as(dead_port(), dead_port(),
                                               serial.Serial(slave, 9600, timeout=1.0))):
            port, _ = await serialport.open_serial(slave, reconnect_interval=0.01)
            self.addAsyncCleanup(port.close)

            os.write(master, b'+T2\n')
            self.assertEqual(await asyncio.wait_for(port.readline(), timeout=5), b'+T2\n')

    async def testWarnsOnceForRepeatedFailures(self):
        master, slave = open_pty()
        self.addCleanup(os.close, master)

        # the port opens, but the device is gone and reopening it fails a few
        # times before it shows up again
        gone = serial.SerialException('could not open port')
        with patch.object(serialport.serial, 'Serial',
                          side_effect=opens_as(dead_port(), gone, gone, gone,
                                               serial.Serial(slave, 9600, timeout=1.0))):
            with self.assertLogs('tellmqtt', level='INFO') as cm:
                port, _ = await serialport.open_serial(slave, reconnect_interval=0.01)
                self.addAsyncCleanup(port.close)

                os.write(master, b'+T2\n')
                self.assertEqual(await asyncio.wait_for(port.readline(), timeout=5), b'+T2\n')

        retry_warnings = [line for line in cm.output if 'retrying every' in line]
        self.assertEqual(len(retry_warnings), 1)
        self.assertTrue(retry_warnings[0].startswith('WARNING'))
        self.assertIn('reconnected', ' '.join(cm.output))

    async def testReopensPortAfterWriteError(self):
        master, slave = open_pty()
        self.addCleanup(os.close, master)

        class UnpluggedPort:
            """A port that reads fine but fails to write, as a stick that was
            unplugged without the kernel noticing on the read side does."""

            def __init__(self):
                self.closed = False

            def readline(self):
                return b''

            def write(self, data):
                raise serial.SerialException('device disconnected')

            def close(self):
                self.closed = True

        first = UnpluggedPort()
        with patch.object(serialport.serial, 'Serial',
                          side_effect=opens_as(first, serial.Serial(slave, 9600, timeout=1.0))):
            port, _ = await serialport.open_serial(slave, reconnect_interval=0.01)
            self.addAsyncCleanup(port.close)

            with self.assertRaises(serial.SerialException):
                port.write(b'+S1\n')
            self.assertFalse(port.connected)
            self.assertTrue(first.closed)

            # the reader picks the device up again
            os.write(master, b'+T2\n')
            self.assertEqual(await asyncio.wait_for(port.readline(), timeout=5), b'+T2\n')
            self.assertTrue(port.connected)

    async def testCloseStopsRetryLoop(self):
        _, slave = open_pty()
        with patch.object(serialport.serial, 'Serial', side_effect=lambda *a, **kw: dead_port()):
            port, _ = await serialport.open_serial(slave, reconnect_interval=0.01)

            # a port that never works must not take the reader thread down
            await asyncio.sleep(0.1)
            self.assertTrue(port._thread.is_alive())

            await asyncio.wait_for(port.close(), timeout=5)
            self.assertFalse(port._thread.is_alive())


if __name__ == '__main__':
    unittest.main()
