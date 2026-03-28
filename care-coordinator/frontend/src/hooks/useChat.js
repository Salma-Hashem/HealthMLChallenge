import { useState, useCallback, useRef } from 'react'
import { sendMessage } from '../services/api'

export function useChat() {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState(null)
  const [workflowState, setWorkflowState] = useState('GREET')
  const [requiresConfirmation, setRequiresConfirmation] = useState(false)
  const [hasActed, setHasActed] = useState(false)
  const [error, setError] = useState(null)

  // Track last user message text for regeneration
  const lastUserMsgRef = useRef('')

  const _addAssistantMessage = useCallback((data) => {
    const assistantMsg = {
      role:       'assistant',
      text:       data.response,
      id:         Date.now() + 1,
      toolCalls:  data.tool_calls || [],
    }
    return assistantMsg
  }, [])

  const send = useCallback(async (text) => {
    if (!text.trim() || loading) return

    setError(null)
    lastUserMsgRef.current = text

    const userMsg = { role: 'user', text, id: Date.now() }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const data = await sendMessage(sessionId, text)
      setSessionId(data.session_id)
      setWorkflowState(data.workflow_state)
      setRequiresConfirmation(data.requires_confirmation)
      // Mark hasActed when booking is confirmed so regenerate is disabled
      if (data.workflow_state === 'BOOKING_CONFIRMED') setHasActed(true)
      setMessages(prev => [...prev, _addAssistantMessage(data)])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [sessionId, loading, _addAssistantMessage])

  const regenerate = useCallback(async () => {
    const text = lastUserMsgRef.current
    if (!text || loading || hasActed || !sessionId) return

    setError(null)
    setLoading(true)

    try {
      const data = await sendMessage(sessionId, text, { regenerate: true })
      setSessionId(data.session_id)
      setWorkflowState(data.workflow_state)
      setRequiresConfirmation(data.requires_confirmation)
      // Replace the last assistant message in-place
      setMessages(prev => {
        const idx = [...prev].reverse().findIndex(m => m.role === 'assistant')
        if (idx === -1) return [...prev, _addAssistantMessage(data)]
        const realIdx = prev.length - 1 - idx
        const next = [...prev]
        next[realIdx] = _addAssistantMessage(data)
        return next
      })
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [sessionId, loading, hasActed, _addAssistantMessage])

  const reset = useCallback(() => {
    setMessages([])
    setSessionId(null)
    setWorkflowState('GREET')
    setRequiresConfirmation(false)
    setHasActed(false)
    setError(null)
    setLoading(false)
    lastUserMsgRef.current = ''
  }, [])

  return {
    messages,
    loading,
    sessionId,
    workflowState,
    requiresConfirmation,
    hasActed,
    error,
    send,
    regenerate,
    reset,
  }
}
