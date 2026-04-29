import { useState, useEffect, useCallback, useRef } from 'react'

interface WebSocketMessage {
  type: string
  content?: string
  slots?: any[]
  workflow_definition?: any
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

  const connect = useCallback(() => {
    if (!sessionId) return

    const wsUrl = `ws://localhost:8000/api/v1/vibe-agent/ws/${sessionId}`
    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      setIsConnected(true)
      setError(null)
      console.log('WebSocket connected')
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        setLastMessage(data)
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e)
      }
    }

    ws.onerror = (event) => {
      setError('WebSocket error')
      console.error('WebSocket error:', event)
    }

    ws.onclose = () => {
      setIsConnected(false)
      console.log('WebSocket disconnected')
    }

    socketRef.current = ws
  }, [sessionId])

  const disconnect = useCallback(() => {
    if (socketRef.current) {
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
    if (sessionId) {
      connect()
    }

    return () => {
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