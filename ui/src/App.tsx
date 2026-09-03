import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppShell from './components/layout/AppShell'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import PlaygroundPage from './pages/PlaygroundPage'
import SettingsPage from './pages/SettingsPage'
import ExecutivePage from './pages/ExecutivePage'
import AgentsPage from './pages/AgentsPage'
import GovernancePage from './pages/GovernancePage'
import BusinessView from './pages/BusinessView'
import PlatformView from './pages/PlatformView'
import TokenomicsView from './pages/TokenomicsView'
import DependencyGraphView from './pages/DependencyGraphView'
import SecurityView from './pages/SecurityView'
import { getAuthToken } from './services/api'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<AuthShell />} />
      </Routes>
    </BrowserRouter>
  )
}

function AuthShell() {
  if (!getAuthToken()) return <Navigate to="/login" replace />
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<ExecutivePage />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/governance" element={<GovernancePage />} />
        <Route path="/business" element={<BusinessView />} />
        <Route path="/platform" element={<PlatformView />} />
        <Route path="/tokenomics" element={<TokenomicsView />} />
        <Route path="/dependencies" element={<DependencyGraphView />} />
        <Route path="/security" element={<SecurityView />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/playground" element={<PlaygroundPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </AppShell>
  )
}