import { FormEvent } from 'react'
import { Save, X } from 'lucide-react'
import Spinner from './Spinner'
import ErrorBanner from './ErrorBanner'

export interface MetaForm {
  [key: string]: string | string[] | null | undefined
  owner_user_id?: string | null
  secondary_owner_id?: string | null
  department_id?: string | null
  environment_id?: string | null
  os_detail?: string | null
  management_ip?: string | null
  application_ids?: string[] | null
  tag_ids?: string[] | null
  notes?: string | null
}
export interface NamedRef { id: string; name: string }
export interface Lookup { id: string; username?: string; name?: string; full_name?: string | null }

interface VmMetadataFormProps {
  form: MetaForm
  setForm: (updater: (f: MetaForm) => MetaForm) => void
  onSubmit: (e: FormEvent) => void
  onCancel: () => void
  saving: boolean
  error?: boolean
  canEditOwner: boolean
  canEditOsDetail: boolean
  canEditMgmtIp: boolean
  canEditApplications: boolean
  canEditTags: boolean
  departments: NamedRef[]
  environments: NamedRef[]
  users: Lookup[]
  applications: NamedRef[]
  tags: NamedRef[]
  submitLabel?: string
}

// Shared VM metadata edit form — used both inline on the VM Detail page and
// inside the slide-in quick-edit drawer from the VMs list, so field
// rendering/permission gating lives in exactly one place.
export default function VmMetadataForm({
  form, setForm, onSubmit, onCancel, saving, error,
  canEditOwner, canEditOsDetail, canEditMgmtIp, canEditApplications, canEditTags,
  departments, environments, users, applications, tags, submitLabel = 'Save',
}: VmMetadataFormProps) {
  return (
    <form onSubmit={onSubmit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {canEditOwner && (
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Owner</label>
            <select
              className="select"
              value={form.owner_user_id ?? ''}
              onChange={e => setForm(f => ({ ...f, owner_user_id: e.target.value || null }))}
            >
              <option value="">— no owner —</option>
              {users.map(u => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
            </select>
          </div>
        )}
        {canEditOwner && (
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Secondary Owner <span className="text-gray-400 font-normal">(optional)</span></label>
            <select
              className="select"
              value={form.secondary_owner_id ?? ''}
              onChange={e => setForm(f => ({ ...f, secondary_owner_id: e.target.value || null }))}
            >
              <option value="">— none —</option>
              {users.map(u => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
            </select>
          </div>
        )}
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Department</label>
          <select
            className="select"
            value={form.department_id ?? ''}
            onChange={e => setForm(f => ({ ...f, department_id: e.target.value || null }))}
          >
            <option value="">— unassigned —</option>
            {departments.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Environment</label>
          <select
            className="select"
            value={form.environment_id ?? ''}
            onChange={e => setForm(f => ({ ...f, environment_id: e.target.value || null }))}
          >
            <option value="">— unassigned —</option>
            {environments.map(e => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </div>
        {canEditOsDetail && (
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">OS Detail</label>
            <input
              type="text"
              className="input"
              value={form.os_detail ?? ''}
              onChange={e => setForm(f => ({ ...f, os_detail: e.target.value }))}
              placeholder="e.g. Ubuntu 22.04 LTS"
            />
          </div>
        )}
        {canEditMgmtIp && (
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">IP Address</label>
            <input
              type="text"
              className="input font-mono"
              value={form.management_ip ?? ''}
              onChange={e => setForm(f => ({ ...f, management_ip: e.target.value }))}
              placeholder="e.g. 10.20.30.40"
            />
          </div>
        )}
      </div>
      {canEditApplications && (
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Applications</label>
          <MultiSelectChips
            options={applications}
            value={(form.application_ids as string[] | null | undefined) ?? []}
            onChange={ids => setForm(f => ({ ...f, application_ids: ids }))}
            placeholder="+ add application..."
            emptyMessage="No applications defined yet — add one in Metadata → Applications."
          />
        </div>
      )}
      {canEditTags && (
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Tags</label>
          <MultiSelectChips
            options={tags}
            value={(form.tag_ids as string[] | null | undefined) ?? []}
            onChange={ids => setForm(f => ({ ...f, tag_ids: ids }))}
            placeholder="+ add tag..."
            emptyMessage="No tags defined yet — add one in Metadata → Tags."
          />
        </div>
      )}
      <div>
        <label className="block text-xs font-medium text-gray-500 mb-1">Notes</label>
        <textarea
          className="input resize-none"
          rows={3}
          value={form.notes ?? ''}
          onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
          placeholder="Optional notes..."
        />
      </div>
      <div className="flex gap-2 pt-1">
        <button type="submit" className="btn-primary" disabled={saving}>
          {saving ? <Spinner size="sm" /> : <Save className="h-4 w-4" />}
          {submitLabel}
        </button>
        <button type="button" onClick={onCancel} className="btn-ghost">
          <X className="h-4 w-4" />
          Cancel
        </button>
      </div>
      {error && <ErrorBanner message="Failed to save metadata." />}
    </form>
  )
}

// Multi-select-with-chips over a fixed set of managed entities (Applications,
// Tags) — pick from the dropdown to add a chip, click the x to remove one.
// Unlike free-text tagging, the value must already exist as a managed entry.
function MultiSelectChips({ options, value, onChange, placeholder, emptyMessage }: {
  options: NamedRef[]
  value: string[]
  onChange: (ids: string[]) => void
  placeholder?: string
  emptyMessage?: string
}) {
  const selected = options.filter(o => value.includes(o.id))
  const available = options.filter(o => !value.includes(o.id))

  function addSelected(id: string) {
    if (id && !value.includes(id)) onChange([...value, id])
  }

  if (options.length === 0) {
    return <p className="text-xs text-gray-400 py-1">{emptyMessage ?? 'Nothing available yet.'}</p>
  }

  return (
    <div className="input flex flex-wrap items-center gap-1.5 h-auto min-h-[2.375rem] py-1.5">
      {selected.map(o => (
        <span key={o.id} className="badge badge-blue inline-flex items-center gap-1">
          {o.name}
          <button
            type="button"
            onClick={() => onChange(value.filter(v => v !== o.id))}
            className="hover:opacity-70"
            aria-label={`Remove ${o.name}`}
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      {available.length > 0 && (
        <select
          className="flex-1 min-w-[120px] border-0 outline-none text-sm bg-transparent text-gray-500"
          value=""
          onChange={e => addSelected(e.target.value)}
        >
          <option value="">{placeholder ?? '+ add...'}</option>
          {available.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
      )}
    </div>
  )
}
