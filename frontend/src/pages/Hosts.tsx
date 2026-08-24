import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Server, Cpu, MemoryStick } from 'lucide-react'
import { listHosts } from '../lib/api'
import SkeletonTable from '../components/SkeletonTable'
import ErrorBanner from '../components/ErrorBanner'
import EmptyState from '../components/EmptyState'
import Pagination from '../components/Pagination'
import { relativeTime } from '../lib/utils'

export default function Hosts() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 50

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['hosts', page],
    queryFn: () => listHosts({ page, page_size: PAGE_SIZE }).then(r => r.data),
    placeholderData: prev => prev,
  })

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-gray-800">Hosts</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {data ? `${data.total} hypervisor nodes` : 'Loading...'}
        </p>
      </div>

      {isError ? (
        <ErrorBanner message="Failed to load hosts." onRetry={refetch} />
      ) : isLoading ? (
        <SkeletonTable rows={8} cols={7} />
      ) : data?.items?.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={Server}
            title="No hosts found"
            description="Hosts will appear after the first sync run completes."
          />
        </div>
      ) : (
        <div className="card">
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Cluster</th>
                  <th>Hypervisor</th>
                  <th>State</th>
                  <th>CPU</th>
                  <th>Memory</th>
                  <th>VMs</th>
                  <th>Last Synced</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((h: Host) => (
                  <tr
                    key={h.id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/hosts/${h.id}`)}
                    title={`View details for ${h.name}`}
                  >
                    <td className="font-medium text-gray-800">{h.name}</td>
                    <td>{h.cluster ?? <span className="text-gray-400">—</span>}</td>
                    <td>
                      <div>
                        <span className="text-sm">{h.hypervisor_type ?? '—'}</span>
                        {h.hypervisor_version && (
                          <p className="text-xs text-gray-400 truncate max-w-[180px]" title={h.hypervisor_version}>
                            {h.hypervisor_version}
                          </p>
                        )}
                      </div>
                    </td>
                    <td>
                      {h.connection_state && (
                        <span className={`badge ${h.connection_state === 'connected' ? 'badge-green' : 'badge-yellow'}`}>
                          {h.connection_state}
                        </span>
                      )}
                      {h.in_maintenance_mode && (
                        <span className="badge badge-yellow ml-1">maintenance</span>
                      )}
                    </td>
                    <td>
                      <div className="text-sm">
                        <div className="flex items-center gap-1">
                          <Cpu className="h-3.5 w-3.5 text-gray-400" />
                          <span>
                            {h.num_cpu_sockets != null
                              ? `${h.num_cpu_sockets}S × ${h.num_cpu_cores}C`
                              : '—'}
                          </span>
                        </div>
                        {h.cpu_capacity_ghz != null && (
                          <p className="text-xs text-gray-400">{h.cpu_capacity_ghz} GHz</p>
                        )}
                        {h.cpu_usage_mhz != null && (
                          <div className="mt-1 w-24 bg-gray-100 rounded-full h-1.5 overflow-hidden">
                            <div
                              className="h-1.5 bg-primary rounded-full"
                              style={{
                                width: `${Math.min(100, ((h.cpu_usage_mhz / 1000) / (h.cpu_capacity_ghz ?? 1)) * 100)}%`
                              }}
                            />
                          </div>
                        )}
                      </div>
                    </td>
                    <td>
                      <div className="text-sm">
                        <div className="flex items-center gap-1">
                          <MemoryStick className="h-3.5 w-3.5 text-gray-400" />
                          <span>{h.memory_capacity_gb != null ? `${h.memory_capacity_gb} GB` : '—'}</span>
                        </div>
                        {h.memory_usage_mb != null && h.memory_capacity_gb != null && (
                          <div className="mt-1 w-24 bg-gray-100 rounded-full h-1.5 overflow-hidden">
                            <div
                              className="h-1.5 bg-mint-400 rounded-full"
                              style={{
                                width: `${Math.min(100, (h.memory_usage_mb / 1024 / h.memory_capacity_gb) * 100)}%`
                              }}
                            />
                          </div>
                        )}
                      </div>
                    </td>
                    <td>
                      <button
                        className="badge badge-teal hover:opacity-80"
                        onClick={e => { e.stopPropagation(); navigate(`/vms?host_id=${h.id}`) }}
                        title={`View VMs on ${h.name}`}
                      >
                        {h.vm_count}
                      </button>
                    </td>
                    <td className="text-xs text-gray-400">{relativeTime(h.last_synced_at)}</td>
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

interface Host {
  id: string; name: string; cluster: string | null; hypervisor_type: string | null
  hypervisor_version: string | null; connection_state: string | null
  in_maintenance_mode: boolean | null; num_cpu_sockets: number | null
  num_cpu_cores: number | null; cpu_capacity_ghz: number | null
  cpu_usage_mhz: number | null; memory_capacity_gb: number | null
  memory_usage_mb: number | null; vm_count: number; last_synced_at: string
}
