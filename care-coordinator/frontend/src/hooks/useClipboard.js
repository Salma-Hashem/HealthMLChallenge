import { useState, useCallback } from 'react'

const RESET_DELAY_MS = 2000

/**
 * Returns { copied, copyText }.
 * copyText(text) writes to clipboard; `copied` is true for 2 s then resets.
 * Falls back to a textarea-based copy for browsers without Clipboard API.
 */
export function useClipboard() {
  const [copied, setCopied] = useState(false)
  const [denied, setDenied] = useState(false)

  const copyText = useCallback(async (text) => {
    if (!text) return

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
      } else {
        // Fallback: create a transient textarea
        const ta = document.createElement('textarea')
        ta.value = text
        ta.style.cssText = 'position:fixed;opacity:0;pointer-events:none'
        document.body.appendChild(ta)
        ta.select()
        const ok = document.execCommand('copy')
        document.body.removeChild(ta)
        if (!ok) throw new Error('execCommand failed')
      }
      setCopied(true)
      setDenied(false)
      setTimeout(() => setCopied(false), RESET_DELAY_MS)
    } catch {
      setDenied(true)
      setTimeout(() => setDenied(false), RESET_DELAY_MS)
    }
  }, [])

  return { copied, denied, copyText }
}
