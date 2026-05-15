import { useState } from 'react';
import { LoginPage } from './pages/LoginPage';
import { Dashboard } from './pages/Dashboard';
import type { SessionState } from './services/api';

function resolveSessionTenantSlug(session: SessionState, submittedSlug: string) {
  const normalized = submittedSlug.trim();
  if (normalized && session.memberships.some((membership) => membership.tenant_slug === normalized)) {
    return normalized;
  }
  return session.memberships[0]?.tenant_slug || normalized || 'sarh-almarifah';
}

export default function App() {
  const [session, setSession] = useState<SessionState | null>(() => {
    const raw = localStorage.getItem('session');
    return raw ? JSON.parse(raw) as SessionState : null;
  });
  const [tenantSlug, setTenantSlug] = useState(() => localStorage.getItem('tenantSlug') || 'sarh-almarifah');

  function handleLogin(s: SessionState, submittedSlug: string) {
    const resolvedSlug = resolveSessionTenantSlug(s, submittedSlug);
    localStorage.setItem('session', JSON.stringify(s));
    localStorage.setItem('tenantSlug', resolvedSlug);
    setSession(s);
    setTenantSlug(resolvedSlug);
  }

  function logout() {
    localStorage.clear();
    setSession(null);
  }

  return session ? <Dashboard session={session} tenantSlug={tenantSlug} onLogout={logout} /> : <LoginPage onLogin={handleLogin} />;
}
