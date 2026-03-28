/**
 * Reusable 28×28 icon button with a hover tooltip.
 * Props:
 *   icon       – Lucide icon component
 *   tooltip    – string shown on hover
 *   onClick    – handler
 *   active     – boolean, applies activeClassName
 *   activeColor– Tailwind text color class when active (default 'text-green-600')
 *   disabled   – boolean
 *   className  – extra classes
 */
export default function ActionButton({
  icon: Icon,
  tooltip,
  onClick,
  active = false,
  activeColor = 'text-green-600',
  disabled = false,
  className = '',
}) {
  return (
    <div className="relative group/tip">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={tooltip}
        className={`
          flex items-center justify-center w-7 h-7 rounded-md
          transition-colors duration-100
          ${active
            ? `${activeColor} bg-transparent`
            : 'text-gray-400 hover:text-gray-700 hover:bg-gray-100'}
          disabled:opacity-30 disabled:cursor-not-allowed
          ${className}
        `}
      >
        <Icon size={16} strokeWidth={active ? 2.5 : 1.75} />
      </button>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="
            pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5
            px-2 py-1 rounded bg-gray-800 text-white text-[11px] whitespace-nowrap
            opacity-0 group-hover/tip:opacity-100 transition-opacity duration-100
            z-50
          "
        >
          {tooltip}
        </div>
      )}
    </div>
  )
}
