// Central RBAC matrix for the frontend. Mirrors the backend's permission
// checks in app/api/vms.py, app/api/deps.py — this only controls what's
// *shown*; the backend is the actual enforcement point.

export type Role = 'admin' | 'global_editor' | 'user' | 'viewer'

export const ROLE_LABELS: Record<Role, string> = {
  admin: 'Admin',
  global_editor: 'Global Editor',
  user: 'User',
  viewer: 'Viewer',
}

// Roles that only ever see/edit VMs they own
const OWNER_SCOPED_ROLES: Role[] = ['user', 'viewer']

export function isVmScopedRole(role?: string | null): boolean {
  return OWNER_SCOPED_ROLES.includes(role as Role)
}

// Pages beyond "my VMs" — hidden from user/viewer entirely (nav + route)
export type Page = 'dashboard' | 'hosts' | 'networks' | 'sync' | 'decommissioned' | 'settings' | 'admin' | 'audit-log'

export function canAccessPage(role: string | undefined | null, page: Page): boolean {
  if (!role) return false
  if (role === 'admin') return true
  if (role === 'global_editor') {
    return page !== 'settings' && page !== 'admin' && page !== 'audit-log'
  }
  // user / viewer: VM list + VM detail only — no other page
  return false
}

const EDITABLE_FIELDS_BY_ROLE: Record<string, string[]> = {
  admin: ['owner_user_id', 'secondary_owner_id', 'department_id', 'environment_id', 'notes', 'os_detail', 'management_ip'],
  global_editor: ['owner_user_id', 'secondary_owner_id', 'department_id', 'environment_id', 'notes', 'os_detail', 'management_ip'],
  user: ['owner_user_id', 'secondary_owner_id', 'department_id', 'environment_id', 'notes'],
}

/** Can this role edit ANY VM metadata at all (ignoring ownership)? */
export function canEditVms(role?: string | null): boolean {
  return !!role && role in EDITABLE_FIELDS_BY_ROLE
}

/** Can this role edit `field` on a VM, given whether they own it? */
export function canEditField(role: string | undefined | null, field: string, isOwnVm: boolean): boolean {
  if (!role) return false
  const fields = EDITABLE_FIELDS_BY_ROLE[role]
  if (!fields) return false
  if (isVmScopedRole(role) && !isOwnVm) return false
  return fields.includes(field)
}

/** Can this role edit at least one field on this specific VM? */
export function canEditVm(role: string | undefined | null, isOwnVm: boolean): boolean {
  if (!role) return false
  if (!(role in EDITABLE_FIELDS_BY_ROLE)) return false
  if (isVmScopedRole(role) && !isOwnVm) return false
  return true
}
