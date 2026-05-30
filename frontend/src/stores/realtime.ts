// frontend/src/stores/realtime.ts

import { defineStore } from "pinia"
import { ref } from "vue"
import { WebSocketService } from "@/realtime/websocket"
import type { WsStatus } from "@/realtime/events"
import { useToastStore } from "./toast"
import i18n from "@/locales"

const { t } = i18n.global

export const useRealtimeStore = defineStore("realtime", () => {
  const wsService = new WebSocketService()
  const connectionStatus = ref<WsStatus>(wsService.getStatus())
  const lastRecoveredSeq = ref(0)

  // 监听连接状态
  wsService.onStatusChange((status) => {
    connectionStatus.value = status
  })

  // 监听事件恢复 — show toast on reconnect recovery
  wsService.onRecovery((count, lastSeq) => {
    lastRecoveredSeq.value = lastSeq
    const toastStore = useToastStore()
    toastStore.success(
      t('connection.recoveryTitle'),
      t('connection.recoveryMessage', { count, seq: lastSeq })
    )
  })

  /**
   * 连接WebSocket
   */
  function connect(): void {
    wsService.connect()
  }

  /**
   * 断开WebSocket
   */
  function disconnect(): void {
    wsService.disconnect()
  }

  /**
   * 订阅工作流
   */
  function subscribeWorkflow(threadId: string): void {
    wsService.subscribe(threadId)
  }

  /**
   * 取消订阅工作流
   */
  function unsubscribeWorkflow(threadId: string): void {
    wsService.unsubscribe(threadId)
  }

  /**
   * 获取最后seq
   */
  function getLastSeq(): number {
    return wsService.getLastSeq()
  }

  return {
    connectionStatus,
    lastRecoveredSeq,
    connect,
    disconnect,
    subscribeWorkflow,
    unsubscribeWorkflow,
    getLastSeq,
    wsService, // 暴露给其他store注册事件处理器
  }
})