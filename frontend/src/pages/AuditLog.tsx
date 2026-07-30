import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileClock } from 'lucide-react'
import { listAuditLogs, listUsers } from '../lib/api'
import SkeletonTable from '../components/SkeletonTable'
import ErrorBanner from '../components/ErrorBanner'
import EmptyState from '../components/EmptyState'
import Pagination from '../components/Pagination'
import { formatDate } from '../lib/utils'

interface Filters {
  date_from: string
  date_to: string
  user_id: string
  action: string
  entity_type: string
}

const DEFAULT_FILTERS: Filters = { date_from: '', date_to: '', user_id: '', action: '', entity_type: '' }

const ACTIONS = [
  'login', 'logout', 'session_timeout', 'password_change',
  'password_reset_requested', 'password_reset_completed',
  'user_created', 'user_updated', 'vm_metadata_updated', 'vm_decommissioned',
  'vm_viewed', 'permission_denied',
]
const ENTITY_TYPES = ['user', 'vm', 'session', 'route']

export default function AuditLog() {
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS)
  const PAGE_SIZE = 50

  const params = {
    page,
    page_size: PAGE_SIZE,
    ...(filters.date_from && { date_from: filters.date_from }),
    ...(filters.date_to && { date_to: filters.date_to }),
    ...(filters.user_id && { user_id: filters.user_id }),
    ...(filters.action && { action: filters.action }),
    ...(filters.entity_type && { entity_type: filters.entity_type }),
  }

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['audit-logs', params],
    queryFn: () => listAuditLogs(params).then(r => r.data),
    placeholderData: prev => prev,
  })

  const { data: users = [] } = useQuery({
    queryKey: ['users'],
    queryFn: () => listUsers().then(r => r.data),
  })

  function setFilter<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters(f => ({ ...f, [key]: value }))
    setPage(1)
  }

  function resetFilters() {
    setFilters(DEFAULT_FILTERS)
    setPage(1)
  }

  const hasActiveFilters = Object.values(filters).some(v => v !== '')

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-gray-800">Audit Log</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {data ? `${data.total.toLocaleString()} events` : 'Loading...'}
        </p>
      </div>

      <div className="card p-3">
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">From</label>
            <input type="date" className="input w-40" value={filters.date_from} onChange={e => setFilter('date_from', e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">To</label>
            <input type="date" className="input w-40" value={filters.date_to} onChange={e => setFilter('date_to', e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">User</label>
            <select className="select w-44" value={filters.user_id} onChange={e => setFilter('user_id', e.target.value)}>
              <option value="">All Users</option>
              {users.map((u: AdminUser) => <option key={u.id} value={u.id}>{u.username}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Action</label>
            <select className="select w-48" value={filters.action} onChange={e => setFilter('action', e.target.value)}>
              <option value="">All Actions</option>
              {ACTIONS.map(a => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Entity</label>
            <select className="select w-36" value={filters.entity_type} onChange={e => setFilter('entity_type', e.target.value)}>
              <option value="">All Entities</option>
              {ENTITY_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          {hasActiveFilters && (
            <button onClick={resetFilters} className="btn-ghost text-red-500 hover:bg-red-50">Clear</button>
          )}
        </div>
      </div>

      {isError ? (
        <ErrorBanner message="Failed to load audit log." onRetry={refetch} />
      ) : isLoading ? (
        <SkeletonTable rows={10} cols={7} />
      ) : data?.items?.length === 0 ? (
        <div className="card">
          <EmptyState icon={FileClock} title="No matching events" description="Try adjusting your filters." />
        </div>
      ) : (
        <div className="card">
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>User</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Result</th>
                  <th>IP Address</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((r: AuditRow) => (
                  <tr key={r.id}>
                    <td className="text-xs text-gray-500 whitespace-nowrap">{formatDate(r.occurred_at)}</td>
                    <td className="text-sm">{r.user_email ?? <span className="text-gray-400">system</span>}</td>
                    <td className="font-medium text-sm">{r.action}</td>
                    <td className="text-xs text-gray-500">
                      {r.entity_type ?? '—'}{r.entity_id ? ` (${r.entity_id.slice(0, 8)}…)` : ''}
                    </td>
                    <td>
                      <span className={`badge ${r.result === 'success' ? 'badge-green' : 'badge-red'}`}>{r.result}</span>
                    </td>
                    <td className="font-mono text-xs">{r.ip_address ?? '—'}</td>
                    <td className="text-xs text-gray-500 max-w-[240px] truncate" title={JSON.stringify(r.details ?? {})}>
                      {r.details ? JSON.stringify(r.details) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-4">
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
          </div>
        </div>
      )}
    </div>
  )
}

interface AuditRow {
  id: string; occurred_at: string; user_email: string | null; action: string
  entity_type: string | null; entity_id: string | null; result: string
  ip_address: string | null; details: Record<string, unknown> | null
}
interface AdminUser { id: string; username: string }
