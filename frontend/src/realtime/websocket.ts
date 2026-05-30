// frontend/src/realtime/websocket.ts

import { EventType, WsMessage, WsClientMessage, WsStatus, WsMissedEventsResponse } from "./events"

/** Event handler callback type */
export type EventHandler = (event: WsMessage) => void

/** Status change callback type */
export type StatusCallback = (status: WsStatus) => void

/** Recovery event callback — fired after missed events are replayed on reconnect */
export type RecoveryCallback = (recoveredCount: number, lastSeq: number) => void

/** WebSocket connection configuration */
export interface WebSocketConfig {
  /** WebSocket server URL (default: derived from window.location) */
  url?: string
  /** Maximum reconnect attempts (default: 5) */
  maxReconnectAttempts?: number
  /** Initial reconnect delay in ms (default: 1000) */
  initialReconnectDelay?: number
  /** Maximum reconnect delay in ms (default: 30000) */
  maxReconnectDelay?: number
  /** Heartbeat interval in ms (default: 25000) */
  heartbeatInterval?: number
}

/** Default configuration */
const DEFAULT_CONFIG: Required<WebSocketConfig> = {
  url: "",
  maxReconnectAttempts: 5,
  initialReconnectDelay: 1000,
  maxReconnectDelay: 30000,
  heartbeatInterval: 25000,
}

/**
 * WebSocketService - Real-time event streaming client
 *
 * Features:
 * - Connection lifecycle management (connect/disconnect)
 * - Auto reconnect with exponential backoff
 * - Thread subscription/unsubscription
 * - Ping/pong heartbeat mechanism
 * - Event recovery on reconnect (get_missed since lastSeq)
 * - Event handler registration
 * - Status change notifications
 */
export class WebSocketService {
  private ws: WebSocket | null = null
  private status: WsStatus = "disconnected"
  private lastSeq: number = 0
  private reconnectAttempts: number = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null

  private subscribedThreads: Set<string> = new Set()
  private messageHandlers: Map<EventType, Set<EventHandler>> = new Map()
  private statusCallbacks: Set<StatusCallback> = new Set()
  private recoveryCallbacks: Set<RecoveryCallback> = new Set()

  private config: Required<WebSocketConfig>

  constructor(config?: WebSocketConfig) {
    this.config = { ...DEFAULT_CONFIG, ...config }
    if (!this.config.url) {
      this.config.url = this.deriveUrl()
    }
  }

  /** Derive WebSocket URL from current window location */
  private deriveUrl(): string {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
    const host = window.location.host
    return `${protocol}//${host}/ws`
  }

  /** Get current connection status */
  getStatus(): WsStatus {
    return this.status
  }

  /** Update status and notify callbacks */
  private notifyStatusChange(newStatus: WsStatus): void {
    this.status = newStatus
    this.statusCallbacks.forEach((cb) => cb(newStatus))
  }

  /**
   * Connect to WebSocket server
   * @param url - Optional override URL
   */
  connect(url?: string): void {
    if (this.ws && (this.status === "connected" || this.status === "connecting")) {
      return
    }

    this.stopHeartbeat()
    this.clearReconnectTimer()

    const wsUrl = url || this.config.url
    this.notifyStatusChange("connecting")

    try {
      this.ws = new WebSocket(wsUrl)
      this.ws.onopen = this.handleOpen.bind(this)
      this.ws.onmessage = this.handleMessage.bind(this)
      this.ws.onclose = this.handleClose.bind(this)
      this.ws.onerror = this.handleError.bind(this)
    } catch (error) {
      console.error("WebSocket connection error:", error)
      this.notifyStatusChange("disconnected")
      this.scheduleReconnect()
    }
  }

  /** Handle WebSocket open event */
  private handleOpen(): void {
    this.reconnectAttempts = 0
    this.notifyStatusChange("connected")

    // Request missed events since last sequence
    if (this.lastSeq > 0) {
      this.send({ action: "get_missed", since: this.lastSeq })
    }

    // Re-subscribe to all threads
    this.subscribedThreads.forEach((threadId) => {
      this.send({ action: "subscribe", thread_id: threadId })
    })

    // Start heartbeat
    this.startHeartbeat()
  }

  /** Handle WebSocket message event */
  private handleMessage(event: MessageEvent): void {
    try {
      const data = JSON.parse(event.data)

      // Handle missed_events response
      if (data.action === "missed_events" && Array.isArray(data.events)) {
        this.handleMissedEvents(data as WsMissedEventsResponse)
        return
      }

      // Handle pong response
      if (data.action === "pong") {
        // Pong received, heartbeat continues
        return
      }

      // Handle business event
      if (data.event_type && data.seq !== undefined) {
        this.handleEvent(data as WsMessage)
      }
    } catch (error) {
      console.error("WebSocket message parse error:", error)
    }
  }

  /** Handle missed events batch */
  private handleMissedEvents(response: WsMissedEventsResponse): void {
    const count = response.events.length
    response.events.forEach((msg) => {
      this.handleEvent(msg)
    })
    // Notify recovery callbacks after all events are processed
    if (count > 0) {
      this.recoveryCallbacks.forEach((cb) => cb(count, this.lastSeq))
    }
  }

  /** Handle individual business event */
  private handleEvent(msg: WsMessage): void {
    // Update last sequence
    this.lastSeq = msg.seq

    // Find handlers for this event type
    const handlers = this.messageHandlers.get(msg.event_type)
    if (handlers) {
      handlers.forEach((handler) => handler(msg))
    }

    // Also dispatch to wildcard handlers (if any)
    const wildcardHandlers = this.messageHandlers.get("*" as EventType)
    if (wildcardHandlers) {
      wildcardHandlers.forEach((handler) => handler(msg))
    }
  }

  /** Handle WebSocket close event */
  private handleClose(event: CloseEvent): void {
    this.ws = null
    this.stopHeartbeat()

    // Always update status when connection closes (handles failed "connecting" attempts too)
    if (this.status !== "disconnected") {
      this.notifyStatusChange("disconnected")
    }

    // Schedule reconnect if not intentional disconnect
    if (event.code !== 1000 && event.code !== 1001) {
      this.scheduleReconnect()
    }
  }

  /** Handle WebSocket error event */
  private handleError(event: Event): void {
    console.error("WebSocket error:", event)
    // Error will trigger onclose, so we handle reconnect there
  }

  /** Disconnect from WebSocket server */
  disconnect(): void {
    this.clearReconnectTimer()
    this.stopHeartbeat()

    if (this.ws) {
      // Intentional close (code 1000)
      this.ws.close(1000, "Client disconnect")
      this.ws = null
    }

    this.notifyStatusChange("disconnected")
  }

  /**
   * Subscribe to thread events
   * @param threadId - Thread to subscribe
   */
  subscribe(threadId: string): void {
    this.subscribedThreads.add(threadId)

    if (this.status === "connected") {
      this.send({ action: "subscribe", thread_id: threadId })
    }
  }

  /**
   * Unsubscribe from thread events
   * @param threadId - Thread to unsubscribe
   */
  unsubscribe(threadId: string): void {
    this.subscribedThreads.delete(threadId)

    if (this.status === "connected") {
      this.send({ action: "unsubscribe", thread_id: threadId })
    }
  }

  /**
   * Register event handler
   * @param eventType - Event type to handle (or "*" for all)
   * @param handler - Handler callback
   */
  onEvent(eventType: EventType | "*", handler: EventHandler): void {
    const handlers = this.messageHandlers.get(eventType as EventType) || new Set()
    handlers.add(handler)
    this.messageHandlers.set(eventType as EventType, handlers)
  }

  /**
   * Remove event handler
   * @param eventType - Event type
   * @param handler - Handler to remove
   */
  offEvent(eventType: EventType | "*", handler: EventHandler): void {
    const handlers = this.messageHandlers.get(eventType as EventType)
    if (handlers) {
      handlers.delete(handler)
      if (handlers.size === 0) {
        this.messageHandlers.delete(eventType as EventType)
      }
    }
  }

  /**
   * Register status change callback
   * @param callback - Status callback
   */
  onStatusChange(callback: StatusCallback): void {
    this.statusCallbacks.add(callback)
  }

  /**
   * Remove status change callback
   * @param callback - Callback to remove
   */
  offStatusChange(callback: StatusCallback): void {
    this.statusCallbacks.delete(callback)
  }

  /**
   * Register recovery callback — fired after missed events are replayed on reconnect
   * @param callback - Recovery callback
   */
  onRecovery(callback: RecoveryCallback): void {
    this.recoveryCallbacks.add(callback)
  }

  /**
   * Remove recovery callback
   * @param callback - Callback to remove
   */
  offRecovery(callback: RecoveryCallback): void {
    this.recoveryCallbacks.delete(callback)
  }

  /** Schedule reconnect with exponential backoff */
  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.config.maxReconnectAttempts) {
      console.warn("Max reconnect attempts reached")
      this.notifyStatusChange("disconnected")
      return
    }

    this.clearReconnectTimer()

    // Exponential backoff: 1s → 2s → 4s → 8s → 16s → 30s (max)
    const delay = Math.min(
      this.config.initialReconnectDelay * Math.pow(2, this.reconnectAttempts),
      this.config.maxReconnectDelay
    )

    this.reconnectAttempts++
    this.notifyStatusChange("reconnecting")

    this.reconnectTimer = setTimeout(() => {
      this.connect()
    }, delay)
  }

  /** Clear reconnect timer */
  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  /** Start heartbeat ping interval */
  private startHeartbeat(): void {
    this.stopHeartbeat()

    this.heartbeatTimer = setInterval(() => {
      if (this.status === "connected" && this.ws) {
        this.send({ action: "ping" })
      }
    }, this.config.heartbeatInterval)
  }

  /** Stop heartbeat */
  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  /** Send message to WebSocket server */
  private send(message: WsClientMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message))
    }
  }

  /** Get currently subscribed threads */
  getSubscribedThreads(): string[] {
    return Array.from(this.subscribedThreads)
  }

  /** Get last received sequence number */
  getLastSeq(): number {
    return this.lastSeq
  }

  /** Check if connected */
  isConnected(): boolean {
    return this.status === "connected"
  }
}

/** Create default WebSocket service instance */
export function createWebSocketService(config?: WebSocketConfig): WebSocketService {
  return new WebSocketService(config)
}