import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Building2, Layers, Tag, AppWindow, Users } from 'lucide-react'
import {
  listDepartments, createDepartment, deleteDepartment,
  listEnvironments, createEnvironment, deleteEnvironment,
  listApplications, createApplication, deleteApplication,
  listTags, createTag, deleteTag,
  listUsers,
} from '../lib/api'
import Spinner from '../components/Spinner'
import ErrorBanner from '../components/ErrorBanner'
import MetadataEntityManager from '../components/MetadataEntityManager'
import { canManageMetadata } from '../lib/permissions'
import { useAuth } from '../lib/auth'

type Section = 'departments' | 'applications' | 'environments' | 'tags' | 'owners'

const SECTIONS: { id: Section; label: string; icon: typeof Building2 }[] = [
  { id: 'departments', label: 'Departments', icon: Building2 },
  { id: 'applications', label: 'Applications', icon: AppWindow },
  { id: 'environments', label: 'Environments', icon: Layers },
  { id: 'tags', label: 'Tags', icon: Tag },
  { id: 'owners', label: 'Users', icon: Users },
]

export default function Metadata() {
  const [section, setSection] = useState<Section>('departments')
  const { user } = useAuth()
  const readOnly = !canManageMetadata(user?.role)

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-gray-800">Metadata</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {readOnly
            ? 'View the lookup lists VMs are classified by, and see which users are currently VM owners'
            : 'Manage the lookup lists VMs are classified by, and see which users are currently VM owners'}
        </p>
      </div>

      <div className="flex gap-1 border-b border-gray-200 overflow-x-auto">
        {SECTIONS.map(s => (
          <button
            key={s.id}
            onClick={() => setSection(s.id)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px
              whitespace-nowrap transition-colors
              ${section === s.id ? 'border-primary text-primary' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
          >
            <s.icon className="h-4 w-4" />
            {s.label}
          </button>
        ))}
      </div>

      {section === 'departments' && (
        <MetadataEntityManager
          label="Department" queryKey="departments" filterParam="department_id" readOnly={readOnly}
          listFn={listDepartments} createFn={p => createDepartment(p.name)} deleteFn={deleteDepartment}
        />
      )}
      {section === 'applications' && (
        <MetadataEntityManager
          label="Application" queryKey="applications" filterParam="application_id" readOnly={readOnly}
          listFn={listApplications} createFn={p => createApplication(p.name)} deleteFn={deleteApplication}
        />
      )}
      {section === 'environments' && (
        <MetadataEntityManager
          label="Environment" queryKey="environments" filterParam="environment_id" readOnly={readOnly}
          listFn={listEnvironments} createFn={p => createEnvironment(p.name)} deleteFn={deleteEnvironment}
        />
      )}
      {section === 'tags' && (
        <MetadataEntityManager
          label="Tag" queryKey="tags" filterParam="tag_id" hasCategory readOnly={readOnly}
          listFn={listTags} createFn={p => createTag(p.name, p.category)} deleteFn={deleteTag}
        />
      )}
      {section === 'owners' && <OwnersSection />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Users — read-only: every user who currently owns at least one VM. Full
// account management (create/edit/role/reset/delete) stays on Admin > Users;
// this is just the ownership-side cross-reference, alongside the other
// lookup lists.
// ---------------------------------------------------------------------------
interface OwnerUser {
  id: string; username: string; full_name: string | null; email: string
  department_id: string | null; owned_vm_count: number
}
interface Lookup { id: string; name: string }

function OwnersSection() {
  const navigate = useNavigate()

  const { data: users = [], isLoading, isError, refetch } = useQuery({
    queryKey: ['users'],
    queryFn: () => listUsers().then(r => r.data as OwnerUser[]),
  })
  const { data: departments = [] } = useQuery({
    queryKey: ['departments'],
    queryFn: () => listDepartments().then(r => r.data as Lookup[]),
  })
  const departmentNameById = useMemo(
    () => new Map<string, string>(departments.map(d => [d.id, d.name])),
    [departments],
  )

  const owners = useMemo(
    () => users.filter(u => u.owned_vm_count > 0).sort((a, b) => a.username.localeCompare(b.username)),
    [users],
  )

  function goToVms(ownerId: string) {
    navigate(`/vms?owner_user_id=${ownerId}`)
  }

  if (isError) {
    return <ErrorBanner message="Failed to load users." onRetry={refetch} />
  }
  if (isLoading) {
    return <div className="flex justify-center py-8"><Spinner /></div>
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="rounded-lg bg-primary-50 border border-primary-100 px-4 py-3 text-sm text-gray-600">
        Users who currently own at least one VM. To create, edit, or reassign roles for a user account,
        go to Admin → Users.
      </div>

      <div className="card">
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Full Name</th>
                <th>Email</th>
                <th>Department</th>
                <th>VM Count</th>
              </tr>
            </thead>
            <tbody>
              {owners.length === 0 && (
                <tr><td colSpan={5} className="text-center text-gray-400 py-8">No VMs have an owner assigned yet</td></tr>
              )}
              {owners.map(u => (
                <tr key={u.id}>
                  <td className="font-medium text-gray-800">{u.username}</td>
                  <td className="text-sm text-gray-600">{u.full_name || <span className="text-gray-400">—</span>}</td>
                  <td className="text-sm text-gray-500">{u.email}</td>
                  <td>{u.department_id ? <span className="badge badge-teal">{departmentNameById.get(u.department_id) ?? 'Unknown'}</span> : '—'}</td>
                  <td>
                    <button
                      onClick={() => goToVms(u.id)}
                      className="badge badge-teal hover:opacity-80"
                      title={`View VMs owned by ${u.username}`}
                    >
                      {u.owned_vm_count}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
