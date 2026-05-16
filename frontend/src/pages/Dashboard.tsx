import { useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import {
  api,
  resolveAssetUrl,
  type Analytics,
  type Branch,
  type Broadcast,
  type BroadcastRecipient,
  type Channel,
  type ConversationDetail,
  type Customer,
  type FaqItem,
  type InboxItem,
  type IntentItem,
  type Readiness,
  type RuntimeClassification,
  type UatRun,
  type DeploymentChecklist,
  type DeploymentEnvironment,
  type WhatsappFixture,
  type AcceptanceSummary,
  type GoLiveBlockers,
  type HandoffPackage,
  type RoutingRule,
  type SessionState,
  type StaffUser,
  type TenantProfile,
  type Ticket,
} from '../services/api';

type Props = { session: SessionState; tenantSlug: string; onLogout: () => void };
type Tab = 'overview' | 'onboarding' | 'inbox' | 'settings' | 'staff' | 'knowledge' | 'channels' | 'tickets' | 'customers' | 'broadcasts' | 'audit' | 'dev';
type DevView = 'uat' | 'deployment' | 'handoff';

const tabs: Array<{ key: Tab; label: string }> = [
  { key: 'overview', label: 'Overview' },
  { key: 'onboarding', label: 'Onboarding' },
  { key: 'inbox', label: 'Inbox' },
  { key: 'settings', label: 'Settings' },
  { key: 'staff', label: 'Staff' },
  { key: 'knowledge', label: 'Knowledge & Responses' },
  { key: 'channels', label: 'Channels' },
  { key: 'tickets', label: 'Tickets' },
  { key: 'customers', label: 'Customers' },
  { key: 'broadcasts', label: 'Broadcasts' },
  { key: 'audit', label: 'Audit' },
];

function boxError(error: string | null) {
  return error ? <div className="error-box">{error}</div> : null;
}

function padTime(value: string) {
  return value.length === 5 ? value : '09:00';
}

function buildBranchHoursJson(morningEnabled: boolean, morningFrom: string, morningTo: string, eveningEnabled: boolean, eveningFrom: string, eveningTo: string) {
  const periods: Array<{ from: string; to: string }> = [];
  if (morningEnabled) periods.push({ from: padTime(morningFrom), to: padTime(morningTo) });
  if (eveningEnabled) periods.push({ from: padTime(eveningFrom), to: padTime(eveningTo) });
  return { periods };
}

function safeJson(text: string): Record<string, unknown> {
  if (!text.trim()) return {};
  const parsed = JSON.parse(text) as unknown;
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('JSON must be an object');
  return parsed as Record<string, unknown>;
}

function formatMessageTime(value?: string | null) {
  if (!value) return '';
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) return '';
  return new Intl.DateTimeFormat(undefined, {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).format(time);
}

function formatClockTime(value: string) {
  const [rawHour, rawMinute] = value.split(':');
  const hour = Number(rawHour);
  const minute = Number(rawMinute);
  if (Number.isNaN(hour) || Number.isNaN(minute)) return value;
  const suffix = hour >= 12 ? 'pm' : 'am';
  const twelveHour = hour % 12 || 12;
  return `${String(twelveHour).padStart(2, '0')}:${String(minute).padStart(2, '0')} ${suffix}`;
}

function initialsFromName(value: string) {
  const words = value.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return 'BA';
  return words.slice(0, 2).map((word) => word[0]?.toUpperCase() || '').join('') || 'BA';
}

function looksLikeImageFile(file: File) {
  if (['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) return true;
  const lower = file.name.toLowerCase();
  return ['.png', '.jpg', '.jpeg', '.webp'].some((ext) => lower.endsWith(ext));
}

export function Dashboard({ session, tenantSlug, onLogout }: Props) {
  const token = session.access_token;
  const [tab, setTab] = useState<Tab>('overview');
  const [tenant, setTenant] = useState<TenantProfile | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [inbox, setInbox] = useState<InboxItem[]>([]);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [staff, setStaff] = useState<StaffUser[]>([]);
  const [faq, setFaq] = useState<FaqItem[]>([]);
  const [intents, setIntents] = useState<IntentItem[]>([]);
  const [routing, setRouting] = useState<RoutingRule[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [broadcasts, setBroadcasts] = useState<Broadcast[]>([]);
  const [audit, setAudit] = useState<Array<{ id: number; action: string; entity_type: string; entity_id?: string | null; created_at?: string | null }>>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<number | null>(null);
  const [conversation, setConversation] = useState<ConversationDetail | null>(null);
  const [previewText, setPreviewText] = useState('السلام عليكم كم السعر');
  const [previewPhone, setPreviewPhone] = useState('0500000000');
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [devView, setDevView] = useState<DevView>('deployment');
  const [devMenuOpen, setDevMenuOpen] = useState(false);
  const [devMenuPosition, setDevMenuPosition] = useState<{ top: number; left: number } | null>(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [handoffToast, setHandoffToast] = useState<{ count: number; visible: boolean } | null>(null);
  const [confirmDeleteAccount, setConfirmDeleteAccount] = useState(false);
  const [deletingAccount, setDeletingAccount] = useState(false);
  const [deleteAccountPassword, setDeleteAccountPassword] = useState('');
  const previousHandoffIdsRef = useRef<number[]>([]);
  const handoffToastTimerRef = useRef<number | null>(null);
  const devButtonRef = useRef<HTMLButtonElement | null>(null);

  const tenantName = tenant?.display_name || session.memberships.find((m) => m.tenant_slug === tenantSlug)?.tenant_name || tenantSlug;
  const logoUrl = resolveAssetUrl(tenant?.brand.logo_url);
  const hasComplaintAlert = inbox.some((row) => row.last_intent === 'COMPLAINT' && row.state !== 'CLOSED');
  const activePageKey = tab === 'dev' ? `dev-${devView}` : tab;
  const currentPageTitle = tab === 'dev'
    ? devView === 'uat' ? 'UAT tests' : devView === 'handoff' ? 'Final handoff' : 'Deployment'
    : tabs.find((item) => item.key === tab)?.label || 'Dashboard';
  const primaryTabs = tabs.slice(0, 3);
  const workspaceTabs = tabs.slice(3, 10);
  const systemTabs = tabs.slice(10);

  function selectTab(nextTab: Tab) {
    setTab(nextTab);
    setMobileNavOpen(false);
  }

  function selectDevTab() {
    setTab('dev');
    if (window.innerWidth <= 980) {
      setDevMenuOpen(false);
      setMobileNavOpen(false);
      return;
    }
    setDevMenuOpen((current) => !current);
  }

  function updateInboxState(rows: InboxItem[]) {
    setInbox(rows);
    const currentHandoffIds = rows.filter((row) => row.state === 'HUMAN_HANDOFF').map((row) => row.id).sort((a, b) => a - b);
    const previousIds = previousHandoffIdsRef.current;
    const hasNewHandoff = currentHandoffIds.some((id) => !previousIds.includes(id));
    if (currentHandoffIds.length > 0 && hasNewHandoff) {
      if (handoffToastTimerRef.current !== null) {
        window.clearTimeout(handoffToastTimerRef.current);
      }
      setHandoffToast({ count: currentHandoffIds.length, visible: true });
      handoffToastTimerRef.current = window.setTimeout(() => {
        setHandoffToast((current) => current ? { ...current, visible: false } : null);
      }, 3800);
    }
    previousHandoffIdsRef.current = currentHandoffIds;
  }

  async function refreshAll() {
    setLoading(true);
    setError(null);
    try {
      const [t, r, a, i, b, s, f, it, rr, ch, tk, c, br] = await Promise.all([
        api.tenant(token, tenantSlug),
        api.readiness(token, tenantSlug),
        api.analytics(token, tenantSlug),
        api.inbox(token, tenantSlug),
        api.branches(token, tenantSlug),
        api.staff(token, tenantSlug),
        api.faq(token, tenantSlug),
        api.intents(token, tenantSlug),
        api.routingRules(token, tenantSlug),
        api.channels(token, tenantSlug),
        api.tickets(token, tenantSlug),
        api.customers(token, tenantSlug),
        api.broadcasts(token, tenantSlug),
      ]);
      setTenant(t); setReadiness(r); setAnalytics(a); updateInboxState(i); setBranches(b); setStaff(s); setFaq(f); setIntents(it); setRouting(rr); setChannels(ch); setTickets(tk); setCustomers(c); setBroadcasts(br);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  }

  async function loadAudit() {
    try {
      const rows = await api.auditLogs(token, tenantSlug);
      setAudit(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load audit logs');
    }
  }

  async function openConversation(id: number) {
    setSelectedConversationId(id);
    setTab('inbox');
    setConversation(await api.conversation(token, tenantSlug, id));
  }

  async function refreshInboxLive() {
    const rows = await api.inbox(token, tenantSlug);
    updateInboxState(rows);
    if (selectedConversationId !== null) {
      setConversation(await api.conversation(token, tenantSlug, selectedConversationId));
    }
  }

  async function runPreview() {
    setError(null);
    try {
      const result = await api.previewInbound(token, tenantSlug, previewText, previewPhone);
      setPreview(result.decision);
      await refreshAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Preview failed');
    }
  }

  useEffect(() => { void refreshAll(); }, []);
  useEffect(() => { if (tab === 'audit') void loadAudit(); }, [tab]);
  useEffect(() => {
    if (tab !== 'dev') setDevMenuOpen(false);
  }, [tab]);
  useEffect(() => {
    if (!mobileNavOpen) return;
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMobileNavOpen(false);
        setDevMenuOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [mobileNavOpen]);
  useEffect(() => {
    if (!mobileNavOpen) return;
    const onResize = () => {
      if (window.innerWidth > 980) setMobileNavOpen(false);
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [mobileNavOpen]);
  useEffect(() => {
    if (!devMenuOpen || !devButtonRef.current) return;
    const updatePosition = () => {
      if (!devButtonRef.current) return;
      const rect = devButtonRef.current.getBoundingClientRect();
      setDevMenuPosition({
        top: rect.top - 6,
        left: rect.right + 16,
      });
    };
    updatePosition();
    window.addEventListener('resize', updatePosition);
    return () => window.removeEventListener('resize', updatePosition);
  }, [devMenuOpen]);
  useEffect(() => {
    void refreshInboxLive();
    const timer = window.setInterval(() => { void refreshInboxLive(); }, 4000);
    return () => window.clearInterval(timer);
  }, [tab, selectedConversationId]);
  useEffect(() => () => {
    if (handoffToastTimerRef.current !== null) {
      window.clearTimeout(handoffToastTimerRef.current);
    }
  }, []);

  return (
    <main className={`app-shell${mobileNavOpen ? ' mobile-nav-open' : ''}`}>
      <header className="mobile-shell-bar">
        <button className="mobile-menu-button" type="button" aria-label={mobileNavOpen ? 'Close navigation menu' : 'Open navigation menu'} aria-expanded={mobileNavOpen} onClick={() => { setMobileNavOpen((current) => !current); if (mobileNavOpen) setDevMenuOpen(false); }}>
          <span aria-hidden="true" />
          <span aria-hidden="true" />
          <span aria-hidden="true" />
        </button>
        <div className="mobile-shell-title">
          <strong>{currentPageTitle}</strong>
          <span>{tenantSlug}</span>
        </div>
      </header>
      <button className="mobile-nav-backdrop" type="button" aria-label="Close navigation menu" aria-hidden={!mobileNavOpen} tabIndex={mobileNavOpen ? 0 : -1} onClick={() => { setMobileNavOpen(false); setDevMenuOpen(false); }} />
      <aside className="sidebar" aria-label="Dashboard navigation">
        <div className="brand-lockup">
          <div className="brand-mark">
            {logoUrl
              ? <img src={logoUrl} alt={`${tenantName} logo`} className="brand-mark-image" />
              : initialsFromName(tenantName)}
          </div>
          <div className="brand-copy">
            <span className="brand-kicker">[Workspace]</span>
            <h2>Agent Platform</h2>
            <p>{tenantSlug}</p>
            <span className="brand-micro">Control node / live</span>
          </div>
        </div>
        <nav>
          <div className="nav-section">
            <span className="nav-section-label">Operate</span>
            {primaryTabs.map((t) => <button key={t.key} className={tab === t.key ? 'active' : ''} aria-current={tab === t.key ? 'page' : undefined} onClick={() => selectTab(t.key)}><span className="nav-button-label">{t.label}{t.key === 'inbox' && hasComplaintAlert && <span className="nav-alert-dot" aria-hidden="true" />}</span></button>)}
          </div>
          <div className="nav-section">
            <span className="nav-section-label">Configure</span>
            {workspaceTabs.map((t) => <button key={t.key} className={tab === t.key ? 'active' : ''} aria-current={tab === t.key ? 'page' : undefined} onClick={() => selectTab(t.key)}><span className="nav-button-label">{t.label}</span></button>)}
          </div>
          <div className="nav-section">
            <span className="nav-section-label">System</span>
            {systemTabs.map((t) => <button key={t.key} className={tab === t.key ? 'active' : ''} aria-current={tab === t.key ? 'page' : undefined} onClick={() => selectTab(t.key)}><span className="nav-button-label">{t.label}</span></button>)}
            <div className="sidebar-flyout-wrap">
              <button ref={devButtonRef} className={tab === 'dev' ? 'active' : ''} aria-current={tab === 'dev' ? 'page' : undefined} onClick={selectDevTab}>
                <span className="nav-button-label">Dev</span>
              </button>
            </div>
          </div>
        </nav>
        <div className="sidebar-actions">
          <button className="secondary" onClick={refreshAll}>Refresh</button>
          <button className="secondary" onClick={onLogout}>Log out</button>
          <button onClick={() => { setDeleteAccountPassword(''); setConfirmDeleteAccount(true); }} disabled={deletingAccount}>Delete account</button>
        </div>
      </aside>
      {devMenuOpen && devMenuPosition && <div className="dev-menu-overlay" onClick={() => setDevMenuOpen(false)}>
        <div className="dev-flyout-panel" style={{ top: `${devMenuPosition.top}px`, left: `${devMenuPosition.left}px` }} onClick={(e) => e.stopPropagation()}>
          <button className={tab === 'dev' && devView === 'deployment' ? 'active' : ''} onClick={() => { setDevView('deployment'); setTab('dev'); setDevMenuOpen(false); setMobileNavOpen(false); }}>
            Deployment
          </button>
          <button className={tab === 'dev' && devView === 'uat' ? 'active' : ''} onClick={() => { setDevView('uat'); setTab('dev'); setDevMenuOpen(false); setMobileNavOpen(false); }}>
            UAT tests
          </button>
          <button className={tab === 'dev' && devView === 'handoff' ? 'active' : ''} onClick={() => { setDevView('handoff'); setTab('dev'); setDevMenuOpen(false); setMobileNavOpen(false); }}>
            Final handoff
          </button>
        </div>
      </div>}
      <section className="content">
        {handoffToast?.visible && <div className="handoff-toast" role="status" aria-live="polite"><strong>Client waiting in handoff</strong><span>{handoffToast.count > 1 ? `${handoffToast.count} conversations need attention` : 'A conversation needs your response'}</span></div>}
        <header className="topbar">
          <div><p className="eyebrow">Tenant control plane / {currentPageTitle}</p><h1>{tenantName}</h1><p className="muted">Logged in as {session.user.full_name}</p></div>
          <div className="topbar-meta">
            <div className="workspace-pill"><span>Workspace</span><strong>{tenantSlug}</strong></div>
            <div className="user-pill">{loading ? 'Loading...' : tenant?.status || 'active'}</div>
          </div>
        </header>
        {boxError(error)}
        <div key={activePageKey} className="page-transition">
          {tab === 'overview' && <Overview tenant={tenant} token={token} tenantSlug={tenantSlug} readiness={readiness} analytics={analytics} previewText={previewText} setPreviewText={setPreviewText} previewPhone={previewPhone} setPreviewPhone={setPreviewPhone} runPreview={runPreview} preview={preview} publish={async () => { await api.publish(token, tenantSlug); await refreshAll(); }} reload={refreshAll} />}
          {tab === 'onboarding' && <OnboardingWizard token={token} tenantSlug={tenantSlug} readiness={readiness} reload={refreshAll} />}
          {tab === 'inbox' && <Inbox rows={inbox} selectedConversationId={selectedConversationId} conversation={conversation} openConversation={openConversation} handoff={async (id) => { await api.handoff(token, tenantSlug, id); await openConversation(id); await refreshAll(); }} resolve={async (id) => { await api.resolve(token, tenantSlug, id); await openConversation(id); await refreshAll(); }} reopen={async (id) => { await api.reopen(token, tenantSlug, id); await openConversation(id); await refreshAll(); }} sendReply={async (id, text) => { await api.replyToConversation(token, tenantSlug, id, text); await openConversation(id); await refreshAll(); }} />}
          {tab === 'settings' && <Settings tenant={tenant} branches={branches} token={token} tenantSlug={tenantSlug} reload={refreshAll} />}
          {tab === 'staff' && <Staff rows={staff} token={token} tenantSlug={tenantSlug} reload={refreshAll} />}
          {tab === 'knowledge' && <KnowledgeResponses faq={faq} intents={intents} routing={routing} token={token} tenantSlug={tenantSlug} reload={refreshAll} />}
          {tab === 'channels' && <Channels rows={channels} token={token} tenantSlug={tenantSlug} reload={refreshAll} />}
          {tab === 'tickets' && <Tickets rows={tickets} token={token} tenantSlug={tenantSlug} reload={refreshAll} openConversation={openConversation} />}
          {tab === 'customers' && <Customers rows={customers} />}
          {tab === 'broadcasts' && <Broadcasts rows={broadcasts} token={token} tenantSlug={tenantSlug} reload={refreshAll} />}
          {tab === 'audit' && <SimpleTable title="Audit logs" rows={audit} />}
          {tab === 'dev' && devView === 'uat' && <UatPanel token={token} tenantSlug={tenantSlug} />}
          {tab === 'dev' && devView === 'deployment' && <DeploymentPanel token={token} tenantSlug={tenantSlug} />}
          {tab === 'dev' && devView === 'handoff' && <HandoffPanel token={token} tenantSlug={tenantSlug} />}
        </div>
      </section>
      {confirmDeleteAccount && <div className="confirm-overlay" role="dialog" aria-modal="true">
        <div className="confirm-card">
          <h3>Delete this account and all data?</h3>
          <p className="muted">{tenantName} · {tenantSlug}</p>
          <p className="muted">This permanently deletes this business account and its tenant data, including conversations, settings, branches, bot responses, tickets, broadcasts, and channels. This cannot be undone.</p>
          <label>
            Enter your password to confirm
            <input
              type="password"
              placeholder="Current account password"
              value={deleteAccountPassword}
              onChange={(e) => setDeleteAccountPassword(e.target.value)}
              disabled={deletingAccount}
            />
          </label>
          <div className="button-row">
            <button
              onClick={async () => {
                if (!deleteAccountPassword.trim()) {
                  setError('Enter your password to delete this account.');
                  return;
                }
                setDeletingAccount(true);
                try {
                  setError(null);
                  await api.deleteAccount(token, tenantSlug, deleteAccountPassword);
                  onLogout();
                } catch (err) {
                  setError(err instanceof Error ? err.message : 'Failed to delete account');
                } finally {
                  setDeletingAccount(false);
                }
              }}
              disabled={deletingAccount || !deleteAccountPassword.trim()}
            >
              {deletingAccount ? 'Deleting...' : 'Delete account'}
            </button>
            <button className="secondary" onClick={() => { setConfirmDeleteAccount(false); setDeleteAccountPassword(''); }} disabled={deletingAccount}>Cancel</button>
          </div>
        </div>
      </div>}
    </main>
  );
}

function Overview({ tenant, token, tenantSlug, readiness, analytics, previewText, setPreviewText, previewPhone, setPreviewPhone, runPreview, preview, publish, reload }: { tenant: TenantProfile | null; token: string; tenantSlug: string; readiness: Readiness | null; analytics: Analytics | null; previewText: string; setPreviewText: (v: string) => void; previewPhone: string; setPreviewPhone: (v: string) => void; runPreview: () => Promise<void>; preview: Record<string, unknown> | null; publish: () => Promise<void>; reload: () => Promise<void> }) {
  const [uploadingLogo, setUploadingLogo] = useState(false);
  const [logoMessage, setLogoMessage] = useState<string | null>(null);
  const logoUrl = resolveAssetUrl(tenant?.brand.logo_url);

  async function uploadLogo(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setLogoMessage(null);
    if (!looksLikeImageFile(file)) {
      setLogoMessage('Please choose a PNG, JPEG, or WebP image.');
      event.target.value = '';
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      setLogoMessage('Please keep the image under 2 MB.');
      event.target.value = '';
      return;
    }
    try {
      setUploadingLogo(true);
      await api.uploadProfileLogo(token, tenantSlug, file);
      await reload();
      setLogoMessage('Profile picture updated.');
    } catch (error) {
      setLogoMessage(error instanceof Error ? error.message : 'Failed to upload profile picture.');
    } finally {
      setUploadingLogo(false);
      event.target.value = '';
    }
  }

  async function removeLogo() {
    setLogoMessage(null);
    try {
      setUploadingLogo(true);
      await api.updateProfile(token, tenantSlug, { logo_url: '' });
      await reload();
      setLogoMessage('Profile picture removed.');
    } catch (error) {
      setLogoMessage(error instanceof Error ? error.message : 'Failed to remove profile picture.');
    } finally {
      setUploadingLogo(false);
    }
  }

  return <>
    <section className="grid cards">
      <div className="card"><p className="eyebrow">Readiness</p><h3>{readiness?.is_ready ? 'Ready to publish' : 'Needs setup'}</h3><div className="checklist">{readiness?.items.map((i) => <div key={i.key} className={i.passed ? 'pass' : 'fail'}><span>{i.passed ? '✓' : '•'}</span>{i.label}</div>)}</div><button onClick={publish}>Publish workspace</button></div>
      <div className="card metrics-card">
        <p className="eyebrow">Metrics</p>
        <div className="metric-grid">{analytics && Object.entries(analytics).filter(([, v]) => typeof v === 'number').map(([k, v]) => <div className="metric" key={k}><strong>{v as number}</strong><span>{k}</span></div>)}</div>
        <div className="logo-upload-panel">
          <div className="logo-upload-preview">
            <div className="brand-mark overview-brand-mark">
              {logoUrl
                ? <img src={logoUrl} alt={`${tenant?.display_name || tenantSlug} logo`} className="brand-mark-image" />
                : initialsFromName(tenant?.display_name || tenantSlug)}
            </div>
            <div>
              <strong>Profile picture</strong>
              <span>Updates the square logo beside Agent Platform.</span>
            </div>
          </div>
          <div className="logo-upload-actions">
            <label className="logo-upload-button">
              <input type="file" accept="image/png,image/jpeg,image/webp" onChange={uploadLogo} disabled={uploadingLogo} />
              <span>{uploadingLogo ? 'Uploading image...' : 'Upload image'}</span>
            </label>
            {tenant?.brand.logo_url && <button type="button" className="secondary logo-remove-button" onClick={() => void removeLogo()} disabled={uploadingLogo}>Remove</button>}
          </div>
          {logoMessage && <p className="logo-upload-message">{logoMessage}</p>}
        </div>
      </div>
    </section>
    <section className="card"><p className="eyebrow">Runtime preview</p><h3>Test tenant-scoped rule engine</h3><div className="preview-row"><input value={previewPhone} onChange={(e) => setPreviewPhone(e.target.value)} /><input value={previewText} onChange={(e) => setPreviewText(e.target.value)} /><button onClick={runPreview}>Run preview</button></div>{preview && <pre>{JSON.stringify(preview, null, 2)}</pre>}</section>
  </>;
}

function OnboardingWizard({ token, tenantSlug, readiness, reload }: { token: string; tenantSlug: string; readiness: Readiness | null; reload: () => Promise<void> }) {
  const [step, setStep] = useState(1);
  const [displayName, setDisplayName] = useState('');
  const [timezone, setTimezone] = useState('');
  const [defaultLang, setDefaultLang] = useState('');
  const [message, setMessage] = useState('كم السعر وهل فيه تسجيل؟');
  const [analysis, setAnalysis] = useState<RuntimeClassification | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const readinessItems = readiness?.items || [];
  const completedCount = readinessItems.filter((item) => item.passed).length;
  const totalCount = readinessItems.length;
  const completionPercent = totalCount ? Math.round((completedCount / totalCount) * 100) : 0;
  const setupSteps = [
    { number: 1, title: 'Business account', detail: 'Profile and workspace identity.' },
    { number: 2, title: 'Branches & hours', detail: 'Locations and availability.' },
    { number: 3, title: 'Staff & roles', detail: 'Team access and ownership.' },
    { number: 4, title: 'FAQ knowledge base', detail: 'Reusable business answers.' },
    { number: 5, title: 'Intents & routing', detail: 'Classification and handoff.' },
    { number: 6, title: 'Sample messages', detail: 'Test common customer asks.' },
    { number: 7, title: 'Channel setup', detail: 'Connect customer channels.' },
    { number: 8, title: 'Review readiness', detail: 'Resolve launch blockers.' },
    { number: 9, title: 'Publish workspace', detail: 'Launch the private agent.' },
  ];
  const currentStepTitle = setupSteps.find((item) => item.number === step)?.title || 'Workspace details';
  async function saveStep(e: FormEvent) {
    e.preventDefault();
    const data = {
      display_name: displayName,
      timezone,
      default_lang: defaultLang,
    };
    await api.saveOnboardingStep(token, tenantSlug, step, data);
    setSaved(`Saved onboarding step ${step}`);
    await reload();
  }
  async function classify() {
    const result = await api.runtimeClassify(token, tenantSlug, message);
    setAnalysis(result);
  }
  return <section className="onboarding-shell">
    <header className="onboarding-hero card">
      <div>
        <p className="eyebrow">Self-serve onboarding</p>
        <h3>Configure a private agent workspace</h3>
        <p className="muted">Save each setup draft, confirm readiness, then publish when the workspace is prepared for real customer conversations.</p>
      </div>
      <div className="onboarding-progress-card" aria-label={`${completionPercent}% onboarding readiness`}>
        <span>Readiness</span>
        <strong>{completionPercent}%</strong>
        <div className="onboarding-progress-track"><i style={{ width: `${completionPercent}%` }} /></div>
        <small>{completedCount} of {totalCount || 0} checks complete</small>
      </div>
    </header>

    <div className="onboarding-steps" aria-label="Onboarding steps">
      {setupSteps.map((item) => {
        const isCurrent = step === item.number;
        const isDone = item.number < step || (item.number === 4 && totalCount > 0 && completedCount === totalCount);
        return <button type="button" key={item.number} className={isCurrent ? 'active' : isDone ? 'done' : ''} onClick={() => setStep(item.number)}>
          <span>{isDone ? '✓' : item.number}</span>
          <strong>{item.title}</strong>
          <small>{item.detail}</small>
        </button>;
      })}
    </div>

    <section className="onboarding-layout">
      <form className="card form-stack onboarding-form-card" onSubmit={saveStep}>
        <div className="onboarding-card-head">
          <div>
            <p className="eyebrow">Draft setup</p>
            <h3>Step {step}: {currentStepTitle}</h3>
          </div>
          <span className="onboarding-required-badge">Required fields</span>
        </div>
        <div className="onboarding-form-grid">
          <label>Step number <span className="required-dot">*</span><input type="number" min={1} max={9} value={step} onChange={(e) => setStep(Number(e.target.value))} /></label>
          <label>Display name <span className="required-dot">*</span><input placeholder="Your business name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} /></label>
          <label>Timezone <span className="required-dot">*</span><input placeholder="Asia/Riyadh" value={timezone} onChange={(e) => setTimezone(e.target.value)} /></label>
          <label>Default language <span className="required-dot">*</span><input placeholder="ar" value={defaultLang} onChange={(e) => setDefaultLang(e.target.value)} /></label>
        </div>
        <div className="onboarding-actions">
          <button>Save step draft</button>
          <span className="field-hint">Draft saves preserve the current step data for this tenant workspace.</span>
        </div>
        {saved && <p className="success-text onboarding-save-message">{saved}</p>}
      </form>

      <aside className="card onboarding-review-card">
        <div className="onboarding-card-head">
          <div>
            <p className="eyebrow">Review readiness</p>
            <h3>Launch checklist</h3>
          </div>
          <span className={totalCount > 0 && completedCount === totalCount ? 'pass-pill' : 'fail-pill'}>{totalCount > 0 && completedCount === totalCount ? 'Ready' : 'Incomplete'}</span>
        </div>
        <div className="checklist onboarding-checklist">
          {readinessItems.length === 0 && <div className="fail"><span>•</span>No readiness checks loaded yet.</div>}
          {readinessItems.map((i) => <div key={i.key} className={i.passed ? 'pass' : 'fail'}><span>{i.passed ? '✓' : '•'}</span><strong>{i.label}</strong></div>)}
        </div>
      </aside>
    </section>

    <section className="card form-stack onboarding-runtime-card">
      <div className="onboarding-card-head">
        <div>
          <p className="eyebrow">Runtime engine proof</p>
          <h3>Classify without creating a message</h3>
        </div>
        <span className="onboarding-required-badge">Test mode</span>
      </div>
      <label>Customer message<input value={message} onChange={(e) => setMessage(e.target.value)} /><small className="field-hint">Use a sample customer message to preview intent and routing behavior.</small></label>
      <div className="onboarding-actions">
        <button onClick={classify}>Classify message</button>
        <span className="field-hint">This does not create an inbox conversation.</span>
      </div>
      {analysis && <RuntimeChatPreview message={message} analysis={analysis} />}
    </section>
  </section>;
}

function RuntimeChatPreview({ message, analysis }: { message: string; analysis: RuntimeClassification }) {
  const intentCode = String((analysis.intent as Record<string, unknown>)?.intent_code ?? 'UNKNOWN');
  const confidence = Number((analysis.intent as Record<string, unknown>)?.confidence ?? 0);
  const action = String((analysis.route as Record<string, unknown>)?.action ?? 'AUTO_REPLY');
  const ownerRole = String((analysis.route as Record<string, unknown>)?.owner_role ?? 'OPERATIONS_STAFF');
  const insideHours = analysis.inside_working_hours ? 'Inside working hours' : 'Outside working hours';

  return <div className="mini-chat-card">
    <div className="mini-chat-head">
      <span>Inbox preview</span>
      <small>{insideHours}</small>
    </div>
    <div className="mini-chat-body">
      <div className="mini-chat-bubble outbound">
        <small>Customer</small>
        <p>{message || 'Type a message to test the inbox flow.'}</p>
      </div>
      <div className="mini-chat-bubble inbound">
        <small>Assistant route</small>
        <p>{action.replace(/_/g, ' ')}</p>
      </div>
    </div>
    <div className="mini-chat-meta">
      <div>
        <small>Intent</small>
        <strong>{intentCode}</strong>
      </div>
      <div>
        <small>Confidence</small>
        <strong>{confidence}</strong>
      </div>
      <div>
        <small>Owner</small>
        <strong>{ownerRole}</strong>
      </div>
    </div>
  </div>;
}

function Inbox({ rows, selectedConversationId, conversation, openConversation, handoff, resolve, reopen, sendReply }: { rows: InboxItem[]; selectedConversationId: number | null; conversation: ConversationDetail | null; openConversation: (id: number) => Promise<void>; handoff: (id: number) => Promise<void>; resolve: (id: number) => Promise<void>; reopen: (id: number) => Promise<void>; sendReply: (id: number, text: string) => Promise<void> }) {
  const [replyText, setReplyText] = useState('');
  const [sendingReply, setSendingReply] = useState(false);
  const [replyError, setReplyError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const replyInputRef = useRef<HTMLTextAreaElement | null>(null);
  const hasComplaintMarker = (metadata?: Record<string, unknown>, lastIntent?: string | null, state?: string) => state !== 'CLOSED' && (lastIntent === 'COMPLAINT' || metadata?.has_open_complaint === true);
  const displayCustomer = (item: InboxItem | ConversationDetail) => {
    if ('customer' in item) return item.customer.name || item.customer.phone || 'Customer';
    return item.customer_name || item.customer_phone || 'Customer';
  };
  const messageLabel = (direction: string) => direction === 'outbound' ? 'Team reply' : direction === 'system' ? 'System' : 'Customer';
  const sortedRows = [...rows].sort((a, b) => {
    const aTime = a.updated_at ? Date.parse(a.updated_at) : 0;
    const bTime = b.updated_at ? Date.parse(b.updated_at) : 0;
    return bTime - aTime || b.id - a.id;
  });

  useEffect(() => {
    setReplyText('');
    setReplyError(null);
  }, [conversation?.conversation.id]);

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [conversation?.messages.length, conversation?.conversation.id]);

  async function submitReply() {
    if (!conversation || sendingReply) return;
    const text = replyText.trim();
    if (!text) return;
    setSendingReply(true);
    setReplyError(null);
    try {
      await sendReply(conversation.conversation.id, text);
      setReplyText('');
      window.requestAnimationFrame(() => {
        replyInputRef.current?.focus();
      });
    } catch (err) {
      setReplyError(err instanceof Error ? err.message : 'Failed to send reply');
    } finally {
      setSendingReply(false);
    }
  }

  function onReplyKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void submitReply();
    }
  }

  return <section className="split inbox-layout">
    <div className="card inbox-panel inbox-list-panel">
      <div className="inbox-panel-head">
        <div><p className="eyebrow">Inbox</p><h3>Conversations</h3></div>
        <span className="inbox-count">{rows.length}</span>
      </div>
      {rows.length === 0 && <div className="inbox-empty-state"><strong>No conversations yet</strong><p>New customer messages will appear here when the workspace receives them.</p></div>}
      <div className="list inbox-list">
        {sortedRows.map((r, index) => {
          const isActive = selectedConversationId === r.id;
          const owner = r.owner_ref || r.owner_type || 'unassigned';
          return <button className={`list-row inbox-row inbox-row-animated${isActive ? ' active' : ''}`} aria-current={isActive ? 'true' : undefined} style={{ animationDelay: `${Math.min(index * 40, 240)}ms` }} key={r.id} onClick={() => void openConversation(r.id)}>
            <span className="inbox-row-top">
              <span className="inbox-customer">
                <strong>{displayCustomer(r)}</strong>
                <small>{r.customer_phone}</small>
              </span>
              <span className="inbox-time">{formatMessageTime(r.updated_at)}</span>
            </span>
            <span className="inbox-preview">{r.last_message || 'No messages yet'}</span>
            <span className="inbox-badges">{hasComplaintMarker(r.metadata_json, r.last_intent, r.state) && <span className="priority-dot" aria-hidden="true" />}<span className="inbox-pill">{r.state}</span><span className="inbox-pill secondary-pill">{r.last_intent || 'UNKNOWN'}</span><span className="inbox-pill secondary-pill">Owner: {owner}</span></span>
          </button>;
        })}
      </div>
    </div>
    <div className="card detail-card inbox-panel conversation-panel">
      <p className="eyebrow">Conversation view</p>
      {conversation ? <>
        <div className="conversation-head">
          <div>
            <h3>{displayCustomer(conversation)}</h3>
            <p>{conversation.customer.phone}{conversation.customer.email ? ` / ${conversation.customer.email}` : ''}</p>
          </div>
          <div className="inbox-badges conversation-status">{hasComplaintMarker(conversation.conversation.metadata_json, conversation.conversation.last_intent, conversation.conversation.state) && <span className="priority-dot" aria-hidden="true" />}<span className="inbox-pill">{conversation.conversation.state}</span><span className="inbox-pill secondary-pill">{conversation.conversation.channel_type}</span></div>
        </div>
        <div className="conversation-context-grid">
          <div><small>Intent</small><strong>{conversation.conversation.last_intent || 'UNKNOWN'}</strong></div>
          <div><small>Owner</small><strong>{conversation.conversation.owner_ref || conversation.conversation.owner_type || 'unassigned'}</strong></div>
          <div><small>Customer</small><strong>{conversation.customer.opt_in ? 'Opted in' : 'Opt-out or unknown'}</strong></div>
        </div>
        <div className="button-row inbox-action-row"><button onClick={() => void handoff(conversation.conversation.id)}>Handoff</button><button className="secondary" onClick={() => void resolve(conversation.conversation.id)}>Resolve</button><button className="secondary" onClick={() => void reopen(conversation.conversation.id)}>Reset bot</button></div>
        <div ref={scrollRef} className="timeline conversation-scroll">
          {conversation.messages.length === 0 && <div className="inbox-empty-state compact"><strong>No messages yet</strong><p>The conversation timeline will appear here.</p></div>}
          {conversation.messages.map((m) => <div key={m.id} className={`message ${m.direction}`}>
            <b>{messageLabel(m.direction)}</b>
            <p>{m.text || ''}</p>
            <div className="message-meta"><small>{m.intent_code || 'No intent'}</small><span className="message-time">{formatMessageTime(m.created_at)}</span></div>
          </div>)}
        </div>
        <div className="reply-composer-wrap">{replyError && <div className="reply-error">{replyError}</div>}<div className="reply-composer"><textarea ref={replyInputRef} className="reply-input" placeholder="Write a clear reply to the customer..." value={replyText} onChange={(e) => setReplyText(e.target.value)} onKeyDown={onReplyKeyDown} disabled={sendingReply} rows={1} /><button className="send-chip" onClick={() => void submitReply()} disabled={sendingReply || !replyText.trim()} aria-label="Send reply">↑</button></div><small className="reply-hint">Press Enter to send. Use Shift+Enter for a new line.</small></div>
      </> : <div className="inbox-empty-state conversation-empty"><strong>Select a conversation</strong><p>Choose a customer thread from the inbox to review messages, routing context, and actions.</p></div>}
    </div>
  </section>;
}

function UatPanel({ token, tenantSlug }: { token: string; tenantSlug: string }) {
  const [run, setRun] = useState<UatRun | null>(null);
  const [customMessage, setCustomMessage] = useState('هل المعهد معتمد؟');
  const [customExpectedIntent, setCustomExpectedIntent] = useState('ACCREDITATION');
  const [customResult, setCustomResult] = useState<Record<string, unknown> | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  async function runAll() {
    setStatus('Running academy UAT cases...');
    const result = await api.runAcademyUat(token, tenantSlug);
    setRun(result);
    setStatus(`Finished: ${result.passed}/${result.total} passed`);
  }

  async function runCustom(e: FormEvent) {
    e.preventDefault();
    const result = await api.customUat(token, tenantSlug, {
      message: customMessage,
      expected_intent: customExpectedIntent || null,
      expected_action: null,
    });
    setCustomResult(result as unknown as Record<string, unknown>);
  }

  return <section className="grid two">
    <div className="card wide">
      <p className="eyebrow">Academy Tenant #1 UAT</p>
      <h3>Run safe scenario checks</h3>
      <p className="muted">This checks tenant-scoped intent and routing results without creating customer messages.</p>
      <button onClick={runAll}>Run academy UAT cases</button>
      {status && <p className="success-text">{status}</p>}
      {run && <div className="uat-summary"><strong>{run.passed}/{run.total}</strong><span>passed · {run.mode}</span></div>}
      {run && <div className="list">{run.results.map((r) => <div className="list-card" key={r.id}>
        <div className="row-between"><b>{r.id}</b><span className={r.passed ? 'pill pass-pill' : 'pill fail-pill'}>{r.passed ? 'pass' : 'check'}</span></div>
        <p>{r.message}</p>
        <small>expected {r.expected_intent}/{r.expected_action} · actual {r.actual_intent}/{r.actual_action} · confidence {Math.round(r.confidence * 100)}%</small>
        {r.matched_phrases.length > 0 && <small>matched: {r.matched_phrases.join(', ')}</small>}
      </div>)}</div>}
    </div>
    <form className="card form-stack" onSubmit={runCustom}>
      <p className="eyebrow">Custom tenant test</p>
      <h3>Try one message</h3>
      <label>Message<input value={customMessage} onChange={(e) => setCustomMessage(e.target.value)} /></label>
      <label>Expected intent<input value={customExpectedIntent} onChange={(e) => setCustomExpectedIntent(e.target.value)} /></label>
      <button>Run custom test</button>
      {customResult && <pre>{JSON.stringify(customResult, null, 2)}</pre>}
    </form>
  </section>;
}

function DeploymentPanel({ token, tenantSlug }: { token: string; tenantSlug: string }) {
  const [checklist, setChecklist] = useState<DeploymentChecklist | null>(null);
  const [environment, setEnvironment] = useState<DeploymentEnvironment | null>(null);
  const [goLive, setGoLive] = useState<Record<string, unknown> | null>(null);
  const [fixtures, setFixtures] = useState<WhatsappFixture[]>([]);
  const [simulation, setSimulation] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadDeployment() {
    setError(null);
    try {
      const [c, e, g, f] = await Promise.all([
        api.deploymentChecklist(token, tenantSlug),
        api.deploymentEnvironment(token, tenantSlug),
        api.whatsappGoLivePackage(token, tenantSlug),
        api.whatsappFixtures(token, tenantSlug),
      ]);
      setChecklist(c);
      setEnvironment(e);
      setGoLive(g as unknown as Record<string, unknown>);
      setFixtures(f.cases);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load deployment status');
    }
  }

  useEffect(() => { void loadDeployment(); }, []);

  async function simulate(caseId: string) {
    const result = await api.simulateWhatsappFixture(token, tenantSlug, caseId);
    setSimulation(result as unknown as Record<string, unknown>);
  }

  return <section className="grid two">
    <div className="card wide">
      <p className="eyebrow">Deployment readiness</p>
      <h3>Staging / production checklist</h3>
      <button onClick={loadDeployment}>Refresh deployment status</button>
      {error && <p className="error-box">{error}</p>}
      {checklist && <div className="uat-summary"><strong>{checklist.passed}/{checklist.total}</strong><span>passed · env {checklist.environment}</span></div>}
      <div className="checklist">{checklist?.items.map((i) => <div key={i.key} className={i.passed ? 'pass' : 'fail'}><span>{i.passed ? '✓' : '•'}</span>{i.label}{i.detail ? <small> · {i.detail}</small> : null}</div>)}</div>
    </div>
    <div className="card">
      <p className="eyebrow">Platform environment</p>
      <h3>Secret-safe env status</h3>
      <div className="list">{environment?.items.map((i) => <div className="list-card" key={i.key}><b>{i.key}</b><p>{i.purpose}</p><small>{i.configured ? 'configured' : 'missing'} · {i.secret ? 'secret' : i.value_preview}</small></div>)}</div>
    </div>
    <div className="card">
      <p className="eyebrow">WhatsApp go-live package</p>
      <h3>Still required before academy live hookup</h3>
      {goLive && <pre>{JSON.stringify(goLive, null, 2)}</pre>}
    </div>
    <div className="card">
      <p className="eyebrow">Webhook UAT fixtures</p>
      <h3>Signed payload samples</h3>
      <p className="muted">These normalize and classify realistic WhatsApp payloads without creating customer messages.</p>
      <div className="list">{fixtures.slice(0, 5).map((f) => <div className="list-card" key={f.id}><b>{f.id}</b><p>{f.message}</p><small>{f.x_hub_signature_256 ? 'signed fixture available' : 'signature unavailable until app_secret is configured'}</small><button onClick={() => void simulate(f.id)}>Simulate</button></div>)}</div>
      {simulation && <pre>{JSON.stringify(simulation, null, 2)}</pre>}
    </div>
  </section>;
}

function HandoffPanel({ token, tenantSlug }: { token: string; tenantSlug: string }) {
  const [summary, setSummary] = useState<AcceptanceSummary | null>(null);
  const [blockers, setBlockers] = useState<GoLiveBlockers | null>(null);
  const [pkg, setPkg] = useState<HandoffPackage | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const [s, b, h] = await Promise.all([
        api.acceptanceSummary(token, tenantSlug),
        api.goLiveBlockers(token, tenantSlug),
        api.handoffPackage(token, tenantSlug),
      ]);
      setSummary(s);
      setBlockers(b);
      setPkg(h);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load handoff package');
    }
  }

  useEffect(() => { void load(); }, []);

  return <section className="grid two">
    <div className="card wide">
      <p className="eyebrow">Final acceptance</p>
      <h3>Definition-of-done tracker</h3>
      <button onClick={load}>Refresh final handoff status</button>
      {error && <p className="error-box">{error}</p>}
      {summary && <div className="uat-summary"><strong>{summary.passed}/{summary.total}</strong><span>{summary.project_status} · env {summary.environment}</span></div>}
      <div className="checklist">{summary?.items.map((i) => <div key={i.key} className={i.passed ? 'pass' : 'fail'}><span>{i.passed ? '✓' : '•'}</span>{i.label}{i.detail ? <small> · {i.detail}</small> : null}</div>)}</div>
    </div>
    <div className="card">
      <p className="eyebrow">Tenant evidence</p>
      <h3>Configuration and operations counts</h3>
      {summary && <div className="metric-grid">{Object.entries(summary.counts).map(([k, v]) => <div className="metric" key={k}><strong>{v}</strong><span>{k}</span></div>)}</div>}
    </div>
    <div className="card">
      <p className="eyebrow">Go-live blockers</p>
      <h3>{blockers?.blocked ? 'Still blocked' : 'No blockers'}</h3>
      <div className="list">{blockers?.blockers.map((b) => <div className="list-card" key={b.key}><b>{b.label}</b><p>{b.detail || b.key}</p></div>)}</div>
      <h4>External academy WhatsApp items</h4>
      <div className="list">{blockers?.expected_remaining_external_blockers.map((b) => <div className="list-card" key={b}><b>{b}</b></div>)}</div>
    </div>
    <div className="card wide">
      <p className="eyebrow">Client handoff package</p>
      <h3>{pkg?.product}</h3>
      {pkg && <div className="grid two">
        <div><h4>Included capabilities</h4><div className="list">{pkg.included_capabilities.map((x) => <div className="list-card" key={x}><b>{x}</b></div>)}</div></div>
        <div><h4>Next steps</h4><div className="list">{pkg.recommended_next_steps.map((x) => <div className="list-card" key={x}><b>{x}</b></div>)}</div></div>
      </div>}
    </div>
  </section>;
}

function Settings({ tenant, branches, token, tenantSlug, reload }: { tenant: TenantProfile | null; branches: Branch[]; token: string; tenantSlug: string; reload: () => Promise<void> }) {
  const [displayName, setDisplayName] = useState(tenant?.display_name || '');
  const [supportPhone, setSupportPhone] = useState(tenant?.brand.support_phone || '');
  const [branchName, setBranchName] = useState('');
  const [branchAddress, setBranchAddress] = useState('');
  const [morningEnabled, setMorningEnabled] = useState(true);
  const [morningFrom, setMorningFrom] = useState('09:00');
  const [morningTo, setMorningTo] = useState('13:00');
  const [eveningEnabled, setEveningEnabled] = useState(true);
  const [eveningFrom, setEveningFrom] = useState('16:30');
  const [eveningTo, setEveningTo] = useState('21:30');
  const [pendingDeleteBranch, setPendingDeleteBranch] = useState<Branch | null>(null);
  const [deletingBranchId, setDeletingBranchId] = useState<number | null>(null);
  const [editingBranch, setEditingBranch] = useState<Branch | null>(null);
  const [editBranchName, setEditBranchName] = useState('');
  const [editBranchAddress, setEditBranchAddress] = useState('');
  const [editMorningEnabled, setEditMorningEnabled] = useState(true);
  const [editMorningFrom, setEditMorningFrom] = useState('09:00');
  const [editMorningTo, setEditMorningTo] = useState('13:00');
  const [editEveningEnabled, setEditEveningEnabled] = useState(true);
  const [editEveningFrom, setEditEveningFrom] = useState('16:30');
  const [editEveningTo, setEditEveningTo] = useState('21:30');
  const [savingBranchId, setSavingBranchId] = useState<number | null>(null);
  useEffect(() => { setDisplayName(tenant?.display_name || ''); setSupportPhone(tenant?.brand.support_phone || ''); }, [tenant]);
  async function saveProfile(e: FormEvent) { e.preventDefault(); await api.updateProfile(token, tenantSlug, { display_name: displayName, support_phone: supportPhone }); await reload(); }
  const branchHoursPreview = buildBranchHoursJson(morningEnabled, morningFrom, morningTo, eveningEnabled, eveningFrom, eveningTo);
  async function addBranch(e: FormEvent) {
    e.preventDefault();
    await api.createBranch(token, tenantSlug, {
      name: branchName,
      address: branchAddress,
      city: 'Jeddah',
      maps_url: null,
      hours_json: branchHoursPreview,
      is_active: true,
    });
    setBranchName('');
    setBranchAddress('');
    setMorningEnabled(true);
    setMorningFrom('09:00');
    setMorningTo('13:00');
    setEveningEnabled(true);
    setEveningFrom('16:30');
    setEveningTo('21:30');
    await reload();
  }
  async function confirmDeleteBranch() {
    if (!pendingDeleteBranch) return;
    setDeletingBranchId(pendingDeleteBranch.id);
    try {
      await api.deleteBranch(token, tenantSlug, pendingDeleteBranch.id);
      setPendingDeleteBranch(null);
      await reload();
    } finally {
      setDeletingBranchId(null);
    }
  }
  function openEditBranch(branch: Branch) {
    const periods = Array.isArray(branch.hours_json?.periods) ? branch.hours_json.periods as Array<{ from?: string; to?: string }> : [];
    const morning = periods[0];
    const evening = periods[1];
    setEditingBranch(branch);
    setEditBranchName(branch.name || '');
    setEditBranchAddress(branch.address || '');
    setEditMorningEnabled(Boolean(morning));
    setEditMorningFrom(morning?.from || '09:00');
    setEditMorningTo(morning?.to || '13:00');
    setEditEveningEnabled(Boolean(evening));
    setEditEveningFrom(evening?.from || '16:30');
    setEditEveningTo(evening?.to || '21:30');
  }
  async function saveBranchEdit() {
    if (!editingBranch) return;
    setSavingBranchId(editingBranch.id);
    try {
      await api.updateBranch(token, tenantSlug, editingBranch.id, {
        name: editBranchName,
        address: editBranchAddress,
        hours_json: buildBranchHoursJson(editMorningEnabled, editMorningFrom, editMorningTo, editEveningEnabled, editEveningFrom, editEveningTo),
      });
      setEditingBranch(null);
      await reload();
    } finally {
      setSavingBranchId(null);
    }
  }
  const previewPeriods = [
    morningEnabled ? { label: 'Morning', from: morningFrom, to: morningTo } : null,
    eveningEnabled ? { label: 'Evening', from: eveningFrom, to: eveningTo } : null,
  ].filter(Boolean) as Array<{ label: string; from: string; to: string }>;
  return <section className="grid two settings-layout"><form className="card form-stack settings-panel" onSubmit={saveProfile}><p className="eyebrow">Business settings</p><h3>Profile</h3><label>Display name<input value={displayName} onChange={(e) => setDisplayName(e.target.value)} /></label><label>Support phone<input value={supportPhone} onChange={(e) => setSupportPhone(e.target.value)} /></label><button>Save profile</button></form><form className="card form-stack settings-panel" onSubmit={addBranch}><p className="eyebrow">Branches</p><h3>Add branch</h3><label>Name<input value={branchName} onChange={(e) => setBranchName(e.target.value)} /></label><label>Address<input value={branchAddress} onChange={(e) => setBranchAddress(e.target.value)} /></label><div className="hours-builder"><div className="hours-period"><div className="row-between"><strong>Morning hours</strong><label className="check-row compact-check"><input type="checkbox" checked={morningEnabled} onChange={(e) => setMorningEnabled(e.target.checked)} /> Open in morning</label></div>{morningEnabled ? <div className="time-range"><label>From<input type="time" value={morningFrom} onChange={(e) => setMorningFrom(e.target.value)} /></label><label>To<input type="time" value={morningTo} onChange={(e) => setMorningTo(e.target.value)} /></label></div> : <p className="muted">Morning period disabled.</p>}</div><div className="hours-period"><div className="row-between"><strong>Evening hours</strong><label className="check-row compact-check"><input type="checkbox" checked={eveningEnabled} onChange={(e) => setEveningEnabled(e.target.checked)} /> Open in evening</label></div>{eveningEnabled ? <div className="time-range"><label>From<input type="time" value={eveningFrom} onChange={(e) => setEveningFrom(e.target.value)} /></label><label>To<input type="time" value={eveningTo} onChange={(e) => setEveningTo(e.target.value)} /></label></div> : <p className="muted">Evening period disabled.</p>}</div><div className="hours-preview"><p className="eyebrow">Hours Preview</p><div className="hours-preview-grid">{previewPeriods.length > 0 ? previewPeriods.map((period) => <div className="hours-preview-card" key={period.label}><strong>{period.label}</strong><span>{formatClockTime(period.from)} - {formatClockTime(period.to)}</span></div>) : <div className="hours-preview-card disabled"><strong>Closed</strong><span>No active periods selected</span></div>}</div></div></div><button disabled={!morningEnabled && !eveningEnabled}>Add branch</button></form><div className="card wide"><h3>Current branches</h3><div className="branch-grid">{branches.length === 0 && <p className="muted">No branches yet.</p>}{branches.map((branch) => { const periods = Array.isArray(branch.hours_json?.periods) ? branch.hours_json.periods as Array<{ from?: string; to?: string }> : []; return <div className="branch-card" key={branch.id}><button className="close-chip branch-close-chip" type="button" aria-label={`Delete ${branch.name}`} onClick={() => setPendingDeleteBranch(branch)}>x</button><div className="branch-head"><strong>{branch.name}</strong></div><div className="branch-meta"><div><small>Address</small><span>{branch.address || 'No address yet'}</span></div><div><small>City</small><span>{branch.city || 'Not set'}</span></div></div><div className="branch-hours"><small>Hours</small>{periods.length > 0 ? periods.map((period, index) => <span className="branch-hour-pill" key={`${branch.id}-${index}`}>{formatClockTime(period.from || '')} - {formatClockTime(period.to || '')}</span>) : <span className="muted">No hours saved</span>}</div><div className="button-row"><button className="secondary" type="button" onClick={() => openEditBranch(branch)}>Edit branch</button></div></div>; })}</div></div>{editingBranch && <div className="confirm-overlay" role="dialog" aria-modal="true"><div className="confirm-card"><h3>Edit branch</h3><div className="form-stack"><label>Name<input value={editBranchName} onChange={(e) => setEditBranchName(e.target.value)} /></label><label>Address<input value={editBranchAddress} onChange={(e) => setEditBranchAddress(e.target.value)} /></label><div className="hours-period"><div className="row-between"><strong>Morning hours</strong><label className="check-row compact-check"><input type="checkbox" checked={editMorningEnabled} onChange={(e) => setEditMorningEnabled(e.target.checked)} /> Open in morning</label></div>{editMorningEnabled ? <div className="time-range"><label>From<input type="time" value={editMorningFrom} onChange={(e) => setEditMorningFrom(e.target.value)} /></label><label>To<input type="time" value={editMorningTo} onChange={(e) => setEditMorningTo(e.target.value)} /></label></div> : <p className="muted">Morning period disabled.</p>}</div><div className="hours-period"><div className="row-between"><strong>Evening hours</strong><label className="check-row compact-check"><input type="checkbox" checked={editEveningEnabled} onChange={(e) => setEditEveningEnabled(e.target.checked)} /> Open in evening</label></div>{editEveningEnabled ? <div className="time-range"><label>From<input type="time" value={editEveningFrom} onChange={(e) => setEditEveningFrom(e.target.value)} /></label><label>To<input type="time" value={editEveningTo} onChange={(e) => setEditEveningTo(e.target.value)} /></label></div> : <p className="muted">Evening period disabled.</p>}</div></div><div className="button-row"><button type="button" onClick={() => void saveBranchEdit()} disabled={savingBranchId === editingBranch.id}>{savingBranchId === editingBranch.id ? 'Saving...' : 'Save branch'}</button><button className="secondary" type="button" onClick={() => setEditingBranch(null)} disabled={savingBranchId === editingBranch.id}>Cancel</button></div></div></div>}{pendingDeleteBranch && <div className="confirm-overlay" role="dialog" aria-modal="true"><div className="confirm-card"><h3>Are you sure you want to delete this branch?</h3><p className="muted">{pendingDeleteBranch.name}</p><div className="button-row"><button onClick={() => void confirmDeleteBranch()} disabled={deletingBranchId === pendingDeleteBranch.id}>{deletingBranchId === pendingDeleteBranch.id ? 'Deleting...' : 'Accept'}</button><button className="secondary" onClick={() => setPendingDeleteBranch(null)} disabled={deletingBranchId === pendingDeleteBranch.id}>Cancel</button></div></div></div>}</section>;
}

function Staff({ rows, token, tenantSlug, reload }: { rows: StaffUser[]; token: string; tenantSlug: string; reload: () => Promise<void> }) {
  const staffRoleOptions = ['OPERATIONS_STAFF', 'BUSINESS_ADMIN', 'SUPERVISOR', 'FINANCE', 'CERTIFICATES'];
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [roles, setRoles] = useState('OPERATIONS_STAFF');
  const [pendingDelete, setPendingDelete] = useState<StaffUser | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (password.length < 8) {
      setFormError('Password must be at least 8 characters.');
      return;
    }
    await api.createStaff(token, tenantSlug, { email, full_name: name, password, roles: [roles] });
    setEmail('');
    setName('');
    setPassword('');
    await reload();
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeletingId(pendingDelete.id);
    try {
      await api.deleteStaff(token, tenantSlug, pendingDelete.id);
      setPendingDelete(null);
      await reload();
    } finally {
      setDeletingId(null);
    }
  }

  return <section className="grid two staff-layout"><form className="card form-stack staff-form-card" onSubmit={submit}><p className="eyebrow">Users and roles</p><h3>Add staff user</h3><label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} /></label><label>Name<input value={name} onChange={(e) => setName(e.target.value)} /></label><label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label><label>Roles<select value={roles} onChange={(e) => setRoles(e.target.value)}>{staffRoleOptions.map((role) => <option key={role} value={role}>{role}</option>)}</select></label>{boxError(formError)}<button>Add staff</button></form><div className="card staff-list-card"><h3>Staff</h3><div className="staff-grid">{rows.length === 0 && <p className="muted">No staff yet.</p>}{rows.map((row) => <div className="staff-card" key={row.id}><button className="close-chip staff-close-chip" type="button" aria-label={`Delete ${row.full_name}`} onClick={() => setPendingDelete(row)}>x</button><div className="staff-head"><div className={`status-dot ${row.is_active ? 'on' : 'off'}`} aria-hidden="true" /><div><strong>{row.full_name}</strong><p>{row.email}</p></div></div><div className="staff-meta"><div><small>ID</small><span>#{row.id}</span></div><div><small>Status</small><span>{row.is_active ? 'active' : 'inactive'}</span></div></div><div className="staff-roles">{row.roles.length > 0 ? row.roles.map((role) => <span className="staff-role-pill" key={role}>{role}</span>) : <span className="muted">No roles</span>}</div></div>)}</div></div>{pendingDelete && <div className="confirm-overlay" role="dialog" aria-modal="true"><div className="confirm-card"><h3>Are you sure you want to delete this role?</h3><p className="muted">{pendingDelete.full_name} · {pendingDelete.email}</p><div className="button-row"><button onClick={() => void confirmDelete()} disabled={deletingId === pendingDelete.id}>{deletingId === pendingDelete.id ? 'Deleting...' : 'Accept'}</button><button className="secondary" onClick={() => setPendingDelete(null)} disabled={deletingId === pendingDelete.id}>Cancel</button></div></div></div>}</section>;
}

function normalizeIntentCode(value: string) {
  return value.trim().toUpperCase().replace(/[\s-]+/g, '_');
}

function normalizeTopicKey(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, '_');
}

function splitTextareaItems(value: string) {
  return value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);
}

function summarizeText(value?: string | null, max = 120) {
  const text = (value || '').trim();
  if (!text) return 'Not added yet';
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function faqLanguageLabel(row: FaqItem) {
  const hasAr = Boolean((row.question_ar || '').trim() || (row.arabic_answer || '').trim());
  const hasEn = Boolean((row.english_question || '').trim() || (row.english_answer || '').trim());
  if (hasAr && hasEn) return 'BOTH';
  if (hasEn) return 'EN';
  return 'AR';
}

function intentLanguageLabel(value: string) {
  if (value === 'both') return 'BOTH';
  if (value === 'en') return 'EN';
  return 'AR';
}

type KnowledgeItem = {
  id: string;
  intent?: IntentItem;
  faq?: FaqItem;
  route?: RoutingRule;
  responseName: string;
  topicKey: string;
  intentCode: string;
  supportedLanguages: string;
  status: 'active' | 'inactive' | 'archived';
  answerAr: string;
  answerEn: string;
  responseMode: string;
  promptsAr: string[];
  promptsEn: string[];
  responseBehavior: string;
  ownerRole: string;
  ticketType: string;
  priority: string;
  notifyRoles: string[];
  followupQuestionAr: string;
  followupQuestionEn: string;
  badges: string[];
};

type KnowledgeFormState = {
  responseName: string;
  topicKey: string;
  topicKeyTouched: boolean;
  status: 'active' | 'inactive';
  supportedLanguages: 'ar' | 'en' | 'both';
  responseMode: 'faq' | 'custom' | 'business_settings';
  promptsAr: string;
  promptsEn: string;
  answerAr: string;
  answerEn: string;
  responseBehavior: 'normal' | 'immediate_handoff' | 'offer_handoff';
  ownerRole: string;
  ticketType: string;
  priority: string;
  notifyRoles: string;
  followupQuestionAr: string;
  followupQuestionEn: string;
};

const knowledgeWizardSteps = [
  'Basic setup',
  'Customer questions',
  'Bot response',
  'After reply',
  'Review',
] as const;

const knowledgeOwnerRoleOptions = [
  'OPERATIONS_STAFF',
  'FINANCE',
  'CERTIFICATES',
  'SUPERVISOR',
  'BUSINESS_ADMIN',
] as const;

const knowledgeTicketTypeOptions = [
  'handoff',
  'complaint',
  'payment',
  'certificate',
  'pricing_help',
  'reservation',
] as const;

const knowledgeNotifyRoleOptions = [
  'OPERATIONS_STAFF',
  'SUPERVISOR',
  'FINANCE',
  'CERTIFICATES',
  'BUSINESS_ADMIN',
] as const;

function prettifyKeyLabel(value: string) {
  const source = value.trim();
  if (!source) return 'New response';
  return source
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function deriveKnowledgeStatus(intent?: IntentItem, faq?: FaqItem): 'active' | 'inactive' | 'archived' {
  if (faq?.status === 'archived') return 'archived';
  if (faq?.status === 'inactive') return 'inactive';
  if (intent && !intent.enabled) return 'inactive';
  return 'active';
}

function normalizeKnowledgeTopic(value: string) {
  return normalizeTopicKey(value).replace(/[^a-z0-9_]/g, '_').replace(/_+/g, '_').replace(/^_+|_+$/g, '');
}

function buildKnowledgeItems(faq: FaqItem[], intents: IntentItem[], routing: RoutingRule[]) {
  const faqByTopic = new Map(faq.map((row) => [row.topic_key, row]));
  const intentByCode = new Map(intents.map((row) => [row.code, row]));
  const routingByCode = new Map(routing.map((row) => [row.intent_code, row]));
  const keys = new Set<string>();

  intents.forEach((intent) => keys.add(intent.code));
  routing.forEach((route) => keys.add(route.intent_code));
  faq.forEach((row) => keys.add(normalizeIntentCode(row.topic_key)));

  return [...keys]
    .map((key) => {
      const intent = intentByCode.get(key);
      const derivedTopicKey = intent?.default_response_topic_key || normalizeKnowledgeTopic(key);
      const faqRow = faqByTopic.get(derivedTopicKey) || faqByTopic.get(normalizeKnowledgeTopic(key));
      const route = routingByCode.get(key);
      const supportedLanguages = intent?.supported_languages || (faqRow?.english_answer || faqRow?.english_question ? (faqRow?.arabic_answer || faqRow?.question_ar ? 'both' : 'en') : 'ar');
      const responseMode = intent?.response_mode || 'faq';
      const promptsAr = intent?.keywords.filter((item) => item.lang === 'ar').map((item) => item.phrase) || [];
      const promptsEn = intent?.keywords.filter((item) => item.lang === 'en').map((item) => item.phrase) || [];
      const responseBehavior = route?.response_behavior || (route?.handoff_required ? 'immediate_handoff' : 'normal');
      const badges: string[] = [];
      if (responseMode !== 'business_settings' && !faqRow && !intent?.custom_response_ar && !intent?.custom_response_en) badges.push('Missing response');
      if (promptsAr.length === 0 && promptsEn.length === 0) badges.push('No keywords yet');
      if (!route) badges.push('Routing not set');
      if (intent?.response_mode === 'custom') badges.push('Custom answer');
      if (responseMode === 'business_settings') badges.push('Automatic from settings');

      return {
        id: key,
        intent,
        faq: faqRow,
        route,
        responseName: intent?.label || prettifyKeyLabel(faqRow?.topic_key || key),
        topicKey: faqRow?.topic_key || derivedTopicKey,
        intentCode: intent?.code || key,
        supportedLanguages,
        status: deriveKnowledgeStatus(intent, faqRow),
        answerAr: faqRow?.arabic_answer || intent?.custom_response_ar || '',
        answerEn: faqRow?.english_answer || intent?.custom_response_en || '',
        responseMode,
        promptsAr,
        promptsEn,
        responseBehavior,
        ownerRole: route?.primary_owner_role || (responseBehavior === 'normal' ? 'BOT' : 'OPERATIONS_STAFF'),
        ticketType: route?.ticket_type || '',
        priority: route?.priority || 'normal',
        notifyRoles: route?.notify_roles_json || [],
        followupQuestionAr: route?.followup_question_ar || '',
        followupQuestionEn: route?.followup_question_en || '',
        badges,
      } satisfies KnowledgeItem;
    })
    .sort((a, b) => a.responseName.localeCompare(b.responseName));
}

function createDefaultKnowledgeForm(): KnowledgeFormState {
  return {
    responseName: '',
    topicKey: '',
    topicKeyTouched: false,
    status: 'active',
    supportedLanguages: 'ar',
    responseMode: 'faq',
    promptsAr: '',
    promptsEn: '',
    answerAr: '',
    answerEn: '',
    responseBehavior: 'normal',
    ownerRole: 'BOT',
    ticketType: '',
    priority: 'normal',
    notifyRoles: '',
    followupQuestionAr: '',
    followupQuestionEn: '',
  };
}

function languageSummaryLabel(value: string) {
  if (value === 'both') return 'Arabic + English';
  if (value === 'en') return 'English';
  return 'Arabic';
}

function behaviorSummaryLabel(value: string) {
  if (value === 'offer_handoff') return 'Bot answers, then offers a human handoff';
  if (value === 'immediate_handoff') return 'Send to human immediately';
  return 'Bot answers only';
}

function KnowledgeResponses({ faq, intents, routing, token, tenantSlug, reload }: { faq: FaqItem[]; intents: IntentItem[]; routing: RoutingRule[]; token: string; tenantSlug: string; reload: () => Promise<void> }) {
  const items = useMemo(() => buildKnowledgeItems(faq, intents, routing), [faq, intents, routing]);
  const [knowledgeSearch, setKnowledgeSearch] = useState('');
  const [knowledgeStatusFilter, setKnowledgeStatusFilter] = useState<'all' | 'active' | 'inactive' | 'archived'>('all');
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardStep, setWizardStep] = useState(1);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [wizardMode, setWizardMode] = useState<'create' | 'edit'>('create');
  const [editingItem, setEditingItem] = useState<KnowledgeItem | null>(null);
  const [pendingArchive, setPendingArchive] = useState<KnowledgeItem | null>(null);
  const [pendingDelete, setPendingDelete] = useState<KnowledgeItem | null>(null);
  const [form, setForm] = useState<KnowledgeFormState>(createDefaultKnowledgeForm);

  function openCreate() {
    setWizardMode('create');
    setEditingItem(null);
    setWizardStep(1);
    setFormError(null);
    setForm(createDefaultKnowledgeForm());
    setWizardOpen(true);
  }

  function openEdit(item: KnowledgeItem) {
    setWizardMode('edit');
    setEditingItem(item);
    setWizardStep(1);
    setFormError(null);
    setForm({
      responseName: item.responseName,
      topicKey: item.topicKey,
      topicKeyTouched: true,
      status: item.status === 'archived' ? 'inactive' : item.status,
      supportedLanguages: (item.supportedLanguages === 'both' || item.supportedLanguages === 'en') ? item.supportedLanguages : 'ar',
      responseMode: item.responseMode === 'custom' || item.responseMode === 'business_settings' ? item.responseMode : 'faq',
      promptsAr: item.promptsAr.join('\n'),
      promptsEn: item.promptsEn.join('\n'),
      answerAr: item.answerAr,
      answerEn: item.answerEn,
      responseBehavior: item.responseBehavior === 'offer_handoff' || item.responseBehavior === 'immediate_handoff' ? item.responseBehavior : 'normal',
      ownerRole: item.ownerRole,
      ticketType: item.ticketType,
      priority: item.priority,
      notifyRoles: item.notifyRoles.join(', '),
      followupQuestionAr: item.followupQuestionAr,
      followupQuestionEn: item.followupQuestionEn,
    });
    setWizardOpen(true);
  }

  function closeWizard() {
    if (saving) return;
    setWizardOpen(false);
    setWizardStep(1);
    setFormError(null);
  }

  function updateForm(patch: Partial<KnowledgeFormState>) {
    setForm((current) => ({ ...current, ...patch }));
  }

  function handleResponseNameChange(value: string) {
    setForm((current) => ({
      ...current,
      responseName: value,
      topicKey: current.topicKeyTouched ? current.topicKey : normalizeKnowledgeTopic(value),
    }));
  }

  function handleTopicKeyChange(value: string) {
    updateForm({ topicKey: normalizeKnowledgeTopic(value), topicKeyTouched: true });
  }

  function changeBehavior(next: KnowledgeFormState['responseBehavior']) {
    setForm((current) => ({
      ...current,
      responseBehavior: next,
      ownerRole: next === 'normal' ? 'BOT' : current.ownerRole === 'BOT' ? 'OPERATIONS_STAFF' : current.ownerRole,
      ticketType: next === 'normal' ? '' : current.ticketType || 'handoff',
      followupQuestionAr: next === 'offer_handoff' ? current.followupQuestionAr : '',
      followupQuestionEn: next === 'offer_handoff' ? current.followupQuestionEn : '',
    }));
  }

  function selectedNotifyRoles() {
    return form.notifyRoles.split(',').map((item) => item.trim()).filter(Boolean);
  }

  function addNotifyRole(role: string) {
    if (!role) return;
    const currentRoles = selectedNotifyRoles();
    if (currentRoles.includes(role)) return;
    updateForm({ notifyRoles: [...currentRoles, role].join(', ') });
  }

  function removeNotifyRole(role: string) {
    updateForm({ notifyRoles: selectedNotifyRoles().filter((item) => item !== role).join(', ') });
  }

  function validateCurrentStep() {
    const topicKey = normalizeKnowledgeTopic(form.topicKey || form.responseName);
    if (wizardStep === 1) {
      if (!form.responseName.trim()) return 'Add a response name.';
      if (!topicKey) return 'Add a topic key.';
    }
    if (wizardStep === 2) {
      const hasArPrompt = form.supportedLanguages !== 'en' && splitTextareaItems(form.promptsAr).length > 0;
      const hasEnPrompt = form.supportedLanguages !== 'ar' && splitTextareaItems(form.promptsEn).length > 0;
      if (!hasArPrompt && !hasEnPrompt) return 'Add at least one example customer question.';
    }
    if (wizardStep === 3) {
      if (form.responseMode !== 'business_settings') {
        if (form.supportedLanguages !== 'en' && !form.answerAr.trim()) return 'Add the Arabic bot reply.';
        if (form.supportedLanguages !== 'ar' && !form.answerEn.trim()) return 'Add the English bot reply.';
        if (form.supportedLanguages === 'en' && !form.answerEn.trim()) return 'Add the English bot reply.';
      }
    }
    if (wizardStep === 4) {
      if (form.responseBehavior !== 'normal' && form.ownerRole === 'BOT') return 'Choose who should handle the human handoff.';
      if (form.responseBehavior !== 'normal' && !form.ticketType.trim()) return 'Add a ticket type for the handoff.';
      if (form.responseBehavior === 'offer_handoff' && !form.followupQuestionAr.trim() && !form.followupQuestionEn.trim()) return 'Add the follow-up handoff question.';
    }
    return null;
  }

  function goNext() {
    const error = validateCurrentStep();
    if (error) {
      setFormError(error);
      return;
    }
    setFormError(null);
    setWizardStep((current) => Math.min(current + 1, knowledgeWizardSteps.length));
  }

  function goBack() {
    setFormError(null);
    setWizardStep((current) => Math.max(current - 1, 1));
  }

  async function saveKnowledgeItem() {
    const error = validateCurrentStep();
    if (error) {
      setFormError(error);
      return;
    }

    const topicKey = normalizeKnowledgeTopic(form.topicKey || form.responseName);
    const intentCode = normalizeIntentCode(topicKey);
    const promptsAr = form.supportedLanguages === 'en' ? [] : splitTextareaItems(form.promptsAr);
    const promptsEn = form.supportedLanguages === 'ar' ? [] : splitTextareaItems(form.promptsEn);
    const arabicAnswer = form.answerAr.trim() || form.answerEn.trim();
    const englishAnswer = form.supportedLanguages === 'ar' ? null : (form.answerEn.trim() || null);

    setSaving(true);
    setFormError(null);
    try {
      if (form.responseMode !== 'business_settings') {
        if (editingItem?.faq) {
          await api.updateFaq(token, tenantSlug, editingItem.faq.id, {
            topic_key: topicKey,
            question_ar: promptsAr[0] || null,
            english_question: promptsEn[0] || null,
            arabic_answer: arabicAnswer,
            english_answer: englishAnswer,
            status: form.status === 'active' ? 'active' : 'inactive',
          });
        } else {
          await api.createFaq(token, tenantSlug, {
            topic_key: topicKey,
            question_ar: promptsAr[0] || null,
            english_question: promptsEn[0] || null,
            arabic_answer: arabicAnswer,
            english_answer: englishAnswer,
            status: form.status === 'active' ? 'active' : 'inactive',
          });
        }
      }

      const intentPayload = {
        code: intentCode,
        label: form.responseName.trim(),
        enabled: form.status === 'active',
        is_universal: false,
        supported_languages: form.supportedLanguages,
        response_mode: form.responseMode,
        default_response_topic_key: topicKey,
        custom_response_ar: form.responseMode === 'custom' ? (form.answerAr.trim() || null) : null,
        custom_response_en: form.responseMode === 'custom' ? (form.answerEn.trim() || null) : null,
      };

      if (editingItem?.intent) {
        await api.updateIntent(token, tenantSlug, editingItem.intent.id, intentPayload);
      } else {
        await api.createIntent(token, tenantSlug, intentPayload);
      }

      const existingIntent = editingItem?.intent || intents.find((item) => item.code === intentCode);
      const existingKeywords = existingIntent?.keywords || [];
      const desiredByLang = {
        ar: promptsAr,
        en: promptsEn,
      };
      for (const lang of ['ar', 'en'] as const) {
        const desired = new Set(desiredByLang[lang]);
        for (const keyword of existingKeywords.filter((item) => item.lang === lang)) {
          if (!desired.has(keyword.phrase)) {
            await api.deleteKeyword(token, tenantSlug, keyword.id);
          }
        }
        const existingPhrases = new Set(existingKeywords.filter((item) => item.lang === lang).map((item) => item.phrase));
        for (const phrase of desiredByLang[lang]) {
          if (!existingPhrases.has(phrase)) {
            await api.createKeyword(token, tenantSlug, { intent_code: intentCode, phrase, weight: 2, lang });
          }
        }
      }

      await api.saveRoutingRule(token, tenantSlug, intentCode, {
        intent_code: intentCode,
        primary_owner_role: form.responseBehavior === 'normal' ? 'BOT' : form.ownerRole,
        notify_roles_json: form.notifyRoles.split(',').map((item) => item.trim()).filter(Boolean),
        escalation_json: {},
        handoff_required: form.responseBehavior === 'immediate_handoff',
        ticket_type: form.responseBehavior === 'normal' ? null : (form.ticketType.trim() || 'handoff'),
        priority: form.priority,
        response_behavior: form.responseBehavior,
        followup_question_ar: form.responseBehavior === 'offer_handoff' ? (form.followupQuestionAr.trim() || null) : null,
        followup_question_en: form.responseBehavior === 'offer_handoff' ? (form.followupQuestionEn.trim() || null) : null,
      });

      await reload();
      closeWizard();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Failed to save bot response.');
    } finally {
      setSaving(false);
    }
  }

  async function confirmArchive() {
    if (!pendingArchive) return;
    setDeleting(true);
    try {
      if (pendingArchive.intent) {
        await api.updateIntent(token, tenantSlug, pendingArchive.intent.id, { enabled: false });
      }
      if (pendingArchive.faq) {
        await api.updateFaq(token, tenantSlug, pendingArchive.faq.id, { status: 'archived' });
      }
      await reload();
      setPendingArchive(null);
    } finally {
      setDeleting(false);
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await api.deleteKnowledgeItem(token, tenantSlug, pendingDelete.intentCode, pendingDelete.topicKey);
      await reload();
      setPendingDelete(null);
    } finally {
      setDeleting(false);
    }
  }

  const summaryTopic = normalizeKnowledgeTopic(form.topicKey || form.responseName);
  const summaryIntentCode = normalizeIntentCode(summaryTopic);
  const summaryPromptsAr = splitTextareaItems(form.promptsAr);
  const summaryPromptsEn = splitTextareaItems(form.promptsEn);
  const knowledgeQuery = knowledgeSearch.trim().toLowerCase();
  const filteredItems = items.filter((item) => {
    const matchesStatus = knowledgeStatusFilter === 'all' || item.status === knowledgeStatusFilter;
    const searchable = [
      item.responseName,
      item.topicKey,
      item.intentCode,
      item.answerAr,
      item.answerEn,
      ...item.promptsAr,
      ...item.promptsEn,
      ...item.badges,
    ].join(' ').toLowerCase();
    return matchesStatus && (!knowledgeQuery || searchable.includes(knowledgeQuery));
  });
  const knowledgeCounts = {
    active: items.filter((item) => item.status === 'active').length,
    inactive: items.filter((item) => item.status === 'inactive').length,
    archived: items.filter((item) => item.status === 'archived').length,
  };

  return <section className={`knowledge-shell ${wizardOpen ? 'modal-open' : ''}`}>
    <div className="knowledge-topbar knowledge-premium-topbar">
      <div className="knowledge-title-block">
        <p className="eyebrow">Tenant knowledge base</p>
        <h3>Knowledge & Responses</h3>
        <p className="muted">Manage approved answers safely. The system still saves FAQ, intents, keywords, and routing behind the scenes, and replies in the customer&apos;s message language when that answer exists.</p>
      </div>
      <div className="knowledge-head-actions">
        <div className="knowledge-stats">
          <div><small>Active</small><strong>{knowledgeCounts.active}</strong></div>
          <div><small>Inactive</small><strong>{knowledgeCounts.inactive}</strong></div>
          <div><small>Archived</small><strong>{knowledgeCounts.archived}</strong></div>
        </div>
        <button onClick={openCreate}>Add new bot response</button>
      </div>
    </div>

    <div className="knowledge-controls">
      <label className="knowledge-search">Search approved answers
        <input value={knowledgeSearch} onChange={(e) => setKnowledgeSearch(e.target.value)} placeholder="Search topic, answer, phrase, or intent" />
      </label>
      <div className="knowledge-filter-tabs" aria-label="Filter knowledge responses by status">
        {(['all', 'active', 'inactive', 'archived'] as const).map((filter) => <button key={filter} type="button" className={knowledgeStatusFilter === filter ? 'active' : ''} onClick={() => setKnowledgeStatusFilter(filter)}>
          {filter}
          <span>{filter === 'all' ? items.length : knowledgeCounts[filter]}</span>
        </button>)}
      </div>
    </div>

    <div className="knowledge-cards-grid">
      {items.length === 0 && <div className="card knowledge-empty-state"><strong>No approved answers yet</strong><p className="muted">Add the first response to teach the assistant how to answer a real customer question.</p></div>}
      {items.length > 0 && filteredItems.length === 0 && <div className="card knowledge-empty-state"><strong>No matching responses</strong><p className="muted">Try another search term or switch the status filter.</p></div>}
      {filteredItems.map((item) => <article className={`card knowledge-card knowledge-status-${item.status}`} key={item.id}>
        <div className="knowledge-card-head">
          <div>
            <p className="eyebrow">Approved answer</p>
            <h3>{item.responseName}</h3>
            <p className="knowledge-card-code">{item.topicKey}</p>
          </div>
          <div className="config-inline-meta">
            <span className="config-badge">{languageSummaryLabel(item.supportedLanguages)}</span>
            <span className={`config-status-pill ${item.status}`}>{item.status}</span>
          </div>
        </div>
        <div className="knowledge-topic-strip">
          <span>Intent {item.intentCode}</span>
          <span>{item.responseMode === 'business_settings' ? 'Settings answer' : item.responseMode === 'custom' ? 'Custom answer' : 'FAQ answer'}</span>
          <span>{item.faq ? `FAQ #${item.faq.id}` : 'No FAQ record'}</span>
        </div>
        <div className="knowledge-summary-grid">
          <div>
            <small>What might customers ask?</small>
            <p>{summarizeText([...item.promptsAr, ...item.promptsEn].join(' • '), 180)}</p>
          </div>
          <div>
            <small>What happens after the reply?</small>
            <p>{behaviorSummaryLabel(item.responseBehavior)}</p>
          </div>
          <div>
            <small>Who should handle it?</small>
            <p>{item.responseBehavior === 'normal' ? 'BOT only' : `${item.ownerRole} · ${item.ticketType || 'handoff'} · ${item.priority}`}</p>
          </div>
        </div>
        <div className="knowledge-answer-grid">
          <div className="knowledge-answer-card">
            <div className="knowledge-answer-head"><small>Arabic answer</small><span>AR</span></div>
            <p dir="auto">{item.responseMode === 'business_settings' ? 'Automatic from current business settings' : summarizeText(item.answerAr, 240)}</p>
          </div>
          <div className="knowledge-answer-card">
            <div className="knowledge-answer-head"><small>English answer</small><span>EN</span></div>
            <p>{item.responseMode === 'business_settings' ? 'Automatic from current business settings' : summarizeText(item.answerEn, 240)}</p>
          </div>
        </div>
        {item.badges.length > 0 && <div className="chip-cloud">
          {item.badges.map((badge) => <span key={badge} className="config-chip secondary-chip">{badge}</span>)}
        </div>}
        <div className="button-row knowledge-card-actions">
          <button type="button" className="secondary" onClick={() => openEdit(item)}>Edit</button>
          <button type="button" className="secondary" onClick={() => setPendingArchive(item)}>Archive</button>
          <button type="button" className="danger-action" onClick={() => setPendingDelete(item)}>Delete</button>
        </div>
      </article>)}
    </div>

    {wizardOpen && <div className="confirm-overlay knowledge-modal-overlay" role="dialog" aria-modal="true">
      <div className="knowledge-modal">
        <div className="knowledge-modal-head">
          <div>
            <p className="eyebrow">{wizardMode === 'edit' ? 'Edit bot response' : 'New bot response'}</p>
            <h3>{wizardMode === 'edit' ? form.responseName || 'Update response' : 'Guided setup'}</h3>
          </div>
          <button type="button" className="secondary knowledge-close-button" onClick={closeWizard}>Close</button>
        </div>

        <div className="knowledge-steps">
          {knowledgeWizardSteps.map((label, index) => <div key={label} className={`knowledge-step-pill ${wizardStep === index + 1 ? 'active' : wizardStep > index + 1 ? 'done' : ''}`}>
            <span>{index + 1}</span>
            <strong>{label}</strong>
          </div>)}
        </div>

        <div className="knowledge-modal-body">
          {wizardStep === 1 && <div className="form-stack">
            <div className="config-language-head"><strong>Basic setup</strong><span className="config-badge">Step 1</span></div>
            <label>Response name
              <input value={form.responseName} onChange={(e) => handleResponseNameChange(e.target.value)} placeholder="Pricing" />
            </label>
            <label>Topic key / code
              <input value={form.topicKey} onChange={(e) => handleTopicKeyChange(e.target.value)} placeholder="pricing" />
            </label>
            <div className="config-form-grid">
              <label>Status
                <select value={form.status} onChange={(e) => updateForm({ status: e.target.value as 'active' | 'inactive' })}>
                  <option value="active">Active</option>
                  <option value="inactive">Inactive</option>
                </select>
              </label>
              <label>Supported languages
                <select value={form.supportedLanguages} onChange={(e) => updateForm({ supportedLanguages: e.target.value as 'ar' | 'en' | 'both' })}>
                  <option value="ar">Arabic</option>
                  <option value="en">English</option>
                  <option value="both">Both</option>
                </select>
              </label>
            </div>
            <label>Response source
              <select value={form.responseMode} onChange={(e) => updateForm({ responseMode: e.target.value as 'faq' | 'custom' | 'business_settings' })}>
                <option value="faq">FAQ approved answer</option>
                <option value="custom">Custom answer</option>
                <option value="business_settings">Business settings automatic answer</option>
              </select>
            </label>
            {form.responseMode === 'business_settings' && <p className="muted">Use this for live settings-driven answers like location, branch address, opening hours, or support phone. The bot will always use the latest saved Settings data at runtime.</p>}
          </div>}

          {wizardStep === 2 && <div className="form-stack">
            <div className="config-language-head"><strong>What might the customer ask?</strong><span className="config-badge">Step 2</span></div>
            {(form.supportedLanguages === 'ar' || form.supportedLanguages === 'both') && <label>Arabic example questions
              <textarea value={form.promptsAr} onChange={(e) => updateForm({ promptsAr: e.target.value })} placeholder={'كم السعر\nبكم؟\nوين موقعكم'} />
            </label>}
            {(form.supportedLanguages === 'en' || form.supportedLanguages === 'both') && <label>English example questions
              <textarea value={form.promptsEn} onChange={(e) => updateForm({ promptsEn: e.target.value })} placeholder={'how much\nwhat is the price\nwhere are you located'} />
            </label>}
          </div>}

          {wizardStep === 3 && <div className="form-stack">
            <div className="config-language-head"><strong>What should the bot reply?</strong><span className="config-badge">Step 3</span></div>
            {form.responseMode === 'business_settings' ? <div className="config-item-card">
              <small>Automatic response source</small>
              <p>The bot will build this answer from the tenant&apos;s current Settings data at runtime and automatically match the customer&apos;s language. Use intents such as `LOCATION`, `SCHEDULES`, or `CONTACT` style questions for this option.</p>
            </div> : <>
            {(form.supportedLanguages === 'ar' || form.supportedLanguages === 'both') && <label>Arabic bot answer
              <textarea value={form.answerAr} onChange={(e) => updateForm({ answerAr: e.target.value })} placeholder="أسعارنا تبدأ من 100 ريال." />
            </label>}
            {(form.supportedLanguages === 'en' || form.supportedLanguages === 'both') && <label>English bot answer
              <textarea value={form.answerEn} onChange={(e) => updateForm({ answerEn: e.target.value })} placeholder="Our prices start from 100 SAR." />
            </label>}
            </>}
          </div>}

          {wizardStep === 4 && <div className="form-stack">
            <div className="config-language-head"><strong>What should happen after the bot replies?</strong><span className="config-badge">Step 4</span></div>
            <label>Should a human get involved?
              <select value={form.responseBehavior} onChange={(e) => changeBehavior(e.target.value as KnowledgeFormState['responseBehavior'])}>
                <option value="normal">Bot answers only</option>
                <option value="immediate_handoff">Send to human immediately</option>
                <option value="offer_handoff">Bot answers, then asks if customer wants a human</option>
              </select>
            </label>

            {form.responseBehavior !== 'normal' && <div className="config-form-grid">
              <label>Who should handle it?
                <select value={form.ownerRole} onChange={(e) => updateForm({ ownerRole: e.target.value })}>
                  {knowledgeOwnerRoleOptions.map((role) => <option key={role} value={role}>{role}</option>)}
                </select>
              </label>
              <label>Ticket type
                <select value={form.ticketType} onChange={(e) => updateForm({ ticketType: e.target.value })}>
                  <option value="">Select ticket type</option>
                  {knowledgeTicketTypeOptions.map((ticketType) => <option key={ticketType} value={ticketType}>{ticketType}</option>)}
                </select>
              </label>
              <div className="knowledge-select-card">
                <label className="knowledge-equal-height">Priority
                  <select value={form.priority} onChange={(e) => updateForm({ priority: e.target.value })}>
                    <option value="normal">normal</option>
                    <option value="high">high</option>
                    <option value="urgent">urgent</option>
                  </select>
                </label>
              </div>
              <div className="knowledge-select-card">
                <label>Notify roles
                  <select
                    value=""
                    onChange={(e) => {
                      addNotifyRole(e.target.value);
                      e.target.value = '';
                    }}
                  >
                    <option value="">Choose a role to notify</option>
                    {knowledgeNotifyRoleOptions
                      .filter((role) => !selectedNotifyRoles().includes(role))
                      .map((role) => <option key={role} value={role}>{role}</option>)}
                  </select>
                </label>
                {selectedNotifyRoles().length > 0 && <div className="chip-cloud">
                  {selectedNotifyRoles().map((role) => <button
                    key={role}
                    type="button"
                    className="config-chip"
                    onClick={() => removeNotifyRole(role)}
                  >
                    {role} ×
                  </button>)}
                </div>}
              </div>
            </div>}

            {form.responseBehavior === 'offer_handoff' && <div className="config-language-grid">
              <label>Follow-up question Arabic
                <textarea value={form.followupQuestionAr} onChange={(e) => updateForm({ followupQuestionAr: e.target.value })} placeholder="هل تحتاج تفاصيل إضافية من موظف؟" />
              </label>
              <label>Follow-up question English
                <textarea value={form.followupQuestionEn} onChange={(e) => updateForm({ followupQuestionEn: e.target.value })} placeholder="Would you like me to direct you to a human agent?" />
              </label>
            </div>}
          </div>}

          {wizardStep === 5 && <div className="form-stack">
            <div className="config-language-head"><strong>Review and save</strong><span className="config-badge">Step 5</span></div>
            <div className="knowledge-review-grid">
              <div className="config-item-card">
                <small>Response</small>
                <strong>{form.responseName || 'Not added yet'}</strong>
                <p>FAQ topic: {summaryTopic || 'Not added yet'}</p>
                <p>Intent code: {summaryIntentCode || 'Not added yet'}</p>
              </div>
              <div className="config-item-card">
                <small>Supported languages</small>
                <p>{languageSummaryLabel(form.supportedLanguages)}</p>
                <small>Status</small>
                <p>{form.status}</p>
              </div>
              <div className="config-item-card">
                <small>Customer asks these phrases</small>
                <p>{summarizeText([...summaryPromptsAr, ...summaryPromptsEn].join(' • '), 220)}</p>
              </div>
              <div className="config-item-card">
                <small>Bot replies with</small>
                <p>{form.responseMode === 'business_settings' ? 'Automatic from current business settings' : summarizeText(form.answerAr || form.answerEn, 220)}</p>
              </div>
              <div className="config-item-card">
                <small>After reply</small>
                <p>{behaviorSummaryLabel(form.responseBehavior)}</p>
              </div>
              <div className="config-item-card">
                <small>Who should handle it?</small>
                <p>{form.responseBehavior === 'normal' ? 'BOT only' : `${form.ownerRole} · ${form.ticketType || 'handoff'} · ${form.priority}`}</p>
              </div>
            </div>
          </div>}
        </div>

        {formError && <div className="error-box">{formError}</div>}

        <div className="knowledge-modal-actions">
          <button type="button" className="secondary" onClick={goBack} disabled={wizardStep === 1 || saving}>Back</button>
          <div className="knowledge-modal-actions-right">
            {wizardStep < knowledgeWizardSteps.length && <button type="button" className="secondary" onClick={goNext} disabled={saving}>Next</button>}
            {wizardStep === knowledgeWizardSteps.length && <button type="button" onClick={() => void saveKnowledgeItem()} disabled={saving}>{saving ? 'Saving...' : 'Save bot response'}</button>}
          </div>
        </div>
      </div>
    </div>}

    {pendingArchive && <div className="confirm-overlay" role="dialog" aria-modal="true">
      <div className="confirm-card">
        <h3>Archive this bot response?</h3>
        <p className="muted">{pendingArchive.responseName}</p>
        <p className="muted">This safely disables the intent and archives the linked FAQ answer when available.</p>
        <div className="button-row">
          <button onClick={() => void confirmArchive()} disabled={deleting}>{deleting ? 'Archiving...' : 'Archive'}</button>
          <button className="secondary" onClick={() => setPendingArchive(null)} disabled={deleting}>Cancel</button>
        </div>
      </div>
    </div>}

    {pendingDelete && <div className="confirm-overlay" role="dialog" aria-modal="true">
      <div className="confirm-card">
        <h3>Delete this bot response?</h3>
        <p className="muted">{pendingDelete.responseName}</p>
        <p className="muted">This permanently deletes the linked bot response records for this item, including its intent, keywords, routing rule, and linked FAQ answer when present.</p>
        <div className="button-row">
          <button onClick={() => void confirmDelete()} disabled={deleting}>{deleting ? 'Deleting...' : 'Delete permanently'}</button>
          <button className="secondary" onClick={() => setPendingDelete(null)} disabled={deleting}>Cancel</button>
        </div>
      </div>
    </div>}
  </section>;
}

function Faq({ rows, token, tenantSlug, reload }: { rows: FaqItem[]; token: string; tenantSlug: string; reload: () => Promise<void> }) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [topicKey, setTopicKey] = useState('');
  const [questionAr, setQuestionAr] = useState('');
  const [answerAr, setAnswerAr] = useState('');
  const [questionEn, setQuestionEn] = useState('');
  const [answerEn, setAnswerEn] = useState('');
  const [status, setStatus] = useState('active');
  const [pendingArchive, setPendingArchive] = useState<FaqItem | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const sortedRows = useMemo(() => [...rows].sort((a, b) => a.topic_key.localeCompare(b.topic_key)), [rows]);

  function resetForm() {
    setEditingId(null);
    setTopicKey('');
    setQuestionAr('');
    setAnswerAr('');
    setQuestionEn('');
    setAnswerEn('');
    setStatus('active');
  }

  function startEdit(row: FaqItem) {
    setEditingId(row.id);
    setTopicKey(row.topic_key);
    setQuestionAr(row.question_ar || '');
    setAnswerAr(row.arabic_answer || '');
    setQuestionEn(row.english_question || '');
    setAnswerEn(row.english_answer || '');
    setStatus(row.status || 'active');
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const payload = {
      topic_key: normalizeTopicKey(topicKey),
      question_ar: questionAr || null,
      english_question: questionEn || null,
      arabic_answer: answerAr,
      english_answer: answerEn || null,
      status,
    };
    if (editingId) {
      await api.updateFaq(token, tenantSlug, editingId, payload);
    } else {
      await api.createFaq(token, tenantSlug, payload);
    }
    resetForm();
    await reload();
  }

  async function toggleStatus(row: FaqItem) {
    setBusyId(row.id);
    try {
      await api.updateFaq(token, tenantSlug, row.id, { status: row.status === 'active' ? 'inactive' : 'active' });
      await reload();
      if (editingId === row.id) {
        setStatus(row.status === 'active' ? 'inactive' : 'active');
      }
    } finally {
      setBusyId(null);
    }
  }

  async function confirmArchive() {
    if (!pendingArchive) return;
    setBusyId(pendingArchive.id);
    try {
      await api.deleteFaq(token, tenantSlug, pendingArchive.id);
      if (editingId === pendingArchive.id) resetForm();
      setPendingArchive(null);
      await reload();
    } finally {
      setBusyId(null);
    }
  }

  return <section className="config-page config-page-two">
    <form className="card config-editor-card faq-editor-card" onSubmit={submit}>
      <div className="config-section-head">
        <div>
          <p className="eyebrow">FAQ manager</p>
          <h3>{editingId ? 'Edit approved answer' : 'Create approved answer'}</h3>
        </div>
        {editingId && <button type="button" className="secondary" onClick={resetForm}>New FAQ</button>}
      </div>
      <div className="config-form-grid">
        <label>Topic key<input value={topicKey} onChange={(e) => setTopicKey(e.target.value)} placeholder="pricing" required /></label>
        <label>Status<select value={status} onChange={(e) => setStatus(e.target.value)}><option value="active">active</option><option value="inactive">inactive</option><option value="archived">archived</option></select></label>
      </div>
      <div className="config-language-grid">
        <div className="config-language-card">
          <div className="config-language-head"><strong>Arabic content</strong><span className="config-badge">AR</span></div>
          <label>Arabic question<input value={questionAr} onChange={(e) => setQuestionAr(e.target.value)} placeholder="كم السعر؟" /></label>
          <label>Arabic answer<textarea value={answerAr} onChange={(e) => setAnswerAr(e.target.value)} placeholder="سعر الخدمة يبدأ من..." required /></label>
        </div>
        <div className="config-language-card">
          <div className="config-language-head"><strong>English content</strong><span className="config-badge secondary-pill">EN</span></div>
          <label>English question<input value={questionEn} onChange={(e) => setQuestionEn(e.target.value)} placeholder="How much does it cost?" /></label>
          <label>English answer<textarea value={answerEn} onChange={(e) => setAnswerEn(e.target.value)} placeholder="Optional English answer" /></label>
        </div>
      </div>
      <div className="config-preview-card">
        <p className="eyebrow">Preview</p>
        <strong>{normalizeTopicKey(topicKey) || 'topic_key'}</strong>
        <p>{summarizeText(answerAr || answerEn, 180)}</p>
        <div className="config-inline-meta">
          <span className="config-badge">{questionAr || answerAr ? 'AR' : 'NO AR'}</span>
          <span className="config-badge secondary-pill">{questionEn || answerEn ? 'EN' : 'NO EN'}</span>
          <span className={`config-status-pill ${status === 'active' ? 'active' : status === 'inactive' ? 'inactive' : 'archived'}`}>{status}</span>
        </div>
      </div>
      <div className="button-row">
        <button>{editingId ? 'Save FAQ changes' : 'Create FAQ item'}</button>
        {editingId && <button type="button" className="secondary" onClick={resetForm}>Cancel edit</button>}
      </div>
    </form>
    <div className="card config-library-card">
      <div className="config-section-head">
        <div>
          <p className="eyebrow">Saved FAQ items</p>
          <h3>{sortedRows.length} approved answers</h3>
        </div>
      </div>
      <div className="config-card-list">
        {sortedRows.length === 0 && <p className="muted">No FAQ items yet.</p>}
        {sortedRows.map((row) => <article className="config-item-card faq-item-card" key={row.id}>
          <div className="config-item-head">
            <div>
              <strong>{row.topic_key}</strong>
              <div className="config-inline-meta">
                <span className="config-badge">{faqLanguageLabel(row)}</span>
                <span className={`config-status-pill ${row.status === 'active' ? 'active' : row.status === 'inactive' ? 'inactive' : 'archived'}`}>{row.status}</span>
              </div>
            </div>
          </div>
          <div className="faq-card-grid">
            <div><small>Arabic question</small><p>{summarizeText(row.question_ar)}</p></div>
            <div><small>English question</small><p>{summarizeText(row.english_question)}</p></div>
            <div><small>Arabic answer</small><p>{summarizeText(row.arabic_answer, 160)}</p></div>
            <div><small>English answer</small><p>{summarizeText(row.english_answer, 160)}</p></div>
          </div>
          <div className="button-row">
            <button type="button" className="secondary" onClick={() => startEdit(row)}>Edit</button>
            <button type="button" className="secondary" onClick={() => void toggleStatus(row)} disabled={busyId === row.id}>{row.status === 'active' ? 'Disable' : 'Enable'}</button>
            <button type="button" onClick={() => setPendingArchive(row)} disabled={busyId === row.id}>Archive</button>
          </div>
        </article>)}
      </div>
    </div>
    {pendingArchive && <div className="confirm-overlay" role="dialog" aria-modal="true">
      <div className="confirm-card">
        <h3>Archive this FAQ item?</h3>
        <p className="muted">{pendingArchive.topic_key}</p>
        <div className="button-row">
          <button onClick={() => void confirmArchive()} disabled={busyId === pendingArchive.id}>{busyId === pendingArchive.id ? 'Archiving...' : 'Archive'}</button>
          <button className="secondary" onClick={() => setPendingArchive(null)} disabled={busyId === pendingArchive.id}>Cancel</button>
        </div>
      </div>
    </div>}
  </section>;
}

function Intents({ intents, faq, routing, token, tenantSlug, reload }: { intents: IntentItem[]; faq: FaqItem[]; routing: RoutingRule[]; token: string; tenantSlug: string; reload: () => Promise<void> }) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [code, setCode] = useState('');
  const [label, setLabel] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [langAr, setLangAr] = useState(true);
  const [langEn, setLangEn] = useState(false);
  const [responseMode, setResponseMode] = useState('faq');
  const [defaultTopic, setDefaultTopic] = useState('');
  const [customResponseAr, setCustomResponseAr] = useState('');
  const [customResponseEn, setCustomResponseEn] = useState('');
  const [arabicKeywords, setArabicKeywords] = useState('');
  const [englishKeywords, setEnglishKeywords] = useState('');
  const [ownerRole, setOwnerRole] = useState('BOT');
  const [handoffRequired, setHandoffRequired] = useState(false);
  const [ticketType, setTicketType] = useState('');
  const [priority, setPriority] = useState('normal');
  const [notifyRoles, setNotifyRoles] = useState('');
  const [responseBehavior, setResponseBehavior] = useState('normal');
  const [followupQuestionAr, setFollowupQuestionAr] = useState('');
  const [followupQuestionEn, setFollowupQuestionEn] = useState('');
  const [pendingDelete, setPendingDelete] = useState<IntentItem | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const faqTopics = useMemo(() => faq.map((row) => row.topic_key).sort(), [faq]);
  const sortedIntents = useMemo(() => [...intents].sort((a, b) => a.code.localeCompare(b.code)), [intents]);
  const routingByIntent = useMemo(() => new Map(routing.map((row) => [row.intent_code, row])), [routing]);

  function applyRoutePreset(intentCode: string) {
    const normalized = normalizeIntentCode(intentCode);
    if (['GREETING', 'FAQ_GENERAL', 'LOCATION', 'SCHEDULES', 'PRICING', 'DELIVERY'].includes(normalized)) {
      setResponseBehavior('normal');
      setOwnerRole('BOT');
      setHandoffRequired(false);
      setTicketType('');
      setPriority('normal');
      setNotifyRoles('');
      setFollowupQuestionAr('');
      setFollowupQuestionEn('');
      return;
    }
    if (normalized === 'COMPLAINT') {
      setResponseBehavior('immediate_handoff');
      setOwnerRole('OPERATIONS_STAFF');
      setHandoffRequired(true);
      setTicketType('complaint');
      setPriority('high');
      setNotifyRoles('');
      setFollowupQuestionAr('');
      setFollowupQuestionEn('');
      return;
    }
    setResponseBehavior('immediate_handoff');
    setOwnerRole('OPERATIONS_STAFF');
    setHandoffRequired(true);
    setTicketType('handoff');
    setPriority('normal');
    setNotifyRoles('');
    setFollowupQuestionAr('');
    setFollowupQuestionEn('');
  }

  function resetForm() {
    setEditingId(null);
    setCode('');
    setLabel('');
    setEnabled(true);
    setLangAr(true);
    setLangEn(false);
    setResponseMode('faq');
    setDefaultTopic('');
    setCustomResponseAr('');
    setCustomResponseEn('');
    setArabicKeywords('');
    setEnglishKeywords('');
    applyRoutePreset('');
  }

  function setLanguages(mode: string) {
    setLangAr(mode === 'ar' || mode === 'both');
    setLangEn(mode === 'en' || mode === 'both');
  }

  function currentLanguageMode() {
    if (langAr && langEn) return 'both';
    if (langEn) return 'en';
    return 'ar';
  }

  function startEdit(intent: IntentItem) {
    setEditingId(intent.id);
    setCode(intent.code);
    setLabel(intent.label);
    setEnabled(intent.enabled);
    setLanguages(intent.supported_languages || 'ar');
    setResponseMode(intent.response_mode || 'faq');
    setDefaultTopic(intent.default_response_topic_key || '');
    setCustomResponseAr(intent.custom_response_ar || '');
    setCustomResponseEn(intent.custom_response_en || '');
    setArabicKeywords(intent.keywords.filter((item) => item.lang === 'ar').map((item) => item.phrase).join('\n'));
    setEnglishKeywords(intent.keywords.filter((item) => item.lang === 'en').map((item) => item.phrase).join('\n'));
    const route = routingByIntent.get(intent.code);
    if (route) {
      setResponseBehavior(route.response_behavior || (route.handoff_required ? 'immediate_handoff' : 'normal'));
      setOwnerRole(route.primary_owner_role);
      setHandoffRequired(route.handoff_required);
      setTicketType(route.ticket_type || '');
      setPriority(route.priority);
      setNotifyRoles((route.notify_roles_json || []).join(', '));
      setFollowupQuestionAr(route.followup_question_ar || '');
      setFollowupQuestionEn(route.followup_question_en || '');
    } else {
      applyRoutePreset(intent.code);
    }
  }

  async function syncKeywords(intent: IntentItem | undefined, intentCode: string) {
    const desiredByLang = {
      ar: langAr ? splitTextareaItems(arabicKeywords) : [],
      en: langEn ? splitTextareaItems(englishKeywords) : [],
    };
    const existing = intent?.keywords || [];
    const existingByLang = {
      ar: existing.filter((item) => item.lang === 'ar'),
      en: existing.filter((item) => item.lang === 'en'),
    };
    for (const lang of ['ar', 'en'] as const) {
      const desired = new Set(desiredByLang[lang]);
      for (const row of existingByLang[lang]) {
        if (!desired.has(row.phrase)) {
          await api.deleteKeyword(token, tenantSlug, row.id);
        }
      }
      const existingPhrases = new Set(existingByLang[lang].map((row) => row.phrase));
      for (const phrase of desiredByLang[lang]) {
        if (!existingPhrases.has(phrase)) {
          await api.createKeyword(token, tenantSlug, { intent_code: intentCode, phrase, weight: 2, lang });
        }
      }
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const normalizedCode = normalizeIntentCode(code);
    const languageMode = currentLanguageMode();
    const intentPayload = {
      code: normalizedCode,
      label,
      enabled,
      is_universal: false,
      supported_languages: languageMode,
      response_mode: responseMode,
      default_response_topic_key: responseMode === 'faq' || responseMode === 'business_settings' ? (defaultTopic || null) : null,
      custom_response_ar: responseMode === 'custom' ? (customResponseAr || null) : null,
      custom_response_en: responseMode === 'custom' ? (customResponseEn || null) : null,
    };

    if (editingId) {
      await api.updateIntent(token, tenantSlug, editingId, intentPayload);
    } else {
      await api.createIntent(token, tenantSlug, intentPayload);
    }

    const currentIntent = editingId
      ? intents.find((item) => item.id === editingId)
      : intents.find((item) => item.code === normalizedCode);
    await syncKeywords(currentIntent, normalizedCode);
    await api.saveRoutingRule(token, tenantSlug, normalizedCode, {
      intent_code: normalizedCode,
      primary_owner_role: responseBehavior === 'normal' ? 'BOT' : ownerRole,
      notify_roles_json: notifyRoles.split(',').map((item) => item.trim()).filter(Boolean),
      escalation_json: {},
      handoff_required: responseBehavior === 'immediate_handoff' ? true : false,
      ticket_type: responseBehavior === 'normal' ? null : (ticketType || 'handoff'),
      priority,
      response_behavior: responseBehavior,
      followup_question_ar: responseBehavior === 'offer_handoff' ? (followupQuestionAr || null) : null,
      followup_question_en: responseBehavior === 'offer_handoff' ? (followupQuestionEn || null) : null,
    });
    resetForm();
    await reload();
  }

  async function toggleEnabled(intent: IntentItem) {
    setBusyId(intent.id);
    try {
      await api.updateIntent(token, tenantSlug, intent.id, { enabled: !intent.enabled });
      if (editingId === intent.id) setEnabled(!intent.enabled);
      await reload();
    } finally {
      setBusyId(null);
    }
  }

  async function deleteKeyword(intent: IntentItem, keywordId: number) {
    setBusyId(intent.id);
    try {
      await api.deleteKeyword(token, tenantSlug, keywordId);
      await reload();
      if (editingId === intent.id) {
        const refreshed = intents.find((item) => item.id === intent.id);
        if (refreshed) startEdit(refreshed);
      }
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setBusyId(pendingDelete.id);
    try {
      await api.deleteIntent(token, tenantSlug, pendingDelete.id);
      if (editingId === pendingDelete.id) resetForm();
      setPendingDelete(null);
      await reload();
    } finally {
      setBusyId(null);
    }
  }

  return <section className="config-page config-page-two">
    <form className="card config-editor-card intents-editor-card" onSubmit={submit}>
      <div className="config-section-head">
        <div>
          <p className="eyebrow">Intent and routing manager</p>
          <h3>{editingId ? 'Edit tenant intent' : 'Create tenant intent'}</h3>
        </div>
        {editingId && <button type="button" className="secondary" onClick={resetForm}>New intent</button>}
      </div>
      <div className="config-form-grid">
        <label>Intent code<input value={code} onChange={(e) => setCode(e.target.value)} placeholder="PRICING" required disabled={editingId !== null} /></label>
        <label>Display name<input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Pricing" required /></label>
      </div>
      <div className="config-toggle-row">
        <label className="check-row"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled</label>
        <div className="language-toggle-group">
          <label className="check-row"><input type="checkbox" checked={langAr} onChange={(e) => { const next = e.target.checked; setLangAr(next); if (!next && !langEn) setLangEn(true); }} /> Arabic</label>
          <label className="check-row"><input type="checkbox" checked={langEn} onChange={(e) => { const next = e.target.checked; setLangEn(next); if (!next && !langAr) setLangAr(true); }} /> English</label>
        </div>
      </div>
      <div className="config-language-grid">
        {langAr && <div className="config-language-card">
          <div className="config-language-head"><strong>Arabic keywords / examples</strong><span className="config-badge">AR</span></div>
          <label>Arabic lines<textarea value={arabicKeywords} onChange={(e) => setArabicKeywords(e.target.value)} placeholder={'وين موقعكم\nكم السعر\nعندكم توصيل'} /></label>
        </div>}
        {langEn && <div className="config-language-card">
          <div className="config-language-head"><strong>English keywords / examples</strong><span className="config-badge secondary-pill">EN</span></div>
          <label>English lines<textarea value={englishKeywords} onChange={(e) => setEnglishKeywords(e.target.value)} placeholder={'where are you located\nhow much\ndo you deliver'} /></label>
        </div>}
      </div>
      <div className="config-block">
        <div className="config-language-head"><strong>Response source</strong></div>
        <div className="config-toggle-row">
          <label className="check-row"><input type="radio" checked={responseMode === 'faq'} onChange={() => setResponseMode('faq')} /> FAQ answer</label>
          <label className="check-row"><input type="radio" checked={responseMode === 'custom'} onChange={() => setResponseMode('custom')} /> Custom direct response</label>
          <label className="check-row"><input type="radio" checked={responseMode === 'business_settings'} onChange={() => setResponseMode('business_settings')} /> Business settings automatic answer</label>
        </div>
        {responseMode === 'faq' || responseMode === 'business_settings' ? <label>{responseMode === 'business_settings' ? 'Optional fallback FAQ topic' : 'FAQ topic key'}
          <select value={defaultTopic} onChange={(e) => setDefaultTopic(e.target.value)}>
            <option value="">{responseMode === 'business_settings' ? 'No FAQ fallback selected' : 'Select FAQ topic'}</option>
            {faqTopics.map((topic) => <option key={topic} value={topic}>{topic}</option>)}
          </select>
        </label> : <div className="config-language-grid">
          <div className="config-language-card">
            <div className="config-language-head"><strong>Arabic direct response</strong><span className="config-badge">AR</span></div>
            <label>Arabic response<textarea value={customResponseAr} onChange={(e) => setCustomResponseAr(e.target.value)} placeholder="اكتب الرد العربي المباشر" /></label>
          </div>
          <div className="config-language-card">
            <div className="config-language-head"><strong>English direct response</strong><span className="config-badge secondary-pill">EN</span></div>
            <label>English response<textarea value={customResponseEn} onChange={(e) => setCustomResponseEn(e.target.value)} placeholder="Optional English response" /></label>
          </div>
        </div>}
        {responseMode === 'business_settings' && <p className="muted">Use live tenant Settings data for answers like branch location, opening hours, or support phone. The bot will generate the reply at runtime in the customer&apos;s language.</p>}
      </div>
      <div className="config-block">
        <div className="config-language-head"><strong>Routing behavior</strong></div>
        <label>What should happen after this intent?
          <select value={responseBehavior} onChange={(e) => {
            const next = e.target.value;
            setResponseBehavior(next);
            if (next === 'normal') {
              setOwnerRole('BOT');
              setHandoffRequired(false);
              setTicketType('');
              setFollowupQuestionAr('');
              setFollowupQuestionEn('');
            } else if (next === 'immediate_handoff') {
              if (ownerRole === 'BOT') setOwnerRole('OPERATIONS_STAFF');
              setHandoffRequired(true);
              if (!ticketType) setTicketType('handoff');
              setFollowupQuestionAr('');
              setFollowupQuestionEn('');
            } else {
              if (ownerRole === 'BOT') setOwnerRole('OPERATIONS_STAFF');
              setHandoffRequired(false);
              if (!ticketType) setTicketType('handoff');
            }
          }}>
            <option value="normal">Bot answers only</option>
            <option value="immediate_handoff">Hand off to human immediately</option>
            <option value="offer_handoff">Bot answers, then asks if customer wants a human</option>
          </select>
        </label>
        <div className="config-form-grid">
          <label>{responseBehavior === 'offer_handoff' ? 'Owner role if customer says yes' : 'Owner role'}
            <select value={ownerRole} onChange={(e) => { setOwnerRole(e.target.value); if (e.target.value === 'BOT' && responseBehavior !== 'normal') setOwnerRole('OPERATIONS_STAFF'); }}>
              <option value="BOT">BOT</option>
              <option value="OPERATIONS_STAFF">OPERATIONS_STAFF</option>
              <option value="FINANCE">FINANCE</option>
              <option value="CERTIFICATES">CERTIFICATES</option>
              <option value="SUPERVISOR">SUPERVISOR</option>
              <option value="BUSINESS_ADMIN">BUSINESS_ADMIN</option>
            </select>
          </label>
          <label>Priority
            <select value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option value="normal">normal</option>
              <option value="high">high</option>
              <option value="urgent">urgent</option>
            </select>
          </label>
          <label className="check-row"><input type="checkbox" checked={handoffRequired} disabled /> Handoff required</label>
          <label>{responseBehavior === 'offer_handoff' ? 'Ticket type if customer says yes' : 'Ticket type'}<input value={ticketType} disabled={responseBehavior === 'normal'} onChange={(e) => setTicketType(e.target.value)} placeholder="handoff / complaint / payment" /></label>
        </div>
        <label>Notify roles<input value={notifyRoles} onChange={(e) => setNotifyRoles(e.target.value)} placeholder="OPERATIONS_STAFF, SUPERVISOR" /></label>
        {responseBehavior === 'offer_handoff' && <div className="config-language-grid">
          <div className="config-language-card">
            <div className="config-language-head"><strong>Follow-up question Arabic</strong><span className="config-badge">AR</span></div>
            <label>Arabic follow-up<textarea value={followupQuestionAr} onChange={(e) => setFollowupQuestionAr(e.target.value)} placeholder="هل تحتاج تفاصيل إضافية من موظف؟" required={responseBehavior === 'offer_handoff'} /></label>
          </div>
          <div className="config-language-card">
            <div className="config-language-head"><strong>Follow-up question English</strong><span className="config-badge secondary-pill">EN</span></div>
            <label>English follow-up<textarea value={followupQuestionEn} onChange={(e) => setFollowupQuestionEn(e.target.value)} placeholder="Would you like me to direct you to a human agent?" /></label>
          </div>
        </div>}
      </div>
      <div className="button-row">
        <button>{editingId ? 'Save intent changes' : 'Create intent'}</button>
        {editingId && <button type="button" className="secondary" onClick={resetForm}>Cancel edit</button>}
      </div>
    </form>
    <div className="card config-library-card">
      <div className="config-section-head">
        <div>
          <p className="eyebrow">Saved intents</p>
          <h3>{sortedIntents.length} tenant intents</h3>
        </div>
      </div>
      <div className="config-card-list">
        {sortedIntents.length === 0 && <p className="muted">No intents yet.</p>}
        {sortedIntents.map((intent) => {
          const route = routingByIntent.get(intent.code);
          const arKeywords = intent.keywords.filter((item) => item.lang === 'ar');
          const enKeywords = intent.keywords.filter((item) => item.lang === 'en');
          return <article className="config-item-card intent-item-card" key={intent.id}>
            <div className="config-item-head">
              <div>
                <strong>{intent.label}</strong>
                <p className="config-code-line">{intent.code}</p>
                <div className="config-inline-meta">
                  <span className="config-badge">{intentLanguageLabel(intent.supported_languages)}</span>
                  <span className={`config-status-pill ${intent.enabled ? 'active' : 'inactive'}`}>{intent.enabled ? 'enabled' : 'disabled'}</span>
                  <span className="config-badge secondary-pill">{intent.response_mode === 'faq' ? `FAQ: ${intent.default_response_topic_key || 'not linked'}` : intent.response_mode === 'business_settings' ? `Settings auto: ${intent.default_response_topic_key || 'dynamic'}` : 'Custom response'}</span>
                  <span className="config-badge secondary-pill">{route?.response_behavior === 'offer_handoff' ? 'Offer handoff' : route?.response_behavior === 'immediate_handoff' ? 'Immediate handoff' : 'Bot answer only'}</span>
                </div>
              </div>
            </div>
            <div className="intent-card-grid">
              <div>
                <small>Arabic keywords</small>
                <div className="chip-cloud">
                  {arKeywords.length > 0 ? arKeywords.map((item) => <button type="button" className="config-chip" key={item.id} onClick={() => void deleteKeyword(intent, item.id)} disabled={busyId === intent.id}>{item.phrase} ×</button>) : <p className="muted">No Arabic keywords</p>}
                </div>
              </div>
              <div>
                <small>English keywords</small>
                <div className="chip-cloud">
                  {enKeywords.length > 0 ? enKeywords.map((item) => <button type="button" className="config-chip secondary-chip" key={item.id} onClick={() => void deleteKeyword(intent, item.id)} disabled={busyId === intent.id}>{item.phrase} ×</button>) : <p className="muted">No English keywords</p>}
                </div>
              </div>
              <div>
                <small>Response</small>
                <p>{intent.response_mode === 'faq' ? `Linked to FAQ topic: ${intent.default_response_topic_key || 'none'}` : intent.response_mode === 'business_settings' ? `Automatic from business settings${intent.default_response_topic_key ? ` with FAQ fallback: ${intent.default_response_topic_key}` : ''}` : summarizeText(intent.custom_response_ar || intent.custom_response_en, 140)}</p>
              </div>
              <div>
                <small>Routing</small>
                <p>{route ? `${route.primary_owner_role} · ${route.priority} · ${route.response_behavior === 'offer_handoff' ? `offer handoff / ${route.ticket_type || 'handoff'}` : route.handoff_required ? `handoff / ${route.ticket_type || 'handoff'}` : 'bot reply'}` : 'No routing rule yet'}</p>
              </div>
              {route?.response_behavior === 'offer_handoff' && <div>
                <small>Follow-up question</small>
                <p>{summarizeText(route.followup_question_ar || route.followup_question_en || '', 140)}</p>
              </div>}
            </div>
            <div className="button-row">
              <button type="button" className="secondary" onClick={() => startEdit(intent)}>Edit</button>
              <button type="button" className="secondary" onClick={() => void toggleEnabled(intent)} disabled={busyId === intent.id}>{intent.enabled ? 'Disable' : 'Enable'}</button>
              <button type="button" onClick={() => setPendingDelete(intent)} disabled={busyId === intent.id}>Delete</button>
            </div>
          </article>;
        })}
      </div>
    </div>
    {pendingDelete && <div className="confirm-overlay" role="dialog" aria-modal="true">
      <div className="confirm-card">
        <h3>Delete this intent?</h3>
        <p className="muted">{pendingDelete.label} · {pendingDelete.code}</p>
        <div className="button-row">
          <button onClick={() => void confirmDelete()} disabled={busyId === pendingDelete.id}>{busyId === pendingDelete.id ? 'Deleting...' : 'Delete'}</button>
          <button className="secondary" onClick={() => setPendingDelete(null)} disabled={busyId === pendingDelete.id}>Cancel</button>
        </div>
      </div>
    </div>}
  </section>;
}

function Channels({ rows, token, tenantSlug, reload }: { rows: Channel[]; token: string; tenantSlug: string; reload: () => Promise<void> }) {
  const [channel, setChannel] = useState('whatsapp');
  const [status, setStatus] = useState('configured');
  const [enabled, setEnabled] = useState('true');
  const [liveSendEnabled, setLiveSendEnabled] = useState('false');
  const [phoneNumberId, setPhoneNumberId] = useState('');
  const [accessToken, setAccessToken] = useState('');
  const [verifyToken, setVerifyToken] = useState('');
  const [appSecret, setAppSecret] = useState('');
  const [botToken, setBotToken] = useState('');

  useEffect(() => {
    const current = rows.find((row) => row.channel_type === channel);
    const publicConfig = current?.public_config || {};
    if (current) {
      setStatus(current.status || 'configured');
      setEnabled(publicConfig.enabled === false ? 'false' : 'true');
      setLiveSendEnabled(publicConfig.live_send_enabled === true ? 'true' : 'false');
      setPhoneNumberId(String(publicConfig.phone_number_id || ''));
      return;
    }
    if (channel === 'telegram') {
      setStatus('not_connected');
      setEnabled('true');
      setLiveSendEnabled('false');
      setPhoneNumberId('');
      return;
    }
    if (channel === 'whatsapp') {
      setStatus('configured');
      setEnabled('true');
      setLiveSendEnabled('false');
      setPhoneNumberId('');
      return;
    }
    setStatus('future');
    setEnabled('false');
    setLiveSendEnabled('false');
    setPhoneNumberId('');
  }, [channel, rows]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const publicConfig: Record<string, unknown> = {
      enabled: enabled === 'true',
      live_send_enabled: liveSendEnabled === 'true',
    };
    const credentials: Record<string, unknown> = {};

    if (channel === 'whatsapp') {
      if (phoneNumberId.trim()) {
        publicConfig.phone_number_id = phoneNumberId.trim();
        credentials.phone_number_id = phoneNumberId.trim();
      }
      if (accessToken.trim()) credentials.access_token = accessToken.trim();
      if (verifyToken.trim()) credentials.verify_token = verifyToken.trim();
      if (appSecret.trim()) credentials.app_secret = appSecret.trim();
    }

    if (channel === 'telegram' && botToken.trim()) {
      credentials.bot_token = botToken.trim();
    }

    await api.saveChannel(token, tenantSlug, channel, { status, public_config: publicConfig, credentials });
    await reload();
  }

  return <section className="grid two channels-layout">
    <form className="card form-stack channel-form-card" onSubmit={submit}>
      <p className="eyebrow">Channel settings</p>
      <h3>Tenant-scoped channel config</h3>
      <label>Channel<select value={channel} onChange={(e) => setChannel(e.target.value)}><option value="whatsapp">whatsapp</option><option value="telegram">telegram</option><option value="email">email</option><option value="instagram">instagram</option><option value="facebook">facebook</option><option value="web_chat">web_chat</option></select></label>
      <label>Status<select value={status} onChange={(e) => setStatus(e.target.value)}><option value="connected">connected</option><option value="configured">configured</option><option value="not_connected">not_connected</option><option value="future">future</option><option value="active">active</option></select></label>
      <div className="two-field-row">
        <label>Enabled<select value={enabled} onChange={(e) => setEnabled(e.target.value)}><option value="true">true</option><option value="false">false</option></select></label>
        <label>Live send enabled<select value={liveSendEnabled} onChange={(e) => setLiveSendEnabled(e.target.value)}><option value="true">true</option><option value="false">false</option></select></label>
      </div>
      {channel === 'whatsapp' && <>
        <label>Phone number ID<input placeholder="demo" value={phoneNumberId} onChange={(e) => setPhoneNumberId(e.target.value)} /></label>
        <label>Access token<input placeholder="Paste WhatsApp access token" value={accessToken} onChange={(e) => setAccessToken(e.target.value)} /></label>
        <label>Verify token<input placeholder="demo-verify" value={verifyToken} onChange={(e) => setVerifyToken(e.target.value)} /></label>
        <label>App secret<input placeholder="pending" value={appSecret} onChange={(e) => setAppSecret(e.target.value)} /></label>
      </>}
      {channel === 'telegram' && <label>Bot token<input placeholder="123456:telegram-demo-token" value={botToken} onChange={(e) => setBotToken(e.target.value)} /></label>}
      {channel !== 'whatsapp' && channel !== 'telegram' && <p className="muted">This channel currently only needs basic status and enabled settings.</p>}
      <button>Save encrypted config</button>
    </form>
    <div className="card channel-list-card">
      <h3>Channels</h3>
      <div className="channel-table">
        {rows.map((row) => {
          const enabledFlag = row.public_config?.enabled === true;
          const liveFlag = row.public_config?.live_send_enabled === true;
          const fullyConnected = enabledFlag && row.has_credentials && liveFlag && ['connected', 'configured', 'active'].includes(row.status);
          return <div className="channel-status-card" key={row.channel_type}>
            <div className="channel-status-head">
              <div className={`status-dot ${fullyConnected ? 'on' : 'off'}`} />
              <div>
                <strong>{row.channel_type}</strong>
                <p>{row.status}</p>
              </div>
            </div>
            <div className="channel-status-grid">
              <div><small>Enabled</small><span>{enabledFlag ? 'true' : 'false'}</span></div>
              <div><small>Live send</small><span>{liveFlag ? 'true' : 'false'}</span></div>
              <div><small>Credentials</small><span>{row.has_credentials ? 'saved' : 'missing'}</span></div>
              <div><small>Phone ID</small><span>{String(row.public_config?.phone_number_id || 'not set')}</span></div>
            </div>
          </div>;
        })}
      </div>
    </div>
  </section>;
}

function Tickets({ rows, token, tenantSlug, reload, openConversation }: { rows: Ticket[]; token: string; tenantSlug: string; reload: () => Promise<void>; openConversation: (id: number) => Promise<void> }) {
  const [filter, setFilter] = useState<'active' | 'escalated' | 'resolved' | 'all'>('active');
  const [ticketMessage, setTicketMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [resolvingId, setResolvingId] = useState<number | null>(null);
  const ticketGridRef = useRef<HTMLDivElement | null>(null);
  const statusClass = (value: string) => value.toLowerCase().replace(/[^a-z0-9_-]/g, '-');
  const isResolved = (row: Ticket) => ['resolved', 'closed'].includes(row.status.toLowerCase());
  const isEscalated = (row: Ticket) => ['high', 'urgent'].includes(row.priority.toLowerCase()) || row.status.toLowerCase() === 'escalated';
  const activeRows = rows.filter((row) => !isResolved(row));
  const escalatedRows = rows.filter(isEscalated);
  const resolvedRows = rows.filter(isResolved);
  const visibleRows = filter === 'active' ? activeRows : filter === 'escalated' ? escalatedRows : filter === 'resolved' ? resolvedRows : rows;
  const filterOptions: Array<{ key: typeof filter; label: string; count: number }> = [
    { key: 'active', label: 'Active', count: activeRows.length },
    { key: 'escalated', label: 'Escalated', count: escalatedRows.length },
    { key: 'resolved', label: 'Resolved', count: resolvedRows.length },
    { key: 'all', label: 'All', count: rows.length },
  ];

  useEffect(() => {
    const grid = ticketGridRef.current;
    if (!grid) return;
    const cards = Array.from(grid.querySelectorAll<HTMLElement>('.ticket-card'));
    if (!('IntersectionObserver' in window)) {
      cards.forEach((card) => card.classList.add('is-visible'));
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        entry.target.classList.toggle('is-visible', entry.isIntersecting);
      });
    }, { root: null, threshold: .18, rootMargin: '-8% 0px -10% 0px' });
    cards.forEach((card) => observer.observe(card));
    return () => observer.disconnect();
  }, [visibleRows.length, filter]);

  async function resolveTicket(ticket: Ticket) {
    setResolvingId(ticket.id);
    setTicketMessage(null);
    try {
      await api.updateTicket(token, tenantSlug, ticket.id, { status: 'resolved' });
      setTicketMessage({ type: 'success', text: `Ticket #${ticket.id} resolved. It remains available in Resolved and All.` });
      await reload();
    } catch (err) {
      setTicketMessage({ type: 'error', text: err instanceof Error ? err.message : 'Failed to resolve ticket' });
    } finally {
      setResolvingId(null);
    }
  }

  return <section className="card tickets-page">
    <div className="tickets-head">
      <div><p className="eyebrow">Tickets</p><h3>Queues and escalations</h3><p className="muted">Track handoffs, complaints, finance, certificate, and supervisor review cases.</p></div>
      <div className="tickets-summary">
        <div><small>Open</small><strong>{activeRows.length}</strong></div>
        <div><small>Escalated</small><strong>{escalatedRows.length}</strong></div>
        <div><small>Total</small><strong>{rows.length}</strong></div>
      </div>
    </div>
    <div className="ticket-filter-tabs" role="tablist" aria-label="Ticket queue filter">
      {filterOptions.map((option) => <button key={option.key} className={filter === option.key ? 'active' : ''} onClick={() => setFilter(option.key)} role="tab" aria-selected={filter === option.key}>{option.label}<span>{option.count}</span></button>)}
    </div>
    {ticketMessage && <div className={`ticket-message ${ticketMessage.type}`} role="status">{ticketMessage.text}</div>}
    {rows.length === 0 && <div className="tickets-empty-state"><strong>No tickets yet</strong><p>Escalations and human-review cases will appear here when conversations require operational follow-up.</p></div>}
    {rows.length > 0 && visibleRows.length === 0 && <div className="tickets-empty-state"><strong>No tickets in {filter}</strong><p>Switch filters to review the rest of the queue.</p></div>}
    <div className="tickets-grid tickets-scroll-queue" ref={ticketGridRef}>
      {visibleRows.map((t) => <article className={`ticket-card ticket-status-${statusClass(t.status)} ticket-priority-${statusClass(t.priority)}`} key={t.id}>
        <div className="ticket-card-top">
          <div>
            <span className="ticket-id">#{t.id}</span>
            <h4>{t.ticket_type || 'general'}</h4>
          </div>
          <span className={`ticket-status-pill ${statusClass(t.status)}`}>{t.status}</span>
        </div>
        <div className="ticket-badge-row">
          <span className={`ticket-priority-pill ${statusClass(t.priority)}`}>{t.priority} priority</span>
          <span className="ticket-soft-pill">Conversation #{t.conversation_id}</span>
        </div>
        <div className="ticket-meta-grid">
          <div><small>Assignee</small><strong>{t.assigned_to || 'unassigned'}</strong></div>
          <div><small>Type</small><strong>{t.ticket_type || 'general'}</strong></div>
          <div><small>Status</small><strong>{t.status}</strong></div>
        </div>
        <div className="button-row ticket-actions"><button onClick={() => void openConversation(t.conversation_id)}>Open conversation</button><button className="secondary ticket-resolve-button" disabled={resolvingId === t.id} onClick={() => void resolveTicket(t)}>{resolvingId === t.id ? 'Resolving...' : 'Resolve'}</button></div>
      </article>)}
    </div>
  </section>;
}

function Customers({ rows }: { rows: Customer[] }) {
  const [selectedId, setSelectedId] = useState<number | null>(rows[0]?.id ?? null);
  const selected = rows.find((row) => row.id === selectedId) || rows[0] || null;
  const optedInCount = rows.filter((row) => row.opt_in).length;
  const taggedCount = rows.filter((row) => (row.tags_json || []).length > 0).length;

  useEffect(() => {
    if (rows.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!rows.some((row) => row.id === selectedId)) setSelectedId(rows[0].id);
  }, [rows, selectedId]);

  return <section className="customers-workspace">
    <div className="card customers-list-panel">
      <div className="customers-head">
        <div><p className="eyebrow">Customers</p><h3>Customer records</h3><p className="muted">Tenant-safe identity, consent, tags, and support context.</p></div>
        <div className="customers-summary">
          <div><small>Total</small><strong>{rows.length}</strong></div>
          <div><small>Opted in</small><strong>{optedInCount}</strong></div>
          <div><small>Tagged</small><strong>{taggedCount}</strong></div>
        </div>
      </div>
      {rows.length === 0 && <div className="customers-empty-state"><strong>No customers yet</strong><p>Customer records will appear here after conversations or imports create tenant-scoped profiles.</p></div>}
      <div className="customers-grid">
        {rows.map((customer, index) => {
          const isSelected = selected?.id === customer.id;
          return <button className={`customer-card${isSelected ? ' active' : ''}`} aria-current={isSelected ? 'true' : undefined} style={{ animationDelay: `${Math.min(index * 45, 260)}ms` }} key={customer.id} onClick={() => setSelectedId(customer.id)}>
            <span className="customer-card-top">
              <span>
                <strong>{customer.name || customer.phone}</strong>
                <small>{customer.phone}</small>
              </span>
              <span className={`customer-opt-pill ${customer.opt_in ? 'in' : 'out'}`}>{customer.opt_in ? 'Opted in' : 'Opt-out'}</span>
            </span>
            <span className="customer-email">{customer.email || 'No email on record'}</span>
            <span className="customer-tags">{(customer.tags_json || []).length > 0 ? customer.tags_json.slice(0, 4).map((tag) => <span key={tag}>{tag}</span>) : <span>No tags</span>}</span>
          </button>;
        })}
      </div>
    </div>
    <aside className="card customer-detail-panel">
      <p className="eyebrow">Customer context</p>
      {selected ? <>
        <div className="customer-detail-head">
          <div><h3>{selected.name || selected.phone}</h3><p>{selected.email || 'No email on record'}</p></div>
          <span className={`customer-opt-pill ${selected.opt_in ? 'in' : 'out'}`}>{selected.opt_in ? 'Opted in' : 'Opt-out'}</span>
        </div>
        <div className="customer-meta-grid">
          <div><small>Phone</small><strong>{selected.phone}</strong></div>
          <div><small>Preferred language</small><strong>{selected.preferred_lang || 'not set'}</strong></div>
          <div><small>Customer ID</small><strong>#{selected.id}</strong></div>
        </div>
        <div className="customer-detail-section">
          <small>Tags</small>
          <div className="customer-tags detail-tags">{(selected.tags_json || []).length > 0 ? selected.tags_json.map((tag) => <span key={tag}>{tag}</span>) : <span>No tags yet</span>}</div>
        </div>
        <div className="customer-detail-section">
          <small>History</small>
          <p className="muted">Conversation activity is available from the Inbox and Tickets workflows when linked records exist.</p>
        </div>
      </> : <div className="customers-empty-state detail-empty"><strong>Select a customer</strong><p>Customer metadata and tags will appear here.</p></div>}
    </aside>
  </section>;
}

function Broadcasts({ rows, token, tenantSlug, reload }: { rows: Broadcast[]; token: string; tenantSlug: string; reload: () => Promise<void> }) {
  const [title, setTitle] = useState('');
  const [template, setTemplate] = useState('');
  const [messageText, setMessageText] = useState('');
  const [channelType, setChannelType] = useState('auto');
  const [busyId, setBusyId] = useState<number | null>(null);
  const [editingBroadcast, setEditingBroadcast] = useState<Broadcast | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editTemplate, setEditTemplate] = useState('');
  const [editMessageText, setEditMessageText] = useState('');
  const [editChannelType, setEditChannelType] = useState('auto');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [recipients, setRecipients] = useState<BroadcastRecipient[]>([]);
  const [statusText, setStatusText] = useState<string | null>(null);
  const statusClass = (value?: string | null) => (value || 'draft').toLowerCase().replace(/[^a-z0-9_-]/g, '-');
  const draftCount = rows.filter((row) => ['draft', 'created', 'queued'].includes(statusClass(row.status))).length;
  const sentCount = rows.filter((row) => ['sent', 'completed', 'delivered'].includes(statusClass(row.status))).length;
  const selectedBroadcast = rows.find((row) => row.id === selectedId) || null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    const payload = {
      title,
      template_ref: template || null,
      audience_type: 'all',
      channel_type: channelType,
      payload: { message_text: messageText },
    };
    await api.createBroadcast(token, tenantSlug, payload);
    setStatusText('Broadcast draft created');
    setTitle('');
    setTemplate('');
    setMessageText('');
    setChannelType('auto');
    await reload();
  }

  function editBroadcast(row: Broadcast) {
    setEditingBroadcast(row);
    setEditTitle(row.title);
    setEditTemplate(row.template_ref || '');
    setEditMessageText(row.message_text || '');
    setEditChannelType(row.channel_type || 'auto');
  }

  function cancelEdit(clearStatus = true) {
    setEditingBroadcast(null);
    setEditTitle('');
    setEditTemplate('');
    setEditMessageText('');
    setEditChannelType('auto');
    if (clearStatus) setStatusText(null);
  }

  async function submitEdit(e: FormEvent) {
    e.preventDefault();
    if (!editingBroadcast) return;
    const editId = editingBroadcast.id;
    setBusyId(editId);
    setStatusText(null);
    try {
      await api.updateBroadcast(token, tenantSlug, editId, {
        title: editTitle,
        template_ref: editTemplate || null,
        audience_type: 'all',
        channel_type: editChannelType,
        payload: { message_text: editMessageText },
      });
      setStatusText(`Broadcast ${editId} updated`);
      cancelEdit(false);
      await reload();
    } catch (err) {
      setStatusText(err instanceof Error ? err.message : 'Broadcast update failed');
    } finally {
      setBusyId(null);
    }
  }

  async function openRecipients(broadcastId: number) {
    if (selectedId === broadcastId) {
      setSelectedId(null);
      setRecipients([]);
      return;
    }
    setSelectedId(broadcastId);
    setRecipients(await api.broadcastRecipients(token, tenantSlug, broadcastId));
  }

  async function sendNow(broadcastId: number) {
    setBusyId(broadcastId);
    setStatusText(null);
    try {
      const result = await api.sendBroadcast(token, tenantSlug, broadcastId);
      setStatusText(`Broadcast ${result.broadcast_id} sent via ${result.channel_type || 'resolved channel'}: ${result.sent_recipients} sent, ${result.failed_recipients} failed`);
      await reload();
      await openRecipients(broadcastId);
    } catch (err) {
      setStatusText(err instanceof Error ? err.message : 'Broadcast send failed');
    } finally {
      setBusyId(null);
    }
  }

  async function deleteNow(broadcastId: number) {
    setBusyId(broadcastId);
    setStatusText(null);
    try {
      await api.deleteBroadcast(token, tenantSlug, broadcastId);
      if (selectedId === broadcastId) {
        setSelectedId(null);
        setRecipients([]);
      }
      setStatusText(`Broadcast ${broadcastId} deleted`);
      await reload();
    } catch (err) {
      setStatusText(err instanceof Error ? err.message : 'Broadcast delete failed');
    } finally {
      setBusyId(null);
    }
  }

  return <>
  <section className="grid two broadcasts-layout">
    <form className="card form-stack broadcast-form-card campaign-form-card" onSubmit={submit}>
      <div className="campaign-form-head">
        <div><p className="eyebrow">Broadcasts</p><h3>Create campaign</h3><p className="muted">Prepare tenant-safe messaging for the selected channel.</p></div>
        <span className="campaign-mode-pill">Draft</span>
      </div>
      <label>Title<input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Campaign title" /></label>
      <label>Message text<textarea placeholder="Write the real broadcast message to send through the tenant channel" value={messageText} onChange={(e) => setMessageText(e.target.value)} /></label>
      <div className="campaign-form-grid">
        <label>Template reference<input value={template} onChange={(e) => setTemplate(e.target.value)} placeholder="Optional template key" /></label>
        <label>Channel preference<select value={channelType} onChange={(e) => setChannelType(e.target.value)}><option value="auto">auto</option><option value="whatsapp">whatsapp</option><option value="telegram">telegram</option></select></label>
      </div>
      <div className="campaign-form-actions">
        <button className="campaign-primary-action">Create draft</button>
      </div>
      {statusText && <div className={`broadcast-status-note ${statusText.toLowerCase().includes('failed') ? 'error' : 'success'}`} role="status">{statusText}</div>}
    </form>
    <div className="card broadcast-list-card campaign-list-card">
      <div className="campaign-list-head">
        <div><p className="eyebrow">Campaign queue</p><h3>Campaigns</h3></div>
        <div className="campaign-summary">
          <div><small>Draft</small><strong>{draftCount}</strong></div>
          <div><small>Sent</small><strong>{sentCount}</strong></div>
          <div><small>Total</small><strong>{rows.length}</strong></div>
        </div>
      </div>
      {rows.length === 0 && <div className="broadcast-empty-state"><strong>No campaigns yet</strong><p>Create a draft campaign to prepare tenant-scoped outbound messaging.</p></div>}
      <div className="broadcast-card-grid">
        {rows.map((row) => <article className={`broadcast-card campaign-card campaign-status-${statusClass(row.status)}`} key={row.id}>
          <button className="close-chip campaign-delete-chip" type="button" aria-label={`Delete ${row.title}`} disabled={busyId === row.id} onClick={() => void deleteNow(row.id)}>x</button>
          <div className="campaign-card-top">
            <div><span className="campaign-id">#{row.id}</span><h4>{row.title}</h4></div>
            <span className={`campaign-status-pill ${statusClass(row.status)}`}>{row.status}</span>
          </div>
          <div className="campaign-badges">
            <span>{row.channel_type || 'auto channel'}</span>
            <span>{row.audience_type || 'all audience'}</span>
            {row.schedule_at && <span>Scheduled {formatMessageTime(row.schedule_at)}</span>}
          </div>
          <div className="campaign-meta-grid">
            <div><small>Template</small><strong>{row.template_ref || 'No template'}</strong></div>
            <div><small>Status</small><strong>{row.status}</strong></div>
            <div><small>Created</small><strong>{formatMessageTime(row.created_at)}</strong></div>
          </div>
          <div className="button-row campaign-actions">
            <button disabled={busyId === row.id || row.status === 'sending'} onClick={() => void sendNow(row.id)}>
              {busyId === row.id ? 'Sending...' : 'Send'}
            </button>
            <button className="secondary" disabled={row.status === 'sending' || row.status === 'sent'} onClick={() => editBroadcast(row)}>Edit</button>
            <button className="secondary" onClick={() => void openRecipients(row.id)}>{selectedId === row.id ? 'Hide recipients' : 'Recipients'}</button>
          </div>
        </article>)}
      </div>
      {selectedId && <div className="recipient-results-panel">
        <div className="recipient-results-head">
          <div><p className="eyebrow">Recipient results</p><h4>{selectedBroadcast?.title || `Broadcast #${selectedId}`}</h4></div>
          <span className="campaign-mode-pill">{recipients.length} tracked</span>
        </div>
        {recipients.length === 0 && <div className="broadcast-empty-state compact"><strong>No tracked recipients yet</strong><p>Recipient delivery status appears after a campaign is sent.</p></div>}
        <div className="recipient-grid">
          {recipients.map((recipient) => <div className="recipient-card" key={recipient.id}>
            <div><strong>Customer #{recipient.customer_id}</strong><span className={`recipient-status-pill ${statusClass(recipient.status)}`}>{recipient.status}</span></div>
            <small>{recipient.delivered_at ? `Delivered ${formatMessageTime(recipient.delivered_at)}` : 'Delivery timestamp pending'}</small>
          </div>)}
        </div>
      </div>}
    </div>
  </section>
  {typeof document !== 'undefined' && editingBroadcast && createPortal(<div className="confirm-overlay" role="dialog" aria-modal="true" aria-labelledby="broadcast-edit-title">
    <form className="confirm-card broadcast-edit-card form-stack" onSubmit={submitEdit}>
      <div className="campaign-form-head">
        <div><p className="eyebrow">Edit broadcast</p><h3 id="broadcast-edit-title">Campaign #{editingBroadcast.id}</h3><p className="muted">Update this campaign before it is sent.</p></div>
        <span className={`campaign-status-pill ${statusClass(editingBroadcast.status)}`}>{editingBroadcast.status}</span>
      </div>
      <label>Title<input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} placeholder="Campaign title" /></label>
      <label>Message text<textarea placeholder="Write the real broadcast message to send through the tenant channel" value={editMessageText} onChange={(e) => setEditMessageText(e.target.value)} /></label>
      <div className="campaign-form-grid">
        <label>Template reference<input value={editTemplate} onChange={(e) => setEditTemplate(e.target.value)} placeholder="Optional template key" /></label>
        <label>Channel preference<select value={editChannelType} onChange={(e) => setEditChannelType(e.target.value)}><option value="auto">auto</option><option value="whatsapp">whatsapp</option><option value="telegram">telegram</option></select></label>
      </div>
      <div className="button-row">
        <button type="submit" disabled={busyId === editingBroadcast.id}>{busyId === editingBroadcast.id ? 'Saving...' : 'Save changes'}</button>
        <button className="secondary" type="button" onClick={() => cancelEdit()} disabled={busyId === editingBroadcast.id}>Cancel</button>
      </div>
    </form>
  </div>, document.body)}
  </>;
}

function SimpleRows<T extends object>({ rows }: { rows: T[] }) {
  return <div className="list">{rows.length === 0 && <p className="muted">No rows yet.</p>}{rows.map((r, idx) => <pre key={idx}>{JSON.stringify(r, null, 2)}</pre>)}</div>;
}

function SimpleTable<T extends object>({ title, rows }: { title: string; rows: T[] }) {
  const keys = useMemo(() => Array.from(new Set(rows.flatMap((r) => Object.keys(r)))).slice(0, 8), [rows]);
  return <section className="card"><p className="eyebrow">Data</p><h3>{title}</h3>{rows.length === 0 ? <p className="muted">No rows yet.</p> : <div className="table-wrap"><table><thead><tr>{keys.map((k) => <th key={k}>{k}</th>)}</tr></thead><tbody>{rows.map((r, i) => { const obj = r as Record<string, unknown>; return <tr key={i}>{keys.map((k) => <td key={k}>{typeof obj[k] === 'object' ? JSON.stringify(obj[k]) : String(obj[k] ?? '')}</td>)}</tr>; })}</tbody></table></div>}</section>;
}
