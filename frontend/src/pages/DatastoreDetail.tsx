import { useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Database, Link2, Unlink2, TrendingUp } from 'lucide-react'
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { getDatastore, getDatastoreHistory } from '../lib/api'
import Spinner from '../components/Spinner'
import ErrorBanner from '../components/ErrorBanner'
import { formatGb, formatDate, relativeTime, connectivityTypeBadge } from '../lib/utils'

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

// Values match the backend's _RANGE_TO_TIMEDELTA keys exactly (app/api/datastores.py).
const RANGE_OPTIONS: { label: string; value: string; hoursSpan: number }[] = [
  { label: '1h', value: '1h', hoursSpan: 1 },
  { label: '3h', value: '3h', hoursSpan: 3 },
  { label: '6h', value: '6h', hoursSpan: 6 },
  { label: '12h', value: '12h', hoursSpan: 12 },
  { label: '1d', value: '1d', hoursSpan: 24 },
  { label: '7d', value: '7d', hoursSpan: 24 * 7 },
  { label: '30d', value: '30d', hoursSpan: 24 * 30 },
]

interface HistoryPoint {
  captured_at: string
  capacity_gb: number | null
  used_gb_avg: number | null
  used_gb_min: number | null
  used_gb_max: number | null
  free_gb_avg: number | null
}

function tickFormatter(iso: string, hoursSpan: number): string {
  const d = new Date(iso)
  if (hoursSpan <= 24) return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function ChartTooltip({ active, payload, label }: {
  active?: boolean
  payload?: { payload: HistoryPoint }[]
  label?: string
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  const hasRange = p.used_gb_min != null && p.used_gb_max != null && p.used_gb_min !== p.used_gb_max
  return (
    <div className="text-xs bg-white border border-gray-200 rounded-lg shadow-sm px-3 py-2 space-y-1">
      <p className="text-gray-500">{label ? formatDate(label) : '—'}</p>
      {p.used_gb_avg != null && (
        <p><span className="font-medium text-gray-700">Used:</span> {p.used_gb_avg.toFixed(1)} GB</p>
      )}
      {hasRange && (
        <p className="text-gray-500">Range: {p.used_gb_min!.toFixed(1)} – {p.used_gb_max!.toFixed(1)} GB</p>
      )}
      {p.capacity_gb != null && (
        <p className="text-gray-400">Capacity: {p.capacity_gb.toFixed(1)} GB</p>
      )}
    </div>
  )
}

export default function DatastoreDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [range, setRange] = useState('7d')
  const activeRange = RANGE_OPTIONS.find(r => r.value === range) ?? RANGE_OPTIONS[5]

  const { data: ds, isLoading, isError } = useQuery({
    queryKey: ['datastore', id],
    queryFn: () => getDatastore(id!).then(r => r.data),
    enabled: !!id,
  })

  const { data: rawHistory = [], isLoading: historyLoading } = useQuery({
    queryKey: ['datastore-history', id, range],
    queryFn: () => getDatastoreHistory(id!, range).then(r => r.data),
    enabled: !!id,
  })

  // Precompute the min-max band height once per fetch — recharts stacks two
  // Areas (an invisible one up to used_gb_min, a visible one of this height)
  // to render a min/max band, since it has no native "range area" mark.
  const history = useMemo(
    () => (rawHistory as HistoryPoint[]).map(p => ({
      ...p,
      used_gb_band: (p.used_gb_max ?? p.used_gb_avg ?? 0) - (p.used_gb_min ?? p.used_gb_avg ?? 0),
    })),
    [rawHistory],
  )

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
      </div>
    )
  }

  if (isError || !ds) {
    return <ErrorBanner message="Failed to load datastore details." />
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-4">
        <button onClick={() => navigate(-1)} className="btn-ghost !px-2 mt-0.5">
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-bold text-gray-800 truncate">{ds.name}</h1>
            <span className={connectivityTypeBadge(ds.connectivity_type)}>
              {CONNECTIVITY_LABELS[ds.connectivity_type] ?? ds.connectivity_type}
            </span>
            <span className="badge badge-gray inline-flex items-center gap-1">
              {ds.is_shared ? <Link2 className="h-3 w-3" /> : <Unlink2 className="h-3 w-3" />}
              {ds.is_shared ? 'Shared' : 'Host-local'}
            </span>
          </div>
          <p className="text-sm text-gray-400 mt-0.5">
            Last synced {relativeTime(ds.last_synced_at)}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
            <Database className="h-4 w-4 text-primary" />
            Storage Facts
            <span className="badge badge-gray ml-1">read-only</span>
          </h3>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2.5">
            {[
              ['Capacity', formatGb(ds.capacity_gb)],
              ['Used', formatGb(ds.used_gb)],
              ['Free', formatGb(ds.free_gb)],
              ['Raw Type', ds.type ?? '—'],
              ['Connectivity', CONNECTIVITY_LABELS[ds.connectivity_type] ?? ds.connectivity_type],
              ['Shared', ds.is_shared ? 'Yes' : 'No (host-local)'],
              ['Platform ID', ds.source_id],
              ['Last Synced', formatDate(ds.last_synced_at)],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between text-sm gap-4">
                <dt className="text-gray-500 shrink-0">{k}</dt>
                <dd className="text-gray-800 font-medium text-right truncate">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>

      {/* Capacity trend */}
      <div className="card p-5">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-4">
          <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-primary" />
            Capacity Trend
          </h3>
          <div className="flex gap-1 flex-wrap">
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

        {historyLoading ? (
          <div className="flex justify-center items-center h-56">
            <Spinner />
          </div>
        ) : history.length < 2 ? (
          <div className="flex flex-col items-center justify-center h-56 text-gray-400">
            <TrendingUp className="h-8 w-8 mb-2 text-gray-300" />
            <p className="text-sm font-medium text-gray-500">Not enough data yet</p>
            <p className="text-xs text-gray-400 mt-0.5">
              History builds up as sync runs and datastore-metrics refreshes complete.
            </p>
          </div>
        ) : (
          <>
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={history} margin={{ left: 0, right: 10, top: 5, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0fafa" />
                <XAxis
                  dataKey="captured_at"
                  tickFormatter={(v: string) => tickFormatter(v, activeRange.hoursSpan)}
                  tick={{ fontSize: 11 }}
                  minTickGap={40}
                />
                <YAxis
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v: number) => `${v} GB`}
                  width={70}
                />
                <Tooltip content={<ChartTooltip />} />
                <Legend
                  iconSize={8}
                  formatter={(v: string) => <span style={{ fontSize: 11 }}>{v}</span>}
                  payload={[
                    { value: 'Used (avg)', type: 'line', color: '#288f6b' },
                    { value: 'Used range (min–max)', type: 'rect', color: '#5cbdb9' },
                    { value: 'Capacity', type: 'line', color: '#c2edda' },
                  ]}
                />
                {/* Min-max band: an invisible base area up to used_gb_min, then a
                    visible one stacked on top whose height is (max - min) — recharts
                    has no native "range area" mark, so two stacked Areas fake one. */}
                <Area
                  type="monotone" dataKey="used_gb_min" stackId="band"
                  stroke="none" fill="transparent" isAnimationActive={false} legendType="none"
                />
                <Area
                  type="monotone" dataKey="used_gb_band" name="Used range (min–max)" stackId="band"
                  stroke="none" fill="#5cbdb9" fillOpacity={0.35} isAnimationActive={false}
                />
                <Line
                  type="monotone" dataKey="used_gb_avg" name="Used (avg)"
                  stroke="#288f6b" strokeWidth={2} dot={false} isAnimationActive={false}
                />
                <Line
                  type="monotone" dataKey="capacity_gb" name="Capacity"
                  stroke="#93dfc0" strokeWidth={1.5} strokeDasharray="4 4" dot={false} isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
            <p className="text-xs text-gray-400 mt-2">
              Shaded band shows the min–max range within each period — widens where a brief spike or dip happened.
            </p>
          </>
        )}
      </div>
    </div>
  )
}
