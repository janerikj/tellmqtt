import unittest

from tellmqtt.__main__ import DuplicateFilter


class TestDuplicateFilter(unittest.TestCase):
    def testFirstOutputPublished(self):
        f = DuplicateFilter(window_ms=1000)
        self.assertFalse(f.suppress(('topic', b'value')))

    def testDuplicateWithinWindowSuppressed(self):
        f = DuplicateFilter(window_ms=1000)
        key = ('topic', b'value')
        self.assertFalse(f.suppress(key))
        self.assertTrue(f.suppress(key))

    def testOtherOutputsNotSuppressed(self):
        f = DuplicateFilter(window_ms=1000)
        self.assertFalse(f.suppress(('a', b'x')))
        self.assertFalse(f.suppress(('b', b'x')))
        self.assertTrue(f.suppress(('b', b'x')))

    def testSameTopicDifferentPayloadNotSuppressed(self):
        f = DuplicateFilter(window_ms=1000)
        self.assertFalse(f.suppress(('topic', b'1')))
        self.assertFalse(f.suppress(('topic', b'2')))

    def testExpiredEntryForgotten(self):
        f = DuplicateFilter(window_ms=100)
        key = ('topic', b'value')
        self.assertFalse(f.suppress(key))
        ts, seen = f._recent.popleft()
        f._recent.appendleft((ts - 0.2, seen))
        self.assertFalse(f.suppress(key))
        self.assertTrue(f.suppress(key))

    def testDisabledWhenWindowZero(self):
        f = DuplicateFilter(window_ms=0)
        key = ('topic', b'value')
        self.assertFalse(f.suppress(key))
        self.assertFalse(f.suppress(key))

    def testDisabledWhenWindowNegative(self):
        f = DuplicateFilter(window_ms=-10)
        self.assertFalse(f.suppress(('a', b'x')))
        self.assertFalse(f.suppress(('a', b'x')))


if __name__ == '__main__':
    unittest.main()