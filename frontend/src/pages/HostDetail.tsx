import { useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Server, Cpu, MemoryStick, TrendingUp } from 'lucide-react'
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { getHost, getHostHistory } from '../lib/api'
import Spinner from '../components/Spinner'
import ErrorBanner from '../components/ErrorBanner'
import { formatDate, relativeTime } from '../lib/utils'

const RANGE_OPTIONS: { label: string; value: string; hoursSpan: number }[] = [
  { label: '1h', value: '1h', hoursSpan: 1 },
  { label: '3h', value: '3h', hoursSpan: 3 },
  { label: '6h', value: '6h', hoursSpan: 6 },
  { label: '12h', value: '12h', hoursSpan: 12 },
  { label: '1d', value: '1d', hoursSpan: 24 },
  { label: '7d', value: '7d', hoursSpan: 24 * 7 },
  { label: '30d', value: '30d', hoursSpan: 24 * 30 },
]

interface RawHistoryPoint {
  captured_at: string
  cpu_capacity_ghz: number | null
  cpu_usage_mhz_avg: number | null
  cpu_usage_mhz_min: number | null
  cpu_usage_mhz_max: number | null
  memory_capacity_gb: number | null
  memory_usage_mb_avg: number | null
  memory_usage_mb_min: number | null
  memory_usage_mb_max: number | null
}

interface UsagePoint {
  captured_at: string
  avg: number | null
  min: number | null
  max: number | null
  capacity: number | null
  band: number
}

function tickFormatter(iso: string, hoursSpan: number): string {
  const d = new Date(iso)
  if (hoursSpan <= 24) return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function peakOf(points: UsagePoint[]): number | null {
  const values = points.map(p => p.max).filter((v): v is number => v != null)
  return values.length ? Math.max(...values) : null
}

function pct(value: number | null, capacity: number | null): string {
  if (value == null || !capacity) return ''
  return ` (${Math.round((value / capacity) * 100)}%)`
}

function UsageChartTooltip({ active, payload, label, unit }: {
  active?: boolean
  payload?: { payload: UsagePoint }[]
  label?: string
  unit: string
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  const hasRange = p.min != null && p.max != null && p.min !== p.max
  return (
    <div className="text-xs bg-white border border-gray-200 rounded-lg shadow-sm px-3 py-2 space-y-1">
      <p className="text-gray-500">{label ? formatDate(label) : '—'}</p>
      {p.avg != null && <p><span className="font-medium text-gray-700">Usage:</span> {p.avg.toFixed(1)} {unit}</p>}
      {hasRange && <p className="text-gray-500">Range: {p.min!.toFixed(1)} – {p.max!.toFixed(1)} {unit}</p>}
      {p.capacity != null && <p className="text-gray-400">Capacity: {p.capacity.toFixed(1)} {unit}</p>}
    </div>
  )
}

function UsageTrendCard({
  title, icon, points, unit, current, capacity, hoursSpan, lineColor, bandColor,
}: {
  title: string
  icon: React.ReactNode
  points: UsagePoint[]
  unit: string
  current: number | null
  capacity: number | null
  hoursSpan: number
  lineColor: string
  bandColor: string
}) {
  const peak = peakOf(points)

  return (
    <div className="card p-5">
      <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
        {icon}
        {title}
      </h3>

      <div className="flex flex-wrap gap-6 mb-4">
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wide">Current</p>
          <p className="text-lg font-bold text-gray-800">
            {current != null ? `${current.toFixed(1)} ${unit}` : '—'}
            <span className="text-sm font-normal text-gray-400">{pct(current, capacity)}</span>
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wide">Peak ({RANGE_OPTIONS.find(r => r.hoursSpan === hoursSpan)?.label})</p>
          <p className="text-lg font-bold text-gray-800">
            {peak != null ? `${peak.toFixed(1)} ${unit}` : '—'}
            <span className="text-sm font-normal text-gray-400">{pct(peak, capacity)}</span>
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wide">Capacity</p>
          <p className="text-lg font-bold text-gray-800">{capacity != null ? `${capacity.toFixed(1)} ${unit}` : '—'}</p>
        </div>
      </div>

      {points.length < 2 ? (
        <div className="flex flex-col items-center justify-center h-48 text-gray-400">
          <TrendingUp className="h-7 w-7 mb-2 text-gray-300" />
          <p className="text-sm font-medium text-gray-500">Not enough data yet</p>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={points} margin={{ left: 0, right: 10, top: 5, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0fafa" />
            <XAxis
              dataKey="captured_at"
              tickFormatter={(v: string) => tickFormatter(v, hoursSpan)}
              tick={{ fontSize: 11 }}
              minTickGap={40}
            />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => `${v} ${unit}`} width={60} />
            <Tooltip content={<UsageChartTooltip unit={unit} />} />
            <Legend
              iconSize={8}
              formatter={(v: string) => <span style={{ fontSize: 11 }}>{v}</span>}
              payload={[
                { value: 'Usage (avg)', type: 'line', color: lineColor },
                { value: 'Range (min–max)', type: 'rect', color: bandColor },
              ]}
            />
            <Area type="monotone" dataKey="min" stackId="band" stroke="none" fill="transparent" isAnimationActive={false} legendType="none" />
            <Area type="monotone" dataKey="band" name="Range (min–max)" stackId="band" stroke="none" fill={bandColor} fillOpacity={0.35} isAnimationActive={false} />
            <Line type="monotone" dataKey="avg" name="Usage (avg)" stroke={lineColor} strokeWidth={2} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

export default function HostDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [range, setRange] = useState('7d')
  const activeRange = RANGE_OPTIONS.find(r => r.value === range) ?? RANGE_OPTIONS[5]

  const { data: host, isLoading, isError } = useQuery({
    queryKey: ['host', id],
    queryFn: () => getHost(id!).then(r => r.data),
    enabled: !!id,
  })

  const { data: rawHistory = [], isLoading: historyLoading } = useQuery({
    queryKey: ['host-history', id, range],
    queryFn: () => getHostHistory(id!, range).then(r => r.data),
    enabled: !!id,
  })

  const cpuPoints = useMemo<UsagePoint[]>(() => (rawHistory as RawHistoryPoint[]).map(p => {
    const avg = p.cpu_usage_mhz_avg != null ? p.cpu_usage_mhz_avg / 1000 : null
    const min = p.cpu_usage_mhz_min != null ? p.cpu_usage_mhz_min / 1000 : null
    const max = p.cpu_usage_mhz_max != null ? p.cpu_usage_mhz_max / 1000 : null
    return { captured_at: p.captured_at, avg, min, max, capacity: p.cpu_capacity_ghz, band: (max ?? avg ?? 0) - (min ?? avg ?? 0) }
  }), [rawHistory])

  const memPoints = useMemo<UsagePoint[]>(() => (rawHistory as RawHistoryPoint[]).map(p => {
    const avg = p.memory_usage_mb_avg != null ? p.memory_usage_mb_avg / 1024 : null
    const min = p.memory_usage_mb_min != null ? p.memory_usage_mb_min / 1024 : null
    const max = p.memory_usage_mb_max != null ? p.memory_usage_mb_max / 1024 : null
    return { captured_at: p.captured_at, avg, min, max, capacity: p.memory_capacity_gb, band: (max ?? avg ?? 0) - (min ?? avg ?? 0) }
  }), [rawHistory])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
      </div>
    )
  }

  if (isError || !host) {
    return <ErrorBanner message="Failed to load host details." />
  }

  const cpuCurrentGhz = host.cpu_usage_mhz != null ? host.cpu_usage_mhz / 1000 : null
  const memCurrentGb = host.memory_usage_mb != null ? host.memory_usage_mb / 1024 : null

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-4">
        <button onClick={() => navigate(-1)} className="btn-ghost !px-2 mt-0.5">
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-bold text-gray-800 truncate">{host.name}</h1>
            {host.connection_state && (
              <span className={`badge ${host.connection_state === 'connected' ? 'badge-green' : 'badge-yellow'}`}>
                {host.connection_state}
              </span>
            )}
            {host.in_maintenance_mode && <span className="badge badge-yellow">maintenance</span>}
            <span className="badge badge-teal">{host.vm_count} VMs</span>
          </div>
          <p className="text-sm text-gray-400 mt-0.5">
            Last synced {relativeTime(host.last_synced_at)}
          </p>
        </div>
        <div className="flex gap-1 shrink-0">
          {RANGE_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => setRange(opt.value)}
              className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors
                ${range === opt.value ? 'bg-primary text-white' : 'text-gray-500 hover:bg-gray-100'}`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="card p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
          <Server className="h-4 w-4 text-primary" />
          Host Facts
          <span className="badge badge-gray ml-1">read-only</span>
        </h3>
        <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2.5">
          {[
            ['Cluster', host.cluster ?? '—'],
            ['Hypervisor', host.hypervisor_type ?? '—'],
            ['Version', host.hypervisor_version ?? '—'],
            ['CPU Sockets × Cores', host.num_cpu_sockets != null ? `${host.num_cpu_sockets} × ${host.num_cpu_cores}` : '—'],
            ['CPU Threads', host.num_cpu_threads ?? '—'],
            ['Platform ID', host.source_id],
          ].map(([k, v]) => (
            <div key={k} className="flex justify-between text-sm gap-4">
              <dt className="text-gray-500 shrink-0">{k}</dt>
              <dd className="text-gray-800 font-medium text-right truncate">{v}</dd>
            </div>
          ))}
        </dl>
      </div>

      {historyLoading ? (
        <div className="card p-5 flex justify-center items-center h-40">
          <Spinner />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <UsageTrendCard
            title="CPU Usage"
            icon={<Cpu className="h-4 w-4 text-primary" />}
            points={cpuPoints}
            unit="GHz"
            current={cpuCurrentGhz}
            capacity={host.cpu_capacity_ghz}
            hoursSpan={activeRange.hoursSpan}
            lineColor="#288f6b"
            bandColor="#5cbdb9"
          />
          <UsageTrendCard
            title="Memory Usage"
            icon={<MemoryStick className="h-4 w-4 text-primary" />}
            points={memPoints}
            unit="GB"
            current={memCurrentGb}
            capacity={host.memory_capacity_gb}
            hoursSpan={activeRange.hoursSpan}
            lineColor="#3ea4a0"
            bandColor="#93dfc0"
          />
        </div>
      )}
    </div>
  )
}
