import { useEffect } from 'react'
import { X } from 'lucide-react'
import { cn } from '../lib/utils'

interface DrawerProps {
  open: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
}

// Slide-in panel attached to the right edge of the screen — used for
// create/edit forms so the underlying list doesn't shift/reflow.
export default function Drawer({ open, onClose, title, children }: DrawerProps) {
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <>
      <div
        className={cn(
          'fixed inset-0 z-40 bg-black/40 transition-opacity duration-200',
          open ? 'opacity-100' : 'opacity-0 pointer-events-none',
        )}
        onClick={onClose}
        aria-hidden
      />
      <div
        className={cn(
          'fixed inset-y-0 right-0 z-50 w-full max-w-md bg-white shadow-2xl',
          'flex flex-col transition-transform duration-250 ease-in-out',
          open ? 'translate-x-0' : 'translate-x-full',
        )}
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
      >
        <div className="flex items-center justify-between px-5 h-16 border-b border-gray-100 shrink-0">
          <h2 className="font-semibold text-gray-800">{title}</h2>
          <button onClick={onClose} className="btn-ghost !px-2 !py-2" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          {children}
        </div>
      </div>
    </>
  )
}
