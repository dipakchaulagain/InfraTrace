import { useEffect } from 'react'
import { AlertTriangle, X } from 'lucide-react'
import { cn } from '../lib/utils'

interface ToastProps {
  message: string
  type?: 'warning' | 'info'
  duration?: number   // ms before auto-dismiss; 0 disables auto-dismiss
  onClose: () => void
}

const STYLES: Record<NonNullable<ToastProps['type']>, string> = {
  warning: 'bg-yellow-50 border-yellow-200 text-yellow-700',
  info: 'bg-primary-50 border-primary-100 text-gray-700',
}

// Fixed top-right notification that auto-dismisses — for transient,
// non-blocking messages (e.g. "your session expired") that shouldn't sit
// permanently in the page layout the way an inline banner would.
export default function Toast({ message, type = 'warning', duration = 6000, onClose }: ToastProps) {
  useEffect(() => {
    if (duration <= 0) return
    const timer = setTimeout(onClose, duration)
    return () => clearTimeout(timer)
  }, [duration, onClose])

  return (
    <div className="fixed top-4 right-4 z-50 w-full max-w-sm page-enter">
      <div className={cn('flex items-start gap-2.5 rounded-lg border shadow-lg px-4 py-3', STYLES[type])}>
        <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
        <p className="text-sm flex-1">{message}</p>
        <button onClick={onClose} className="shrink-0 opacity-60 hover:opacity-100 transition-opacity" aria-label="Dismiss">
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
