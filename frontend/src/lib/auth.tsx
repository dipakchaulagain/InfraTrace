import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'
import { login as apiLogin, logoutApi } from './api'

interface AuthUser {
  id: string
  username: string
  email: string
  role: string
  department_id: string | null
  must_reset_password: boolean
  session_idle_timeout_minutes: number
}

interface AuthContextValue {
  user: AuthUser | null
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  refreshUser: (patch: Partial<AuthUser>) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

function loadUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem('infratrace_user')
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(loadUser)

  const login = useCallback(async (username: string, password: string) => {
    const { data } = await apiLogin(username, password)
    localStorage.setItem('infratrace_token', data.access_token)
    localStorage.setItem('infratrace_user', JSON.stringify(data.user))
    setUser(data.user as AuthUser)
  }, [])

  const logout = useCallback(() => {
    // Best-effort — revoke the server-side session, but always clear local
    // state even if the request fails (e.g. session already expired).
    logoutApi().catch(() => {})
    localStorage.removeItem('infratrace_token')
    localStorage.removeItem('infratrace_user')
    setUser(null)
  }, [])

  const refreshUser = useCallback((patch: Partial<AuthUser>) => {
    setUser(prev => {
      if (!prev) return prev
      const next = { ...prev, ...patch }
      localStorage.setItem('infratrace_user', JSON.stringify(next))
      return next
    })
  }, [])

  return (
    <AuthContext.Provider value={{ user, isAuthenticated: !!user, login, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
