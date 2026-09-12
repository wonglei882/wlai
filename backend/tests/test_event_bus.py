"""EventBus unit tests."""
import asyncio
import pytest
from app.services.core.event_bus import EventBus


@pytest.fixture
def bus():
    return EventBus()


class TestRegisterUnregister:
    def test_register_handler(self, bus):
        handler = lambda **kw: None
        bus.register('test.event', handler, handler_id='h1')
        assert len(bus._listeners['test.event']) == 1

    def test_register_dedup(self, bus):
        handler = lambda **kw: None
        bus.register('test.event', handler, handler_id='h1')
        bus.register('test.event', handler, handler_id='h1')
        assert len(bus._listeners['test.event']) == 1

    def test_unregister(self, bus):
        handler = lambda **kw: None
        bus.register('test.event', handler, handler_id='h1')
        bus.unregister('test.event', 'h1')
        assert len(bus._listeners['test.event']) == 0

    def test_multiple_handlers(self, bus):
        h1 = lambda **kw: None
        h2 = lambda **kw: None
        bus.register('test.event', h1, handler_id='h1')
        bus.register('test.event', h2, handler_id='h2')
        assert len(bus._listeners['test.event']) == 2


class TestEmit:
    def test_sync_handler_called(self, bus):
        called = []
        bus.register('test.event', lambda **kw: called.append(1), handler_id='h1')
        bus.emit('test.event')
        assert called == [1]

    def test_sync_handler_receives_kwargs(self, bus):
        received = []
        bus.register('test.event', lambda **kw: received.append(kw), handler_id='h1')
        bus.emit('test.event', foo='bar', baz=42)
        assert received == [{'foo': 'bar', 'baz': 42}]

    def test_exception_isolation(self, bus):
        results = []

        def bad_handler(**kw):
            raise ValueError('boom')

        def good_handler(**kw):
            results.append('ok')

        bus.register('test.event', bad_handler, handler_id='bad')
        bus.register('test.event', good_handler, handler_id='good')
        bus.emit('test.event')
        assert results == ['ok']

    @pytest.mark.asyncio
    async def test_async_handler(self, bus):
        results = []

        async def async_handler(**kw):
            results.append('async_ok')

        bus.register('test.event', async_handler, handler_id='ah1')
        bus.emit('test.event')
        await asyncio.sleep(0.1)
        assert results == ['async_ok']

    def test_no_listeners(self, bus):
        bus.emit('nonexistent.event')

    def test_emit_no_running_loop_fallback(self, bus):
        handler = lambda **kw: None
        bus.register('test.event', handler, handler_id='h1')
        bus.emit('test.event')
