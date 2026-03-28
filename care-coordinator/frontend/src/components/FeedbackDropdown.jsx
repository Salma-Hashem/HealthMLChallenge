import { useEffect, useRef } from 'react'

const OPTIONS = [
  { value: 'wrong_info',      label: 'Wrong information' },
  { value: 'unanswered',      label: "Didn't answer my question" },
  { value: 'too_slow',        label: 'Too slow' },
  { value: 'other',           label: 'Other' },
]

/**
 * Small dropdown that appears after a thumbs-down click.
 * Props:
 *   onSelect(reason)  – called with one of the option values
 *   onDismiss()       – called when dismissed without selection
 */
export default function FeedbackDropdown({ onSelect, onDismiss }) {
  const ref = useRef(null)

  // Dismiss on click outside
  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) onDismiss()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onDismiss])

  return (
    <div
      ref={ref}
      className="
        absolute left-0 top-full mt-1 z-50
        bg-white border border-gray-200 rounded-xl shadow-lg
        py-1 min-w-[192px]
        animate-in fade-in slide-in-from-top-1 duration-100
      "
    >
      <p className="px-3 pt-1.5 pb-1 text-[11px] font-medium text-gray-400 uppercase tracking-wide">
        What went wrong?
      </p>
      {OPTIONS.map(opt => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onSelect(opt.value)}
          className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
        >
          {opt.label}
        </button>
      ))}
      <button
        type="button"
        onClick={onDismiss}
        className="w-full text-left px-3 py-1.5 text-sm text-gray-400 hover:bg-gray-50 transition-colors border-t border-gray-100 mt-1"
      >
        Skip
      </button>
    </div>
  )
}
