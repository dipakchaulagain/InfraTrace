import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, ToggleLeft, ToggleRight, Users, Building2, Layers, Server, Tag, AppWindow, KeyRound, Copy, Check, Download, Trash2, AlertTriangle } from 'lucide-react'
import {
  listDepartments, createDepartment, deleteDepartment,
  listEnvironments, createEnvironment, deleteEnvironment,
  listApplications, createApplication, deleteApplication,
  listTags, createTag, deleteTag,
  listUsers, createUser, updateUser, triggerUserReset,
  getUserOwnedVms, deleteUser,
  listSources, toggleSource,
  exportVms,
} from '../lib/api'
import ErrorBanner from '../components/ErrorBanner'
import Spinner from '../components/Spinner'
import Drawer from '../components/Drawer'
import MetadataEntityManager from '../components/MetadataEntityManager'
import { formatDate } from '../lib/utils'
import { ROLE_LABELS, type Role } from '../lib/permissions'
import PasswordRules from '../components/PasswordRules'
import { useAuth } from '../lib/auth'

type Section = 'users' | 'departments' | 'applications' | 'environments' | 'tags' | 'sources' | 'export'

export default function Admin() {
  const [section, setSection] = useState<Section>('users')
  const qc = useQueryClient()

  const SECTIONS: { id: Section; label: string; icon: typeof Users }[] = [
    { id: 'users', label: 'Users', icon: Users },
    { id: 'departments', label: 'Departments', icon: Building2 },
    { id: 'applications', label: 'Applications', icon: AppWindow },
    { id: 'environments', label: 'Environments', icon: Layers },
    { id: 'tags', label: 'Tags', icon: Tag },
    { id: 'sources', label: 'Connectors', icon: Server },
    { id: 'export', label: 'Export', icon: Download },
  ]

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-gray-800">Admin</h1>
        <p className="text-sm text-gray-500 mt-0.5">Manage users, lookups, and source system connectors</p>
      </div>

      <div className="flex gap-1 border-b border-gray-200 overflow-x-auto">
        {SECTIONS.map(s => (
          <button
            key={s.id}
            onClick={() => setSection(s.id)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px
              whitespace-nowrap transition-colors
              ${section === s.id ? 'border-primary text-primary' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
          >
            <s.icon className="h-4 w-4" />
            {s.label}
          </button>
        ))}
      </div>

      {section === 'users' && <UsersSection qc={qc} />}
      {section === 'departments' && (
        <MetadataEntityManager
          label="Department" queryKey="departments" filterParam="department_id"
          listFn={listDepartments} createFn={p => createDepartment(p.name)} deleteFn={deleteDepartment}
        />
      )}
      {section === 'applications' && (
        <MetadataEntityManager
          label="Application" queryKey="applications" filterParam="application_id"
          listFn={listApplications} createFn={p => createApplication(p.name)} deleteFn={deleteApplication}
        />
      )}
      {section === 'environments' && (
        <MetadataEntityManager
          label="Environment" queryKey="environments" filterParam="environment_id"
          listFn={listEnvironments} createFn={p => createEnvironment(p.name)} deleteFn={deleteEnvironment}
        />
      )}
      {section === 'tags' && (
        <MetadataEntityManager
          label="Tag" queryKey="tags" filterParam="tag_id" hasCategory
          listFn={listTags} createFn={p => createTag(p.name, p.category)} deleteFn={deleteTag}
        />
      )}
      {section === 'sources' && <SourcesSection qc={qc} />}
      {section === 'export' && <ExportSection />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------
const ROLE_BADGE: Record<string, string> = {
  admin: 'badge-red', global_editor: 'badge-blue', user: 'badge-teal', viewer: 'badge-gray',
}

const EMPTY_FORM = {
  username: '', email: '', full_name: '', phone: '', password: '',
  role: 'viewer', department_id: '', login_allowed: false,
}

function UsersSection({ qc }: { qc: ReturnType<typeof useQueryClient> }) {
  const navigate = useNavigate()
  const { user: currentUser } = useAuth()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [error, setError] = useState('')
  const [resetCode, setResetCode] = useState<{ username: string; code: string } | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null)

  const { data: users = [], isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: () => listUsers().then(r => r.data),
  })
  const { data: departments = [] } = useQuery({
    queryKey: ['departments'],
    queryFn: () => listDepartments().then(r => r.data),
  })

  const createMutation = useMutation({
    mutationFn: () => createUser({ ...form, department_id: form.department_id || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['users'] })
      setDrawerOpen(false)
      setForm(EMPTY_FORM)
      setError('')
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to create user.')
    },
  })

  const toggleMutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, unknown> }) => updateUser(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })

  const resetMutation = useMutation({
    mutationFn: (u: AdminUser) => triggerUserReset(u.id).then(r => ({ username: u.username, code: r.data.code })),
    onSuccess: (data) => { setResetCode(data); qc.invalidateQueries({ queryKey: ['users'] }) },
  })

  function handleDeleted() {
    setDeleteTarget(null)
    qc.invalidateQueries({ queryKey: ['users'] })
  }

  function closeDrawer() {
    setDrawerOpen(false)
    setError('')
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button onClick={() => setDrawerOpen(true)} className="btn-primary">
          <Plus className="h-4 w-4" /> New User
        </button>
      </div>

      {resetCode && (
        <ResetCodeModal username={resetCode.username} code={resetCode.code} onClose={() => setResetCode(null)} />
      )}

      {deleteTarget && (
        <DeleteUserModal user={deleteTarget} onClose={() => setDeleteTarget(null)} onDeleted={handleDeleted} />
      )}

      <Drawer open={drawerOpen} onClose={closeDrawer} title="Create User">
        <form onSubmit={e => { e.preventDefault(); createMutation.mutate() }} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Username</label>
            <input type="text" className="input" value={form.username} onChange={e => setForm(v => ({ ...v, username: e.target.value }))} required />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Full Name</label>
            <input type="text" className="input" value={form.full_name} onChange={e => setForm(v => ({ ...v, full_name: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Email</label>
            <input type="email" className="input" value={form.email} onChange={e => setForm(v => ({ ...v, email: e.target.value }))} required />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Phone <span className="text-gray-400 font-normal">(optional)</span></label>
            <input type="tel" className="input" value={form.phone} onChange={e => setForm(v => ({ ...v, phone: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Temporary Password</label>
            <input type="password" className="input" value={form.password} onChange={e => setForm(v => ({ ...v, password: e.target.value }))} required />
            <PasswordRules password={form.password} />
            <p className="text-xs text-gray-400 mt-1">The user will be required to change this at first login.</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Role</label>
            <select className="select" value={form.role} onChange={e => setForm(v => ({ ...v, role: e.target.value }))}>
              {(Object.keys(ROLE_LABELS) as Role[]).map(r => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Department</label>
            <select className="select" value={form.department_id} onChange={e => setForm(v => ({ ...v, department_id: e.target.value }))}>
              <option value="">— none —</option>
              {departments.map((d: Lookup) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              className="rounded border-gray-300 text-primary focus:ring-primary"
              checked={form.login_allowed}
              onChange={e => setForm(v => ({ ...v, login_allowed: e.target.checked }))}
            />
            Allow login immediately (defaults off)
          </label>
          {error && <ErrorBanner message={error} />}
          <div className="flex gap-2 pt-1">
            <button type="submit" className="btn-primary" disabled={createMutation.isPending}>
              {createMutation.isPending ? <Spinner size="sm" /> : null} Create
            </button>
            <button type="button" onClick={closeDrawer} className="btn-ghost">Cancel</button>
          </div>
        </form>
      </Drawer>

      <div className="card">
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Full Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Department</th>
                <th>VM Count</th>
                <th>Last Login</th>
                <th>Login Allowed</th>
                <th>Active</th>
                <th>Reset</th>
                <th>Delete</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={11} className="text-center py-8"><Spinner /></td></tr>
              ) : users.map((u: AdminUser) => (
                <tr key={u.id}>
                  <td className="font-medium">
                    {u.username}
                    {u.must_reset_password && <span className="badge badge-yellow ml-2">reset pending</span>}
                  </td>
                  <td className="text-sm text-gray-600">{u.full_name || <span className="text-gray-400">—</span>}</td>
                  <td className="text-sm text-gray-500">{u.email}</td>
                  <td><span className={`badge ${ROLE_BADGE[u.role] ?? 'badge-gray'}`}>{ROLE_LABELS[u.role as Role] ?? u.role}</span></td>
                  <td>{u.department_id ? <span className="badge badge-teal">{u.department_id.slice(0, 8)}…</span> : '—'}</td>
                  <td>
                    <button
                      onClick={() => navigate(`/vms?owner_user_id=${u.id}`)}
                      className={u.owned_vm_count > 0 ? 'badge badge-teal hover:opacity-80' : 'badge badge-gray'}
                      title={`View VMs owned by ${u.username}`}
                    >
                      {u.owned_vm_count}
                    </button>
                  </td>
                  <td className="text-xs text-gray-400">{u.last_login_at ? formatDate(u.last_login_at) : 'never'}</td>
                  <td>
                    <button
                      onClick={() => toggleMutation.mutate({ id: u.id, patch: { login_allowed: !u.login_allowed } })}
                      className={u.login_allowed ? 'text-green-500' : 'text-gray-400'}
                      title={u.login_allowed ? 'Login allowed — click to revoke' : 'Login blocked — click to allow'}
                    >
                      {u.login_allowed ? <ToggleRight className="h-5 w-5" /> : <ToggleLeft className="h-5 w-5" />}
                    </button>
                  </td>
                  <td>
                    <button
                      onClick={() => toggleMutation.mutate({ id: u.id, patch: { active: !u.active } })}
                      className={u.active ? 'text-green-500' : 'text-gray-400'}
                    >
                      {u.active ? <ToggleRight className="h-5 w-5" /> : <ToggleLeft className="h-5 w-5" />}
                    </button>
                  </td>
                  <td>
                    <button
                      onClick={() => resetMutation.mutate(u)}
                      className="btn-ghost !px-2 !py-1"
                      disabled={resetMutation.isPending}
                      title="Generate a one-time password reset code"
                    >
                      <KeyRound className="h-4 w-4" />
                    </button>
                  </td>
                  <td>
                    <button
                      onClick={() => setDeleteTarget(u)}
                      className="btn-ghost !px-2 !py-1 text-red-500 hover:bg-red-50 disabled:opacity-30 disabled:hover:bg-transparent"
                      disabled={u.id === currentUser?.id}
                      title={u.id === currentUser?.id ? "You can't delete your own account" : 'Delete user'}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Source systems (connectors) — read-only view; credentials managed in Settings
// ---------------------------------------------------------------------------
function SourcesSection({ qc }: { qc: ReturnType<typeof useQueryClient> }) {
  const { data: sources = [] } = useQuery({ queryKey: ['sources'], queryFn: () => listSources().then(r => r.data) })
  const toggleMut = useMutation({
    mutationFn: (id: string) => toggleSource(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sources'] }),
  })

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-primary-50 border border-primary-100 px-4 py-3 text-sm text-gray-600">
        Connector credentials (host, username, password) are managed in the{' '}
        <a href="/settings" className="text-primary font-medium underline underline-offset-2">Settings page</a>.
        Use the toggle here to enable or disable a connector without losing its credentials.
      </div>

      <div className="card divide-y divide-gray-50">
        {sources.length === 0 && (
          <div className="text-center text-gray-400 text-sm py-8">
            No connectors configured yet. Go to Settings to add credentials.
          </div>
        )}
        {sources.map((s: SourceItem) => (
          <div key={s.id} className="px-4 py-4 flex items-center justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium text-gray-800">{s.display_name}</span>
                <span className={`badge ${s.platform === 'vmware' ? 'badge-blue' : 'badge-teal'}`}>
                  {s.platform}
                </span>
                <span className={`badge ${s.has_credentials ? 'badge-green' : 'badge-yellow'}`}>
                  {s.has_credentials ? 'credentials saved' : 'no credentials'}
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-0.5 truncate">{s.base_url || '—'}</p>
            </div>
            <button
              onClick={() => toggleMut.mutate(s.id)}
              className={s.is_active ? 'text-green-500 shrink-0' : 'text-gray-300 shrink-0'}
              title={s.is_active ? 'Active — click to disable' : 'Inactive — click to enable'}
            >
              {s.is_active ? <ToggleRight className="h-6 w-6" /> : <ToggleLeft className="h-6 w-6" />}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Export — full VM inventory + metadata as CSV (admin only)
// ---------------------------------------------------------------------------
function ExportSection() {
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')

  async function handleExport() {
    setExporting(true)
    setError('')
    try {
      const { data } = await exportVms()
      const headers = [
        'Name', 'Platform', 'Power State', 'OS', 'OS Detail', 'vCPU', 'Memory', 'Disk', 'IP',
        'IP Address', 'IP Address Status', 'Applications', 'Tags', 'Cluster', 'Host', 'Owner', 'Secondary Owner',
        'Department', 'Environment', 'Notes',
      ]
      const rows = (data as ExportVM[]).map(vm => [
        vm.name, vm.source_platform, vm.power_state,
        vm.os_type ?? '', vm.os_detail ?? '', vm.vcpu ?? '', vm.memory_mb ? `${vm.memory_mb}MB` : '',
        vm.disk_gb ? `${vm.disk_gb}GB` : '', vm.primary_ip ?? '',
        vm.management_ip ?? '', vm.management_ip_status ?? '',
        (vm.applications ?? []).map(a => a.name).join('; '),
        (vm.tags ?? []).map(t => t.name).join('; '),
        vm.cluster ?? '', vm.host_node ?? '',
        vm.owner_username ?? '', vm.secondary_owner_username ?? '',
        vm.department_name ?? '', vm.environment_name ?? '', vm.notes ?? '',
      ])
      const csv = [headers, ...rows].map(r => r.map((v: unknown) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n')
      const blob = new Blob([csv], { type: 'text/csv' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'infratrace-vms.csv'; a.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('Failed to export VMs.')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="space-y-4 max-w-lg">
      <div className="rounded-lg bg-primary-50 border border-primary-100 px-4 py-3 text-sm text-gray-600">
        Exports every active (non-decommissioned) VM with full metadata — ownership, department,
        environment, OS detail, IP address, applications, and notes — as a single CSV file.
      </div>
      {error && <ErrorBanner message={error} />}
      <button onClick={handleExport} className="btn-primary" disabled={exporting}>
        {exporting ? <Spinner size="sm" /> : <Download className="h-4 w-4" />}
        Export CSV
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Reset code modal — shows a generated one-time code exactly once
// ---------------------------------------------------------------------------
function ResetCodeModal({ username, code, onClose }: { username: string; code: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false)

  function copy() {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="card max-w-sm w-full p-6 space-y-4">
        <div>
          <h3 className="font-semibold text-gray-800">Reset code for {username}</h3>
          <p className="text-xs text-gray-500 mt-1">
            Relay this code to the user out-of-band. It will not be shown again and expires shortly.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <code className="flex-1 text-center text-lg font-mono tracking-widest bg-gray-50 border border-gray-200 rounded-lg py-2">
            {code}
          </code>
          <button onClick={copy} className="btn-secondary !px-2.5" title="Copy to clipboard">
            {copied ? <Check className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
          </button>
        </div>
        <button onClick={onClose} className="btn-primary w-full justify-center">Done</button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Delete user modal — confirms permanent deletion, previewing any VMs the
// user owns since deleting them clears ownership on all of those VMs.
// ---------------------------------------------------------------------------
function DeleteUserModal({ user, onClose, onDeleted }: { user: AdminUser; onClose: () => void; onDeleted: () => void }) {
  const [error, setError] = useState('')

  const { data: owned, isLoading } = useQuery({
    queryKey: ['user-owned-vms', user.id],
    queryFn: () => getUserOwnedVms(user.id).then(r => r.data as { count: number; vms: { id: string; name: string }[] }),
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteUser(user.id),
    onSuccess: onDeleted,
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to delete user.')
    },
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="card max-w-md w-full p-6 space-y-4">
        <div className="flex items-start gap-3">
          <div className="shrink-0 rounded-full bg-red-100 p-2">
            <AlertTriangle className="h-5 w-5 text-red-600" />
          </div>
          <div className="min-w-0">
            <h3 className="font-semibold text-gray-800">Delete {user.username}?</h3>
            <p className="text-sm text-gray-500 mt-1">
              This permanently removes the account. This cannot be undone.
            </p>
          </div>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-2"><Spinner size="sm" /></div>
        ) : owned && owned.count > 0 ? (
          <div className="rounded-lg bg-yellow-50 border border-yellow-200 px-4 py-3 text-sm text-yellow-800">
            <p className="font-medium">
              This user owns {owned.count} VM{owned.count === 1 ? '' : 's'}. Deleting the account will clear
              ownership on {owned.count === 1 ? 'it' : 'them'}.
            </p>
            <ul className="mt-2 max-h-32 overflow-y-auto space-y-0.5 list-disc list-inside">
              {owned.vms.map(v => <li key={v.id} className="truncate">{v.name}</li>)}
            </ul>
          </div>
        ) : (
          <p className="text-sm text-gray-500">This user does not own any VMs.</p>
        )}

        {error && <ErrorBanner message={error} />}

        <div className="flex gap-2 pt-1">
          <button
            onClick={() => deleteMutation.mutate()}
            className="btn-primary !bg-red-600 hover:!bg-red-700 focus:!ring-red-400"
            disabled={deleteMutation.isPending || isLoading}
          >
            {deleteMutation.isPending ? <Spinner size="sm" /> : <Trash2 className="h-4 w-4" />}
            Delete User
          </button>
          <button type="button" onClick={onClose} className="btn-ghost" disabled={deleteMutation.isPending}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

interface Lookup { id: string; name: string }
interface AdminUser {
  id: string; username: string; email: string; full_name: string | null; phone: string | null
  role: string; active: boolean
  login_allowed: boolean; must_reset_password: boolean
  department_id: string | null; last_login_at: string | null
  owned_vm_count: number
}
interface SourceItem { id: string; platform: string; display_name: string; base_url: string; is_active: boolean; has_credentials: boolean }
interface ExportVM {
  name: string; source_platform: string; power_state: string
  os_type: string | null; os_detail: string | null; vcpu: number | null; memory_mb: number | null
  disk_gb: number | null; primary_ip: string | null; management_ip: string | null
  management_ip_status: string | null
  applications: { id: string; name: string }[] | null
  tags: { id: string; name: string }[] | null
  cluster: string | null
  host_node: string | null; owner_username: string | null; secondary_owner_username: string | null
  department_name: string | null; environment_name: string | null; notes: string | null
}
