import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

// Attach JWT token from localStorage on every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('infratrace_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Timestamp of the last successful authenticated response — drives the
// idle-session warning (see SessionTimeoutWarning.tsx). Role/ownership
// denials surface as 403 and never touch this or the redirect logic below.
export const activity = { lastActivityAt: Date.now() }

// On 401 (bad/expired/revoked session), clear local auth state and redirect
// to login. 403s are role/ownership denials and are left for callers to
// handle as in-app errors — they never force a logout.
api.interceptors.response.use(
  (res) => {
    activity.lastActivityAt = Date.now()
    return res
  },
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('infratrace_token')
      localStorage.removeItem('infratrace_user')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login?reason=session_expired'
      }
    }
    return Promise.reject(err)
  },
)

// ---- Auth ----
export const login = (username: string, password: string) => {
  const form = new URLSearchParams()
  form.append('username', username)
  form.append('password', password)
  return api.post('/auth/token', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
}
export const logoutApi = () => api.post('/auth/logout')
export const getMe = () => api.get('/auth/me')
export const changePassword = (current_password: string, new_password: string) =>
  api.post('/auth/change-password', { current_password, new_password })
export const resetPassword = (username: string, code: string, new_password: string) =>
  api.post('/auth/reset-password', { username, code, new_password })

// ---- VMs ----
export const getVmSummary = () => api.get('/vms/summary')
export const listVms = (params?: Record<string, unknown>) => api.get('/vms', { params })
export const listDecommissionedVms = (params?: Record<string, unknown>) => api.get('/vms/decommissioned', { params })
export const getVm = (id: string) => api.get(`/vms/${id}`)
export const updateVmMetadata = (id: string, data: Record<string, unknown>) =>
  api.patch(`/vms/${id}/metadata`, data)
export const getVmHistory = (id: string) => api.get(`/vms/${id}/history`)
export const getVmMetadataAudit = (id: string) => api.get(`/vms/${id}/metadata-audit`)

// ---- Hosts ----
export const listHosts = (params?: Record<string, unknown>) => api.get('/hosts', { params })

// ---- Networks ----
export const listNetworks = (params?: Record<string, unknown>) => api.get('/networks', { params })

// ---- Sync ----
export const listSyncRuns = (limit = 20) => api.get('/sync/runs', { params: { limit } })
export const getSyncRun = (id: string) => api.get(`/sync/runs/${id}`)
export const triggerSync = (platform: string) => api.post(`/sync/trigger/${platform}`)
export const listDeadLetters = (resolved = false) =>
  api.get('/sync/dead-letters', { params: { resolved } })
export const resolveDeadLetter = (id: string) => api.post(`/sync/dead-letters/${id}/resolve`)

// ---- Settings (admin) ----
export const getSettings = () => api.get('/settings')
export const updateVmwareSettings = (data: Record<string, unknown>) => api.put('/settings/vmware', data)
export const updateNutanixSettings = (data: Record<string, unknown>) => api.put('/settings/nutanix', data)
export const updateSyncSettings = (data: Record<string, unknown>) => api.put('/settings/sync', data)
export const updateGeneralSettings = (data: Record<string, unknown>) => api.put('/settings/general', data)
export const testConnection = (platform: string) => api.post(`/settings/test/${platform}`)

// ---- Admin ----
export const listDepartments = () => api.get('/admin/departments')
export const createDepartment = (name: string) => api.post('/admin/departments', { name })
export const listEnvironments = () => api.get('/admin/environments')
export const createEnvironment = (name: string) => api.post('/admin/environments', { name })
export const listTags = () => api.get('/admin/tags')
export const createTag = (name: string, category?: string) => api.post('/admin/tags', { name, category })
export const listUsers = () => api.get('/admin/users')
export const listUsersLookup = () => api.get('/admin/users/lookup')
export const createUser = (data: Record<string, unknown>) => api.post('/admin/users', data)
export const updateUser = (id: string, data: Record<string, unknown>) => api.patch(`/admin/users/${id}`, data)
export const triggerUserReset = (id: string) => api.post(`/admin/users/${id}/trigger-reset`)
export const listSources = () => api.get('/admin/sources')
export const createSource = (data: Record<string, unknown>) => api.post('/admin/sources', data)
export const toggleSource = (id: string) => api.patch(`/admin/sources/${id}/toggle`)
export const listAuditLogs = (params?: Record<string, unknown>) => api.get('/admin/audit-logs', { params })
