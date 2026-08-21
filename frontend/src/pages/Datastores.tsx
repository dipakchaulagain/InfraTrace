import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Search, Database, Link2, Unlink2 } from 'lucide-react'
import { listDatastores } from '../lib/api'
import SkeletonTable from '../components/SkeletonTable'
import ErrorBanner from '../components/ErrorBanner'
import EmptyState from '../components/EmptyState'
import Pagination from '../components/Pagination'
import { relativeTime, formatGb, connectivityTypeBadge } from '../lib/utils'

interface DatastoreRow {
  id: string
  name: string
  capacity_gb: number | null
  used_gb: number | null
  free_gb: number | null
  type: string | null
  connectivity_type: string
  is_shared: boolean
  last_synced_at: string | null
}

const CONNECTIVITY_TYPES = [
  'ISCSI', 'FC', 'LOCAL', 'SAS', 'NFS', 'NFS41', 'VSAN', 'VVOL', 'NUTANIX_CONTAINER', 'UNKNOWN',
]

const CONNECTIVITY_LABELS: Record<string, string> = {
  ISCSI: 'iSCSI',
  FC: 'FC',
  LOCAL: 'Local',
  SAS: 'SAS',
  NFS: 'NFS',
  NFS41: 'NFS 4.1',
  VSAN: 'vSAN',
  VVOL: 'VVOL',
  NUTANIX_CONTAINER: 'Nutanix Container',
  UNKNOWN: 'Unknown',
}

// Deep-link support — the Dashboard's "Datastores on Local Storage" stat
// card links here with ?is_shared=false.
function isSharedFromSearchParams(params: URLSearchParams): string {
  const v = params.get('is_shared')
  return v === 'true' || v === 'false' ? v : ''
}

export default function Datastores() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [connectivityType, setConnectivityType] = useState('')
  const [isShared, setIsShared] = useState(isSharedFromSearchParams(searchParams))
  const PAGE_SIZE = 50

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['datastores', page, search, connectivityType, isShared],
    queryFn: () =>
      listDatastores({
        page, page_size: PAGE_SIZE,
        ...(search && { search }),
        ...(connectivityType && { connectivity_type: connectivityType }),
        ...(isShared && { is_shared: isShared }),
      }).then(r => r.data),
    placeholderData: prev => prev,
  })

  function updateFilter(setter: (v: string) => void, value: string) {
    setter(value)
    setPage(1)
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-gray-800">Datastores</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {data ? `${data.total} datastores` : 'Loading...'}
        </p>
      </div>

      <div className="card p-3 flex flex-wrap items-center gap-3">
        <div className="relative max-w-sm flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search name..."
            className="input pl-9"
            value={search}
            onChange={e => updateFilter(setSearch, e.target.value)}
          />
        </div>
        <select
          className="select w-44"
          value={connectivityType}
          onChange={e => updateFilter(setConnectivityType, e.target.value)}
        >
          <option value="">All connectivity types</option>
          {CONNECTIVITY_TYPES.map(ct => (
            <option key={ct} value={ct}>{CONNECTIVITY_LABELS[ct]}</option>
          ))}
        </select>
        <select
          className="select w-44"
          value={isShared}
          onChange={e => updateFilter(setIsShared, e.target.value)}
        >
          <option value="">Shared &amp; local</option>
          <option value="true">Shared only</option>
          <option value="false">Local only</option>
        </select>
      </div>

      {isError ? (
        <ErrorBanner message="Failed to load datastores." onRetry={refetch} />
      ) : isLoading ? (
        <SkeletonTable rows={8} cols={7} />
      ) : data?.items?.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={Database}
            title="No datastores found"
            description="Datastores will appear after the first sync run."
          />
        </div>
      ) : (
        <div className="card">
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Connectivity</th>
                  <th>Capacity</th>
                  <th>Used</th>
                  <th>Free</th>
                  <th>Last Synced</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((d: DatastoreRow) => (
                  <tr
                    key={d.id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/datastores/${d.id}`)}
                  >
                    <td className="font-medium text-gray-800">{d.name}</td>
                    <td>
                      <div className="flex items-center gap-1.5">
                        <span className={connectivityTypeBadge(d.connectivity_type)}>
                          {CONNECTIVITY_LABELS[d.connectivity_type] ?? d.connectivity_type}
                        </span>
                        {d.is_shared ? (
                          <span title="Shared across hosts"><Link2 className="h-3.5 w-3.5 text-gray-400" /></span>
                        ) : (
                          <span title="Host-local storage"><Unlink2 className="h-3.5 w-3.5 text-yellow-500" /></span>
                        )}
                      </div>
                    </td>
                    <td>{formatGb(d.capacity_gb)}</td>
                    <td>{formatGb(d.used_gb)}</td>
                    <td>{formatGb(d.free_gb)}</td>
                    <td className="text-xs text-gray-400">{relativeTime(d.last_synced_at)}</td>
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
