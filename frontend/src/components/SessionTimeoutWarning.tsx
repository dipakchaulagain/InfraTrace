import { useEffect, useRef, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { activity, getMe } from '../lib/api'
import { useAuth } from '../lib/auth'

const WARN_BEFORE_MS = 2 * 60 * 1000   // show the warning 2 minutes before idle expiry
const CHECK_INTERVAL_MS = 15 * 1000

export default function SessionTimeoutWarning() {
  const { user, logout } = useAuth()
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null)
  const idleTimeoutMs = (user?.session_idle_timeout_minutes ?? 30) * 60 * 1000
  const stayingSignedIn = useRef(false)

  useEffect(() => {
    const interval = setInterval(() => {
      const idleFor = Date.now() - activity.lastActivityAt
      const remaining = idleTimeoutMs - idleFor

      if (remaining <= 0) {
        clearInterval(interval)
        logout()
        window.location.href = '/login?reason=session_expired'
        return
      }
      setSecondsLeft(remaining <= WARN_BEFORE_MS ? Math.round(remaining / 1000) : null)
    }, CHECK_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [idleTimeoutMs, logout])

  if (secondsLeft === null) return null

  async function staySignedIn() {
    if (stayingSignedIn.current) return
    stayingSignedIn.current = true
    try {
      await getMe()   // any authenticated call refreshes server-side session activity
    } finally {
      stayingSignedIn.current = false
    }
  }

  const minutes = Math.floor(secondsLeft / 60)
  const seconds = secondsLeft % 60

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="card max-w-sm w-full p-6 text-center space-y-4">
        <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-yellow-50 text-yellow-500 mx-auto">
          <AlertTriangle className="h-6 w-6" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-gray-800">Session expiring soon</h2>
          <p className="text-sm text-gray-500 mt-1">
            You've been inactive. For your security, you'll be signed out in{' '}
            <span className="font-semibold text-gray-700">
              {minutes}:{String(seconds).padStart(2, '0')}
            </span>.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={staySignedIn} className="btn-primary flex-1 justify-center">
            Stay signed in
          </button>
          <button onClick={logout} className="btn-ghost flex-1 justify-center">
            Log out
          </button>
        </div>
      </div>
    </div>
  )
}
