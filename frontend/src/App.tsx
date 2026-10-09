import React from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { ProtectedLayout, AdminGuard } from './routes/Guards'
import { EntryPage } from './pages/EntryPage'
import { WelcomePage } from './pages/WelcomePage'
import { ChangePinPage } from './pages/ChangePinPage'
import { Dashboard } from './pages/Dashboard'
import { ServicesPage } from './pages/ServicesPage'
import { ServiceOpenPage } from './pages/ServiceOpenPage'
import { ProfilePage } from './pages/ProfilePage'
import { AdminTabs } from './pages/admin/AdminTabs'
import { PeoplePage } from './pages/admin/PeoplePage'
import { AccountsPage } from './pages/admin/AccountsPage'
import { AccessPage } from './pages/admin/AccessPage'
import { ServicesAdminPage } from './pages/admin/ServicesAdminPage'
import { AuditPage } from './pages/admin/AuditPage'
import { ActivityPage } from './pages/admin/ActivityPage'
import { RolesPage } from './pages/admin/RolesPage'
import { LlmPage } from './pages/admin/LlmPage'
import { AgentsPage } from './pages/admin/AgentsPage'
import { DepartmentsPage } from './pages/admin/DepartmentsPage'
import { CapabilitiesPage } from './pages/admin/CapabilitiesPage'

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<EntryPage />} />
          <Route path="/welcome" element={<WelcomePage />} />
          <Route path="/change-pin" element={<ChangePinPage />} />

          <Route element={<ProtectedLayout />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/services" element={<ServicesPage />} />
            <Route path="/services/open/:slug" element={<ServiceOpenPage />} />
            <Route path="/profile" element={<ProfilePage />} />

            <Route element={<AdminGuard />}>
              <Route path="/ai" element={<LlmPage />} />
              <Route path="/admin" element={<AdminTabs />}>
                <Route index element={<Navigate to="people" replace />} />
                <Route path="access" element={<AccessPage />} />
                <Route path="people" element={<PeoplePage />} />
                <Route path="accounts" element={<AccountsPage />} />
                <Route path="agents" element={<AgentsPage />} />
                <Route path="departments" element={<DepartmentsPage />} />
                <Route path="capabilities" element={<CapabilitiesPage />} />
                <Route path="services" element={<ServicesAdminPage />} />
                <Route path="roles" element={<RolesPage />} />
                <Route path="audit" element={<AuditPage />} />
                <Route path="activity" element={<ActivityPage />} />
              </Route>
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
