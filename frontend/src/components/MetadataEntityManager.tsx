import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import Spinner from './Spinner'
import ErrorBanner from './ErrorBanner'

interface EntityRow {
  id: string
  name: string
  category?: string | null
  vm_count: number
}

interface DeleteErrorDetail {
  message: string
  affected_vms?: { id: string; name: string }[]
}

interface MetadataEntityManagerProps {
  label: string                 // singular, e.g. "Department"
  queryKey: string               // react-query cache key, e.g. "departments"
  filterParam: string             // VMs page query param, e.g. "department_id"
  listFn: () => Promise<{ data: EntityRow[] }>
  createFn: (payload: { name: string; category?: string }) => Promise<unknown>
  deleteFn: (id: string) => Promise<unknown>
  hasCategory?: boolean
  readOnly?: boolean              // hide create/delete controls — view + click-through only
}

// Shared "metadata lookup" management surface — create/delete/VM-count/
// click-through-filter — reused across Departments, Applications,
// Environments, and Tags so all four behave identically instead of four
// separate hand-rolled implementations.
export default function MetadataEntityManager({
  label, queryKey, filterParam, listFn, createFn, deleteFn, hasCategory = false, readOnly = false,
}: MetadataEntityManagerProps) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [category, setCategory] = useState('')
  const [deleteError, setDeleteError] = useState<DeleteErrorDetail | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const { data = [], isLoading, isError, refetch } = useQuery({
    queryKey: [queryKey],
    queryFn: () => listFn().then(r => r.data),
  })

  const createMutation = useMutation({
    mutationFn: () => createFn(hasCategory ? { name, category: category || undefined } : { name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [queryKey] })
      setName('')
      setCategory('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteFn(id),
    onMutate: (id: string) => { setDeletingId(id); setDeleteError(null) },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [queryKey] })
      setDeletingId(null)
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string | DeleteErrorDetail } } })?.response?.data?.detail
      if (typeof detail === 'string') {
        setDeleteError({ message: detail })
      } else if (detail) {
        setDeleteError(detail)
      } else {
        setDeleteError({ message: `Failed to delete this ${label.toLowerCase()}.` })
      }
      setDeletingId(null)
    },
  })

  function goToVms(entityId: string) {
    navigate(`/vms?${filterParam}=${entityId}`)
  }

  const columnCount = 2 + (hasCategory ? 1 : 0) + (readOnly ? 0 : 1)

  return (
    <div className="space-y-4 max-w-2xl">
      {!readOnly && (
        <div className="card p-4 flex flex-wrap gap-2">
          <input
            type="text"
            className="input flex-1 min-w-[160px]"
            placeholder={`New ${label} name`}
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && name && createMutation.mutate()}
          />
          {hasCategory && (
            <input
              type="text"
              className="input w-40"
              placeholder="Category (optional)"
              value={category}
              onChange={e => setCategory(e.target.value)}
            />
          )}
          <button onClick={() => createMutation.mutate()} className="btn-primary" disabled={!name || createMutation.isPending}>
            {createMutation.isPending ? <Spinner size="sm" /> : <Plus className="h-4 w-4" />}
            Add
          </button>
        </div>
      )}

      {!readOnly && createMutation.isError && (
        <ErrorBanner
          message={
            (createMutation.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
            || `Failed to create ${label.toLowerCase()}.`
          }
        />
      )}

      {!readOnly && deleteError && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          <p className="font-medium">{deleteError.message}</p>
          {deleteError.affected_vms && deleteError.affected_vms.length > 0 && (
            <ul className="mt-2 max-h-32 overflow-y-auto space-y-0.5 list-disc list-inside">
              {deleteError.affected_vms.map(v => (
                <li key={v.id}>
                  <button onClick={() => navigate(`/vms/${v.id}`)} className="underline underline-offset-2 hover:text-red-900">
                    {v.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {isError ? (
        <ErrorBanner message={`Failed to load ${label.toLowerCase()}s.`} onRetry={refetch} />
      ) : isLoading ? (
        <div className="flex justify-center py-8"><Spinner /></div>
      ) : (
        <div className="card">
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  {hasCategory && <th>Category</th>}
                  <th>VM Count</th>
                  {!readOnly && <th>Delete</th>}
                </tr>
              </thead>
              <tbody>
                {data.length === 0 && (
                  <tr><td colSpan={columnCount} className="text-center text-gray-400 py-8">No {label.toLowerCase()}s yet</td></tr>
                )}
                {data.map(row => (
                  <tr key={row.id}>
                    <td>
                      <button
                        onClick={() => goToVms(row.id)}
                        className="font-medium text-gray-800 hover:text-primary transition-colors text-left"
                        title={`View VMs with ${label} = ${row.name}`}
                      >
                        {row.name}
                      </button>
                    </td>
                    {hasCategory && <td className="text-xs text-gray-400">{row.category || '—'}</td>}
                    <td>
                      <button
                        onClick={() => goToVms(row.id)}
                        className={row.vm_count > 0 ? 'badge badge-teal hover:opacity-80' : 'badge badge-gray'}
                        title={`View VMs with ${label} = ${row.name}`}
                      >
                        {row.vm_count}
                      </button>
                    </td>
                    {!readOnly && (
                      <td>
                        <button
                          onClick={() => deleteMutation.mutate(row.id)}
                          className="btn-ghost !px-2 !py-1 text-red-500 hover:bg-red-50 disabled:opacity-30"
                          disabled={deletingId === row.id}
                          title={`Delete ${label.toLowerCase()}`}
                        >
                          {deletingId === row.id ? <Spinner size="sm" /> : <Trash2 className="h-4 w-4" />}
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
