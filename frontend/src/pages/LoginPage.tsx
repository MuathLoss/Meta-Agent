import { useState, type FormEvent } from 'react';
import { login, signupBusiness, type SessionState } from '../services/api';

type Props = { onLogin: (session: SessionState, tenantSlug: string) => void; onForgotPassword: () => void };
export function LoginPage({ onLogin, onForgotPassword }: Props) {
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [tenantSlug, setTenantSlug] = useState('');
  const [slugEdited, setSlugEdited] = useState(false);
  const [businessName, setBusinessName] = useState('');
  const [adminName, setAdminName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null);
    if (mode === 'signup' && !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(tenantSlug.trim())) {
      setError('Choose a workspace address using English letters, numbers, and hyphens.'); return;
    }
    setLoading(true);
    try {
      const session = mode === 'login'
        ? await login(email.trim(), password, tenantSlug.trim())
        : await signupBusiness({ business_name: businessName.trim(), tenant_slug: tenantSlug.trim(), admin_name: adminName.trim(), admin_email: email.trim(), admin_password: password, timezone: 'Asia/Riyadh', default_lang: 'ar' });
      const slug = session.memberships.find(m => m.tenant_slug === tenantSlug.trim())?.tenant_slug || session.memberships[0]?.tenant_slug;
      if (!slug) throw new Error('Your account has no business workspace. Contact your platform administrator.');
      onLogin(session, slug);
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not sign in. Please try again.'); }
    finally { setLoading(false); }
  }
  return <main className="welcome-page">
    <a className="welcome-brand" href="#"><span className="app-monogram">a</span><strong>Agent Workspace</strong></a>
    <div className="welcome-layout">
      <section className="welcome-story">
        <span className="section-caption">YOUR BUSINESS. YOUR ANSWERS.</span>
        <h1>A clear place to<br />care for customers.</h1>
        <p>Bring your messages, business knowledge, and team together. Set up once, then stay in control of every conversation.</p>
        <ol className="welcome-steps">
          <li><span>01</span><div><strong>Add your business</strong><p>Tell customers who you are and when you’re available.</p></div></li>
          <li><span>02</span><div><strong>Teach your agent</strong><p>Add answers or turn your existing chats into drafts.</p></div></li>
          <li><span>03</span><div><strong>Connect and test</strong><p>Try the experience before you welcome customers.</p></div></li>
        </ol>
        <small>Your team decides what the agent knows and when a person takes over.</small>
      </section>
      <section className="welcome-form-card">
        <div className="welcome-tabs" role="tablist" aria-label="Account access">
          <button type="button" role="tab" aria-selected={mode === 'login'} className={mode === 'login' ? 'active' : ''} onClick={() => {setMode('login'); setError(null);}}>Sign in</button>
          <button type="button" role="tab" aria-selected={mode === 'signup'} className={mode === 'signup' ? 'active' : ''} onClick={() => {setMode('signup'); setError(null);}}>Create workspace</button>
        </div>
        <h2>{mode === 'login' ? 'Welcome back' : 'Make room for your business'}</h2>
        <p className="muted">{mode === 'login' ? 'Sign in to your business workspace.' : 'Start with the basics. We’ll guide you through the rest.'}</p>
        <form onSubmit={submit} className="form-stack">
          {mode === 'signup' && <><label>Business name<input required autoComplete="organization" value={businessName} onChange={e => {setBusinessName(e.target.value); if (!slugEdited) setTenantSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''));}} placeholder="Your business" /></label><label>Your name<input required autoComplete="name" value={adminName} onChange={e => setAdminName(e.target.value)} /></label></>}
          <label>Email address<input required type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@business.com" /></label>
          <label>Password<div className="password-field"><input required minLength={mode === 'signup' ? 8 : undefined} type={showPassword ? 'text' : 'password'} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={e => setPassword(e.target.value)} /><button className="text-button" type="button" aria-label={showPassword ? 'Hide password' : 'Show password'} onClick={() => setShowPassword(!showPassword)}>{showPassword ? 'Hide' : 'Show'}</button></div>{mode === 'signup' && <small className="field-hint">At least 8 characters.</small>}</label>
          {mode === 'signup' ? <label>Workspace address<input required value={tenantSlug} onChange={e => {setSlugEdited(true); setTenantSlug(e.target.value.toLowerCase());}} placeholder="your-business" /><small className="field-hint">A short, unique name for your workspace. Use English letters.</small></label> : <details className="quiet-details"><summary>Need a specific workspace?</summary><label>Workspace address<input value={tenantSlug} onChange={e => setTenantSlug(e.target.value.toLowerCase())} placeholder="Optional" /><small className="field-hint">Leave blank to open your default workspace.</small></label></details>}
          {error && <div className="error-box" role="alert">{error}</div>}
          <button className="welcome-submit" disabled={loading}>{loading ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create my workspace'}</button>
          {mode === 'login' && <button type="button" className="text-button" onClick={onForgotPassword}>Forgot your password?</button>}
        </form>
      </section>
    </div>
  </main>;
}
