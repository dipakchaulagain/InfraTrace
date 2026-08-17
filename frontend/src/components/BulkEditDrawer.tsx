import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save, X } from 'lucide-react'
import {
  bulkUpdateVmMetadata, listDepartments, listEnvironments, listUsersLookup, listApplications, listTags,
} from '../lib/api'
import { useAuth } from '../lib/auth'
import { canEditField } from '../lib/permissions'
import Drawer from './Drawer'
import Spinner from './Spinner'
import ErrorBanner from './ErrorBanner'
import type { MetaForm, NamedRef, Lookup } from './VmMetadataForm'

export interface BulkEditVm {
  id: string
  name: string
}

type BulkForm = Omit<MetaForm, 'management_ip'>
const EMPTY_BULK_FORM: BulkForm = {
  owner_user_id: '', secondary_owner_id: '', department_id: '', environment_id: '',
  os_detail: '', application_ids: [], tag_ids: [], notes: '',
}

interface BulkResult {
  updated: string[]
  skipped: { vm_id: string; reason: string }[]
}

const SKIP_REASON_LABEL: Record<string, string> = {
  not_found: 'no longer exists',
  not_owner: "you don't own it",
}

// Bulk metadata edit for a set of VMs selected on the VMs list. Unlike the
// single-VM form, no field is pre-filled from any one VM (the selection can
// span VMs with different current values) and nothing is applied unless its
// checkbox is explicitly turned on — otherwise every blank/default value
// would get pushed onto every selected VM. IP Address is intentionally not
// offered here at all: it's a per-VM fact, not something to set identically
// across a batch (mirrors BulkVmMetadataUpdate on the backend).
export default function BulkEditDrawer({ vms, onClose, onSaved }: {
  vms: BulkEditVm[]
  onClose: () => void
  onSaved: () => void
}) {
  const { user } = useAuth()
  const qc = useQueryClient()

  const [form, setForm] = useState<BulkForm>(EMPTY_BULK_FORM)
  const [enabled, setEnabled] = useState<Record<string, boolean>>({})
  const [result, setResult] = useState<BulkResult | null>(null)

  const canEditOwner = user?.role === 'admin' || user?.role === 'global_editor'
  const canEditOsDetail = canEditField(user?.role, 'os_detail', true)
  const canEditApplications = canEditField(user?.role, 'application_ids', true)
  const canEditTags = canEditField(user?.role, 'tag_ids', true)

  const { data: departments = [] } = useQuery({
    queryKey: ['departments'],
    queryFn: () => listDepartments().then(r => r.data),
  })
  const { data: environments = [] } = useQuery({
    queryKey: ['environments'],
    queryFn: () => listEnvironments().then(r => r.data),
  })
  const { data: users = [] } = useQuery({
    queryKey: ['users-lookup'],
    queryFn: () => listUsersLookup().then(r => r.data),
    enabled: canEditOwner,
  })
  const { data: applications = [] } = useQuery({
    queryKey: ['applications'],
    queryFn: () => listApplications().then(r => r.data),
  })
  const { data: tags = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: () => listTags().then(r => r.data),
  })

  const saveMutation = useMutation({
    mutationFn: () => {
      const changes: Record<string, unknown> = {}
      for (const key of Object.keys(enabled)) {
        if (enabled[key]) changes[key] = form[key]
      }
      return bulkUpdateVmMetadata(vms.map(v => v.id), changes)
    },
    onSuccess: ({ data }) => {
      qc.invalidateQueries({ queryKey: ['vms'] })
      setResult(data as BulkResult)
    },
  })

  const anyFieldEnabled = Object.values(enabled).some(Boolean)

  function toggle(key: string, value: boolean) {
    setEnabled(e => ({ ...e, [key]: value }))
  }

  if (result) {
    return (
      <Drawer open onClose={onSaved} title="Bulk Edit — Done">
        <div className="space-y-4">
          <p className="text-sm text-gray-700">
            Updated <span className="font-semibold">{result.updated.length}</span> of {vms.length} selected VMs.
          </p>
          {result.skipped.length > 0 && (
            <div className="rounded-lg bg-yellow-50 border border-yellow-200 px-4 py-3 text-sm text-yellow-800">
              <p className="font-medium">{result.skipped.length} skipped:</p>
              <ul className="mt-1.5 space-y-0.5">
                {result.skipped.map(s => {
                  const vm = vms.find(v => v.id === s.vm_id)
                  return (
                    <li key={s.vm_id}>
                      {vm?.name ?? s.vm_id} — {SKIP_REASON_LABEL[s.reason] ?? s.reason}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
          <button onClick={onSaved} className="btn-primary w-full justify-center">Done</button>
        </div>
      </Drawer>
    )
  }

  return (
    <Drawer open onClose={onClose} title={`Bulk Edit Metadata — ${vms.length} VMs`}>
      <form onSubmit={e => { e.preventDefault(); saveMutation.mutate() }} className="space-y-4">
        <p className="text-xs text-gray-500">
          Turn on a field to apply it to all {vms.length} selected VMs. Fields left off are not touched.
        </p>

        <div className="grid grid-cols-1 gap-3">
          {canEditOwner && (
            <FieldToggle label="Owner" enabled={!!enabled.owner_user_id} onToggle={v => toggle('owner_user_id', v)}>
              <select
                className="select"
                value={form.owner_user_id ?? ''}
                onChange={e => setForm(f => ({ ...f, owner_user_id: e.target.value || null }))}
              >
                <option value="">— no owner —</option>
                {users.map((u: Lookup) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
              </select>
            </FieldToggle>
          )}
          {canEditOwner && (
            <FieldToggle label="Secondary Owner" enabled={!!enabled.secondary_owner_id} onToggle={v => toggle('secondary_owner_id', v)}>
              <select
                className="select"
                value={form.secondary_owner_id ?? ''}
                onChange={e => setForm(f => ({ ...f, secondary_owner_id: e.target.value || null }))}
              >
                <option value="">— none —</option>
                {users.map((u: Lookup) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
              </select>
            </FieldToggle>
          )}
          <FieldToggle label="Department" enabled={!!enabled.department_id} onToggle={v => toggle('department_id', v)}>
            <select
              className="select"
              value={form.department_id ?? ''}
              onChange={e => setForm(f => ({ ...f, department_id: e.target.value || null }))}
            >
              <option value="">— unassigned —</option>
              {departments.map((d: NamedRef) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </FieldToggle>
          <FieldToggle label="Environment" enabled={!!enabled.environment_id} onToggle={v => toggle('environment_id', v)}>
            <select
              className="select"
              value={form.environment_id ?? ''}
              onChange={e => setForm(f => ({ ...f, environment_id: e.target.value || null }))}
            >
              <option value="">— unassigned —</option>
              {environments.map((e: NamedRef) => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select>
          </FieldToggle>
          {canEditOsDetail && (
            <FieldToggle label="OS Detail" enabled={!!enabled.os_detail} onToggle={v => toggle('os_detail', v)}>
              <input
                type="text"
                className="input"
                value={form.os_detail ?? ''}
                onChange={e => setForm(f => ({ ...f, os_detail: e.target.value }))}
                placeholder="e.g. Ubuntu 22.04 LTS"
              />
            </FieldToggle>
          )}
        </div>

        {canEditApplications && (
          <FieldToggle
            label="Applications" enabled={!!enabled.application_ids} onToggle={v => toggle('application_ids', v)}
            hint="replaces each VM's full list"
          >
            <MultiSelectChips
              options={applications}
              value={(form.application_ids as string[] | null | undefined) ?? []}
              onChange={ids => setForm(f => ({ ...f, application_ids: ids }))}
              placeholder="+ add application..."
              emptyMessage="No applications defined yet — add one in Metadata → Applications."
            />
          </FieldToggle>
        )}
        {canEditTags && (
          <FieldToggle
            label="Tags" enabled={!!enabled.tag_ids} onToggle={v => toggle('tag_ids', v)}
            hint="replaces each VM's full list"
          >
            <MultiSelectChips
              options={tags}
              value={(form.tag_ids as string[] | null | undefined) ?? []}
              onChange={ids => setForm(f => ({ ...f, tag_ids: ids }))}
              placeholder="+ add tag..."
              emptyMessage="No tags defined yet — add one in Metadata → Tags."
            />
          </FieldToggle>
        )}
        <FieldToggle label="Notes" enabled={!!enabled.notes} onToggle={v => toggle('notes', v)} hint="replaces each VM's notes">
          <textarea
            className="input resize-none"
            rows={3}
            value={form.notes ?? ''}
            onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
            placeholder="Optional notes..."
          />
        </FieldToggle>

        <div className="flex gap-2 pt-1">
          <button type="submit" className="btn-primary" disabled={!anyFieldEnabled || saveMutation.isPending}>
            {saveMutation.isPending ? <Spinner size="sm" /> : <Save className="h-4 w-4" />}
            Apply to {vms.length} VMs
          </button>
          <button type="button" onClick={onClose} className="btn-ghost">
            <X className="h-4 w-4" />
            Cancel
          </button>
        </div>
        {!anyFieldEnabled && (
          <p className="text-xs text-gray-400">Turn on at least one field above to enable Apply.</p>
        )}
        {saveMutation.isError && <ErrorBanner message="Failed to save metadata." />}
      </form>
    </Drawer>
  )
}

function FieldToggle({ label, enabled, onToggle, children, hint }: {
  label: string
  enabled: boolean
  onToggle: (v: boolean) => void
  children: React.ReactNode
  hint?: string
}) {
  return (
    <div>
      <label className="flex items-center gap-2 text-xs font-medium text-gray-500 mb-1 cursor-pointer">
        <input
          type="checkbox"
          className="rounded border-gray-300 text-primary focus:ring-primary"
          checked={enabled}
          onChange={e => onToggle(e.target.checked)}
        />
        {label}
        {hint && <span className="text-gray-400 font-normal">({hint})</span>}
      </label>
      <fieldset disabled={!enabled} className={`border-0 p-0 m-0 ${enabled ? '' : 'opacity-50'}`}>
        {children}
      </fieldset>
    </div>
  )
}

// Same multi-select-with-chips pattern as VmMetadataForm's — duplicated
// rather than imported since that one isn't exported, and this one has a
// bulk-specific "replaces the full list" hint via the parent FieldToggle.
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
