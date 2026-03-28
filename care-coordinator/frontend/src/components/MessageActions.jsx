import { useState, useCallback } from 'react'
import { Check, Clipboard, ThumbsDown, ThumbsUp, RefreshCw } from 'lucide-react'
import ActionButton from './ActionButton'
import FeedbackDropdown from './FeedbackDropdown'
import { useClipboard } from '../hooks/useClipboard'
import { postFeedback } from '../services/api'

/**
 * Action button bar rendered below each assistant message bubble.
 *
 * Props:
 *   message         – the full message object { id, text, toolCalls, ... }
 *   messageIndex    – position in the messages array (for feedback payload)
 *   sessionId       – current session id
 *   workflowState   – current workflow state string
 *   isLatest        – true only for the most recent assistant message
 *   isLoading       – true while a response is in flight
 *   hasActed        – true after nurse confirmed booking / selected slot
 *   onRegenerate    – () => void
 */
export default function MessageActions({
  message,
  messageIndex,
  sessionId,
  workflowState,
  isLatest,
  isLoading,
  hasActed,
  onRegenerate,
}) {
  const { copied, denied, copyText } = useClipboard()
  const [feedback, setFeedback] = useState(null)   // 'positive' | 'negative' | null
  const [showDropdown, setShowDropdown] = useState(false)

  // ── Copy ──────────────────────────────────────────────────────────────────
  const handleCopy = useCallback(() => {
    copyText(message.text || '')
  }, [copyText, message.text])

  // ── Feedback ──────────────────────────────────────────────────────────────
  const recordFeedback = useCallback(async (value) => {
    try {
      await postFeedback({
        session_id:         sessionId,
        message_index:      messageIndex,
        feedback:           value,
        workflow_state:     workflowState,
        tool_calls_in_turn: message.toolCalls || [],
        response_text:      message.text || '',
      })
    } catch {
      // Best-effort; do not surface errors to the nurse
    }
  }, [sessionId, messageIndex, workflowState, message])

  const handleThumbsUp = useCallback(() => {
    const next = feedback === 'positive' ? null : 'positive'
    setFeedback(next)
    setShowDropdown(false)
    recordFeedback(next)
  }, [feedback, recordFeedback])

  const handleThumbsDown = useCallback(() => {
    if (feedback === 'negative') {
      setFeedback(null)
      setShowDropdown(false)
      recordFeedback(null)
    } else {
      setFeedback('negative')
      setShowDropdown(true)
      recordFeedback('negative')
    }
  }, [feedback, recordFeedback])

  const handleDropdownSelect = useCallback(async (reason) => {
    setShowDropdown(false)
    try {
      await postFeedback({
        session_id:         sessionId,
        message_index:      messageIndex,
        feedback:           'negative',
        feedback_reason:    reason,
        workflow_state:     workflowState,
        tool_calls_in_turn: message.toolCalls || [],
        response_text:      message.text || '',
      })
    } catch { /* best-effort */ }
  }, [sessionId, messageIndex, workflowState, message])

  // ── Regenerate ────────────────────────────────────────────────────────────
  const canRegenerate = isLatest && !isLoading && !hasActed

  return (
    <div className="relative flex items-center gap-0.5 pt-1 pl-0.5">
      {/* Copy */}
      <ActionButton
        icon={copied ? Check : Clipboard}
        tooltip={denied ? 'Try selecting the text manually' : copied ? 'Copied!' : 'Copy message'}
        onClick={handleCopy}
        disabled={!message.text}
        active={copied}
        activeColor="text-green-600"
      />

      {/* Thumbs Up */}
      <ActionButton
        icon={ThumbsUp}
        tooltip="Good response"
        onClick={handleThumbsUp}
        active={feedback === 'positive'}
        activeColor="text-green-600"
      />

      {/* Thumbs Down + dropdown */}
      <div className="relative">
        <ActionButton
          icon={ThumbsDown}
          tooltip="Bad response"
          onClick={handleThumbsDown}
          active={feedback === 'negative'}
          activeColor="text-red-500"
        />
        {showDropdown && (
          <FeedbackDropdown
            onSelect={handleDropdownSelect}
            onDismiss={() => setShowDropdown(false)}
          />
        )}
      </div>

      {/* Regenerate — only on the latest message */}
      {isLatest && (
        <ActionButton
          icon={RefreshCw}
          tooltip={hasActed ? 'Cannot regenerate after acting' : 'Regenerate response'}
          onClick={onRegenerate}
          disabled={!canRegenerate}
        />
      )}
    </div>
  )
}
