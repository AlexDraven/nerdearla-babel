from app.ws.connection_manager import ConnectionManager


class FakeWebSocket:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.accepted = False
        self.sent: list[dict] = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        if self.fail:
            raise RuntimeError("conexión caída")
        self.sent.append(payload)


async def test_connect_accepts_and_registers():
    manager = ConnectionManager()
    ws = FakeWebSocket()

    await manager.connect(ws)

    assert ws.accepted
    assert ws in manager._connections


async def test_disconnect_removes_connection():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    await manager.connect(ws)

    await manager.disconnect(ws)

    assert ws not in manager._connections


async def test_disconnect_unknown_connection_is_noop():
    manager = ConnectionManager()
    await manager.disconnect(FakeWebSocket())  # no debe lanzar


async def test_broadcast_sends_to_all_connections():
    manager = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    await manager.connect(ws1)
    await manager.connect(ws2)

    await manager.broadcast({"hello": "world"})

    assert ws1.sent == [{"hello": "world"}]
    assert ws2.sent == [{"hello": "world"}]


async def test_broadcast_removes_only_the_failing_connection():
    manager = ConnectionManager()
    healthy, broken = FakeWebSocket(), FakeWebSocket(fail=True)
    await manager.connect(healthy)
    await manager.connect(broken)

    await manager.broadcast({"a": 1})

    assert healthy in manager._connections
    assert broken not in manager._connections
    assert healthy.sent == [{"a": 1}]


async def test_broadcast_with_no_connections_is_noop():
    manager = ConnectionManager()
    await manager.broadcast({"a": 1})  # no debe lanzar
