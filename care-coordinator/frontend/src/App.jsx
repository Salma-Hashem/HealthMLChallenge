import { useState, useRef } from 'react'
import { useChat } from './hooks/useChat'
import ChatThread from './components/ChatThread'
import BookingChecklist from './components/BookingChecklist'
import BookingCard from './components/BookingCard'
import SessionSummary from './components/SessionSummary'
import QuickActionBar from './components/QuickActionBar'
import './index.css'

function ChatInput({ onSend, disabled }) {
  const [text, setText] = useState('')
  const textareaRef = useRef(null)

  function handleSubmit(e) {
    e.preventDefault()
    if (!text.trim() || disabled) return
    onSend(text.trim())
    setText('')
    textareaRef.current?.focus()
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-end gap-2 px-4 py-3 border-t border-gray-200 bg-white">
      <textarea
        ref={textareaRef}
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Type a message… (Enter to send, Shift+Enter for newline)"
        rows={1}
        disabled={disabled}
        className="flex-1 resize-none rounded-xl border border-gray-300 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-50 disabled:cursor-not-allowed leading-relaxed"
        style={{ maxHeight: '120px', overflowY: 'auto' }}
      />
      <button
        type="submit"
        disabled={disabled || !text.trim()}
        className="shrink-0 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white rounded-xl px-4 py-2.5 text-sm font-medium transition-colors"
      >
        Send
      </button>
    </form>
  )
}

export default function App() {
  const {
    messages, loading, sessionId, workflowState, requiresConfirmation,
    hasActed, error, send, regenerate, reset,
  } = useChat()

  return (
    <div className="flex h-screen bg-slate-100">
      {/* Main chat panel */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Header */}
        <header className="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-blue-600 flex items-center justify-center text-white font-bold text-sm">
              CC
            </div>
            <div>
              <h1 className="text-sm font-semibold text-gray-900">Care Coordinator</h1>
              <p className="text-xs text-gray-500">Healthcare Appointment Assistant</p>
            </div>
          </div>
          <button
            onClick={reset}
            className="text-xs text-gray-500 hover:text-red-500 border border-gray-200 hover:border-red-300 px-3 py-1.5 rounded-lg transition-colors"
          >
            New Session
          </button>
        </header>

        {/* Error banner */}
        {error && (
          <div className="bg-red-50 border-b border-red-200 px-4 py-2 text-xs text-red-700">
            ⚠️ {error}
          </div>
        )}

        {/* Chat messages */}
        <ChatThread
          messages={messages}
          loading={loading}
          sessionId={sessionId}
          workflowState={workflowState}
          hasActed={hasActed}
          onRegenerate={regenerate}
        />

        {/* Session summary (shows when booking is done) */}
        <SessionSummary workflowState={workflowState} loading={loading} onReset={reset} />

        {/* Booking confirmation card */}
        <BookingCard requiresConfirmation={requiresConfirmation} onSend={send} />

        {/* Quick actions */}
        <QuickActionBar onSend={send} disabled={loading} />

        {/* Message input */}
        <ChatInput onSend={send} disabled={loading} />
      </div>

      {/* Booking checklist sidebar */}
      <BookingChecklist workflowState={workflowState} />
    </div>
  )
}
