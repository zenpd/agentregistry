import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppShell from './components/layout/AppShell'
import LoginPage from './pages/LoginPage'
import PlaygroundPage from './pages/PlaygroundPage'

// Trying an agent lives in one place, its Integrate tab. Old /playground links land there.
function PlaygroundRedirect() {
  const agent = new URLSearchParams(window.location.search).get('agent')
  return <Navigate to={agent ? `/agents/${agent}?tab=integrate` : '/agents'} replace />
}
void PlaygroundPage   // kept until the final cleanup
import SettingsPage from './pages/SettingsPage'
import ExecutivePage from './pages/ExecutivePage'
import AgentsPage from './pages/AgentsPage'
import AgentPage from './pages/AgentPage'
import GovernancePage from './pages/GovernancePage'
import PlatformView from './pages/PlatformView'
import DependencyGraphView from './pages/DependencyGraphView'
import BusinessView from './pages/BusinessView'
import ApprovalsPage from './pages/ApprovalsPage'
import DiscoveredPage from './pages/DiscoveredPage'
import AskPage from './pages/AskPage'
import HowItWorksPage from './pages/HowItWorksPage'
import PipelinesPage from './pages/PipelinesPage'
import AuditPage from './pages/AuditPage'
import ProgrammeHealthPage from './pages/ProgrammeHealthPage'
import CompliancePage from './pages/CompliancePage'
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
        <Route path="/business" element={<BusinessView />} />
        <Route path="/discovered" element={<DiscoveredPage />} />
        <Route path="/ask" element={<AskPage />} />
        <Route path="/approvals" element={<ApprovalsPage />} />
        <Route path="/how-it-works" element={<HowItWorksPage />} />
        <Route path="/pipelines" element={<PipelinesPage />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/agents/:id" element={<AgentPage />} />
        <Route path="/governance" element={<GovernancePage />} />
        <Route path="/platform" element={<PlatformView />} />
        <Route path="/dependencies" element={<DependencyGraphView />} />
        <Route path="/playground" element={<PlaygroundRedirect />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/programme" element={<ProgrammeHealthPage />} />
        <Route path="/compliance" element={<CompliancePage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </AppShell>
  )
}

function NotFound() {
  return (
    <div className="p-12 text-center">
      <p className="text-lg font-semibold text-slate-700">Page not found</p>
      <p className="text-sm text-slate-500 mt-1">There's nothing at this address.</p>
      <a href="/" className="text-sm text-zen-600 underline mt-3 inline-block">Back to the registry</a>
    </div>
  )
}
