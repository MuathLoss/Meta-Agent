import { useState, type FormEvent } from 'react';
import { login, signupBusiness, type SessionState } from '../services/api';

type Props = { onLogin: (session: SessionState, tenantSlug: string) => void };

export function LoginPage({ onLogin }: Props) {
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [tenantSlug, setTenantSlug] = useState('');
  const [businessName, setBusinessName] = useState('');
  const [adminName, setAdminName] = useState('');
  const [supportPhone, setSupportPhone] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const session = mode === 'login'
        ? await login(email, password, tenantSlug)
        : await signupBusiness({ business_name: businessName, tenant_slug: tenantSlug, admin_name: adminName, admin_email: email, admin_password: password, support_phone: supportPhone, timezone: 'Asia/Riyadh', default_lang: 'ar' });
      onLogin(session, tenantSlug);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed');
    } finally {
      setLoading(false);
    }
  }

  return <main className="auth-page"><section className="auth-card"><p className="eyebrow">Multi-tenant platform</p><h1>Business Agent Workspace</h1><div className="button-row"><button type="button" className={mode === 'login' ? '' : 'secondary'} onClick={() => setMode('login')}>Sign in</button><button type="button" className={mode === 'signup' ? '' : 'secondary'} onClick={() => setMode('signup')}>Create business</button></div><form onSubmit={submit} className="form-stack">{mode === 'signup' && <><label>Business name<input placeholder="Test Business" value={businessName} onChange={(e) => setBusinessName(e.target.value)} /></label><label>Admin name<input placeholder="Business Admin" value={adminName} onChange={(e) => setAdminName(e.target.value)} /></label><label>Support phone<input placeholder="0500000000" value={supportPhone} onChange={(e) => setSupportPhone(e.target.value)} /></label></>}<label>Email<input placeholder="academy.admin@example.com" value={email} onChange={(e) => setEmail(e.target.value)} /></label><label>Password<input type="password" placeholder="Enter your password" value={password} onChange={(e) => setPassword(e.target.value)} /></label><label>Tenant slug<input placeholder="tenant slug" value={tenantSlug} onChange={(e) => setTenantSlug(e.target.value)} /></label>{error && <div className="error-box">{error}</div>}<button disabled={loading}>{loading ? 'Working...' : mode === 'login' ? 'Sign in' : 'Create workspace'}</button></form></section></main>;
}
