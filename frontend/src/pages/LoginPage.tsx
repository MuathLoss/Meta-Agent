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

  function validateForm() {
    const trimmedTenantSlug = tenantSlug.trim();
    if (!email.trim()) return 'Enter an email address.';
    if (!password) return 'Enter your password.';
    if (!trimmedTenantSlug) return 'Enter your tenant slug.';
    if (!/^[a-z0-9-]+$/.test(trimmedTenantSlug)) return 'Tenant slug can only use lowercase letters, numbers, and hyphens.';
    if (mode === 'signup') {
      if (!businessName.trim()) return 'Enter a business name.';
      if (!adminName.trim()) return 'Enter the admin name.';
      if (password.length < 8) return 'Password must be at least 8 characters.';
    }
    return null;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const normalizedTenantSlug = tenantSlug.trim();
      const session = mode === 'login'
        ? await login(email.trim(), password, normalizedTenantSlug)
        : await signupBusiness({ business_name: businessName.trim(), tenant_slug: normalizedTenantSlug, admin_name: adminName.trim(), admin_email: email.trim(), admin_password: password, support_phone: supportPhone.trim() || undefined, timezone: 'Asia/Riyadh', default_lang: 'ar' });
      onLogin(session, normalizedTenantSlug);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-shell" aria-label="Business Agent Workspace sign in">
        <section className="auth-copy-panel">
          <div className="auth-topline">
            <span>[TENANT WORKSPACE]</span>
            <span>[PRIVATE CONFIG]</span>
          </div>

          <div className="auth-headline" aria-label="Configure your business agent">
            <span>Configure</span>
            <span>Your</span>
            <span>Business</span>
            <span>Agent</span>
          </div>

          <section className="auth-card">
            <div className="auth-card-head">
              <div className="auth-mark" aria-hidden="true">BA</div>
              <div>
                <p className="eyebrow">Multi-tenant platform</p>
                <h1>Business Agent Workspace</h1>
                <p className="auth-subtitle">Manage customer conversations, routing, staff, and channels from one secure admin workspace.</p>
              </div>
            </div>

            <div className="auth-mode-switch" role="tablist" aria-label="Authentication mode">
              <button type="button" role="tab" aria-selected={mode === 'login'} className={mode === 'login' ? 'active' : ''} onClick={() => { setMode('login'); setError(null); }}>Sign in</button>
              <button type="button" role="tab" aria-selected={mode === 'signup'} className={mode === 'signup' ? 'active' : ''} onClick={() => { setMode('signup'); setError(null); }}>Create business</button>
            </div>

            <form onSubmit={submit} className="form-stack auth-form" noValidate>
              {mode === 'signup' && (
                <div className="auth-signup-fields">
                  <label>Business name<input autoComplete="organization" placeholder="Your business name" value={businessName} onChange={(e) => setBusinessName(e.target.value)} /></label>
                  <label>Admin name<input autoComplete="name" placeholder="Workspace admin name" value={adminName} onChange={(e) => setAdminName(e.target.value)} /></label>
                  <label>Support phone<input autoComplete="tel" placeholder="Support phone number" value={supportPhone} onChange={(e) => setSupportPhone(e.target.value)} /></label>
                </div>
              )}

              <label>Email<input autoComplete="email" placeholder="admin@business.com" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
              <label>Password<input autoComplete={mode === 'login' ? 'current-password' : 'new-password'} type="password" placeholder="Enter your password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
              <label>
                Tenant slug
                <input autoComplete="organization" placeholder="business-slug" value={tenantSlug} onChange={(e) => setTenantSlug(e.target.value.toLowerCase())} />
                <span className="field-hint">Use the workspace slug assigned to this tenant.</span>
              </label>

              {error && <div className="error-box auth-error" role="alert">{error}</div>}
              <button className="auth-submit" disabled={loading}>{loading ? 'Checking access...' : mode === 'login' ? 'Sign in securely' : 'Create workspace'}</button>
            </form>
          </section>
        </section>

        <div className="auth-visual-panel" aria-hidden="true">
          <div className="auth-tech-line">
            <span>[CHANNEL READY]</span>
            <span>[VIEW DASHBOARD]</span>
          </div>
          <div className="auth-hero-placeholder">
            <div className="auth-hero-label">[AI OPERATIONS CORE]</div>
            <div className="auth-ambient auth-ambient-one"></div>
            <div className="auth-ambient auth-ambient-two"></div>
            <div className="auth-orbit auth-orbit-one"></div>
            <div className="auth-orbit auth-orbit-two"></div>
            <div className="auth-orbit auth-orbit-three"></div>
            <div className="auth-core-object">
              <div className="auth-core-ring"></div>
              <div className="auth-core-panel">
                <span>Agent signal</span>
                <strong>Configured</strong>
                <div className="mock-progress-line"></div>
              </div>
            </div>
            <div className="auth-dashboard-float">
              <div className="auth-dashboard-mock">
                <div className="mock-topbar">
                  <div className="tenant-logo-placeholder">Workspace OS</div>
                  <div className="mock-status"><span className="mock-status-dot"></span>Live</div>
                </div>
                <div className="mock-card-stack">
                  <div className="mock-card mock-card-wide">
                    <span>Conversation routing</span>
                    <strong>Priority queue active</strong>
                    <div className="mock-message-row"></div>
                    <div className="mock-message-row short"></div>
                  </div>
                  <div className="mock-card">
                    <span>Agent analytics</span>
                    <div className="mock-bars"><i></i><i></i><i></i><i></i></div>
                  </div>
                  <div className="mock-card">
                    <span>Channel sync</span>
                    <div className="mock-channel-line"></div>
                    <div className="mock-channel-line second"></div>
                    <div className="mock-progress-line"></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
