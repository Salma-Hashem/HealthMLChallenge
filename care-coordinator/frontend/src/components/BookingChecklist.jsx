const WORKFLOW_STEPS = [
  { key: 'GREET',             label: 'Greet & Identify',       states: ['GREET'] },
  { key: 'VERIFY_PATIENT',    label: 'Verify Patient',          states: ['VERIFY_PATIENT'] },
  { key: 'COLLECT_REFERRAL',  label: 'Collect Referral Info',   states: ['COLLECT_REFERRAL'] },
  { key: 'DETERMINE_APPT',    label: 'Determine Appt. Type',    states: ['DETERMINE_APPT_TYPE'] },
  { key: 'CHECK_AVAIL',       label: 'Check Availability',      states: ['CHECK_AVAILABILITY'] },
  { key: 'VERIFY_INSURANCE',  label: 'Verify Insurance',        states: ['VERIFY_INSURANCE'] },
  { key: 'CONFIRM_BOOKING',   label: 'Confirm Booking',         states: ['CONFIRM_BOOKING'] },
  { key: 'BOOKING_CONFIRMED', label: 'Booking Confirmed',       states: ['BOOKING_CONFIRMED'] },
  { key: 'FINAL_SUMMARY',     label: 'Final Summary',           states: ['FINAL_SUMMARY'] },
]

function stepStatus(step, currentState) {
  const ORDER = [
    'GREET', 'VERIFY_PATIENT', 'COLLECT_REFERRAL', 'DETERMINE_APPT_TYPE',
    'CHECK_AVAILABILITY', 'VERIFY_INSURANCE', 'CONFIRM_BOOKING',
    'BOOKING_CONFIRMED', 'FINAL_SUMMARY',
  ]
  const currentIdx = ORDER.indexOf(currentState)
  const stepIdx = ORDER.indexOf(step.states[0])
  if (stepIdx < currentIdx) return 'done'
  if (step.states.includes(currentState)) return 'active'
  return 'pending'
}

export default function BookingChecklist({ workflowState }) {
  return (
    <div className="bg-white border-l border-gray-200 w-64 shrink-0 flex flex-col">
      <div className="px-4 py-3 border-b border-gray-200">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Booking Progress</h2>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-4">
        <ol className="relative border-l border-gray-200 ml-2">
          {WORKFLOW_STEPS.map((step) => {
            const status = stepStatus(step, workflowState)
            return (
              <li key={step.key} className="mb-6 ml-4">
                <span
                  className={`absolute -left-[9px] flex items-center justify-center w-4 h-4 rounded-full ring-2 ring-white ${
                    status === 'done'
                      ? 'bg-green-500'
                      : status === 'active'
                      ? 'bg-blue-600'
                      : 'bg-gray-200'
                  }`}
                >
                  {status === 'done' && (
                    <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 16 12">
                      <path stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M1 5.917 5.724 10.5 15 1.5" />
                    </svg>
                  )}
                </span>
                <p
                  className={`text-sm leading-tight ${
                    status === 'active'
                      ? 'font-semibold text-blue-700'
                      : status === 'done'
                      ? 'text-gray-400 line-through'
                      : 'text-gray-500'
                  }`}
                >
                  {step.label}
                </p>
              </li>
            )
          })}
        </ol>
      </div>
      <div className="px-4 py-3 border-t border-gray-200">
        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-blue-50 text-blue-700">
          {workflowState.replace(/_/g, ' ')}
        </span>
      </div>
    </div>
  )
}
