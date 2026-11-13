import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { acceptInvite, confirmPasswordReset, requestPasswordReset, verifyEmail, type SessionState } from '../services/api';

// Pages reached from links in account emails (spec v1.2, Phase 1).
export type AccountLink = { kind: 'verify_email' | 'reset_password' | 'invite'; token: string };

export function readAccountLink(search: string): AccountLink | null {
  const params = new URLSearchParams(search);
  for (const kind of ['verify_email', 'reset_password', 'invite'] as const) {
    const token = params.get(kind);
    if (token) return { kind, token };
  }
  return null;
}

function Shell({ title, children }: { title: string; children: ReactNode }) {
  return <main className="auth-v2"><section className="card form-stack" style={{ maxWidth: 440, margin: '10vh auto' }}><h2>{title}</h2>{children}</section></main>;
}

export function AccountLinkPage({ link, onDone, onSignedIn }: { link: AccountLink; onDone: () => void; onSignedIn: (s: SessionState) => void }) {
  const [state, setState] = useState<'idle' | 'busy' | 'done' | 'error'>(link.kind === 'verify_email' ? 'busy' : 'idle');
  const [message, setMessage] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');

  useEffect(() => {
    if (link.kind !== 'verify_email') return;
    verifyEmail(link.token)
      .then(() => { setState('done'); setMessage('Your email address is confirmed.'); })
      .catch(err => { setState('error'); setMessage(err instanceof Error ? err.message : 'This link did not work.'); });
  }, [link]);

  async function submit(e: FormEvent) {
    e.preventDefault(); setState('busy'); setMessage('');
    try {
      if (link.kind === 'reset_password') {
        await confirmPasswordReset(link.token, password);
        setState('done'); setMessage('Your password is changed. Sign in with the new password.');
      } else {
        onSignedIn(await acceptInvite(link.token, password, fullName.trim() || undefined));
      }
    } catch (err) { setState('error'); setMessage(err instanceof Error ? err.message : 'Something went wrong.'); }
  }

  if (link.kind === 'verify_email') {
    return <Shell title="Email confirmation">
      <p role="status" className={state === 'error' ? 'error-box' : 'muted'}>{state === 'busy' ? 'Checking the link…' : message}</p>
      {state !== 'busy' && <button onClick={onDone}>Continue</button>}
    </Shell>;
  }
  const isInvite = link.kind === 'invite';
  return <Shell title={isInvite ? 'Join your team' : 'Choose a new password'}>
    {state === 'done' ? <><p role="status" className="muted">{message}</p><button onClick={onDone}>Go to sign in</button></> :
      <form className="form-stack" onSubmit={submit}>
        {isInvite && <p className="muted">New here? Enter your name and choose a password. Already have an account with this email? Leave the name empty and enter your current password.</p>}
        {isInvite && <label>Your name<input autoComplete="name" value={fullName} onChange={e => setFullName(e.target.value)} maxLength={255} /></label>}
        <label>{isInvite ? 'Password' : 'New password'}<input required type="password" minLength={8} autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
        {state === 'error' && <div className="error-box" role="alert">{message}</div>}
        <button disabled={state === 'busy'}>{state === 'busy' ? 'Please wait…' : isInvite ? 'Accept invitation' : 'Save password'}</button>
        <button type="button" className="secondary" onClick={onDone}>Cancel</button>
      </form>}
  </Shell>;
}

export function ForgotPassword({ onBack }: { onBack: () => void }) {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null);
    try { await requestPasswordReset(email.trim()); setSent(true); }
    catch (err) { setError(err instanceof Error ? err.message : 'Please try again.'); }
  }
  return <Shell title="Reset your password">
    {sent ? <p role="status" className="muted">If an account uses this address, we sent it a link to choose a new password. The link works for one hour.</p> :
      <form className="form-stack" onSubmit={submit}>
        <label>Email address<input required type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} /></label>
        {error && <div className="error-box" role="alert">{error}</div>}
        <button>Send reset link</button>
      </form>}
    <button type="button" className="secondary" onClick={onBack}>Back to sign in</button>
  </Shell>;
}
