import pytest
from xhs_growth.realtime.event_bus import EventBusService
from xhs_growth.realtime.events import EventType, Event


@pytest.fixture(autouse=True)
def reset_event_bus():
    """每个测试重置单例"""
    EventBusService._instance = None


def test_event_bus_singleton():
    """EventBusService是单例"""
    bus1 = EventBusService.get_instance()
    bus2 = EventBusService.get_instance()
    assert bus1 is bus2


def test_event_bus_emit():
    """emit创建事件并存储"""
    bus = EventBusService.get_instance()

    bus.emit(
        EventType.WORKFLOW_PHASE_CHANGED,
        thread_id="thread_123",
        payload={"new_phase": "planning"},
    )

    # 验证存储（使用-1获取所有事件，包括seq=0）
    events = bus.get_events_since(-1)
    assert len(events) == 1
    assert events[0].event_type == EventType.WORKFLOW_PHASE_CHANGED
    assert events[0].thread_id == "thread_123"
    assert events[0].seq == 0


def test_event_bus_subscribe():
    """订阅者收到事件"""
    bus = EventBusService.get_instance()

    received_events = []
    def handler(event: Event):
        received_events.append(event)

    bus.subscribe(handler)
    bus.emit(EventType.WORKFLOW_STARTED, "thread_123", {"phase": "scouting"})

    assert len(received_events) == 1
    assert received_events[0].event_type == EventType.WORKFLOW_STARTED


def test_event_bus_unsubscribe():
    """取消订阅后不再收到事件"""
    bus = EventBusService.get_instance()

    received_events = []
    def handler(event: Event):
        received_events.append(event)

    bus.subscribe(handler)
    bus.emit(EventType.WORKFLOW_STARTED, "thread_123", {})

    bus.unsubscribe(handler)
    bus.emit(EventType.WORKFLOW_PHASE_CHANGED, "thread_123", {})

    assert len(received_events) == 1  # 只收到第一个


def test_event_bus_get_events_since():
    """补传：获取指定seq之后的事件"""
    bus = EventBusService.get_instance()

    # 发送3个事件
    bus.emit(EventType.WORKFLOW_STARTED, "t1", {})
    bus.emit(EventType.WORKFLOW_PHASE_CHANGED, "t1", {})
    bus.emit(EventType.WORKFLOW_AGENT_STARTED, "t1", {})

    # 获取seq > 0的事件
    events = bus.get_events_since(0)
    assert len(events) == 2
    assert events[0].seq == 1
    assert events[1].seq == 2


def test_event_bus_max_events():
    """事件超过MAX_EVENTS时，旧事件被丢弃"""
    bus = EventBusService.get_instance()

    # 发送超过100个事件
    for i in range(150):
        bus.emit(EventType.WORKFLOW_STARTED, f"t{i}", {"index": i})

    # 只有最近100个事件保留
    events = bus.get_events_since(0)
    assert len(events) == 100
    # 最早保留的是seq=50
    assert events[0].seq == 50


def test_event_bus_seq_increment():
    """seq连续递增"""
    bus = EventBusService.get_instance()

    bus.emit(EventType.WORKFLOW_STARTED, "t1", {})
    bus.emit(EventType.WORKFLOW_PHASE_CHANGED, "t1", {})

    # 使用-1获取所有事件，包括seq=0
    events = bus.get_events_since(-1)
    assert events[0].seq == 0
    assert events[1].seq == 1