import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Menu } from 'lucide-react'
import Sidebar from './Sidebar'
import SessionTimeoutWarning from './SessionTimeoutWarning'

export default function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div className="flex min-h-screen bg-background">
      <SessionTimeoutWarning />
      <Sidebar mobileOpen={mobileOpen} onMobileClose={() => setMobileOpen(false)} />

      <div className="flex flex-1 flex-col min-w-0">
        {/* Mobile top bar */}
        <header className="flex lg:hidden items-center h-14 px-4 bg-white border-b border-gray-100 shrink-0">
          <button
            onClick={() => setMobileOpen(true)}
            className="btn-ghost !px-2"
            aria-label="Open menu"
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="ml-3 font-semibold text-gray-800">InfraTrace</span>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto p-4 sm:p-6 page-enter">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
