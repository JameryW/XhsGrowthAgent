---
title: 实时更新系统设计
date: 2026-05-26
module: Module 1 - Real-time Updates
status: approved
---

# 实时更新系统设计文档

## 1. 概述

为XhsGrowthAgent前端应用建立WebSocket实时通信系统，推送所有业务事件（工作流、审核、分析），替代现有的轮询机制，提升用户体验和系统响应性。

## 2. 需求

### 2.1 功能需求
- 推送所有业务事件：工作流状态、审核结果、分析数据
- 单一WebSocket端点连接
- 自动重连机制
- 状态指示器显示连接状态
- 消息补传（断线期间丢失的事件）

### 2.2 非功能需求
- 断线自动重连，指数退避策略（1s → 2s → 4s → ... → 30s max）
- 心跳检测（25秒ping/pong）
- 最多重连5次
- 内存保留最近100条事件用于补传

## 3. 架构设计

### 3.1 整体架构

```
Frontend                          Backend
┌────────────────────┐            ┌────────────────────┐
│ Pinia Stores       │            │ Business Modules   │
│  - WorkflowStore   │            │  - Graph nodes     │
│  - ReviewStore     │            │  - Review routes   │
│  - AnalyticsStore  │            │  - Analytics svc   │
└─────────┬──────────┘            └─────────┬──────────┘
          │                                 │
          │ register handlers               │ emit events
          ▼                                 ▼
┌────────────────────┐            ┌────────────────────┐
│ WebSocketService   │◄──ws://──►│ WebSocketEndpoint  │
│  - connect()       │            │  - connection mgmt │
│  - reconnect()     │            │  - session binding │
│  - subscribe()     │            │  - heartbeat       │
│  - getMissed()     │            └─────────┬──────────┘
└────────────────────┘                      │
                                            │ subscribe/push
                                            ▼
                                  ┌────────────────────┐
                                  │ EventBusService    │
                                  │  - emit()          │
                                  │  - subscribe()     │
                                  │  - getEventsSince()│
                                  │  - 100 event buffer│
                                  └────────────────────┘
```

### 3.2 核心组件

| 层级 | 组件 | 职责 |
|------|------|------|
| Backend | `WebSocketEndpoint` | FastAPI WebSocket路由，连接生命周期管理 |
| Backend | `EventBusService` | 单例服务，事件收集、分发、存储 |
| Backend | `WsSession` | 单个WebSocket连接状态管理 |
| Frontend | `WebSocketService` | Vue组合式类，连接、重连、消息解析 |
| Frontend | `RealtimeStore` | Pinia store，连接状态管理 |
| Frontend | `ConnectionStatus` | UI组件，显示WebSocket连接状态 |

## 4. 消息格式

### 4.1 服务端推送消息

```typescript
interface WsMessage {
  event_type: EventType      // 事件类型枚举
  thread_id: string | null   // 工作流ID（null表示全局事件）
  payload: unknown           // 事件数据
  timestamp: string          // ISO 8601
  seq: number                // 序列号（用于补传）
}
```

### 4.2 客户端发送消息

```typescript
interface WsClientMessage {
  action: 'subscribe' | 'unsubscribe' | 'ping' | 'get_missed'
  thread_id?: string         // subscribe/unsubscribe必需
  since?: number             // get_missed必需
}
```

### 4.3 事件类型枚举

```typescript
enum EventType {
  // Workflow
  WORKFLOW_STARTED = 'workflow.started',
  WORKFLOW_PHASE_CHANGED = 'workflow.phase_changed',
  WORKFLOW_AGENT_STARTED = 'workflow.agent_started',
  WORKFLOW_AGENT_COMPLETED = 'workflow.agent_completed',
  WORKFLOW_DATA_UPDATED = 'workflow.data_updated',
  WORKFLOW_PAUSED = 'workflow.paused',
  WORKFLOW_RESUMED = 'workflow.resumed',
  WORKFLOW_COMPLETED = 'workflow.completed',
  WORKFLOW_ERROR = 'workflow.error',
  
  // Review
  REVIEW_PENDING = 'review.pending',
  REVIEW_SUBMITTED = 'review.submitted',
  REVIEW_APPROVED = 'review.approved',
  REVIEW_REJECTED = 'review.rejected',
  REVIEW_NEEDS_REVISION = 'review.needs_revision',
  
  // Analytics
  ANALYTICS_REPORT_UPDATED = 'analytics.report_updated',
  ANALYTICS_COST_ALERT = 'analytics.cost_alert',
  ANALYTICS_PERFORMANCE_NEW = 'analytics.performance_new',
}
```

## 5. 后端实现

### 5.1 文件结构

```
xhs_growth/
  realtime/
    __init__.py
    event_bus.py        # EventBusService
    websocket.py        # WebSocketManager + WsSession
    events.py           # EventType + Event + payload类型
    missed_events.py    # HTTP补传接口
  api/
    routes/
      realtime.py       # WebSocket路由注册
```

### 5.2 EventBusService

```python
class EventBusService:
    _instance = None
    MAX_EVENTS = 100
    
    def __init__(self):
        self._events: deque[Event] = deque(maxlen=self.MAX_EVENTS)
        self._subscribers: list[Callable] = []
        self._seq = 0
    
    @classmethod
    def get_instance(cls) -> EventBusService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def emit(self, event_type: EventType, thread_id: str | None, payload: dict):
        event = Event(event_type, thread_id, payload, datetime.utcnow(), self._seq)
        self._seq += 1
        self._events.append(event)
        for handler in self._subscribers:
            handler(event)
    
    def subscribe(self, handler: Callable):
        self._subscribers.append(handler)
    
    def get_events_since(self, since_seq: int) -> list[Event]:
        return [e for e in self._events if e.seq > since_seq]
```

### 5.3 WebSocketManager

```python
class WebSocketManager:
    _instance = None
    sessions: dict[str, WsSession]
    
    async def handle_connection(self, websocket: WebSocket):
        await websocket.accept()
        session = WsSession(websocket)
        session_id = uuid4().hex
        self.sessions[session_id] = session
        
        event_bus = EventBusService.get_instance()
        async def handler(event: Event):
            if event.thread_id is None or event.thread_id in session.subscribed_threads:
                await session.websocket.send_json(event.to_dict())
        event_bus.subscribe(handler)
        
        try:
            while True:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=30.0)
                await self._handle_client_message(session, msg)
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        finally:
            event_bus.unsubscribe(handler)
            self.sessions.pop(session_id, None)
```

### 5.4 FastAPI路由

```python
# xhs_growth/api/routes/realtime.py

@router.websocket_route("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await WebSocketManager.get_instance().handle_connection(websocket)

@router.get("/events/missed")
async def get_missed_events(since: int):
    events = EventBusService.get_instance().get_events_since(since)
    return {'events': [e.to_dict() for e in events]}
```

## 6. 前端实现

### 6.1 文件结构

```
frontend/src/
  realtime/
    index.ts              # 导出
    websocket.ts          # WebSocketService类
    events.ts             # EventType枚举 + 类型
    useRealtime.ts        # Vue组合式函数（可选）
  stores/
    realtime.ts           # RealtimeStore
  components/
    ConnectionStatus.vue  # 状态指示器
    Toast.vue             # 通知组件
```

### 6.2 WebSocketService

```typescript
type WsStatus = 'disconnected' | 'connecting' | 'connected' | 'reconnecting'

export class WebSocketService {
  private ws: WebSocket | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 1000
  private lastSeq = 0
  private messageHandlers: Map<EventType, Function> = new Map()
  private statusCallbacks: Set<Function> = new Set()
  private status: WsStatus = 'disconnected'
  private heartbeatInterval: number | null = null
  
  connect(url?: string) {
    this.status = 'connecting'
    this.ws = new WebSocket(url || defaultUrl)
    
    this.ws.onopen = () => {
      this.status = 'connected'
      this.reconnectAttempts = 0
      if (this.lastSeq > 0) {
        this.send({ action: 'get_missed', since: this.lastSeq })
      }
      this.startHeartbeat()
    }
    
    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.action === 'missed_events') {
        data.events.forEach(e => this.handleEvent(e))
      } else if (data.action === 'pong') {
        return
      } else {
        this.handleEvent(data)
      }
    }
    
    this.ws.onclose = () => this.scheduleReconnect()
  }
  
  handleEvent(msg: WsMessage) {
    this.lastSeq = msg.seq
    const handler = this.messageHandlers.get(msg.event_type)
    handler?.(msg.payload)
  }
  
  scheduleReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return
    this.reconnectAttempts++
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000)
    this.status = 'reconnecting'
    setTimeout(() => this.connect(), this.reconnectDelay)
  }
  
  startHeartbeat() {
    this.heartbeatInterval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.send({ action: 'ping' })
      }
    }, 25000)
  }
  
  stopHeartbeat() {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval)
      this.heartbeatInterval = null
    }
  }
  
  disconnect() {
    this.stopHeartbeat()
    this.ws?.close()
    this.ws = null
    this.status = 'disconnected'
    this.notifyStatusChange()
  }
  
  subscribe(threadId: string) {
    this.send({ action: 'subscribe', thread_id: threadId })
  }
  
  onEvent(eventType: EventType, handler: Function) {
    this.messageHandlers.set(eventType, handler)
  }
}
```

### 6.3 Store集成

```typescript
// stores/workflow.ts

const realtimeStore = useRealtimeStore()

realtimeStore.wsService.onEvent(EventType.WORKFLOW_PHASE_CHANGED, (payload) => {
  if (payload.thread_id === currentThreadId.value) {
    workflowState.value.values.phase = payload.new_phase
  }
})

realtimeStore.wsService.onEvent(EventType.WORKFLOW_DATA_UPDATED, (payload) => {
  if (payload.thread_id === currentThreadId.value) {
    workflowState.value.values[payload.data_type] = payload.data
  }
})

async function startWorkflow(accountId: string, phase: WorkflowPhase) {
  const result = await workflowApi.startWorkflow({ account_id: accountId, phase })
  realtimeStore.connect()
  realtimeStore.subscribeWorkflow(result.thread_id)
  return result
}
```

### 6.4 ConnectionStatus组件

显示WebSocket连接状态：🟢实时连接 / 🟡连接中 / 🔴已断开

### 6.5 Toast组件

通知组件，显示成功/错误/警告/信息提示，自动消失（默认5秒）。

## 7. 故障处理

| 故障场景 | 处理方式 |
|---------|---------|
| WebSocket断开 | 自动重连，指数退避，最多5次 |
| 心跳超时（30s无响应） | 关闭连接，触发重连 |
| 重连失败（5次后） | 显示"已断开"状态，停止重连 |
| 重连成功 | 自动请求补传事件（since: lastSeq） |
| HTTP API错误 | Toast显示错误消息 |

## 8. 测试策略

### 8.1 后端测试
- EventBusService单元测试：emit、subscribe、get_events_since
- WebSocketManager集成测试：连接、订阅、消息路由
- 消息补传测试：断线后重连获取丢失事件

### 8.2 前端测试
- WebSocketService单元测试：连接、重连、消息处理
- Store集成测试：事件触发状态更新
- 组件测试：ConnectionStatus状态变化

## 9. 实现顺序

1. 后端EventBusService + events.py
2. 后端WebSocketManager + websocket.py
3. 后端FastAPI路由注册
4. 前端WebSocketService + events.ts
5. 前端RealtimeStore
6. 前端Store集成（workflow/review/analytics）
7. 前端ConnectionStatus + Toast组件
8. App.vue集成
9. 测试

## 10. 后续优化

- 未来可升级到Redis Pub/Sub架构（支持多WebSocket实例）
- 添加消息压缩（大型payload）
- 添加权限验证（WebSocket连接token）