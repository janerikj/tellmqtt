import asyncio
import logging
import threading
import time

import serial

logger = logging.getLogger('tellmqtt')

# in s; how long to wait between attempts to reopen a port that went away
RECONNECT_INTERVAL = 5


class AsyncSerial:
    """asyncio wrapper around a pyserial port.

    Reads happen on a daemon thread and are delivered to an asyncio queue,
    so that readline() can be awaited from the event loop. Writing is done
    directly on the pyserial port.

    The port is opened once, in open_serial(). If it disappears while
    running, the reader thread keeps trying to reopen it, so a tellstick
    that is unplugged and plugged in again is picked up without restarting
    tellmqtt.
    """

    def __init__(self, url, baudrate=9600, reconnect_interval=RECONNECT_INTERVAL):
        self._url = url
        self._baudrate = baudrate
        self._reconnect_interval = reconnect_interval

        self._port = None
        self._queue = asyncio.Queue()
        self._loop = None
        self._thread = None
        self._stop = threading.Event()
        self._reconnect_failures = 0
        self._pending = b''

    def _open(self):
        logger.debug('Opening serial port {} @ {}'.format(self._url, self._baudrate))
        port = serial.Serial(self._url, self._baudrate, timeout=1.0)
        self._port = port
        self._pending = b''

    def _close(self):
        if self._port is not None:
            try:
                self._port.close()
            except Exception as e:
                logger.debug('error closing serial port: {!r}'.format(e))
        self._port = None
        self._pending = b''

    def _reconnect(self):
        """Try to reopen the port until it works or close() is called."""
        while not self._stop.is_set():
            self._reconnect_failures += 1
            try:
                self._open()
            except Exception as e:
                # The stick may be absent for a long time, so only the first
                # failure of a series is worth a warning.
                if self._reconnect_failures == 1:
                    logger.warning(
                        'Serial port {} lost, retrying every {} s: {!r}'.format(
                            self._url, self._reconnect_interval, e))
                else:
                    logger.debug(
                        'retrying serial port {}: {!r}'.format(self._url, e))
            else:
                logger.info('Serial port {} reconnected'.format(self._url))
                self._reconnect_failures = 0
                return
            time.sleep(self._reconnect_interval)

    def _reader(self):
        while not self._stop.is_set():
            if self._port is None:
                # a failed write closed the port
                self._reconnect()
                continue
            try:
                data = self._port.readline()
            except (serial.SerialException, OSError) as e:
                logger.warning(
                    'Serial read error on {}: {!r}'.format(self._url, e))
                self._close()
                self._reconnect()
                continue
            except Exception as e:
                if self._stop.is_set():
                    break
                logger.error(
                    'Unexpected serial reader error: {!r}'.format(e))
                self._close()
                self._reconnect()
                continue

            if not data:
                continue

            # A read timeout may cut a line short, so hold on to the
            # incomplete tail until the rest of it arrives.
            self._pending += data
            *lines, self._pending = self._pending.split(b'\n')
            if not lines:
                continue
            for line in lines:
                if line:
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, line + b'\n')

        self._close()

    async def start(self):
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        return self

    async def readline(self):
        return await self._queue.get()

    @property
    def connected(self):
        return self._port is not None and not self._stop.is_set()

    def write(self, data):
        if not self.connected:
            raise ConnectionError(
                'Serial device {} is not connected'.format(self._url))
        try:
            self._port.write(data)
        except (serial.SerialException, OSError):
            self._close()
            raise

    async def close(self):
        self._stop.set()
        # Let the reader thread finish first, closing the port underneath a
        # blocked read makes pyserial fail.
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._close()


async def open_serial(url, baudrate=9600, reconnect_interval=RECONNECT_INTERVAL):
    port = AsyncSerial(url, baudrate, reconnect_interval)
    try:
        port._open()
    except Exception:
        await port.close()
        raise
    await port.start()
    return port, port
