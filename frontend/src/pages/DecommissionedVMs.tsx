import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Archive } from 'lucide-react'
import { listDecommissionedVms, listDepartments, listEnvironments, listUsersLookup } from '../lib/api'
import SkeletonTable from '../components/SkeletonTable'
import ErrorBanner from '../components/ErrorBanner'
import EmptyState from '../components/EmptyState'
import Pagination from '../components/Pagination'
import { formatDate, platformBadge } from '../lib/utils'

interface Filters {
  decommissioned_from: string
  decommissioned_to: string
  owner_user_id: string
  department_id: string
  environment_id: string
}

const DEFAULT_FILTERS: Filters = {
  decommissioned_from: '', decommissioned_to: '',
  owner_user_id: '', department_id: '', environment_id: '',
}

export default function DecommissionedVMs() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS)
  const PAGE_SIZE = 50

  const params = {
    page,
    page_size: PAGE_SIZE,
    ...(filters.decommissioned_from && { decommissioned_from: filters.decommissioned_from }),
    ...(filters.decommissioned_to && { decommissioned_to: filters.decommissioned_to }),
    ...(filters.owner_user_id && { owner_user_id: filters.owner_user_id }),
    ...(filters.department_id && { department_id: filters.department_id }),
    ...(filters.environment_id && { environment_id: filters.environment_id }),
  }

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['vms-decommissioned', params],
    queryFn: () => listDecommissionedVms(params).then(r => r.data),
    placeholderData: prev => prev,
  })

  const { data: departments = [] } = useQuery({
    queryKey: ['departments'],
    queryFn: () => listDepartments().then(r => r.data),
  })
  const { data: environments = [] } = useQuery({
    queryKey: ['environments'],
    queryFn: () => listEnvironments().then(r => r.data),
  })
  const { data: owners = [] } = useQuery({
    queryKey: ['users-lookup'],
    queryFn: () => listUsersLookup().then(r => r.data),
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
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-800">Decommissioned VMs</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {data ? `${data.total.toLocaleString()} VMs` : 'Loading...'} — historical reference only
          </p>
        </div>
        <button onClick={() => navigate('/vms')} className="btn-ghost">Back to active VMs</button>
      </div>

      <div className="card p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Decommissioned from</label>
            <input
              type="date"
              className="input w-40"
              value={filters.decommissioned_from}
              onChange={e => setFilter('decommissioned_from', e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Decommissioned to</label>
            <input
              type="date"
              className="input w-40"
              value={filters.decommissioned_to}
              onChange={e => setFilter('decommissioned_to', e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Owner</label>
            <select className="select w-40" value={filters.owner_user_id} onChange={e => setFilter('owner_user_id', e.target.value)}>
              <option value="">All Owners</option>
              {owners.map((o: Lookup) => <option key={o.id} value={o.id}>{o.username}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Department</label>
            <select className="select w-40" value={filters.department_id} onChange={e => setFilter('department_id', e.target.value)}>
              <option value="">All Departments</option>
              {departments.map((d: Lookup) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Environment</label>
            <select className="select w-40" value={filters.environment_id} onChange={e => setFilter('environment_id', e.target.value)}>
              <option value="">All Environments</option>
              {environments.map((e: Lookup) => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select>
          </div>
          {hasActiveFilters && (
            <button onClick={resetFilters} className="btn-ghost text-red-500 hover:bg-red-50 self-end">
              Clear
            </button>
          )}
        </div>
      </div>

      {isError ? (
        <ErrorBanner message="Failed to load decommissioned VMs." onRetry={refetch} />
      ) : isLoading ? (
        <SkeletonTable rows={10} cols={7} />
      ) : data?.items?.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={Archive}
            title="No decommissioned VMs"
            description={hasActiveFilters ? 'Try adjusting your filters.' : 'Nothing has been decommissioned yet.'}
            action={hasActiveFilters ? <button onClick={resetFilters} className="btn-secondary">Clear filters</button> : undefined}
          />
        </div>
      ) : (
        <div className="card">
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Platform</th>
                  <th>Decommissioned At</th>
                  <th>Owner</th>
                  <th>Department</th>
                  <th>Environment</th>
                  <th>Last Known IP</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((vm: DecommissionedVM) => (
                  <tr key={vm.id} className="cursor-pointer" onClick={() => navigate(`/vms/${vm.id}`)}>
                    <td className="font-medium text-gray-800">{vm.name}</td>
                    <td><span className={platformBadge(vm.source_platform)}>{vm.source_platform}</span></td>
                    <td className="text-xs text-gray-500">{formatDate(vm.decommissioned_at)}</td>
                    <td>{vm.owner_username ?? '—'}</td>
                    <td>{vm.department_name ?? '—'}</td>
                    <td>{vm.environment_name ?? '—'}</td>
                    <td className="font-mono text-xs">{vm.primary_ip ?? '—'}</td>
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

interface DecommissionedVM {
  id: string; name: string; source_platform: string; decommissioned_at: string | null
  owner_username: string | null; department_name: string | null; environment_name: string | null
  primary_ip: string | null
}
interface Lookup { id: string; name?: string; username?: string }
