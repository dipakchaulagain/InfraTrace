import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, Network } from 'lucide-react'
import { api } from '../lib/api'
import SkeletonTable from '../components/SkeletonTable'
import ErrorBanner from '../components/ErrorBanner'
import EmptyState from '../components/EmptyState'
import Pagination from '../components/Pagination'
import { relativeTime } from '../lib/utils'

interface NetworkRow {
  id: string
  name: string
  vlan_id: string | null
  vswitch_or_dvs_name: string | null
  subnet_cidr: string | null
  default_gateway: string | null
  dhcp_enabled: boolean | null
  last_synced_at: string | null
  vm_count: number
}

export default function Networks() {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const PAGE_SIZE = 50

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['networks', page, search],
    queryFn: () =>
      api.get('/networks', { params: { page, page_size: PAGE_SIZE, ...(search && { search }) } })
        .then(r => r.data),
    placeholderData: prev => prev,
  })

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-gray-800">Networks</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {data ? `${data.total} networks / VLANs` : 'Loading...'}
        </p>
      </div>

      <div className="card p-3">
        <div className="relative max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search name or VLAN..."
            className="input pl-9"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
          />
        </div>
      </div>

      {isError ? (
        <ErrorBanner message="Failed to load networks." onRetry={refetch} />
      ) : isLoading ? (
        <SkeletonTable rows={8} cols={8} />
      ) : data?.items?.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={Network}
            title="No networks found"
            description="Networks will appear after the first sync run."
          />
        </div>
      ) : (
        <div className="card">
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>VLAN ID</th>
                  <th>vSwitch / DVS</th>
                  <th>Subnet</th>
                  <th>Gateway</th>
                  <th>DHCP</th>
                  <th>VM Count</th>
                  <th>Last Synced</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((n: NetworkRow) => (
                  <tr key={n.id}>
                    <td className="font-medium text-gray-800">{n.name}</td>
                    <td>
                      {n.vlan_id != null ? (
                        <span className={`badge ${n.vlan_id === 'trunk' ? 'badge-yellow' : 'badge-teal'}`}>
                          {n.vlan_id}
                        </span>
                      ) : '—'}
                    </td>
                    <td className="text-sm text-gray-500 truncate max-w-[160px]">
                      {n.vswitch_or_dvs_name ?? '—'}
                    </td>
                    <td className="font-mono text-xs">{n.subnet_cidr ?? '—'}</td>
                    <td className="font-mono text-xs">{n.default_gateway ?? '—'}</td>
                    <td>
                      {n.dhcp_enabled == null ? '—' : (
                        <span className={`badge ${n.dhcp_enabled ? 'badge-green' : 'badge-gray'}`}>
                          {n.dhcp_enabled ? 'yes' : 'no'}
                        </span>
                      )}
                    </td>
                    <td><span className="badge badge-teal">{n.vm_count}</span></td>
                    <td className="text-xs text-gray-400">{relativeTime(n.last_synced_at)}</td>
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
