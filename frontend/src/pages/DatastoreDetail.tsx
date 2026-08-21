import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Database, Link2, Unlink2 } from 'lucide-react'
import { getDatastore } from '../lib/api'
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

export default function DatastoreDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: ds, isLoading, isError } = useQuery({
    queryKey: ['datastore', id],
    queryFn: () => getDatastore(id!).then(r => r.data),
    enabled: !!id,
  })

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
    </div>
  )
}
