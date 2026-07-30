import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ShieldAlert } from 'lucide-react'
import { changePassword } from '../lib/api'
import { useAuth } from '../lib/auth'
import Spinner from '../components/Spinner'
import PasswordRules from '../components/PasswordRules'

export default function ResetRequired() {
  const { logout, refreshUser } = useAuth()
  const navigate = useNavigate()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    if (newPassword !== confirm) {
      setError('New password and confirmation do not match.')
      return
    }
    setLoading(true)
    try {
      await changePassword(currentPassword, newPassword)
      refreshUser({ must_reset_password: false })
      navigate('/')
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Could not update password.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <img src="/login-logo.png" alt="InfraTrace" className="mx-auto w-72 max-w-full h-auto mb-4" />
          <h1 className="text-xl font-bold text-gray-800 flex items-center justify-center gap-2">
            <ShieldAlert className="h-5 w-5 text-primary" />
            Password reset required
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Set a new password before continuing.
          </p>
        </div>

        <div className="card p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Current / temporary password</label>
              <input
                type="password"
                className="input"
                value={currentPassword}
                onChange={e => setCurrentPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">New password</label>
              <input
                type="password"
                className="input"
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                autoComplete="new-password"
                required
              />
              <PasswordRules password={newPassword} />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Confirm new password</label>
              <input
                type="password"
                className="input"
                value={confirm}
                onChange={e => setConfirm(e.target.value)}
                autoComplete="new-password"
                required
              />
            </div>

            {error && (
              <div className="rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2.5">
                {error}
              </div>
            )}

            <button type="submit" className="btn-primary w-full justify-center py-2.5" disabled={loading}>
              {loading ? <Spinner size="sm" /> : null}
              Set new password
            </button>
            <button type="button" onClick={logout} className="btn-ghost w-full justify-center">
              Log out instead
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
