import { useEffect, useState, type FormEvent } from 'react';
import { createInvite, listInvites, revokeInvite, type TeamInvite } from '../services/api';

// Invite people by email (spec v1.2, Phase 1). They choose their own password from the link.
const STAFF_ROLES: Array<[string, string]> = [
  ['OPERATIONS_STAFF', 'Operations staff'],
  ['SUPERVISOR', 'Supervisor'],
  ['FINANCE', 'Finance'],
  ['CERTIFICATES', 'Certificates'],
];

export function TeamInvites({ tenantSlug, canInviteAdmins }: { tenantSlug: string; canInviteAdmins: boolean }) {
  const roles = canInviteAdmins ? [['BUSINESS_ADMIN', 'Administrator'] as [string, string], ...STAFF_ROLES] : STAFF_ROLES;
  const [rows, setRows] = useState<TeamInvite[]>([]);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState(STAFF_ROLES[0][0]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() { try { setRows(await listInvites(tenantSlug)); } catch (err) { setError(err instanceof Error ? err.message : 'Could not load invitations.'); } }
  useEffect(() => { void load(); }, [tenantSlug]);

  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null); setNotice(null);
    try {
      const sent = await createInvite(tenantSlug, email.trim(), role);
      setNotice(sent.email_sent === false ? 'Invitation saved, but the email could not be sent. Try again later.' : `Invitation sent to ${sent.email}.`);
      setEmail('');
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not send the invitation.'); }
  }

  async function revoke(id: number) {
    setError(null);
    try { await revokeInvite(tenantSlug, id); await load(); } catch (err) { setError(err instanceof Error ? err.message : 'Could not cancel the invitation.'); }
  }

  return <section className="card form-stack" aria-labelledby="invite-heading">
    <h3 id="invite-heading">Invite by email</h3>
    <p className="muted">The person gets a link to join this workspace and chooses their own password. Links work for 7 days.</p>
    <form className="form-stack" onSubmit={submit}>
      <label>Email address<input required type="email" value={email} onChange={e => setEmail(e.target.value)} /></label>
      <label>Role<select value={role} onChange={e => setRole(e.target.value)}>{roles.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></label>
      <button>Send invitation</button>
    </form>
    {notice && <p role="status" className="muted">{notice}</p>}
    {error && <div className="error-box" role="alert">{error}</div>}
    {rows.length > 0 && <table><thead><tr><th>Email</th><th>Role</th><th>Status</th><th></th></tr></thead><tbody>
      {rows.map(row => <tr key={row.id}><td>{row.email}</td><td>{row.role_code}</td><td>{row.status}</td><td>{row.status === 'pending' && <button className="secondary" onClick={() => revoke(row.id)}>Cancel</button>}</td></tr>)}
    </tbody></table>}
  </section>;
}
