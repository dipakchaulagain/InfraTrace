import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './lib/auth'
import { canAccessPage, type Page } from './lib/permissions'
import Layout from './components/Layout'
import Login from './pages/Login'
import ResetRequired from './pages/ResetRequired'
import Dashboard from './pages/Dashboard'
import VMs from './pages/VMs'
import VMDetail from './pages/VMDetail'
import DecommissionedVMs from './pages/DecommissionedVMs'
import Hosts from './pages/Hosts'
import Networks from './pages/Networks'
import Datastores from './pages/Datastores'
import DatastoreDetail from './pages/DatastoreDetail'
import SyncHealth from './pages/SyncHealth'
import Settings from './pages/Settings'
import Admin from './pages/Admin'
import Metadata from './pages/Metadata'
import AuditLog from './pages/AuditLog'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, user } = useAuth()
  const location = useLocation()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (user?.must_reset_password && location.pathname !== '/reset-required') {
    return <Navigate to="/reset-required" replace />
  }
  return <>{children}</>
}

function RequirePage({ page, children }: { page: Page; children: React.ReactNode }) {
  const { user } = useAuth()
  // Roles without dashboard access land on "/" too (their home is /vms) —
  // redirecting a blocked dashboard visit back to "/" would loop forever.
  const fallback = page === 'dashboard' ? '/vms' : '/'
  return canAccessPage(user?.role, page) ? <>{children}</> : <Navigate to={fallback} replace />
}

function AppRoutes() {
  const { isAuthenticated, user } = useAuth()

  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route
        path="/reset-required"
        element={
          isAuthenticated
            ? <ResetRequired />
            : <Navigate to="/login" replace />
        }
      />

      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route
          index
          element={
            <RequirePage page="dashboard"><Dashboard /></RequirePage>
          }
        />
        <Route path="vms" element={<VMs />} />
        <Route path="vms/:id" element={<VMDetail />} />
        <Route
          path="vms-decommissioned"
          element={<RequirePage page="decommissioned"><DecommissionedVMs /></RequirePage>}
        />
        <Route path="hosts" element={<RequirePage page="hosts"><Hosts /></RequirePage>} />
        <Route path="networks" element={<RequirePage page="networks"><Networks /></RequirePage>} />
        <Route path="datastores" element={<RequirePage page="datastores"><Datastores /></RequirePage>} />
        <Route path="datastores/:id" element={<RequirePage page="datastores"><DatastoreDetail /></RequirePage>} />
        <Route path="sync" element={<RequirePage page="sync"><SyncHealth /></RequirePage>} />
        <Route
          path="settings"
          element={<RequirePage page="settings"><Settings /></RequirePage>}
        />
        <Route
          path="admin"
          element={<RequirePage page="admin"><Admin /></RequirePage>}
        />
        <Route
          path="metadata"
          element={<RequirePage page="metadata"><Metadata /></RequirePage>}
        />
        <Route
          path="admin/audit-log"
          element={<RequirePage page="audit-log"><AuditLog /></RequirePage>}
        />
      </Route>

      {/* Catch-all */}
      <Route path="*" element={<Navigate to={user ? '/' : '/login'} replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  )
}
