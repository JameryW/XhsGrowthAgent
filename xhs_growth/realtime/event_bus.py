"""EventBusService - 单例服务，收集、存储、分发业务事件."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Callable

from xhs_growth.realtime.events import Event, EventType


class EventBusService:
    """单例服务 - 事件收集、分发、存储.

    用于业务模块emit事件，WebSocket订阅推送。
    内存保留最近100条事件用于补传。
    """

    _instance: EventBusService | None = None
    MAX_EVENTS = 100

    def __init__(self):
        self._events: deque[Event] = deque(maxlen=self.MAX_EVENTS)
        self._subscribers: list[Callable[[Event], None]] = []
        self._seq = 0

    @classmethod
    def get_instance(cls) -> EventBusService:
        """获取单例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def emit(
        self,
        event_type: EventType,
        thread_id: str | None,
        payload: dict[str, any],
    ) -> Event:
        """发送事件.

        Args:
            event_type: 事件类型
            thread_id: 工作流ID（None表示全局事件）
            payload: 事件数据

        Returns:
            创建的Event对象
        """
        event = Event(
            event_type=event_type,
            thread_id=thread_id,
            payload=payload,
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            seq=self._seq,
        )
        self._seq += 1
        self._events.append(event)

        # 分发给所有订阅者
        for handler in self._subscribers:
            handler(event)

        return event

    def subscribe(self, handler: Callable[[Event], None]) -> None:
        """订阅事件.

        Args:
            handler: 事件处理函数，接收Event参数
        """
        self._subscribers.append(handler)

    def unsubscribe(self, handler: Callable[[Event], None]) -> None:
        """取消订阅."""
        if handler in self._subscribers:
            self._subscribers.remove(handler)

    def get_events_since(self, since_seq: int) -> list[Event]:
        """获取seq > since_seq的所有事件（用于补传）.

        Args:
            since_seq: 最后收到的事件seq

        Returns:
            事件列表（按seq排序）
        """
        return [e for e in self._events if e.seq > since_seq]