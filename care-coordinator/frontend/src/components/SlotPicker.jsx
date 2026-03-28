export default function SlotPicker({ slots, selectedSlot, onSelect }) {
  if (!slots || slots.length === 0) return null

  return (
    <div className="mt-2">
      <p className="text-xs font-medium text-gray-500 mb-2">Available slots</p>
      <div className="flex flex-wrap gap-2">
        {slots.map((slot, i) => (
          <button
            key={i}
            onClick={() => onSelect(slot)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
              selectedSlot === slot
                ? 'bg-blue-600 text-white border-blue-600'
                : 'bg-white text-gray-700 border-gray-300 hover:border-blue-400 hover:text-blue-600'
            }`}
          >
            {slot}
          </button>
        ))}
      </div>
    </div>
  )
}
