import { useState, useEffect, useCallback, useRef } from 'react'

import type { Slot } from '../api/vibeAgent'

export interface WebSocketMessage {
  type: string
  content?: string
  slots?: Slot[]
  workflow_type?: string
  workflow_definition?: { name?: string; nodes?: unknown[]; edges?: unknown[] } | null
  python_code?: string
  mermaid_diagram?: string
  error_message?: string
  timestamp: string
}

interface UseWebSocketReturn {
  isConnected: boolean
  sendMessage: (type: string, content: string, metadata?: any) => void
  lastMessage: WebSocketMessage | null
  error: string | null
}

export const useWebSocket = (sessionId: string | null): UseWebSocketReturn => {
  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  // 组件卸载标记：卸载后到达的消息/状态回调不再 setState（避免内存泄漏警告）
  const unmountedRef = useRef(false)

  const connect = useCallback(() => {
    if (!sessionId) return

    // 与 axios baseURL('/api/v1') 同源：开发环境走 vite 代理，生产走当前站点
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const wsUrl = `${proto}://${window.location.host}/api/v1/vibe-agent/ws/${sessionId}`
    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      if (unmountedRef.current) return
      setIsConnected(true)
      setError(null)
      console.log('WebSocket connected')
    }

    ws.onmessage = (event) => {
      if (unmountedRef.current) return
      try {
        const data = JSON.parse(event.data)
        setLastMessage(data)
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e)
      }
    }

    ws.onerror = (event) => {
      if (unmountedRef.current) return
      setError('WebSocket error')
      console.error('WebSocket error:', event)
    }

    ws.onclose = () => {
      if (unmountedRef.current) return
      setIsConnected(false)
      console.log('WebSocket disconnected')
    }

    socketRef.current = ws
  }, [sessionId])

  const disconnect = useCallback(() => {
    if (socketRef.current) {
      // 先摘掉回调再关闭，避免 close 事件触发已卸载组件的 setState
      socketRef.current.onopen = null
      socketRef.current.onmessage = null
      socketRef.current.onerror = null
      socketRef.current.onclose = null
      socketRef.current.close()
      socketRef.current = null
    }
  }, [])

  const sendMessage = useCallback((type: string, content: string, metadata?: any) => {
    if (socketRef.current && isConnected) {
      socketRef.current.send(JSON.stringify({
        type,
        content,
        metadata,
      }))
    }
  }, [isConnected])

  useEffect(() => {
    unmountedRef.current = false
    if (sessionId) {
      connect()
    }

    return () => {
      unmountedRef.current = true
      disconnect()
    }
  }, [sessionId, connect, disconnect])

  return {
    isConnected,
    sendMessage,
    lastMessage,
    error,
  }
}

export default useWebSocket