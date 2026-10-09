import unittest
import os
from unittest.mock import patch

import tellmqtt.tellstickhandler
from tellmqtt.protocols.fineoffset import CHANNEL_IN_TOPIC, probe_channel, topic_path
import json

class TestFineoffset(unittest.TestCase):
    def setUp(self):
        self.handler = tellmqtt.tellstickhandler.TellstickHandler()

    def testFineoffsetTemperatureSensor(self):
        r = self.handler.decode(b'+Wclass:sensor;protocol:fineoffset;data:49801AFF9E;\r\n')
        self.assertIsNotNone(r)
        self.assertEqual(('fineoffset',152), r.path)
        self.assertIn('temperature', r.values)
        self.assertAlmostEqual(r.values['temperature'], 2.6)
        self.assertNotIn('humidity', r.values)

        self.assertIn('json', r.values)
        vals = json.loads(r.values['json'])
        self.assertIn('temperature', vals)
        self.assertAlmostEqual(vals['temperature'], 2.6)
        self.assertNotIn('humidity', vals)

    def testFineoffsetTemperatureSensorNegative(self):
        r = self.handler.decode(b'+Wclass:sensor;protocol:fineoffset;data:49881FFFBB;\r\n')
        self.assertIsNotNone(r)
        self.assertEqual(('fineoffset',152), r.path)
        self.assertIn('temperature', r.values)
        self.assertAlmostEqual(r.values['temperature'], -3.1)
        self.assertNotIn('humidity', r.values)

        self.assertIn('json', r.values)
        vals = json.loads(r.values['json'])
        self.assertIn('temperature', vals)
        self.assertAlmostEqual(vals['temperature'], -3.1)
        self.assertNotIn('humidity', vals)

    def testFineoffsetTemperatureHumiditySensor(self):
        r = self.handler.decode(b'+Wclass:sensor;protocol:fineoffset;data:4970D82884;\r\n')
        self.assertIsNotNone(r)
        self.assertEqual(('fineoffset',151), r.path)
        self.assertIn('temperature', r.values)
        self.assertAlmostEqual(r.values['temperature'], 21.6)
        self.assertIn('humidity', r.values)
        self.assertAlmostEqual(r.values['humidity'], 40)

        self.assertIn('json', r.values)
        vals = json.loads(r.values['json'])
        self.assertIn('temperature', vals)
        self.assertAlmostEqual(vals['temperature'], 21.6)
        self.assertIn('humidity', vals)
        self.assertAlmostEqual(vals['humidity'], 40)

    def testFineoffsetChannelInTopicDisabledByDefault(self):
        with patch.dict(os.environ):
            os.environ.pop(CHANNEL_IN_TOPIC, None)
            r = self.handler.decode(b'+Wclass:sensor;protocol:fineoffset;data:4970D82884;\r\n')
            self.assertIsNotNone(r)
            self.assertEqual(('fineoffset',151), r.path)

    def testFineoffsetInternalSensorChannelInTopic(self):
        with patch.dict(os.environ, {CHANNEL_IN_TOPIC: '1'}):
            r = self.handler.decode(b'+Wclass:sensor;protocol:fineoffset;data:4970D82884;\r\n')
            self.assertIsNotNone(r)
            self.assertEqual(('fineoffset',2,'intern'), r.path)

            # the values themselves do not depend on the topic levels
            self.assertIn('temperature', r.values)
            self.assertAlmostEqual(r.values['temperature'], 21.6)
            self.assertIn('humidity', r.values)
            self.assertAlmostEqual(r.values['humidity'], 40)

            self.assertIn('json', r.values)
            vals = json.loads(r.values['json'])
            self.assertAlmostEqual(vals['temperature'], 21.6)
            self.assertAlmostEqual(vals['humidity'], 40)

    def testFineoffsetExternalSensorChannelInTopic(self):
        with patch.dict(os.environ, {CHANNEL_IN_TOPIC: '1'}):
            r = self.handler.decode(b'+Wclass:sensor;protocol:fineoffset;data:49801AFF9E;\r\n')
            self.assertIsNotNone(r)
            self.assertEqual(('fineoffset',2,'extern'), r.path)

            self.assertIn('temperature', r.values)
            self.assertAlmostEqual(r.values['temperature'], 2.6)
            self.assertNotIn('humidity', r.values)

            self.assertIn('json', r.values)
            vals = json.loads(r.values['json'])
            self.assertAlmostEqual(vals['temperature'], 2.6)
            self.assertNotIn('humidity', vals)

    def testFineoffsetProbeChannel(self):
        # the ids reported by the sensors we have seen
        self.assertEqual(('intern',2), probe_channel(151))
        self.assertEqual(('extern',2), probe_channel(152))
        self.assertEqual(('intern',7), probe_channel(231))
        self.assertEqual(('intern',8), probe_channel(247))
        self.assertEqual(('extern',8), probe_channel(248))

    def testFineoffsetProbeChannelAllChannels(self):
        for channel in range(1, 9):
            self.assertEqual(('intern',channel), probe_channel((channel + 7) * 16 + 7))
            self.assertEqual(('extern',channel), probe_channel((channel + 7) * 16 + 8))

    def testFineoffsetProbeChannelUnknownId(self):
        # ids whose low nibble is neither 7 nor 8
        self.assertIsNone(probe_channel(147))
        self.assertIsNone(probe_channel(148))
        self.assertIsNone(probe_channel(171))
        self.assertIsNone(probe_channel(118))
        self.assertIsNone(probe_channel(249))
        self.assertIsNone(probe_channel(250))
        # ids whose high nibble gives a channel below 1, an id is one byte so
        # the channel cannot get above 8
        self.assertIsNone(probe_channel(103))
        self.assertIsNone(probe_channel(104))

    def testFineoffsetUnknownIdKeepsIdInTopic(self):
        with patch.dict(os.environ, {CHANNEL_IN_TOPIC: '1'}):
            with self.assertLogs('tellmqtt.protocols.fineoffset', level='WARNING'):
                self.assertEqual((171,), topic_path(171, {'temperature': 1.0}))

    def testFineoffsetExternalIdWithHumidityWarns(self):
        with patch.dict(os.environ, {CHANNEL_IN_TOPIC: '1'}):
            with self.assertLogs('tellmqtt.protocols.fineoffset', level='WARNING'):
                self.assertEqual((2,'extern'), topic_path(152, {'temperature': 1.0, 'humidity': 40}))

class TestOregon(unittest.TestCase):
    def setUp(self):
        self.handler = tellmqtt.tellstickhandler.TellstickHandler()

    def testOregonTemperatureHumiditySensorChecksumDisabled(self):
        os.environ.pop('TELLMQTT_OREGON_CHECKSUM', None)
        r = self.handler.decode(b'+Wclass:sensor;protocol:oregon;model:0x1A2D;data:405F741310063EAA;\r\n')
        self.assertIsNotNone(r)
        self.assertEqual(('oregon',4,'1A2D'), r.path)
        self.assertIn('temperature', r.values)
        self.assertAlmostEqual(r.values['temperature'], 13.7)
        self.assertIn('humidity', r.values)
        self.assertAlmostEqual(r.values['humidity'], 61.0)
        self.assertIn('battery', r.values)
        self.assertEqual(r.values['battery'], 0)

        self.assertIn('json', r.values)
        vals = json.loads(r.values['json'])
        self.assertIn('temperature', vals)
        self.assertAlmostEqual(vals['temperature'], 13.7)
        self.assertIn('humidity', vals)
        self.assertAlmostEqual(vals['humidity'], 61.0)
        self.assertEqual(vals['battery'], 0)

    def testOregonTemperatureHumiditySensorChecksumEnabled(self):
        os.environ['TELLMQTT_OREGON_CHECKSUM'] = 'true'
        r = self.handler.decode(b'+Wclass:sensor;protocol:oregon;model:0x1A2D;data:405F741310063EAA;\r\n')
        self.assertIsNotNone(r)
        self.assertEqual(('oregon',4,'1D20'), r.path)
        self.assertIn('temperature', r.values)
        self.assertAlmostEqual(r.values['temperature'], 13.7)
        self.assertIn('humidity', r.values)
        self.assertAlmostEqual(r.values['humidity'], 61.0)
        self.assertIn('battery', r.values)
        self.assertEqual(r.values['battery'], 0)

class TestMandolyn(unittest.TestCase):
    def setUp(self):
        self.handler = tellmqtt.tellstickhandler.TellstickHandler()

    def testMandolynTemperatureHumiditySensor(self):
        r = self.handler.decode(b'+Wclass:sensor;protocol:mandolyn;model:temperaturehumidity;data:0x5B323FC9;\r\n')
        self.assertIsNotNone(r)
        self.assertEqual(('mandolyn',3,5), r.path)
        self.assertIn('temperature', r.values)
        self.assertAlmostEqual(r.values['temperature'], 13.8)
        self.assertIn('humidity', r.values)
        self.assertAlmostEqual(r.values['humidity'], 50)
        self.assertIn('battery', r.values)
        self.assertEqual(r.values['battery'], 0)

        self.assertIn('json', r.values)
        vals = json.loads(r.values['json'])
        self.assertIn('temperature', vals)
        self.assertAlmostEqual(vals['temperature'], 13.8)
        self.assertIn('humidity', vals)
        self.assertAlmostEqual(vals['humidity'], 50)
        self.assertEqual(vals['battery'], 0)

    def testMandolynTemperatureHumiditySensorLowBattery(self):
        r = self.handler.decode(b'+Wclass:sensor;protocol:mandolyn;model:temperaturehumidity;data:0x57B43FCB;\r\n')
        self.assertIsNotNone(r)
        self.assertEqual(('mandolyn',2,5), r.path)
        self.assertIn('temperature', r.values)
        self.assertAlmostEqual(r.values['temperature'], 13.8)
        self.assertIn('humidity', r.values)
        self.assertAlmostEqual(r.values['humidity'], 52)
        self.assertIn('battery', r.values)
        self.assertEqual(r.values['battery'], 1)
