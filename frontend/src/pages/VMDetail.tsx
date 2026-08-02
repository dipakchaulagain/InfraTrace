import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Edit2, Save, X, Tag,
  Network, HardDrive, History, Shield,
} from 'lucide-react'
import {
  getVm, updateVmMetadata, getVmHistory, getVmMetadataAudit,
  listDepartments, listEnvironments, listUsersLookup, listApplications, listTags,
} from '../lib/api'
import Spinner from '../components/Spinner'
import ErrorBanner from '../components/ErrorBanner'
import {
  formatBytes, formatGb, formatDate, relativeTime,
  powerStateBadge, platformBadge,
} from '../lib/utils'
import { useAuth } from '../lib/auth'
import { canEditField, canEditVm } from '../lib/permissions'

const MGMT_IP_STATUS: Record<string, { label: string; className: string }> = {
  match: { label: 'Match', className: 'badge-green' },
  mismatch: { label: 'Mismatch', className: 'badge-red' },
  no_platform_ip: { label: 'No platform IP', className: 'badge-gray' },
}

export default function VMDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()
  const qc = useQueryClient()

  const [editing, setEditing] = useState(false)
  const [metaForm, setMetaForm] = useState<MetaForm>({})

  const { data: vm, isLoading, isError } = useQuery({
    queryKey: ['vm', id],
    queryFn: () => getVm(id!).then(r => r.data),
    enabled: !!id,
  })

  const { data: history = [] } = useQuery({
    queryKey: ['vm-history', id],
    queryFn: () => getVmHistory(id!).then(r => r.data),
    enabled: !!id,
  })

  const { data: metaAudit = [] } = useQuery({
    queryKey: ['vm-meta-audit', id],
    queryFn: () => getVmMetadataAudit(id!).then(r => r.data),
    enabled: !!id,
  })

  const { data: departments = [] } = useQuery({
    queryKey: ['departments'],
    queryFn: () => listDepartments().then(r => r.data),
    enabled: editing,
  })

  const { data: environments = [] } = useQuery({
    queryKey: ['environments'],
    queryFn: () => listEnvironments().then(r => r.data),
    enabled: editing,
  })

  const { data: users = [] } = useQuery({
    queryKey: ['users-lookup'],
    queryFn: () => listUsersLookup().then(r => r.data),
    enabled: editing && (user?.role === 'admin' || user?.role === 'global_editor'),
  })

  const { data: applications = [] } = useQuery({
    queryKey: ['applications'],
    queryFn: () => listApplications().then(r => r.data),
    enabled: editing,
  })

  const { data: tags = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: () => listTags().then(r => r.data),
    enabled: editing,
  })

  const saveMutation = useMutation({
    mutationFn: (data: MetaForm) => updateVmMetadata(id!, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['vm', id] })
      qc.invalidateQueries({ queryKey: ['vm-meta-audit', id] })
      setEditing(false)
    },
  })

  function startEdit() {
    setMetaForm({
      owner_user_id: vm?.owner_user_id ?? '',
      secondary_owner_id: vm?.secondary_owner_id ?? '',
      department_id: vm?.department_id ?? '',
      environment_id: vm?.environment_id ?? '',
      os_detail: vm?.os_detail ?? '',
      management_ip: vm?.management_ip ?? '',
      application_ids: (vm?.applications ?? []).map((a: NamedRef) => a.id),
      tag_ids: (vm?.tags ?? []).map((t: NamedRef) => t.id),
      notes: vm?.notes ?? '',
    })
    setEditing(true)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
      </div>
    )
  }

  if (isError || !vm) {
    return <ErrorBanner message="Failed to load VM details." />
  }

  const isOwnVm = !!user && vm.owner_user_id === user.id
  const canEdit = canEditVm(user?.role, isOwnVm)
  const canEditOsDetail = canEditField(user?.role, 'os_detail', isOwnVm)
  const canEditMgmtIp = canEditField(user?.role, 'management_ip', isOwnVm)
  const canEditApplications = canEditField(user?.role, 'application_ids', isOwnVm)
  const canEditTags = canEditField(user?.role, 'tag_ids', isOwnVm)
  const canEditOwner = user?.role === 'admin' || user?.role === 'global_editor'
  const mgmtStatus = vm.management_ip_status ? MGMT_IP_STATUS[vm.management_ip_status] : null

  return (
    <div className="space-y-4">
      {/* Back + header */}
      <div className="flex items-start gap-4">
        <button onClick={() => navigate(-1)} className="btn-ghost !px-2 mt-0.5">
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-bold text-gray-800 truncate">{vm.name}</h1>
            <span className={platformBadge(vm.source_platform)}>{vm.source_platform}</span>
            <span className={powerStateBadge(vm.power_state)}>{vm.power_state}</span>
            {vm.is_decommissioned && <span className="badge badge-red">decommissioned</span>}
          </div>
          <p className="text-sm text-gray-400 mt-0.5">
            Last synced {relativeTime(vm.last_synced_at)}
          </p>
        </div>
        {canEdit && !editing && (
          <button onClick={startEdit} className="btn-secondary shrink-0">
            <Edit2 className="h-4 w-4" />
            Edit metadata
          </button>
        )}
      </div>

      {/* Facts + Ownership */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Synced facts (Layer A — read-only) */}
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
            <Tag className="h-4 w-4 text-primary" />
            Infrastructure Facts
            <span className="badge badge-gray ml-1">read-only</span>
          </h3>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2.5">
            {[
              ['OS', vm.os_type ?? '—'],
              ['vCPU', vm.vcpu ?? '—'],
              ['Memory', formatBytes(vm.memory_mb)],
              ['Disk', formatGb(vm.disk_gb)],
              ['Primary IP', vm.primary_ip ?? '—'],
              ['Cluster', vm.cluster ?? '—'],
              ['Host Node', vm.host_node ?? '—'],
              ['Platform ID', vm.source_id],
              ['Tools Status', vm.tools_status ?? '—'],
              ['Decommissioned', vm.is_decommissioned ? (formatDate(vm.decommissioned_at)) : 'No'],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between text-sm gap-4">
                <dt className="text-gray-500 shrink-0">{k}</dt>
                <dd className="text-gray-800 font-medium text-right truncate">{v}</dd>
              </div>
            ))}
          </dl>
        </div>

        {/* Ownership (Layer B — editable) */}
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
            <Shield className="h-4 w-4 text-primary" />
            Ownership &amp; Metadata
          </h3>

          {editing ? (
            <form
              onSubmit={e => { e.preventDefault(); saveMutation.mutate(metaForm) }}
              className="space-y-3"
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {canEditOwner && (
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Owner</label>
                    <select
                      className="select"
                      value={metaForm.owner_user_id ?? ''}
                      onChange={e => setMetaForm(f => ({ ...f, owner_user_id: e.target.value || null }))}
                    >
                      <option value="">— no owner —</option>
                      {users.map((u: Lookup) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
                    </select>
                  </div>
                )}
                {canEditOwner && (
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Secondary Owner <span className="text-gray-400 font-normal">(optional)</span></label>
                    <select
                      className="select"
                      value={metaForm.secondary_owner_id ?? ''}
                      onChange={e => setMetaForm(f => ({ ...f, secondary_owner_id: e.target.value || null }))}
                    >
                      <option value="">— none —</option>
                      {users.map((u: Lookup) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
                    </select>
                  </div>
                )}
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Department</label>
                  <select
                    className="select"
                    value={metaForm.department_id ?? ''}
                    onChange={e => setMetaForm(f => ({ ...f, department_id: e.target.value || null }))}
                  >
                    <option value="">— unassigned —</option>
                    {departments.map((d: Lookup) => <option key={d.id} value={d.id}>{d.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Environment</label>
                  <select
                    className="select"
                    value={metaForm.environment_id ?? ''}
                    onChange={e => setMetaForm(f => ({ ...f, environment_id: e.target.value || null }))}
                  >
                    <option value="">— unassigned —</option>
                    {environments.map((e: Lookup) => <option key={e.id} value={e.id}>{e.name}</option>)}
                  </select>
                </div>
                {canEditOsDetail && (
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">OS Detail</label>
                    <input
                      type="text"
                      className="input"
                      value={metaForm.os_detail ?? ''}
                      onChange={e => setMetaForm(f => ({ ...f, os_detail: e.target.value }))}
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
                      value={metaForm.management_ip ?? ''}
                      onChange={e => setMetaForm(f => ({ ...f, management_ip: e.target.value }))}
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
                    value={(metaForm.application_ids as string[] | null | undefined) ?? []}
                    onChange={ids => setMetaForm(f => ({ ...f, application_ids: ids }))}
                    placeholder="+ add application..."
                    emptyMessage="No applications defined yet — add one in Admin → Applications."
                  />
                </div>
              )}
              {canEditTags && (
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Tags</label>
                  <MultiSelectChips
                    options={tags}
                    value={(metaForm.tag_ids as string[] | null | undefined) ?? []}
                    onChange={ids => setMetaForm(f => ({ ...f, tag_ids: ids }))}
                    placeholder="+ add tag..."
                    emptyMessage="No tags defined yet — add one in Admin → Tags."
                  />
                </div>
              )}
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Notes</label>
                <textarea
                  className="input resize-none"
                  rows={3}
                  value={metaForm.notes ?? ''}
                  onChange={e => setMetaForm(f => ({ ...f, notes: e.target.value }))}
                  placeholder="Optional notes..."
                />
              </div>
              <div className="flex gap-2 pt-1">
                <button type="submit" className="btn-primary" disabled={saveMutation.isPending}>
                  {saveMutation.isPending ? <Spinner size="sm" /> : <Save className="h-4 w-4" />}
                  Save
                </button>
                <button type="button" onClick={() => setEditing(false)} className="btn-ghost">
                  <X className="h-4 w-4" />
                  Cancel
                </button>
              </div>
              {saveMutation.isError && (
                <ErrorBanner message="Failed to save metadata." />
              )}
            </form>
          ) : (
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2.5">
              {[
                ['Owner', vm.owner_username ?? '—'],
                ['Secondary Owner', vm.secondary_owner_username ?? '—'],
                ['Department', vm.department_name ?? <span className="text-yellow-600">unassigned</span>],
                ['Environment', vm.environment_name ?? <span className="text-yellow-600">unassigned</span>],
                ['OS Detail', vm.os_detail ?? '—'],
                ['IP Address', (
                  <span className="inline-flex items-center gap-1.5">
                    <span className="font-mono">{vm.management_ip ?? '—'}</span>
                    {mgmtStatus && <span className={`badge ${mgmtStatus.className}`}>{mgmtStatus.label}</span>}
                  </span>
                )],
                ['Applications', (
                  (vm.applications ?? []).length > 0 ? (
                    <span className="inline-flex flex-wrap gap-1 justify-end">
                      {(vm.applications as NamedRef[]).map(app => (
                        <span key={app.id} className="badge badge-blue">{app.name}</span>
                      ))}
                    </span>
                  ) : '—'
                )],
                ['Tags', (
                  (vm.tags ?? []).length > 0 ? (
                    <span className="inline-flex flex-wrap gap-1 justify-end">
                      {(vm.tags as NamedRef[]).map(tag => (
                        <span key={tag.id} className="badge badge-teal">{tag.name}</span>
                      ))}
                    </span>
                  ) : '—'
                )],
                ['Notes', vm.notes ?? '—'],
              ].map(([k, v]) => (
                <div key={String(k)} className="flex justify-between text-sm gap-4">
                  <dt className="text-gray-500 shrink-0">{k}</dt>
                  <dd className="text-gray-800 font-medium text-right truncate">{v}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>

      {/* NICs — full width: IP address lists (esp. IPv6) need the room */}
      <div className="card">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
          <Network className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold text-gray-700">NICs</span>
          <span className="badge badge-gray">{vm.nics?.length ?? 0}</span>
        </div>
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>MAC Address</th>
                <th>VLAN</th>
                <th>Connected</th>
                <th>IP Addresses</th>
              </tr>
            </thead>
            <tbody>
              {(vm.nics ?? []).map((nic: NIC, i: number) => (
                <tr key={i}>
                  <td className="font-medium">{nic.label ?? `NIC ${i + 1}`}</td>
                  <td className="font-mono text-xs">{nic.mac_address ?? '—'}</td>
                  <td>{nic.vlan_id != null ? <span className="badge badge-teal">{nic.vlan_id}</span> : '—'}</td>
                  <td>
                    <span className={`badge ${nic.connected ? 'badge-green' : 'badge-gray'}`}>
                      {nic.connected ? 'yes' : 'no'}
                    </span>
                  </td>
                  <td>
                    <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                      {(nic.ip_addresses ?? []).map((ip: IPEntry, j: number) => (
                        <div key={j} className="flex items-center gap-1.5">
                          <span className={`font-mono text-xs ${ip.valid ? 'text-gray-700' : 'text-red-400 line-through'}`}>
                            {ip.ip}
                          </span>
                          {!ip.valid && ip.reason && (
                            <span className="badge badge-red">{ip.reason}</span>
                          )}
                        </div>
                      ))}
                      {(nic.ip_addresses ?? []).length === 0 && <span className="text-gray-400 text-xs">no IPs</span>}
                    </div>
                  </td>
                </tr>
              ))}
              {(vm.nics ?? []).length === 0 && (
                <tr><td colSpan={5} className="text-center text-gray-400 py-8">No NICs found</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Disks — full width for consistency with NICs above */}
      <div className="card">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
          <HardDrive className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold text-gray-700">Disks</span>
          <span className="badge badge-gray">{vm.disks?.length ?? 0}</span>
        </div>
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Capacity</th>
                <th>Thin Provisioned</th>
                <th>Datastore / Container</th>
              </tr>
            </thead>
            <tbody>
              {(vm.disks ?? []).map((disk: Disk, i: number) => (
                <tr key={i}>
                  <td className="font-medium">{disk.label ?? `Disk ${i + 1}`}</td>
                  <td>{formatGb(disk.capacity_gb)}</td>
                  <td>
                    {disk.thin_provisioned == null ? '—' : (
                      <span className={`badge ${disk.thin_provisioned ? 'badge-teal' : 'badge-gray'}`}>
                        {disk.thin_provisioned ? 'thin' : 'thick'}
                      </span>
                    )}
                  </td>
                  <td className="text-xs text-gray-500">
                    {disk.datastore ?? disk.storage_container_uuid ?? '—'}
                  </td>
                </tr>
              ))}
              {(vm.disks ?? []).length === 0 && (
                <tr><td colSpan={4} className="text-center text-gray-400 py-8">No disks found</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Ownership Audit */}
      <div className="card">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
          <Shield className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold text-gray-700">Ownership Audit Trail</span>
          <span className="badge badge-gray">{metaAudit.length}</span>
        </div>
        <div className="table-wrapper max-h-80 overflow-y-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Changed At</th>
                <th>Field</th>
                <th>Old Value</th>
                <th>New Value</th>
                <th>Changed By</th>
              </tr>
            </thead>
            <tbody>
              {metaAudit.map((a: AuditRow) => (
                <tr key={a.id}>
                  <td className="text-xs text-gray-500 whitespace-nowrap">{formatDate(a.changed_at)}</td>
                  <td className="font-medium text-sm">{a.field_name}</td>
                  <td className="text-xs text-red-500">{a.old_value ?? '—'}</td>
                  <td className="text-xs text-green-600">{a.new_value ?? '—'}</td>
                  <td className="text-xs text-gray-500">{a.changed_by ?? '—'}</td>
                </tr>
              ))}
              {metaAudit.length === 0 && (
                <tr><td colSpan={5} className="text-center text-gray-400 py-8">No ownership changes recorded</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Infra History */}
      <div className="card">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
          <History className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold text-gray-700">Infrastructure Change History</span>
          <span className="badge badge-gray">{history.length}</span>
        </div>
        <div className="table-wrapper max-h-80 overflow-y-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Changed At</th>
                <th>Changed Fields</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h: HistoryRow) => (
                <tr key={h.id}>
                  <td className="text-xs text-gray-500 whitespace-nowrap">{formatDate(h.changed_at)}</td>
                  <td>
                    <div className="space-y-1">
                      {Object.entries(h.changed_fields).map(([field, change]) => {
                        const c = change as { old: unknown; new: unknown }
                        return (
                          <div key={field} className="text-xs">
                            <span className="font-semibold text-gray-700">{field}:</span>{' '}
                            <span className="text-red-500 line-through">{String(c.old ?? '—')}</span>
                            {' → '}
                            <span className="text-green-600">{String(c.new ?? '—')}</span>
                          </div>
                        )
                      })}
                    </div>
                  </td>
                </tr>
              ))}
              {history.length === 0 && (
                <tr><td colSpan={2} className="text-center text-gray-400 py-8">No infra changes recorded</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
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

// Local types
interface MetaForm { [key: string]: string | string[] | null | undefined; owner_user_id?: string | null; secondary_owner_id?: string | null; department_id?: string | null; environment_id?: string | null; os_detail?: string | null; management_ip?: string | null; application_ids?: string[] | null; tag_ids?: string[] | null; notes?: string | null }
interface NamedRef { id: string; name: string }
interface NIC { label: string | null; mac_address: string | null; vlan_id: string | number | null; connected: boolean | null; ip_addresses: IPEntry[] }
interface IPEntry { ip: string; valid: boolean; reason: string | null }
interface Disk { label: string | null; capacity_gb: number | null; thin_provisioned: boolean | null; datastore?: string; storage_container_uuid?: string }
interface HistoryRow { id: string; changed_at: string; changed_fields: Record<string, unknown> }
interface AuditRow { id: string; changed_at: string; field_name: string; old_value: string | null; new_value: string | null; changed_by: string | null }
interface Lookup { id: string; username?: string; name?: string; full_name?: string | null }
