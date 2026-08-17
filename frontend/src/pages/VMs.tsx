import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Search, Filter, Archive, ArrowUp, ArrowDown, ArrowUpDown, Pencil } from 'lucide-react'
import { listVms, listDepartments, listEnvironments, listUsersLookup, listApplications, listTags, listHosts } from '../lib/api'
import SkeletonTable from '../components/SkeletonTable'
import ErrorBanner from '../components/ErrorBanner'
import EmptyState from '../components/EmptyState'
import Pagination from '../components/Pagination'
import VmEditDrawer from '../components/VmEditDrawer'
import ColumnPicker from '../components/ColumnPicker'
import { formatBytes, formatGb, relativeTime, powerStateBadge, platformBadge } from '../lib/utils'
import { Monitor } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { canAccessPage, canEditVm } from '../lib/permissions'

interface Filters {
  search: string
  platform: string
  power_state: string
  os_detail: string
  tools_status: string
  cluster: string
  owner_user_id: string
  department_id: string
  environment_id: string
  application_id: string
  tag_id: string
  host_id: string
  unassigned_only: boolean
}

const DEFAULT_FILTERS: Filters = {
  search: '', platform: '', power_state: '',
  os_detail: '', tools_status: '', cluster: '', owner_user_id: '',
  department_id: '', environment_id: '', application_id: '', tag_id: '', host_id: '',
  unassigned_only: false,
}

const TOOLS_STATUS_OPTIONS = ['toolsOk', 'toolsOld', 'toolsNotRunning', 'toolsNotInstalled']

// Allows deep-linking in — from the Dashboard's stat cards (platform,
// power_state, unassigned_only), from Admin's metadata tabs / Users page
// click-through (department_id, environment_id, owner_user_id,
// application_id, tag_id), and from the Hosts page click-through (host_id).
function filtersFromSearchParams(params: URLSearchParams): Filters {
  return {
    ...DEFAULT_FILTERS,
    platform: params.get('platform') ?? '',
    power_state: params.get('power_state') ?? '',
    department_id: params.get('department_id') ?? '',
    environment_id: params.get('environment_id') ?? '',
    owner_user_id: params.get('owner_user_id') ?? '',
    application_id: params.get('application_id') ?? '',
    tag_id: params.get('tag_id') ?? '',
    host_id: params.get('host_id') ?? '',
    unassigned_only: params.get('unassigned_only') === 'true',
  }
}

// Filters only ever set via "More Filters" (never the always-visible main
// bar) — used to auto-expand that section when deep-linking sets one of them.
function hasMoreFiltersSet(f: Filters): boolean {
  return !!(f.application_id || f.tag_id || f.host_id || f.unassigned_only)
}

type SortField = 'name' | 'platform' | 'power_state' | 'os_type' | 'vcpu' | 'memory_mb' | 'disk_gb'
  | 'cluster' | 'owner' | 'department' | 'environment' | 'last_synced_at'

interface ColumnDef {
  key: string
  label: string
  group: 'Infrastructure' | 'Metadata'
  sortField?: SortField
  defaultVisible: boolean
  cellClassName?: string
  render: (vm: VM) => React.ReactNode
}

// Name and Edit are pinned (always shown, never toggleable) — everything
// else is opt-in/opt-out via the Columns picker. Order here is the display
// order; "defaultVisible" preserves exactly what the table showed before
// this picker existed, so nothing changes until a user opts in to more.
const ALL_COLUMNS: ColumnDef[] = [
  { key: 'platform', label: 'Platform', group: 'Infrastructure', sortField: 'platform', defaultVisible: true,
    render: vm => <span className={platformBadge(vm.source_platform)}>{vm.source_platform}</span> },
  { key: 'power_state', label: 'State', group: 'Infrastructure', sortField: 'power_state', defaultVisible: true,
    render: vm => <span className={powerStateBadge(vm.power_state)}>{vm.power_state}</span> },
  { key: 'os_type', label: 'OS', group: 'Infrastructure', sortField: 'os_type', defaultVisible: true,
    cellClassName: 'max-w-[200px] truncate text-gray-500 text-xs',
    render: vm => vm.os_type ?? '—' },
  { key: 'os_detail', label: 'OS Detail', group: 'Metadata', defaultVisible: false,
    cellClassName: 'max-w-[200px] truncate text-gray-500 text-xs',
    render: vm => vm.os_detail ?? '—' },
  { key: 'vcpu', label: 'vCPU', group: 'Infrastructure', sortField: 'vcpu', defaultVisible: true,
    render: vm => vm.vcpu ?? '—' },
  { key: 'memory_mb', label: 'Memory', group: 'Infrastructure', sortField: 'memory_mb', defaultVisible: true,
    render: vm => formatBytes(vm.memory_mb) },
  { key: 'disk_gb', label: 'Disk', group: 'Infrastructure', sortField: 'disk_gb', defaultVisible: true,
    render: vm => formatGb(vm.disk_gb) },
  { key: 'primary_ip', label: 'IP', group: 'Infrastructure', defaultVisible: true,
    cellClassName: 'font-mono text-xs',
    render: vm => vm.primary_ip ?? '—' },
  { key: 'management_ip', label: 'IP Address', group: 'Metadata', defaultVisible: false,
    cellClassName: 'font-mono text-xs',
    render: vm => vm.management_ip ?? '—' },
  { key: 'cluster', label: 'Cluster', group: 'Infrastructure', sortField: 'cluster', defaultVisible: false,
    cellClassName: 'text-xs text-gray-500',
    render: vm => vm.cluster ?? '—' },
  { key: 'host_node', label: 'Host', group: 'Infrastructure', defaultVisible: false,
    cellClassName: 'text-xs text-gray-500',
    render: vm => vm.host_node ?? '—' },
  { key: 'tools_status', label: 'Tools Status', group: 'Infrastructure', defaultVisible: false,
    cellClassName: 'text-xs text-gray-500',
    render: vm => vm.tools_status ?? '—' },
  { key: 'owner', label: 'Owner', group: 'Metadata', sortField: 'owner', defaultVisible: true,
    cellClassName: 'text-xs text-gray-600',
    render: vm => vm.owner_full_name ?? vm.owner_username ?? <span className="text-gray-400">—</span> },
  { key: 'secondary_owner', label: 'Secondary Owner', group: 'Metadata', defaultVisible: false,
    cellClassName: 'text-xs text-gray-600',
    render: vm => vm.secondary_owner_full_name ?? vm.secondary_owner_username ?? <span className="text-gray-400">—</span> },
  { key: 'department', label: 'Department', group: 'Metadata', sortField: 'department', defaultVisible: true,
    render: vm => vm.department_name ? <span className="badge badge-teal">{vm.department_name}</span> : <span className="text-gray-400 text-xs">unassigned</span> },
  { key: 'environment', label: 'Environment', group: 'Metadata', sortField: 'environment', defaultVisible: true,
    render: vm => vm.environment_name ? <span className="badge badge-green">{vm.environment_name}</span> : '—' },
  { key: 'applications', label: 'Applications', group: 'Metadata', defaultVisible: false,
    render: vm => {
      const apps = vm.applications ?? []
      return apps.length > 0
        ? <span className="inline-flex flex-wrap gap-1">{apps.map(a => <span key={a.id} className="badge badge-blue">{a.name}</span>)}</span>
        : <span className="text-gray-400 text-xs">—</span>
    } },
  { key: 'tags', label: 'Tags', group: 'Metadata', defaultVisible: false,
    render: vm => {
      const tags = vm.tags ?? []
      return tags.length > 0
        ? <span className="inline-flex flex-wrap gap-1">{tags.map(t => <span key={t.id} className="badge badge-teal">{t.name}</span>)}</span>
        : <span className="text-gray-400 text-xs">—</span>
    } },
  { key: 'notes', label: 'Notes', group: 'Metadata', defaultVisible: false,
    cellClassName: 'max-w-[200px] truncate text-xs text-gray-500',
    render: vm => vm.notes || '—' },
  { key: 'last_synced_at', label: 'Last Synced', group: 'Infrastructure', sortField: 'last_synced_at', defaultVisible: true,
    cellClassName: 'text-xs text-gray-400',
    render: vm => relativeTime(vm.last_synced_at) },
]

const DEFAULT_VISIBLE_COLUMNS = new Set(ALL_COLUMNS.filter(c => c.defaultVisible).map(c => c.key))
const COLUMNS_STORAGE_KEY = 'infratrace_vms_columns'

function loadVisibleColumns(): Set<string> {
  try {
    const raw = localStorage.getItem(COLUMNS_STORAGE_KEY)
    if (!raw) return DEFAULT_VISIBLE_COLUMNS
    const keys = JSON.parse(raw) as string[]
    const valid = new Set(ALL_COLUMNS.map(c => c.key))
    return new Set(keys.filter(k => valid.has(k)))
  } catch {
    return DEFAULT_VISIBLE_COLUMNS
  }
}

export default function VMs() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [searchParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState<Filters>(() => filtersFromSearchParams(searchParams))
  const [showFilters, setShowFilters] = useState(() => hasMoreFiltersSet(filtersFromSearchParams(searchParams)))
  const [sortBy, setSortBy] = useState<SortField>('name')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc')
  const [editTarget, setEditTarget] = useState<VM | null>(null)
  const [visibleColumns, setVisibleColumns] = useState<Set<string>>(loadVisibleColumns)
  const PAGE_SIZE = 50

  useEffect(() => {
    localStorage.setItem(COLUMNS_STORAGE_KEY, JSON.stringify([...visibleColumns]))
  }, [visibleColumns])

  const columns = ALL_COLUMNS.filter(c => visibleColumns.has(c.key))

  const params = {
    page,
    page_size: PAGE_SIZE,
    sort_by: sortBy,
    sort_order: sortOrder,
    ...(filters.search && { search: filters.search }),
    ...(filters.platform && { platform: filters.platform }),
    ...(filters.power_state && { power_state: filters.power_state }),
    ...(filters.os_detail && { os_detail: filters.os_detail }),
    ...(filters.tools_status && { tools_status: filters.tools_status }),
    ...(filters.cluster && { cluster: filters.cluster }),
    ...(filters.owner_user_id && { owner_user_id: filters.owner_user_id }),
    ...(filters.department_id && { department_id: filters.department_id }),
    ...(filters.environment_id && { environment_id: filters.environment_id }),
    ...(filters.application_id && { application_id: filters.application_id }),
    ...(filters.tag_id && { tag_id: filters.tag_id }),
    ...(filters.host_id && { host_id: filters.host_id }),
    ...(filters.unassigned_only && { unassigned_only: true }),
  }

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['vms', params],
    queryFn: () => listVms(params).then(r => r.data),
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

  const { data: applications = [] } = useQuery({
    queryKey: ['applications'],
    queryFn: () => listApplications().then(r => r.data),
  })

  const { data: tags = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: () => listTags().then(r => r.data),
  })

  // Hosts are hidden from user/viewer roles everywhere else in the app —
  // don't even fetch the lookup list for them (would 403 anyway).
  const canFilterByHost = canAccessPage(user?.role, 'hosts')
  const { data: hosts = [] } = useQuery({
    queryKey: ['hosts-lookup'],
    queryFn: () => listHosts({ page_size: 200 }).then(r => r.data.items),
    enabled: canFilterByHost,
  })

  function setFilter<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters(f => ({ ...f, [key]: value }))
    setPage(1)
  }

  function resetFilters() {
    setFilters(DEFAULT_FILTERS)
    setPage(1)
  }

  function toggleSort(field: SortField) {
    if (sortBy === field) {
      setSortOrder(o => o === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(field)
      setSortOrder('asc')
    }
    setPage(1)
  }

  function SortIcon({ field }: { field: SortField }) {
    if (sortBy !== field) return <ArrowUpDown className="h-3 w-3 text-gray-300" />
    return sortOrder === 'asc' ? <ArrowUp className="h-3 w-3 text-primary" /> : <ArrowDown className="h-3 w-3 text-primary" />
  }

  function SortableTh({ field, children }: { field: SortField; children: React.ReactNode }) {
    return (
      <th
        onClick={() => toggleSort(field)}
        className="cursor-pointer select-none hover:text-primary-700 transition-colors"
      >
        <span className="inline-flex items-center gap-1">
          {children}
          <SortIcon field={field} />
        </span>
      </th>
    )
  }

  const hasActiveFilters = Object.values(filters).some(v => v !== '' && v !== false)

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-800">Virtual Machines</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {data ? `${data.total.toLocaleString()} VMs` : 'Loading...'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ColumnPicker columns={ALL_COLUMNS} visible={visibleColumns} onChange={setVisibleColumns} />
          {canAccessPage(user?.role, 'decommissioned') && (
            <button onClick={() => navigate('/vms-decommissioned')} className="btn-ghost">
              <Archive className="h-4 w-4" />
              Decommissioned VMs
            </button>
          )}
        </div>
      </div>

      {/* Search + filter bar */}
      <div className="card p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search name, IP, OS..."
              className="input pl-9"
              value={filters.search}
              onChange={e => setFilter('search', e.target.value)}
            />
          </div>

          <select
            className="select w-36"
            value={filters.platform}
            onChange={e => setFilter('platform', e.target.value)}
          >
            <option value="">All Platforms</option>
            <option value="vmware">VMware</option>
            <option value="nutanix">Nutanix</option>
          </select>

          <select
            className="select w-36"
            value={filters.power_state}
            onChange={e => setFilter('power_state', e.target.value)}
          >
            <option value="">All States</option>
            <option value="on">On</option>
            <option value="off">Off</option>
            <option value="suspended">Suspended</option>
          </select>

          <select
            className="select w-44"
            value={filters.department_id}
            onChange={e => setFilter('department_id', e.target.value)}
          >
            <option value="">All Departments</option>
            {departments.map((d: Lookup) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>

          <select
            className="select w-40"
            value={filters.environment_id}
            onChange={e => setFilter('environment_id', e.target.value)}
          >
            <option value="">All Environments</option>
            {environments.map((e: Lookup) => (
              <option key={e.id} value={e.id}>{e.name}</option>
            ))}
          </select>

          <select
            className="select w-40"
            value={filters.owner_user_id}
            onChange={e => setFilter('owner_user_id', e.target.value)}
          >
            <option value="">All Owners</option>
            {owners.map((o: Lookup) => (
              <option key={o.id} value={o.id}>{o.full_name || o.username}</option>
            ))}
          </select>

          <button
            onClick={() => setShowFilters(f => !f)}
            className={showFilters ? 'btn-primary' : 'btn-secondary'}
          >
            <Filter className="h-4 w-4" />
            More Filters {hasActiveFilters && '●'}
          </button>

          {hasActiveFilters && (
            <button onClick={resetFilters} className="btn-ghost text-red-500 hover:bg-red-50">
              Clear
            </button>
          )}
        </div>

        {/* Expanded filters */}
        {showFilters && (
          <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-gray-100">
            <input
              type="text"
              placeholder="Cluster..."
              className="input w-36"
              value={filters.cluster}
              onChange={e => setFilter('cluster', e.target.value)}
            />

            <input
              type="text"
              placeholder="OS Detail..."
              className="input w-36"
              value={filters.os_detail}
              onChange={e => setFilter('os_detail', e.target.value)}
            />

            <select
              className="select w-44"
              value={filters.tools_status}
              onChange={e => setFilter('tools_status', e.target.value)}
            >
              <option value="">All Tools Statuses</option>
              {TOOLS_STATUS_OPTIONS.map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>

            <select
              className="select w-44"
              value={filters.application_id}
              onChange={e => setFilter('application_id', e.target.value)}
            >
              <option value="">All Applications</option>
              {applications.map((a: Lookup) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>

            <select
              className="select w-40"
              value={filters.tag_id}
              onChange={e => setFilter('tag_id', e.target.value)}
            >
              <option value="">All Tags</option>
              {tags.map((t: Lookup) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>

            {canFilterByHost && (
              <select
                className="select w-44"
                value={filters.host_id}
                onChange={e => setFilter('host_id', e.target.value)}
              >
                <option value="">All Hosts</option>
                {hosts.map((h: Lookup) => (
                  <option key={h.id} value={h.id}>{h.name}</option>
                ))}
              </select>
            )}

            <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input
                type="checkbox"
                className="rounded border-gray-300 text-primary focus:ring-primary"
                checked={filters.unassigned_only}
                onChange={e => setFilter('unassigned_only', e.target.checked)}
              />
              Unassigned only
            </label>
          </div>
        )}
      </div>

      {/* Table */}
      {isError ? (
        <ErrorBanner message="Failed to load VMs." onRetry={refetch} />
      ) : isLoading ? (
        <SkeletonTable rows={10} cols={columns.length + 2} />
      ) : data?.items?.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={Monitor}
            title="No VMs found"
            description="Try adjusting your search or filter criteria."
            action={hasActiveFilters ? (
              <button onClick={resetFilters} className="btn-secondary">Clear filters</button>
            ) : undefined}
          />
        </div>
      ) : (
        <div className="card">
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <SortableTh field="name">Name</SortableTh>
                  {columns.map(col => (
                    col.sortField
                      ? <SortableTh key={col.key} field={col.sortField}>{col.label}</SortableTh>
                      : <th key={col.key}>{col.label}</th>
                  ))}
                  <th>Edit</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((vm: VM) => {
                  const isOwnVm = !!user && vm.owner_user_id === user.id
                  const canEdit = canEditVm(user?.role, isOwnVm)
                  return (
                    <tr
                      key={vm.id}
                      className="cursor-pointer"
                      onClick={() => navigate(`/vms/${vm.id}`)}
                    >
                      <td>
                        <span className="font-medium text-gray-800 hover:text-primary transition-colors">
                          {vm.name}
                        </span>
                        {vm.is_decommissioned && (
                          <span className="ml-2 badge badge-red">decommissioned</span>
                        )}
                      </td>
                      {columns.map(col => (
                        <td key={col.key} className={col.cellClassName}>{col.render(vm)}</td>
                      ))}
                      <td>
                        {canEdit && (
                          <button
                            onClick={e => { e.stopPropagation(); setEditTarget(vm) }}
                            className="btn-ghost !px-2 !py-1"
                            title="Quick-edit metadata"
                          >
                            <Pencil className="h-4 w-4" />
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="px-4">
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={data.total}
              onPage={setPage}
            />
          </div>
        </div>
      )}

      {editTarget && (
        <VmEditDrawer
          vm={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={() => setEditTarget(null)}
        />
      )}
    </div>
  )
}

interface VM {
  id: string; name: string; source_platform: string; power_state: string
  os_type: string | null; os_detail: string | null; vcpu: number | null; memory_mb: number | null
  disk_gb: number | null; primary_ip: string | null; cluster: string | null
  host_node: string | null; tools_status: string | null
  owner_user_id: string | null; owner_username: string | null; owner_full_name: string | null
  secondary_owner_id: string | null; secondary_owner_username: string | null; secondary_owner_full_name: string | null
  department_id: string | null; department_name: string | null
  environment_id: string | null; environment_name: string | null
  management_ip: string | null
  applications: { id: string; name: string }[] | null
  tags: { id: string; name: string }[] | null
  notes: string | null
  is_decommissioned: boolean; last_synced_at: string
}
interface Lookup { id: string; name?: string; username?: string; full_name?: string | null }
