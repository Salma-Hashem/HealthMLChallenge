const ACTIONS = [
  { label: '🆕 New Referral',      message: 'I have a new referral to process.' },
  { label: '🏥 Check Insurance',   message: 'Can you check the patient\'s insurance coverage?' },
  { label: '📅 View Bookings',     message: 'Show me the patient\'s booking history.' },
  { label: '🔍 Find Slots',        message: 'Find available appointment slots.' },
  { label: '📋 Verify Patient',    message: 'I need to verify a patient\'s identity.' },
]

export default function QuickActionBar({ onSend, disabled }) {
  return (
    <div className="px-4 py-2 border-t border-gray-200 bg-gray-50 flex gap-2 overflow-x-auto">
      {ACTIONS.map(action => (
        <button
          key={action.label}
          onClick={() => onSend(action.message)}
          disabled={disabled}
          className="shrink-0 px-3 py-1.5 rounded-full text-xs font-medium bg-white border border-gray-300 text-gray-600 hover:border-blue-400 hover:text-blue-600 hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {action.label}
        </button>
      ))}
    </div>
  )
}
