import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Play, AlertTriangle, CheckCircle, XCircle, Clock, CheckCircle2 } from 'lucide-react'
import { listSyncRuns, getSyncRun, triggerSync, listDeadLetters, resolveDeadLetter } from '../lib/api'
import ErrorBanner from '../components/ErrorBanner'
import Spinner from '../components/Spinner'
import { formatDate, relativeTime } from '../lib/utils'
import { useAuth } from '../lib/auth'

type View = 'runs' | 'dead-letters'

export default function SyncHealth() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [view, setView] = useState<View>('runs')
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [triggerMsg, setTriggerMsg] = useState<{ type: 'ok' | 'error'; text: string } | null>(null)

  const { data: runs = [], isLoading, refetch } = useQuery({
    queryKey: ['sync-runs', 20],
    queryFn: () => listSyncRuns(20).then(r => r.data),
    refetchInterval: 30_000,
  })

  const { data: selectedRun } = useQuery({
    queryKey: ['sync-run', selectedRunId],
    queryFn: () => getSyncRun(selectedRunId!).then(r => r.data),
    enabled: !!selectedRunId,
  })

  const { data: deadLetters = [] } = useQuery({
    queryKey: ['dead-letters'],
    queryFn: () => listDeadLetters(false).then(r => r.data),
    enabled: view === 'dead-letters' && user?.role === 'admin',
  })

  // Separate mutation instances so one platform's state doesn't block the other
  const vmwareMutation = useMutation({
    mutationFn: () => triggerSync('vmware'),
    onSuccess: () => {
      setTriggerMsg({ type: 'ok', text: 'VMware sync triggered — new run will appear shortly.' })
      setTimeout(() => {
        refetch()
        setTriggerMsg(null)
      }, 3000)
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (e as Error)?.message ?? 'Unknown error'
      setTriggerMsg({ type: 'error', text: `VMware sync failed: ${detail}` })
    },
  })

  const nutanixMutation = useMutation({
    mutationFn: () => triggerSync('nutanix'),
    onSuccess: () => {
      setTriggerMsg({ type: 'ok', text: 'Nutanix sync triggered — new run will appear shortly.' })
      setTimeout(() => {
        refetch()
        setTriggerMsg(null)
      }, 3000)
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (e as Error)?.message ?? 'Unknown error'
      setTriggerMsg({ type: 'error', text: `Nutanix sync failed: ${detail}` })
    },
  })

  const resolveMutation = useMutation({
    mutationFn: (id: string) => resolveDeadLetter(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['dead-letters'] }),
  })

  function statusIcon(status: string) {
    switch (status) {
      case 'success': return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'failed':  return <XCircle className="h-4 w-4 text-red-500" />
      case 'partial': return <AlertTriangle className="h-4 w-4 text-yellow-500" />
      default:        return <Clock className="h-4 w-4 text-gray-400 animate-spin" />
    }
  }

  function statusBadge(status: string) {
    return status === 'success' ? 'badge-green' : status === 'failed' ? 'badge-red' : status === 'partial' ? 'badge-yellow' : 'badge-gray'
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-800">Sync Health</h1>
          <p className="text-sm text-gray-500 mt-0.5">Monitor sync runs, validation reports, and dead-letter queue</p>
        </div>
        {user?.role === 'admin' && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => { setTriggerMsg(null); vmwareMutation.mutate() }}
              disabled={vmwareMutation.isPending || nutanixMutation.isPending}
              className="btn-secondary"
            >
              {vmwareMutation.isPending ? <Spinner size="sm" /> : <Play className="h-4 w-4" />}
              Sync VMware
            </button>
            <button
              onClick={() => { setTriggerMsg(null); nutanixMutation.mutate() }}
              disabled={vmwareMutation.isPending || nutanixMutation.isPending}
              className="btn-secondary"
            >
              {nutanixMutation.isPending ? <Spinner size="sm" /> : <Play className="h-4 w-4" />}
              Sync Nutanix
            </button>
          </div>
        )}
      </div>

      {triggerMsg && (
        <div className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm
          ${triggerMsg.type === 'ok'
            ? 'bg-mint-100 border-mint-200 text-mint-800'
            : 'bg-red-50 border-red-200 text-red-700'}`}>
          {triggerMsg.type === 'ok'
            ? <CheckCircle2 className="h-4 w-4 shrink-0" />
            : <XCircle className="h-4 w-4 shrink-0" />}
          {triggerMsg.text}
        </div>
      )}

      {/* View toggle */}
      <div className="flex gap-1 border-b border-gray-200">
        {(['runs', 'dead-letters'] as View[]).map(v => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors
              ${view === v ? 'border-primary text-primary' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
          >
            {v === 'runs' ? 'Sync Runs' : 'Dead Letters'}
            {v === 'dead-letters' && deadLetters.length > 0 && (
              <span className="ml-1.5 badge badge-red">{deadLetters.length}</span>
            )}
          </button>
        ))}
      </div>

      {view === 'runs' && (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
          {/* Run list */}
          <div className="lg:col-span-2 card">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
              <span className="text-sm font-semibold text-gray-700">Recent Runs</span>
              <button onClick={() => refetch()} className="btn-ghost !px-2 !py-1">
                <RefreshCw className="h-4 w-4" />
              </button>
            </div>
            {isLoading ? (
              <div className="flex justify-center py-12"><Spinner /></div>
            ) : runs.length === 0 ? (
              <div className="text-center text-gray-400 text-sm py-10">No sync runs yet</div>
            ) : (
              <div className="divide-y divide-gray-50">
                {runs.map((run: SyncRun) => (
                  <button
                    key={run.id}
                    onClick={() => setSelectedRunId(run.id)}
                    className={`w-full text-left px-4 py-3 transition-colors hover:bg-primary-50 
                      ${selectedRunId === run.id ? 'bg-primary-50 border-l-2 border-primary' : ''}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        {statusIcon(run.status)}
                        <span className="text-sm font-medium capitalize">{run.source_platform}</span>
                        <span className={`badge ${statusBadge(run.status)}`}>{run.status}</span>
                      </div>
                      <span className="text-xs text-gray-400">{relativeTime(run.started_at)}</span>
                    </div>
                    <div className="mt-1 text-xs text-gray-500 pl-6">
                      {run.records_seen} seen · {run.records_ok} ok · {run.records_failed} failed
                      {run.records_dead_lettered > 0 && (
                        <span className="text-red-500 ml-1">· {run.records_dead_lettered} dead-lettered</span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Run detail */}
          <div className="lg:col-span-3">
            {!selectedRunId ? (
              <div className="card flex items-center justify-center h-40 text-gray-400 text-sm">
                Select a run to see its validation report
              </div>
            ) : !selectedRun ? (
              <div className="card flex justify-center py-12"><Spinner /></div>
            ) : (
              <div className="card p-5 space-y-4">
                <div className="flex items-center gap-2">
                  {statusIcon(selectedRun.status)}
                  <h3 className="font-semibold text-gray-800 capitalize">{selectedRun.source_platform} sync</h3>
                  <span className={`badge ${statusBadge(selectedRun.status)}`}>{selectedRun.status}</span>
                </div>

                <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                  {[
                    ['Started', formatDate(selectedRun.started_at)],
                    ['Completed', formatDate(selectedRun.completed_at)],
                    ['Records seen', selectedRun.records_seen],
                    ['Records OK', selectedRun.records_ok],
                    ['Records failed', selectedRun.records_failed],
                    ['Dead-lettered', selectedRun.records_dead_lettered],
                  ].map(([k, v]) => (
                    <div key={String(k)}>
                      <dt className="text-gray-500">{k}</dt>
                      <dd className="font-medium text-gray-800">{v}</dd>
                    </div>
                  ))}
                </dl>

                {selectedRun.error_message && (
                  <ErrorBanner message={selectedRun.error_message} />
                )}

                {selectedRun.validation_report && (
                  <div>
                    <h4 className="text-xs font-semibold text-gray-500 uppercase mb-2">Validation Report</h4>
                    {Object.keys(selectedRun.validation_report.missing_field_counts ?? {}).length > 0 && (
                      <div className="mb-3">
                        <p className="text-xs font-medium text-gray-600 mb-1">Missing field counts:</p>
                        <div className="space-y-1 max-h-48 overflow-y-auto">
                          {Object.entries(selectedRun.validation_report.missing_field_counts)
                            .sort(([, a], [, b]) => (b as number) - (a as number))
                            .map(([field, count]) => (
                              <div key={field} className="flex justify-between text-xs">
                                <span className="text-gray-600 truncate">{field}</span>
                                <span className="font-medium text-gray-800 ml-2">{String(count)}</span>
                              </div>
                            ))}
                        </div>
                      </div>
                    )}
                    {(selectedRun.validation_report.failures?.length ?? 0) > 0 && (
                      <div>
                        <p className="text-xs font-medium text-red-600 mb-1">
                          Failures ({selectedRun.validation_report.failures.length}):
                        </p>
                        <div className="space-y-1 max-h-36 overflow-y-auto">
                          {selectedRun.validation_report.failures.slice(0, 10).map((f: { vm: string; error: string }, i: number) => (
                            <div key={i} className="text-xs bg-red-50 rounded px-2 py-1">
                              <span className="font-medium text-red-700">{f.vm}:</span>{' '}
                              <span className="text-red-600">{f.error}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {view === 'dead-letters' && (
        <div className="card">
          {deadLetters.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-gray-400">
              <CheckCircle className="h-10 w-10 text-green-400 mb-2" />
              <p className="text-sm font-medium text-gray-600">No unresolved dead letters</p>
              <p className="text-xs text-gray-400 mt-0.5">All records processed successfully</p>
            </div>
          ) : (
            <div className="table-wrapper">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Platform</th>
                    <th>Error</th>
                    <th>Sync Run</th>
                    <th>Created</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {deadLetters.map((dl: DeadLetter) => (
                    <tr key={dl.id}>
                      <td><span className="badge badge-teal capitalize">{dl.source_platform}</span></td>
                      <td className="max-w-xs truncate text-xs text-red-600" title={dl.error_message}>
                        {dl.error_message}
                      </td>
                      <td className="font-mono text-xs text-gray-400">{dl.sync_run_id.slice(0, 8)}…</td>
                      <td className="text-xs text-gray-500">{relativeTime(dl.created_at)}</td>
                      <td>
                        <button
                          onClick={() => resolveMutation.mutate(dl.id)}
                          disabled={resolveMutation.isPending}
                          className="btn-secondary !py-1 !px-2 text-xs"
                        >
                          Resolve
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

interface SyncRun {
  id: string; source_platform: string; status: string; started_at: string
  records_seen: number; records_ok: number; records_failed: number; records_dead_lettered: number
}
interface DeadLetter {
  id: string; source_platform: string; error_message: string; sync_run_id: string; created_at: string
}
