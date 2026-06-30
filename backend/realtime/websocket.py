"""WebSocketManager and WsSession - WebSocket connection management."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from backend.realtime.events import Event


class WsSession:
    """单个WebSocket连接状态."""

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.subscribed_threads: set[str] = set()
        self.last_seq = 0

    def subscribe(self, thread_id: str) -> None:
        """订阅工作流"""
        self.subscribed_threads.add(thread_id)

    def unsubscribe(self, thread_id: str) -> None:
        """取消订阅"""
        self.subscribed_threads.discard(thread_id)

    def should_receive_event(self, event: Event) -> bool:
        """判断是否应该接收该事件."""
        if event.thread_id is None:
            return True
        return event.thread_id in self.subscribed_threads

    async def send_event(self, event: Event) -> None:
        """推送事件（过滤后）"""
        if self.should_receive_event(event):
            await self.websocket.send_json(event.to_dict())
            self.last_seq = event.seq


class WebSocketManager:
    """全局管理器 - 所有WebSocket连接."""

    _instance: WebSocketManager | None = None

    def __init__(self) -> None:
        self.sessions: dict[str, WsSession] = {}

    @classmethod
    def get_instance(cls) -> WebSocketManager:
        """获取单例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def handle_connection(self, websocket: WebSocket) -> None:
        """处理WebSocket连接生命周期."""
        await websocket.accept()

        # Capture running event loop for thread-safe task scheduling
        loop = asyncio.get_running_loop()

        session = WsSession(websocket)
        session_id = uuid.uuid4().hex
        self.sessions[session_id] = session

        # 订阅EventBus
        from backend.realtime.event_bus import EventBusService

        event_bus = EventBusService.get_instance()

        async def event_handler(event: Event) -> None:
            await session.send_event(event)

        def sync_handler(event: Event) -> None:
            # Use call_soon_threadsafe to safely schedule async task
            # from potentially non-async context (EventBusService.emit is sync)
            loop.call_soon_threadsafe(lambda: asyncio.create_task(event_handler(event)))

        event_bus.subscribe(sync_handler)

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=30.0,
                    )
                    await self._handle_client_message(session, msg)
                except TimeoutError:
                    await websocket.close(code=1001, reason="heartbeat timeout")
                    break

        except WebSocketDisconnect:
            pass
        except Exception:
            await websocket.close(code=1011, reason="internal error")
        finally:
            event_bus.unsubscribe(sync_handler)
            self.sessions.pop(session_id, None)

    async def _handle_client_message(self, session: WsSession, msg: dict) -> None:
        """处理客户端消息."""
        action = msg.get("action")

        if action == "subscribe":
            thread_id = msg.get("thread_id")
            if thread_id:
                session.subscribe(thread_id)

        elif action == "unsubscribe":
            thread_id = msg.get("thread_id")
            if thread_id:
                session.unsubscribe(thread_id)

        elif action == "ping":
            await session.websocket.send_json({"action": "pong"})

        elif action == "get_missed":
            since = msg.get("since", 0)
            from backend.realtime.event_bus import EventBusService

            events = EventBusService.get_instance().get_events_since(since)
            await session.websocket.send_json(
                {
                    "action": "missed_events",
                    "events": [e.to_dict() for e in events],
                }
            )
