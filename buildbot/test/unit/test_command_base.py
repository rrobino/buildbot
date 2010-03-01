import sys

from twisted.trial import unittest
from twisted.internet import task, defer

from buildbot.slave.commands.base import SlaveShellCommand, ShellCommand, Obfuscated, \
    DummyCommand, WaitCommand, waitCommandRegistry
from buildbot.slave.commands.utils import getCommand

class FakeSlaveBuilder:
    debug = False
    def __init__(self, usePTY, basedir):
        self.updates = []
        self.basedir = basedir
        self.usePTY = usePTY

    def sendUpdate(self, data):
        if self.debug:
            print "FakeSlaveBuilder.sendUpdate", data
        self.updates.append(data)

class TestLogging(unittest.TestCase):
    def testSendStatus(self):
        basedir = "test_command_base.logging.sendStatus"
        b = FakeSlaveBuilder(False, basedir)
        s = ShellCommand(b, ['echo', 'hello'], basedir)
        s.sendStatus({'stdout': 'hello\n'})
        self.failUnlessEqual(b.updates, [{'stdout': 'hello\n'}])

    def testSendBuffered(self):
        basedir = "test_command_base.logging.sendBuffered"
        b = FakeSlaveBuilder(False, basedir)
        s = ShellCommand(b, ['echo', 'hello'], basedir)
        s._addToBuffers('stdout', 'hello ')
        s._addToBuffers('stdout', 'world')
        s._sendBuffers()
        self.failUnlessEqual(b.updates, [{'stdout': 'hello world'}])

    def testSendBufferedInterleaved(self):
        basedir = "test_command_base.logging.sendBufferedInterleaved"
        b = FakeSlaveBuilder(False, basedir)
        s = ShellCommand(b, ['echo', 'hello'], basedir)
        s._addToBuffers('stdout', 'hello ')
        s._addToBuffers('stderr', 'DIEEEEEEE')
        s._addToBuffers('stdout', 'world')
        s._sendBuffers()
        self.failUnlessEqual(b.updates, [
            {'stdout': 'hello '},
            {'stderr': 'DIEEEEEEE'},
            {'stdout': 'world'},
            ])

    def testSendChunked(self):
        basedir = "test_command_base.logging.sendBufferedChunked"
        b = FakeSlaveBuilder(False, basedir)
        s = ShellCommand(b, ['echo', 'hello'], basedir)
        data = "x" * ShellCommand.CHUNK_LIMIT * 2
        s._addToBuffers('stdout', data)
        s._sendBuffers()
        self.failUnless(len(b.updates), 2)

    def testSendNotimeout(self):
        basedir = "test_command_base.logging.sendNotimeout"
        b = FakeSlaveBuilder(False, basedir)
        s = ShellCommand(b, ['echo', 'hello'], basedir)
        data = "x" * (ShellCommand.BUFFER_SIZE + 1)
        s._addToBuffers('stdout', data)
        self.failUnless(len(b.updates), 1)

class TestObfuscated(unittest.TestCase):
    def testSimple(self):
        c = Obfuscated('real', '****')
        self.failUnlessEqual(str(c), '****')
        self.failUnlessEqual(repr(c), "'****'")

    def testObfuscatedCommand(self):
        cmd = ['echo', Obfuscated('password', '*******')]

        self.failUnlessEqual(['echo', 'password'], Obfuscated.get_real(cmd))
        self.failUnlessEqual(['echo', '*******'], Obfuscated.get_fake(cmd))

    def testObfuscatedNonString(self):
        cmd = ['echo', 1]
        self.failUnlessEqual(['echo', '1'], Obfuscated.get_real(cmd))
        self.failUnlessEqual(['echo', '1'], Obfuscated.get_fake(cmd))

    def testObfuscatedNonList(self):
        cmd = 1
        self.failUnlessEqual(1, Obfuscated.get_real(cmd))
        self.failUnlessEqual(1, Obfuscated.get_fake(cmd))

class TestUtils(unittest.TestCase):
    def testGetCommand(self):
        self.failUnlessEqual(sys.executable, getCommand(sys.executable))

    def testGetBadCommand(self):
        self.failUnlessRaises(RuntimeError, getCommand, "bad_command_that_really_would_never_exist.bat")

class TestDummy(unittest.TestCase):
    def testDummy(self):
        basedir = "test_command_base.dummy.dummy"
        b = FakeSlaveBuilder(False, basedir)
        c = DummyCommand(b, 1, {})
        c._reactor = task.Clock()
        d = c.doStart()
        def _check(ign):
            self.failUnless({'rc': 0} in b.updates, b.updates)
            self.failUnless({'stdout': 'data'} in b.updates, b.updates)
        d.addCallback(_check)

        # Advance by 2 seconds so that doStatus gets fired
        c._reactor.advance(2)
        # Now advance by 5 seconds so that finished gets fired
        c._reactor.advance(5)

        return d

    def testDummyInterrupt(self):
        basedir = "test_command_base.dummy.interrupt"
        b = FakeSlaveBuilder(False, basedir)
        c = DummyCommand(b, 1, {})
        c._reactor = task.Clock()
        d = c.doStart()
        def _check(ign):
            self.failUnlessEqual(c.interrupted, True)
            self.failUnless({'rc': 1} in b.updates, b.updates)
            self.failUnless({'stdout': 'data'} in b.updates, b.updates)
        d.addCallback(_check)

        # Advance by 2 seconds so that doStatus gets fired
        c._reactor.advance(2)
        # Now interrupt it
        c.interrupt()

        return d

    def testDummyInterruptTwice(self):
        basedir = "test_command_base.dummy.interruptTwice"
        b = FakeSlaveBuilder(False, basedir)
        c = DummyCommand(b, 1, {})
        c._reactor = task.Clock()
        d = c.doStart()
        def _check(ign):
            self.failUnlessEqual(c.interrupted, True)
            self.failUnless({'rc': 1} in b.updates, b.updates)
            self.failUnless({'stdout': 'data'} not in b.updates, b.updates)
        d.addCallback(_check)

        # Don't advance the clock to precent doStatus from being fired

        # Now interrupt it, twice!
        c.interrupt()
        c._reactor.advance(1)
        c.interrupt()

        return d

class TestWait(unittest.TestCase):
    def testWait(self):
        basedir = "test_command_base.wait.wait"
        b = FakeSlaveBuilder(False, basedir)
        clock = task.Clock()

        def cb():
            d = defer.Deferred()
            clock.callLater(1, d.callback, None)
            return d

        waitCommandRegistry['foo'] = cb

        w = WaitCommand(b, 1, {'handle': 'foo'})
        w._reactor = clock

        d1 = w.doStart()

        def _check(ign):
            self.failUnless({'rc': 0} in b.updates, b.updates)
            self.failUnlessEqual(w.interrupted, False)
        d1.addCallback(_check)
        # Advance 1 second to get our callback called
        clock.advance(1)
        # Advance 1 second to call the callback's deferred (the d returned by
        # cb)
        clock.advance(1)
        return d1

    def testWaitInterrupt(self):
        basedir = "test_command_base.wait.interrupt"
        b = FakeSlaveBuilder(False, basedir)
        clock = task.Clock()

        def cb():
            d = defer.Deferred()
            clock.callLater(1, d.callback, None)
            return d

        waitCommandRegistry['foo'] = cb

        w = WaitCommand(b, 1, {'handle': 'foo'})
        w._reactor = clock

        d1 = w.doStart()

        def _check(ign):
            self.failUnless({'rc': 2} in b.updates, b.updates)
            self.failUnlessEqual(w.interrupted, True)
        d1.addCallback(_check)
        # Advance 1 second to get our callback called
        clock.advance(1)

        # Now interrupt it
        w.interrupt()
        # And again, to make sure nothing bad happened
        clock.advance(0.1)
        w.interrupt()
        return d1

    def testWaitFailed(self):
        basedir = "test_command_base.wait.failed"
        b = FakeSlaveBuilder(False, basedir)
        clock = task.Clock()

        def cb():
            d = defer.Deferred()
            clock.callLater(1, d.errback, AssertionError())
            return d

        waitCommandRegistry['foo'] = cb

        w = WaitCommand(b, 1, {'handle': 'foo'})
        w._reactor = clock

        d1 = w.doStart()

        def _check(ign):
            self.failUnless({'rc': 1} in b.updates, b.updates)
            self.failUnlessEqual(w.interrupted, False)
        d1.addCallback(_check)
        # Advance 1 second to get our callback called
        clock.advance(1)

        # Advance 1 second to call the callback's deferred (the d returned by
        # cb)
        clock.advance(1)
        return d1