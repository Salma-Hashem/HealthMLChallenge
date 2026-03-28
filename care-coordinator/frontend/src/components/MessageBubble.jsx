import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import MessageActions from './MessageActions'

/** Tailwind prose classes for assistant message markdown */
const mdComponents = {
  p:      ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
  em:     ({ children }) => <em className="italic">{children}</em>,
  ul:     ({ children }) => <ul className="list-disc list-inside mb-2 space-y-0.5">{children}</ul>,
  ol:     ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-0.5">{children}</ol>,
  li:     ({ children }) => <li className="text-sm">{children}</li>,
  h1:     ({ children }) => <h1 className="text-base font-semibold mb-1">{children}</h1>,
  h2:     ({ children }) => <h2 className="text-sm font-semibold mb-1">{children}</h2>,
  h3:     ({ children }) => <h3 className="text-sm font-semibold mb-1">{children}</h3>,
  hr:     () => <hr className="my-2 border-gray-200" />,
  code:   ({ children }) => (
    <code className="bg-gray-100 text-gray-800 rounded px-1 py-0.5 text-xs font-mono">{children}</code>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-gray-300 pl-3 text-gray-600 italic mb-2">{children}</blockquote>
  ),
}

export default function MessageBubble({
  message,
  messageIndex,
  sessionId,
  workflowState,
  isLatest,
  isLoading,
  hasActed,
  onRegenerate,
}) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3 group`}>
      {!isUser && (
        <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-xs font-bold shrink-0 mr-2 mt-1">
          CC
        </div>
      )}

      <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} max-w-[75%]`}>
        {/* Bubble */}
        <div
          className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
            isUser
              ? 'bg-blue-600 text-white rounded-br-sm whitespace-pre-wrap'
              : 'bg-white text-gray-800 rounded-bl-sm shadow-sm border border-gray-100'
          }`}
        >
          {isUser ? (
            message.text
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
              {message.text || ''}
            </ReactMarkdown>
          )}
        </div>

        {/* Action bar — assistant messages only, fades in on group hover */}
        {!isUser && (
          <div className="opacity-0 group-hover:opacity-100 transition-opacity duration-150">
            <MessageActions
              message={message}
              messageIndex={messageIndex}
              sessionId={sessionId}
              workflowState={workflowState}
              isLatest={isLatest}
              isLoading={isLoading}
              hasActed={hasActed}
              onRegenerate={onRegenerate}
            />
          </div>
        )}
      </div>

      {isUser && (
        <div className="w-8 h-8 rounded-full bg-gray-300 flex items-center justify-center text-gray-600 text-xs font-bold shrink-0 ml-2 mt-1">
          RN
        </div>
      )}
    </div>
  )
}
