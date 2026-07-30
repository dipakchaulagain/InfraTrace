import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Monitor, Power, PowerOff, Layers,
  UserX, Trash2, RefreshCw,
} from 'lucide-react'
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend,
} from 'recharts'
import { getVmSummary, listSyncRuns } from '../lib/api'
import { canAccessPage } from '../lib/permissions'
import { useAuth } from '../lib/auth'
import StatCard from '../components/StatCard'
import ErrorBanner from '../components/ErrorBanner'
import { relativeTime } from '../lib/utils'

// Theme palette for charts
const CHART_COLORS = ['#5cbdb9', '#c2edda', '#3ea4a0', '#93dfc0', '#80d3d0', '#288f6b', '#b3e6e4']

export default function Dashboard() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const qc = useQueryClient()

  const {
    data: summary, isLoading, isError, refetch, dataUpdatedAt,
  } = useQuery({
    queryKey: ['vm-summary'],
    queryFn: () => getVmSummary().then(r => r.data),
    refetchInterval: 5 * 60_000, // auto-refresh every 5 min
  })

  const { data: runsData } = useQuery({
    queryKey: ['sync-runs', 5],
    queryFn: () => listSyncRuns(5).then(r => r.data),
    enabled: canAccessPage(user?.role, 'sync'),
  })

  function refreshAll() {
    refetch()
    qc.invalidateQueries({ queryKey: ['sync-runs', 5] })
  }

  if (isError) {
    return (
      <div className="max-w-2xl">
        <ErrorBanner message="Failed to load dashboard data." onRetry={refetch} />
      </div>
    )
  }

  const runs: SyncRun[] = runsData ?? []

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-bold text-gray-800">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">VM inventory overview across all platforms</p>
        </div>
        <div className="flex items-center gap-3">
          {dataUpdatedAt > 0 && (
            <span className="text-xs text-gray-400">Updated {relativeTime(new Date(dataUpdatedAt).toISOString())}</span>
          )}
          <button onClick={refreshAll} className="btn-secondary">
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        <StatCard label="Total VMs" value={summary?.total ?? '—'} icon={Monitor} color="teal" loading={isLoading} onClick={() => navigate('/vms')} />
        <StatCard label="Running" value={summary?.power_on ?? '—'} icon={Power} color="green" loading={isLoading} onClick={() => navigate('/vms?power_state=on')} />
        <StatCard label="Powered Off" value={summary?.power_off ?? '—'} icon={PowerOff} color="gray" loading={isLoading} onClick={() => navigate('/vms?power_state=off')} />
        {canAccessPage(user?.role, 'decommissioned') && (
          <StatCard label="Decommissioned" value={summary?.decommissioned ?? '—'} icon={Trash2} color="red" loading={isLoading} onClick={() => navigate('/vms-decommissioned')} />
        )}
        <StatCard label="Unassigned" value={summary?.unassigned ?? '—'} icon={UserX} color="yellow" loading={isLoading} onClick={() => navigate('/vms?unassigned_only=true')} />
        <StatCard
          label="VMware / Nutanix"
          value={isLoading ? '—' : `${summary?.by_platform?.find((p: PlatformCount) => p.platform === 'vmware')?.count ?? 0} / ${summary?.by_platform?.find((p: PlatformCount) => p.platform === 'nutanix')?.count ?? 0}`}
          icon={Layers}
          color="teal"
          loading={isLoading}
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* OS distribution — bar chart */}
        <div className="card p-5 lg:col-span-2">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">OS Distribution (top 10)</h2>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="flex items-center gap-2">
                  <div className="skeleton h-4 w-32 rounded" />
                  <div className="skeleton h-4 flex-1 rounded" />
                </div>
              ))}
            </div>
          ) : (
            // Height scales with the number of bars — a fixed height caused Recharts
            // to auto-skip every other Y-axis label once more than ~5 bars were packed in.
            <ResponsiveContainer width="100%" height={Math.max(220, (summary?.by_os?.length ?? 0) * 34)}>
              <BarChart
                data={summary?.by_os ?? []}
                layout="vertical"
                margin={{ left: 10, right: 20, top: 0, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#f0fafa" />
                <XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} />
                <YAxis
                  type="category"
                  dataKey="os"
                  tick={{ fontSize: 11 }}
                  width={140}
                  interval={0}
                  tickFormatter={(v: string) => v.length > 22 ? v.slice(0, 22) + '…' : v}
                />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
                />
                <Bar dataKey="count" fill="#5cbdb9" radius={[0, 4, 4, 0]} barSize={18} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Department split — pie */}
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">By Department</h2>
          {isLoading ? (
            <div className="flex justify-center items-center h-44">
              <div className="skeleton h-32 w-32 rounded-full" />
            </div>
          ) : (summary?.by_department?.length ?? 0) === 0 ? (
            <div className="flex justify-center items-center h-44 text-sm text-gray-400">
              No department data yet
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={summary?.by_department ?? []}
                  dataKey="count"
                  nameKey="department"
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  paddingAngle={2}
                >
                  {(summary?.by_department ?? []).map((_: DeptCount, i: number) => (
                    <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(v: number, n: string) => [v, n]}
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
                />
                <Legend
                  iconSize={8}
                  formatter={(v: string) => <span style={{ fontSize: 11 }}>{v}</span>}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Environment split + recent syncs */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Environment */}
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">By Environment</h2>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3">
                  <div className="skeleton h-3 w-24 rounded" />
                  <div className="flex-1 bg-gray-100 rounded-full h-2">
                    <div className="skeleton h-2 rounded-full" style={{ width: `${60 - i * 10}%` }} />
                  </div>
                  <div className="skeleton h-3 w-8 rounded" />
                </div>
              ))}
            </div>
          ) : (
            <div className="space-y-3">
              {(summary?.by_environment ?? []).map((e: EnvCount) => {
                const pct = summary?.total ? Math.round((e.count / summary.total) * 100) : 0
                return (
                  <div key={e.environment} className="flex items-center gap-3">
                    <span className="text-sm text-gray-600 w-24 truncate">{e.environment}</span>
                    <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                      <div
                        className="h-2 rounded-full bg-primary transition-all duration-500"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-sm font-medium text-gray-700 w-8 text-right">{e.count}</span>
                  </div>
                )
              })}
              {(summary?.by_environment?.length ?? 0) === 0 && (
                <p className="text-sm text-gray-400">No environment data yet</p>
              )}
            </div>
          )}
        </div>

        {/* Recent sync runs */}
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Recent Syncs</h2>
          <div className="space-y-2">
            {runs.length === 0 && !isLoading && (
              <p className="text-sm text-gray-400">No sync runs yet</p>
            )}
            {runs.map((run) => (
              <div key={run.id} className="flex items-center justify-between py-1.5 border-b border-gray-50 last:border-0">
                <div className="flex items-center gap-2">
                  <span className={`badge ${run.status === 'success' ? 'badge-green' : run.status === 'failed' ? 'badge-red' : 'badge-yellow'}`}>
                    {run.status}
                  </span>
                  <span className="text-sm text-gray-600 capitalize">{run.source_platform}</span>
                </div>
                <div className="text-right">
                  <p className="text-xs text-gray-500">{relativeTime(run.started_at)}</p>
                  <p className="text-xs text-gray-400">{run.records_ok} ok / {run.records_failed} failed</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// Local types (no shared type file needed for this scope)
interface SyncRun { id: string; status: string; source_platform: string; started_at: string; records_ok: number; records_failed: number }
interface PlatformCount { platform: string; count: number }
interface DeptCount { department: string; count: number }
interface EnvCount { environment: string; count: number }
