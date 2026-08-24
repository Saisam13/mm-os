import React from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { ProtectedLayout, AdminGuard } from './routes/Guards'
import { EntryPage } from './pages/EntryPage'
import { ServicesPage } from './pages/ServicesPage'
import { ProfilePage } from './pages/ProfilePage'
import { AdminTabs } from './pages/admin/AdminTabs'
import { PeoplePage } from './pages/admin/PeoplePage'
import { AccessPage } from './pages/admin/AccessPage'
import { ServicesAdminPage } from './pages/admin/ServicesAdminPage'
import { AuditPage } from './pages/admin/AuditPage'
import { LlmPage } from './pages/admin/LlmPage'

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<EntryPage />} />

          <Route element={<ProtectedLayout />}>
            <Route path="/services" element={<ServicesPage />} />
            <Route path="/profile" element={<ProfilePage />} />

            <Route element={<AdminGuard />}>
              <Route path="/ai" element={<LlmPage />} />
              <Route path="/admin" element={<AdminTabs />}>
                <Route index element={<Navigate to="access" replace />} />
                <Route path="access" element={<AccessPage />} />
                <Route path="people" element={<PeoplePage />} />
                <Route path="services" element={<ServicesAdminPage />} />
                <Route path="audit" element={<AuditPage />} />
              </Route>
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
