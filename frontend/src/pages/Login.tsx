import { useState, FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Eye, EyeOff, KeyRound } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { resetPassword } from '../lib/api'
import Spinner from '../components/Spinner'
import PasswordRules from '../components/PasswordRules'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [mode, setMode] = useState<'login' | 'reset'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const sessionExpired = searchParams.get('reason') === 'session_expired'

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(username, password)
      navigate('/')
    } catch {
      setError('Invalid username or password.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-primary text-white text-2xl font-bold shadow-lg mb-4">
            I
          </div>
          <h1 className="text-2xl font-bold text-gray-800">InfraTrace</h1>
          <p className="text-sm text-gray-500 mt-1">VM Inventory Management System</p>
        </div>

        {sessionExpired && mode === 'login' && (
          <div className="rounded-lg bg-yellow-50 border border-yellow-200 text-yellow-700 text-sm px-3 py-2.5 mb-4">
            Your session expired due to inactivity. Please sign in again.
          </div>
        )}

        {mode === 'login' ? (
          <div className="card p-6">
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="username" className="block text-sm font-medium text-gray-700 mb-1">
                  Username
                </label>
                <input
                  id="username"
                  type="text"
                  className="input"
                  placeholder="admin"
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  autoComplete="username"
                  required
                />
              </div>

              <div>
                <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
                  Password
                </label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPw ? 'text' : 'password'}
                    className="input pr-10"
                    placeholder="••••••••"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    autoComplete="current-password"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw(s => !s)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    aria-label={showPw ? 'Hide password' : 'Show password'}
                  >
                    {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              {error && (
                <div className="rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2.5">
                  {error}
                </div>
              )}

              <button
                type="submit"
                className="btn-primary w-full justify-center py-2.5"
                disabled={loading}
              >
                {loading ? <Spinner size="sm" /> : null}
                Sign in
              </button>

              <button
                type="button"
                onClick={() => { setMode('reset'); setError('') }}
                className="w-full text-center text-xs text-gray-400 hover:text-primary transition-colors"
              >
                Have a password reset code?
              </button>
            </form>
          </div>
        ) : (
          <ResetForm onBack={() => { setMode('login'); setError('') }} />
        )}

        <p className="text-center text-xs text-gray-400 mt-6">
          InfraTrace v2.0 · Read-only sync from VMware &amp; Nutanix
        </p>
      </div>
    </div>
  )
}

function ResetForm({ onBack }: { onBack: () => void }) {
  const [username, setUsername] = useState('')
  const [code, setCode] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await resetPassword(username, code.trim(), newPassword)
      setDone(true)
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Invalid or expired code.')
    } finally {
      setLoading(false)
    }
  }

  if (done) {
    return (
      <div className="card p-6 text-center space-y-3">
        <KeyRound className="h-8 w-8 text-primary mx-auto" />
        <p className="text-sm text-gray-700">Password updated. You can now sign in.</p>
        <button onClick={onBack} className="btn-primary w-full justify-center">Back to sign in</button>
      </div>
    )
  }

  return (
    <div className="card p-6">
      <p className="text-xs text-gray-500 mb-4">
        Ask an administrator for a one-time reset code, then enter it below with your new password.
      </p>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
          <input type="text" className="input" value={username} onChange={e => setUsername(e.target.value)} required />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Reset code</label>
          <input
            type="text"
            className="input font-mono uppercase"
            value={code}
            onChange={e => setCode(e.target.value)}
            placeholder="A1B2C3D4"
            required
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">New password</label>
          <input type="password" className="input" value={newPassword} onChange={e => setNewPassword(e.target.value)} required />
          <PasswordRules password={newPassword} />
        </div>

        {error && (
          <div className="rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2.5">
            {error}
          </div>
        )}

        <button type="submit" className="btn-primary w-full justify-center py-2.5" disabled={loading}>
          {loading ? <Spinner size="sm" /> : null}
          Reset password
        </button>
        <button type="button" onClick={onBack} className="btn-ghost w-full justify-center">
          Back to sign in
        </button>
      </form>
    </div>
  )
}
