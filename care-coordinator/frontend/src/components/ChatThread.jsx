import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble'

function TypingIndicator() {
  return (
    <div className="flex justify-start mb-3">
      <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-xs font-bold shrink-0 mr-2 mt-1">
        CC
      </div>
      <div className="bg-white border border-gray-100 shadow-sm px-4 py-3 rounded-2xl rounded-bl-sm flex items-center gap-1">
        <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0ms]" />
        <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:150ms]" />
        <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:300ms]" />
      </div>
    </div>
  )
}

export default function ChatThread({
  messages,
  loading,
  sessionId,
  workflowState,
  hasActed,
  onRegenerate,
}) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // Index of the last assistant message
  const lastAssistantIdx = [...messages].reverse().findIndex(m => m.role === 'assistant')
  const latestAssistantId = lastAssistantIdx === -1
    ? null
    : messages[messages.length - 1 - lastAssistantIdx].id

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4">
      {messages.length === 0 && (
        <div className="flex flex-col items-center justify-center h-full text-gray-400 gap-2">
          <div className="text-4xl">💬</div>
          <p className="text-sm">Start by greeting the assistant or providing a patient name.</p>
        </div>
      )}
      {messages.map((msg, idx) => (
        <MessageBubble
          key={msg.id}
          message={msg}
          messageIndex={idx}
          sessionId={sessionId}
          workflowState={workflowState}
          isLatest={msg.id === latestAssistantId}
          isLoading={loading}
          hasActed={hasActed}
          onRegenerate={onRegenerate}
        />
      ))}
      {loading && <TypingIndicator />}
      <div ref={bottomRef} />
    </div>
  )
}
