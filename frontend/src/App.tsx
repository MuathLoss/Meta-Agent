import { useEffect, useState } from 'react';
import { LoginPage } from './pages/LoginPage';
import { Dashboard } from './pages/Dashboard';
import { AccountLinkPage, ForgotPassword, readAccountLink, type AccountLink } from './pages/AccountLinks';
import { logoutSession, resendVerification, restoreSession, setCsrfToken, type SessionState } from './services/api';

function resolveSessionTenantSlug(session: SessionState, preferredSlug: string) {
  const normalized = preferredSlug.trim();
  if (normalized && session.memberships.some((membership) => membership.tenant_slug === normalized)) {
    return normalized;
  }
  return session.tenant_slug || session.memberships[0]?.tenant_slug || '';
}

export default function App() {
  const [session, setSession] = useState<SessionState | null>(null);
  const [checking, setChecking] = useState(true);
  const [tenantSlug, setTenantSlug] = useState(() => localStorage.getItem('tenantSlug') || '');
  const [link, setLink] = useState<AccountLink | null>(() => readAccountLink(window.location.search));
  const [forgot, setForgot] = useState(false);
  const [verifyNotice, setVerifyNotice] = useState<string | null>(null);

  const [supportReason, setSupportReason] = useState(() => sessionStorage.getItem('supportAccessReason') || '');
  const [supportDraft, setSupportDraft] = useState('');

  useEffect(() => {
    // Earlier versions kept a sign-in token here; remove it for good.
    localStorage.removeItem('session');
    restoreSession().then((restored) => { if (restored) adopt(restored, localStorage.getItem('tenantSlug') || ''); }).finally(() => setChecking(false));
    const expired = () => { setCsrfToken(''); setSession(null); };
    window.addEventListener('session-expired', expired);
    return () => window.removeEventListener('session-expired', expired);
  }, []);

  function adopt(s: SessionState, preferredSlug: string) {
    setCsrfToken(s.csrf_token);
    const resolvedSlug = resolveSessionTenantSlug(s, preferredSlug);
    localStorage.setItem('tenantSlug', resolvedSlug); // not a secret: just the last workspace used
    setSession(s);
    setTenantSlug(resolvedSlug);
  }

  function leaveLink() {
    window.history.replaceState(null, '', window.location.pathname);
    setLink(null);
  }

  async function logout() {
    try { await logoutSession(); } catch { /* the session may already have ended */ }
    setCsrfToken('');
    sessionStorage.removeItem('supportAccessReason');
    setSupportReason('');
    setSession(null);
  }

  async function resend() {
    try { await resendVerification(); setVerifyNotice('We sent a new confirmation link.'); }
    catch (err) { setVerifyNotice(err instanceof Error ? err.message : 'Please try again later.'); }
  }

  if (link) return <AccountLinkPage link={link} onDone={leaveLink} onSignedIn={(s) => { leaveLink(); adopt(s, s.tenant_slug || ''); }} />;
  if (checking) return <main className="auth-v2"><p className="muted" role="status" style={{ textAlign: 'center', marginTop: '20vh' }}>Loading…</p></main>;
  if (!session) return forgot ? <ForgotPassword onBack={() => setForgot(false)} /> : <LoginPage onLogin={adopt} onForgotPassword={() => setForgot(true)} />;
  if (session.user.is_platform_admin && !supportReason) return <main className="auth-v2"><form className="card form-stack" onSubmit={e => {e.preventDefault();const reason=supportDraft.trim();if(!reason)return;sessionStorage.setItem('supportAccessReason',reason);setSupportReason(reason);}}><h2>Platform support access</h2><p>Enter why you are opening this workspace. The reason is recorded in its audit history.</p><label>Access reason<input required value={supportDraft} onChange={e=>setSupportDraft(e.target.value)} maxLength={240}/></label><button>Open workspace</button><button type="button" className="secondary" onClick={logout}>Sign out</button></form></main>;
  return <>
    {!session.user.email_verified && <div className="error-box" role="status" style={{ borderRadius: 0, margin: 0, textAlign: 'center' }}>
      Please confirm your email address ({session.user.email}) using the link we sent. {verifyNotice || <button className="text-button" onClick={resend}>Send the link again</button>}
    </div>}
    <Dashboard session={session} tenantSlug={tenantSlug} onLogout={logout} />
  </>;
}
