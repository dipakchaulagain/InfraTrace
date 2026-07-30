import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Server,
  RefreshCw,
  Settings,
  Settings2,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Monitor,
  Network,
  Archive,
  FileClock,
} from 'lucide-react'
import { cn } from '../lib/utils'
import { useAuth } from '../lib/auth'
import { canAccessPage, isVmScopedRole, ROLE_LABELS, type Page, type Role } from '../lib/permissions'

const NAV: { to: string; label: string; icon: typeof Monitor; page?: Page }[] = [
  { to: '/',                 label: 'Dashboard',          icon: LayoutDashboard, page: 'dashboard' },
  { to: '/vms',               label: 'VMs',                icon: Monitor },
  { to: '/vms-decommissioned', label: 'Decommissioned VMs', icon: Archive,         page: 'decommissioned' },
  { to: '/hosts',             label: 'Hosts',              icon: Server,          page: 'hosts' },
  { to: '/networks',          label: 'Networks',           icon: Network,         page: 'networks' },
  { to: '/sync',              label: 'Sync Health',        icon: RefreshCw,       page: 'sync' },
  { to: '/settings',          label: 'Settings',           icon: Settings2,       page: 'settings' },
  { to: '/admin',             label: 'Admin',              icon: Settings,        page: 'admin' },
  { to: '/admin/audit-log',   label: 'Audit Log',          icon: FileClock,       page: 'audit-log' },
]
interface SidebarProps {
  mobileOpen: boolean
  onMobileClose: () => void
}

export default function Sidebar({ mobileOpen, onMobileClose }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false)
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  const items = NAV
    .filter(n => !n.page || canAccessPage(user?.role, n.page))
    .map(n => n.to === '/vms' && isVmScopedRole(user?.role) ? { ...n, label: 'My VMs' } : n)

  return (
    <>
      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/40 lg:hidden"
          onClick={onMobileClose}
          aria-hidden
        />
      )}

      {/* Sidebar panel */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-30 flex flex-col bg-white border-r border-gray-100 shadow-sm',
          'transition-all duration-250 ease-in-out',
          // Desktop width toggle
          collapsed ? 'w-16' : 'w-60',
          // Mobile: off-canvas
          'lg:translate-x-0',
          mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0',
        )}
      >
        {/* Logo / brand */}
        <div className={cn(
          'flex items-center gap-3 px-4 h-16 border-b border-gray-100 shrink-0',
          collapsed ? 'justify-center' : '',
        )}>
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-white font-bold text-sm">
            I
          </div>
          {!collapsed && (
            <span className="font-semibold text-gray-800 leading-tight truncate">
              InfraTrace
            </span>
          )}
        </div>

        {/* Nav items */}
        <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-0.5">
          {items.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/' || to === '/admin'}
              onClick={onMobileClose}
              className={({ isActive }) =>
                cn('nav-item', isActive && 'active', collapsed && 'justify-center !px-2')
              }
              title={collapsed ? label : undefined}
            >
              <Icon className="h-5 w-5 shrink-0" />
              {!collapsed && <span className="truncate">{label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* User + logout */}
        <div className={cn(
          'border-t border-gray-100 px-2 py-3 space-y-0.5 shrink-0',
        )}>
          {!collapsed && (
            <div className="px-3 py-2 mb-1">
              <p className="text-xs font-semibold text-gray-800 truncate">{user?.username}</p>
              <p className="text-xs text-gray-400 truncate">{ROLE_LABELS[user?.role as Role] ?? user?.role}</p>
            </div>
          )}
          <button
            onClick={handleLogout}
            className={cn('nav-item w-full text-red-500 hover:bg-red-50 hover:text-red-600',
              collapsed && 'justify-center !px-2')}
            title={collapsed ? 'Log out' : undefined}
          >
            <LogOut className="h-5 w-5 shrink-0" />
            {!collapsed && <span>Log out</span>}
          </button>
        </div>

        {/* Collapse toggle — desktop only */}
        <button
          onClick={() => setCollapsed(c => !c)}
          className="hidden lg:flex items-center justify-center h-8 w-8 rounded-full
                     bg-white border border-gray-200 shadow-sm text-gray-400
                     hover:text-primary hover:border-primary transition-colors
                     absolute -right-4 top-1/2 -translate-y-1/2"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </aside>

      {/* Spacer so main content doesn't slide under sidebar (desktop) */}
      <div className={cn(
        'hidden lg:block shrink-0 transition-all duration-250',
        collapsed ? 'w-16' : 'w-60',
      )} />
    </>
  )
}
