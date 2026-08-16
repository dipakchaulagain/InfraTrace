import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  updateVmMetadata, listDepartments, listEnvironments, listUsersLookup, listApplications, listTags,
} from '../lib/api'
import { useAuth } from '../lib/auth'
import { canEditField } from '../lib/permissions'
import Drawer from './Drawer'
import VmMetadataForm, { type MetaForm } from './VmMetadataForm'

export interface EditableVm {
  id: string
  name: string
  owner_user_id: string | null
  secondary_owner_id: string | null
  department_id: string | null
  environment_id: string | null
  os_detail: string | null
  management_ip: string | null
  applications: { id: string; name: string }[] | null
  tags: { id: string; name: string }[] | null
  notes: string | null
}

// Quick-edit slide-in for VM metadata — same form as the VM Detail page's
// "Edit metadata", just reachable straight from the VMs list so a bulk
// ownership/department pass doesn't need a click-through per VM.
export default function VmEditDrawer({ vm, onClose, onSaved }: {
  vm: EditableVm
  onClose: () => void
  onSaved: () => void
}) {
  const { user } = useAuth()
  const qc = useQueryClient()

  const [form, setForm] = useState<MetaForm>({
    owner_user_id: vm.owner_user_id ?? '',
    secondary_owner_id: vm.secondary_owner_id ?? '',
    department_id: vm.department_id ?? '',
    environment_id: vm.environment_id ?? '',
    os_detail: vm.os_detail ?? '',
    management_ip: vm.management_ip ?? '',
    application_ids: (vm.applications ?? []).map(a => a.id),
    tag_ids: (vm.tags ?? []).map(t => t.id),
    notes: vm.notes ?? '',
  })

  const isOwnVm = !!user && vm.owner_user_id === user.id
  const canEditOwner = user?.role === 'admin' || user?.role === 'global_editor'
  const canEditOsDetail = canEditField(user?.role, 'os_detail', isOwnVm)
  const canEditMgmtIp = canEditField(user?.role, 'management_ip', isOwnVm)
  const canEditApplications = canEditField(user?.role, 'application_ids', isOwnVm)
  const canEditTags = canEditField(user?.role, 'tag_ids', isOwnVm)

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
    mutationFn: () => updateVmMetadata(vm.id, form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['vms'] })
      qc.invalidateQueries({ queryKey: ['vm', vm.id] })
      qc.invalidateQueries({ queryKey: ['vm-meta-audit', vm.id] })
      onSaved()
    },
  })

  return (
    <Drawer open onClose={onClose} title={`Edit Metadata — ${vm.name}`}>
      <VmMetadataForm
        form={form}
        setForm={setForm}
        onSubmit={e => { e.preventDefault(); saveMutation.mutate() }}
        onCancel={onClose}
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
    </Drawer>
  )
}
