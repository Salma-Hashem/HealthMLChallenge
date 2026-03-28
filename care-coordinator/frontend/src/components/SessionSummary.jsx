export default function SessionSummary({ workflowState, onReset }) {
  const isDone = workflowState === 'BOOKING_CONFIRMED' || workflowState === 'FINAL_SUMMARY'

  if (!isDone) return null

  return (
    <div className="mx-4 mb-3 bg-green-50 border border-green-200 rounded-xl p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-green-600 text-xl">✅</span>
          <div>
            <p className="text-sm font-semibold text-green-800">Session Complete</p>
            <p className="text-xs text-green-600">Booking has been confirmed successfully.</p>
          </div>
        </div>
        <button
          onClick={onReset}
          className="text-xs font-medium text-green-700 bg-green-100 hover:bg-green-200 px-3 py-1.5 rounded-lg transition-colors"
        >
          New Session
        </button>
      </div>
    </div>
  )
}
