import { useState } from 'react'
import SlotPicker from './SlotPicker'

export default function BookingCard({ requiresConfirmation, onSend }) {
  const [slots] = useState([])
  const [selected, setSelected] = useState(null)

  if (!requiresConfirmation) return null

  return (
    <div className="mx-4 mb-3 bg-amber-50 border border-amber-200 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-amber-600 text-lg">📋</span>
        <p className="text-sm font-semibold text-amber-800">Booking Confirmation Required</p>
      </div>
      <p className="text-xs text-amber-700 mb-3">
        Please review the booking details in the chat and confirm or cancel below.
      </p>
      <SlotPicker slots={slots} selectedSlot={selected} onSelect={setSelected} />
      <div className="flex gap-2 mt-3">
        <button
          onClick={() => onSend('Yes, please confirm the booking.')}
          className="flex-1 bg-green-600 hover:bg-green-700 text-white text-sm font-medium py-2 px-3 rounded-lg transition-colors"
        >
          ✓ Confirm Booking
        </button>
        <button
          onClick={() => onSend('Cancel the booking.')}
          className="flex-1 bg-red-100 hover:bg-red-200 text-red-700 text-sm font-medium py-2 px-3 rounded-lg transition-colors"
        >
          ✕ Cancel
        </button>
      </div>
    </div>
  )
}
