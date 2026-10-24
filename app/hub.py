"""WebSocket fan-out hub. `publish_threadsafe` may be called from the sensor thread."""
import asyncio
import json

from fastapi import WebSocket


class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket, initial: dict | None = None):
        await ws.accept()
        self.clients.add(ws)
        if initial is not None:
            await ws.send_text(json.dumps(initial))

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    def count(self) -> int:
        return len(self.clients)

    async def broadcast(self, msg: dict):
        data = json.dumps(msg)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def publish_threadsafe(self, msg: dict):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(msg), self.loop)
