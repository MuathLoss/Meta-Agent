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

export function accessTokenSession(session: SessionState): SessionState {
  return {
    access_token: session.access_token,
    token_type: session.token_type || 'bearer',
    user: session.user,
    memberships: session.memberships,
  };
}

export default function App() {
  const [session, setSession] = useState<SessionState | null>(() => {
    const raw = localStorage.getItem('session');
    try { return raw ? accessTokenSession(JSON.parse(raw) as SessionState) : null; } catch { return null; }
  });
  const [tenantSlug, setTenantSlug] = useState(() => localStorage.getItem('tenantSlug') || 'sarh-almarifah');

  const [supportReason, setSupportReason] = useState(() => sessionStorage.getItem('supportAccessReason') || '');
  const [supportDraft, setSupportDraft] = useState('');

  function handleLogin(s: SessionState, submittedSlug: string) {
    const accessOnlySession = accessTokenSession(s);
    const resolvedSlug = resolveSessionTenantSlug(s, submittedSlug);
    localStorage.setItem('session', JSON.stringify(accessOnlySession));
    localStorage.setItem('tenantSlug', resolvedSlug);
    setSession(accessOnlySession);
    setTenantSlug(resolvedSlug);
  }

  function logout() {
    localStorage.removeItem('session');
    localStorage.removeItem('tenantSlug');
    sessionStorage.removeItem('supportAccessReason');
    setSupportReason('');
    setSession(null);
  }

  if (session?.user.is_platform_admin && !supportReason) return <main className="auth-v2"><form className="card form-stack" onSubmit={e => {e.preventDefault();const reason=supportDraft.trim();if(!reason)return;sessionStorage.setItem('supportAccessReason',reason);setSupportReason(reason);}}><h2>Platform support access</h2><p>Enter why you are opening this workspace. The reason is recorded in its audit history.</p><label>Access reason<input required value={supportDraft} onChange={e=>setSupportDraft(e.target.value)} maxLength={240}/></label><button>Open workspace</button><button type="button" className="secondary" onClick={logout}>Sign out</button></form></main>;
  return session ? <Dashboard session={session} tenantSlug={tenantSlug} onLogout={logout} /> : <LoginPage onLogin={handleLogin} />;
}
