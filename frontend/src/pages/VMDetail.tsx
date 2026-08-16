import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Edit2, Tag,
  Network, HardDrive, History, Shield,
} from 'lucide-react'
import {
  getVm, updateVmMetadata, getVmHistory, getVmMetadataAudit,
  listDepartments, listEnvironments, listUsersLookup, listApplications, listTags,
} from '../lib/api'
import Spinner from '../components/Spinner'
import ErrorBanner from '../components/ErrorBanner'
import VmMetadataForm, { type MetaForm, type NamedRef } from '../components/VmMetadataForm'
import {
  formatBytes, formatGb, formatDate, relativeTime,
  powerStateBadge, platformBadge,
} from '../lib/utils'
import { useAuth } from '../lib/auth'
import { canEditField, canEditVm } from '../lib/permissions'

const FIELD_LABELS: Record<string, string> = {
  owner_user_id: 'Owner',
  secondary_owner_id: 'Secondary Owner',
  department_id: 'Department',
  environment_id: 'Environment',
  os_detail: 'OS Detail',
  management_ip: 'IP Address',
  application_ids: 'Applications',
  tag_ids: 'Tags',
  notes: 'Notes',
}

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
            <VmMetadataForm
              form={metaForm}
              setForm={setMetaForm}
              onSubmit={e => { e.preventDefault(); saveMutation.mutate(metaForm) }}
              onCancel={() => setEditing(false)}
              saving={saveMutation.isPending}
              error={saveMutation.isError}
              canEditOwner={canEditOwner}
              canEditOsDetail={canEditOsDetail}
              canEditMgmtIp={canEditMgmtIp}
              canEditApplications={canEditApplications}
              canEditTags={canEditTags}
              departments={departments}
              environments={environments}
              users={users}
              applications={applications}
              tags={tags}
            />
          ) : (
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2.5">
              {[
                ['Owner', vm.owner_full_name ?? vm.owner_username ?? '—'],
                ['Secondary Owner', vm.secondary_owner_full_name ?? vm.secondary_owner_username ?? '—'],
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
                  <td className="font-medium text-sm">{FIELD_LABELS[a.field_name] ?? a.field_name}</td>
                  <td className="text-xs text-red-500">{a.old_value ?? '—'}</td>
                  <td className="text-xs text-green-600">{a.new_value ?? '—'}</td>
                  <td className="text-xs text-gray-500">{a.changed_by_name ?? '—'}</td>
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

// Local types
interface NIC { label: string | null; mac_address: string | null; vlan_id: string | number | null; connected: boolean | null; ip_addresses: IPEntry[] }
interface IPEntry { ip: string; valid: boolean; reason: string | null }
interface Disk { label: string | null; capacity_gb: number | null; thin_provisioned: boolean | null; datastore?: string; storage_container_uuid?: string }
interface HistoryRow { id: string; changed_at: string; changed_fields: Record<string, unknown> }
interface AuditRow { id: string; changed_at: string; field_name: string; old_value: string | null; new_value: string | null; changed_by: string | null; changed_by_name: string | null }
