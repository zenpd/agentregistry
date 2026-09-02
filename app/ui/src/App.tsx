import { BrowserRouter, Routes, Route } from 'react-router-dom'
import AppShell from './components/layout/AppShell'
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

export default function App() {
  return (
    <BrowserRouter>
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
    </BrowserRouter>
  )
}
