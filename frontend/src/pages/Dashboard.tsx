import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import {
  api,
  resolveAssetUrl,
  type Analytics,
  type Branch,
  type Broadcast,
  type BroadcastRecipient,
  type Channel,
  type ChannelTestConsoleResult,
  type ConversationDetail,
  type Customer,
  type FaqItem,
  type InboxItem,
  type IntentItem,
  type Readiness,
  type RuntimeClassification,
  type SmartImportPreview,
  type SmartImportRow,
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
  const metricEntries = analytics ? Object.entries(analytics).filter(([, value]) => typeof value === 'number') as Array<[string, number]> : [];
  const conversationStates = analytics?.conversation_states ? Object.entries(analytics.conversation_states) : [];

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
        <div className="analytics-head">
          <div>
            <p className="eyebrow">Analytics</p>
            <h3>Tenant operations snapshot</h3>
            <p className="muted">Live counts from the loaded tenant analytics endpoint.</p>
          </div>
          {analytics && <span className="analytics-freshness-pill">Loaded</span>}
        </div>
        {metricEntries.length > 0 ? <div className="metric-grid analytics-metric-grid">
          {metricEntries.map(([key, value]) => <div className={`metric analytics-metric metric-${key.replace(/_/g, '-')}`} key={key}>
            <span>{prettifyKeyLabel(key)}</span>
            <strong>{value}</strong>
          </div>)}
        </div> : <div className="analytics-empty-state"><strong>No analytics loaded</strong><p>Tenant metrics will appear here after the analytics endpoint returns data.</p></div>}
        {conversationStates.length > 0 && <div className="analytics-breakdown">
          <div className="analytics-breakdown-head">
            <strong>Conversation states</strong>
            <span>{conversationStates.length} states</span>
          </div>
          <div className="analytics-state-grid">
            {conversationStates.map(([state, count]) => <div key={state}><small>{prettifyKeyLabel(state)}</small><span>{count}</span></div>)}
          </div>
        </div>}
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

  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTo({ top: node.scrollHeight, behavior: 'auto' });
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

const SECRET_LIKE_KEY = /(secret|token|password|credential|authorization|api[_-]?key|app[_-]?secret|verify[_-]?token|provider[_-]?id|phone[_-]?number[_-]?id|waba|bot[_-]?token|signature|x[_-]?hub)/i;

function sanitizeDiagnosticValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => sanitizeDiagnosticValue(item));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [
      key,
      SECRET_LIKE_KEY.test(key) ? '[hidden]' : sanitizeDiagnosticValue(item),
    ]));
  }
  return value;
}

function formatDiagnosticValue(value: unknown) {
  const safeValue = sanitizeDiagnosticValue(value);
  if (safeValue === null || safeValue === undefined || safeValue === '') return 'not set';
  if (typeof safeValue === 'boolean') return safeValue ? 'yes' : 'no';
  if (typeof safeValue === 'number') return String(safeValue);
  if (typeof safeValue === 'string') return safeValue;
  return JSON.stringify(safeValue);
}

function DiagnosticOutput({ title, description, data }: { title: string; description: string; data: Record<string, unknown> }) {
  const safeData = sanitizeDiagnosticValue(data) as Record<string, unknown>;
  const summaryEntries = Object.entries(safeData).slice(0, 4);
  return <details className="diagnostic-panel" open>
    <summary>
      <span>
        <strong>{title}</strong>
        <small>{description}</small>
      </span>
      <span className="diagnostic-toggle">Details</span>
    </summary>
    {summaryEntries.length > 0 && <div className="diagnostic-kv-grid">
      {summaryEntries.map(([key, value]) => <div key={key}>
        <small>{prettifyKeyLabel(key)}</small>
        <strong>{formatDiagnosticValue(value)}</strong>
      </div>)}
    </div>}
    <pre className="system-pre diagnostic-pre">{JSON.stringify(safeData, null, 2)}</pre>
  </details>;
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

  return <section className="grid two system-surface">
    <div className="card wide system-panel">
      <div className="system-panel-head">
        <div>
          <p className="eyebrow">Academy Tenant #1 UAT</p>
          <h3>Run safe scenario checks</h3>
          <p className="muted">This checks tenant-scoped intent and routing results without creating customer messages.</p>
        </div>
        <button onClick={runAll}>Run academy UAT cases</button>
      </div>
      {status && <p className="success-text">{status}</p>}
      {run && <div className="uat-summary"><strong>{run.passed}/{run.total}</strong><span>passed · {run.mode}</span></div>}
      {run ? <div className="list system-list">{run.results.map((r) => <div className="list-card system-list-card" key={r.id}>
        <div className="row-between"><b>{r.id}</b><span className={r.passed ? 'pill pass-pill' : 'pill fail-pill'}>{r.passed ? 'pass' : 'check'}</span></div>
        <p>{r.message}</p>
        <small>expected {r.expected_intent}/{r.expected_action} · actual {r.actual_intent}/{r.actual_action} · confidence {Math.round(r.confidence * 100)}%</small>
        {r.matched_phrases.length > 0 && <small>matched: {r.matched_phrases.join(', ')}</small>}
      </div>)}</div> : <div className="system-empty-state"><strong>No UAT run yet</strong><p>Run the safe scenario checks to review tenant intent and routing behavior.</p></div>}
    </div>
    <form className="card form-stack system-panel" onSubmit={runCustom}>
      <p className="eyebrow">Custom tenant test</p>
      <h3>Try one message</h3>
      <p className="muted">Run a single classification check without creating a customer conversation.</p>
      <label>Message<input value={customMessage} onChange={(e) => setCustomMessage(e.target.value)} /></label>
      <label>Expected intent<input value={customExpectedIntent} onChange={(e) => setCustomExpectedIntent(e.target.value)} /></label>
      <button>Run custom test</button>
      {customResult && <DiagnosticOutput title="Classification result" description="Safe structured response from the custom tenant UAT check." data={customResult} />}
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

  return <section className="grid two system-surface">
    <div className="card wide system-panel">
      <div className="system-panel-head">
        <div>
          <p className="eyebrow">Deployment readiness</p>
          <h3>Staging / production checklist</h3>
          <p className="muted">Secret-safe operational checks for release readiness.</p>
        </div>
        <button onClick={loadDeployment}>Refresh deployment status</button>
      </div>
      {error && <p className="error-box">{error}</p>}
      {checklist && <div className="uat-summary"><strong>{checklist.passed}/{checklist.total}</strong><span>passed · env {checklist.environment}</span></div>}
      <div className="checklist">{checklist?.items.map((i) => <div key={i.key} className={i.passed ? 'pass' : 'fail'}><span>{i.passed ? '✓' : '•'}</span>{i.label}{i.detail ? <small> · {i.detail}</small> : null}</div>)}</div>
    </div>
    <div className="card system-panel">
      <p className="eyebrow">Platform environment</p>
      <h3>Secret-safe env status</h3>
      <p className="muted">Shows configuration status only. Secret values stay hidden.</p>
      <div className="list system-list">{environment?.items.map((i) => <div className="list-card system-list-card" key={i.key}><b>{i.key}</b><p>{i.purpose}</p><small>{i.configured ? 'configured' : 'missing'} · {i.secret ? 'secret value hidden' : i.value_preview}</small></div>)}</div>
    </div>
    <div className="card system-panel">
      <p className="eyebrow">WhatsApp go-live package</p>
      <h3>Still required before academy live hookup</h3>
      <p className="muted">Provider-facing requirements and readiness notes.</p>
      {goLive ? <DiagnosticOutput title="Go-live package" description="Provider-facing readiness fields with credential-like values hidden." data={goLive} /> : <div className="system-empty-state compact"><strong>No package loaded</strong><p>Refresh deployment status to load the go-live package.</p></div>}
    </div>
    <div className="card system-panel">
      <p className="eyebrow">Webhook UAT fixtures</p>
      <h3>Signed payload samples</h3>
      <p className="muted">These normalize and classify realistic WhatsApp payloads without creating customer messages.</p>
      <div className="list system-list">{fixtures.slice(0, 5).map((f) => <div className="list-card system-list-card" key={f.id}><b>{f.id}</b><p>{f.message}</p><small>{f.x_hub_signature_256 ? 'signed fixture available' : 'signature unavailable until app secret is configured'}</small><button onClick={() => void simulate(f.id)}>Simulate</button></div>)}</div>
      {simulation && <DiagnosticOutput title="Simulation result" description="Safe structured result from the selected webhook fixture." data={simulation} />}
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

  return <section className="grid two system-surface">
    <div className="card wide system-panel">
      <div className="system-panel-head">
        <div>
          <p className="eyebrow">Final acceptance</p>
          <h3>Definition-of-done tracker</h3>
          <p className="muted">Internal handoff readiness across acceptance, blockers, and client package items.</p>
        </div>
        <button onClick={load}>Refresh final handoff status</button>
      </div>
      {error && <p className="error-box">{error}</p>}
      {summary && <div className="uat-summary"><strong>{summary.passed}/{summary.total}</strong><span>{summary.project_status} · env {summary.environment}</span></div>}
      <div className="checklist">{summary?.items.map((i) => <div key={i.key} className={i.passed ? 'pass' : 'fail'}><span>{i.passed ? '✓' : '•'}</span>{i.label}{i.detail ? <small> · {i.detail}</small> : null}</div>)}</div>
    </div>
    <div className="card system-panel">
      <p className="eyebrow">Tenant evidence</p>
      <h3>Configuration and operations counts</h3>
      {summary && <div className="metric-grid">{Object.entries(summary.counts).map(([k, v]) => <div className="metric" key={k}><strong>{v}</strong><span>{k}</span></div>)}</div>}
    </div>
    <div className="card system-panel">
      <p className="eyebrow">Go-live blockers</p>
      <h3>{blockers?.blocked ? 'Still blocked' : 'No blockers'}</h3>
      <div className="list system-list">{blockers?.blockers.map((b) => <div className="list-card system-list-card" key={b.key}><b>{b.label}</b><p>{b.detail || b.key}</p></div>)}</div>
      <h4>External academy WhatsApp items</h4>
      <div className="list system-list">{blockers?.expected_remaining_external_blockers.map((b) => <div className="list-card system-list-card" key={b}><b>{b}</b></div>)}</div>
    </div>
    <div className="card wide system-panel">
      <p className="eyebrow">Client handoff package</p>
      <h3>{pkg?.product}</h3>
      {pkg && <div className="grid two">
        <div><h4>Included capabilities</h4><div className="list system-list">{pkg.included_capabilities.map((x) => <div className="list-card system-list-card" key={x}><b>{x}</b></div>)}</div></div>
        <div><h4>Next steps</h4><div className="list system-list">{pkg.recommended_next_steps.map((x) => <div className="list-card system-list-card" key={x}><b>{x}</b></div>)}</div></div>
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
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileStatus, setProfileStatus] = useState<string | null>(null);
  const [addingBranch, setAddingBranch] = useState(false);
  const [branchStatus, setBranchStatus] = useState<string | null>(null);
  useEffect(() => { setDisplayName(tenant?.display_name || ''); setSupportPhone(tenant?.brand.support_phone || ''); }, [tenant]);
  async function saveProfile(e: FormEvent) {
    e.preventDefault();
    setSavingProfile(true);
    setProfileStatus(null);
    try {
      await api.updateProfile(token, tenantSlug, { display_name: displayName, support_phone: supportPhone });
      await reload();
      setProfileStatus('Business profile saved.');
    } finally {
      setSavingProfile(false);
    }
  }
  const branchHoursPreview = buildBranchHoursJson(morningEnabled, morningFrom, morningTo, eveningEnabled, eveningFrom, eveningTo);
  async function addBranch(e: FormEvent) {
    e.preventDefault();
    setAddingBranch(true);
    setBranchStatus(null);
    try {
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
      setBranchStatus('Branch added to business settings.');
    } finally {
      setAddingBranch(false);
    }
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
  const logoUrl = resolveAssetUrl(tenant?.brand.logo_url);
  const activeBranchCount = branches.filter((branch) => branch.is_active !== false).length;
  const savedPeriodsCount = branches.reduce((count, branch) => {
    const periods = Array.isArray(branch.hours_json?.periods) ? branch.hours_json.periods : [];
    return count + periods.length;
  }, 0);
  return <section className="settings-shell">
    <div className="settings-hero">
      <div>
        <p className="eyebrow">Business settings</p>
        <h2>Workspace profile and operating details</h2>
        <p className="muted">Keep the public business identity, support contact, branches, and hours ready for automated customer replies.</p>
      </div>
      <div className="settings-summary-grid" aria-label="Business settings summary">
        <div><span>Branches</span><strong>{branches.length}</strong></div>
        <div><span>Active</span><strong>{activeBranchCount}</strong></div>
        <div><span>Hours blocks</span><strong>{savedPeriodsCount}</strong></div>
      </div>
    </div>

    <div className="grid two settings-layout">
      <form className="card form-stack settings-panel settings-profile-card" onSubmit={saveProfile}>
        <div className="settings-card-head">
          <div>
            <p className="eyebrow">Profile</p>
            <h3>Business identity</h3>
            <p className="muted">This information powers workspace labels and settings-driven bot answers.</p>
          </div>
          <div className="settings-brand-tile" aria-label="Current brand logo">
            {logoUrl
              ? <img src={logoUrl} alt={`${tenant?.display_name || tenantSlug} logo`} className="brand-mark-image" />
              : <span>{initialsFromName(displayName || tenantSlug)}</span>}
          </div>
        </div>
        <div className="settings-field-group">
          <label>Display name
            <span className="field-helper">Shown across the tenant workspace and customer-facing references.</span>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </label>
          <label>Support phone
            <span className="field-helper">Used by the agent for contact and escalation answers.</span>
            <input value={supportPhone} onChange={(e) => setSupportPhone(e.target.value)} placeholder="+966..." />
          </label>
        </div>
        {profileStatus && <p className="settings-status success">{profileStatus}</p>}
        <div className="settings-actions">
          <button disabled={savingProfile}>{savingProfile ? 'Saving...' : 'Save profile'}</button>
        </div>
      </form>

      <form className="card form-stack settings-panel settings-branch-form" onSubmit={addBranch}>
        <div className="settings-card-head">
          <div>
            <p className="eyebrow">Branches</p>
            <h3>Add branch</h3>
            <p className="muted">Create a customer-ready location with the hours your agent can safely quote.</p>
          </div>
        </div>
        <div className="settings-field-group">
          <label>Name
            <span className="field-helper">Use the public branch or location name.</span>
            <input value={branchName} onChange={(e) => setBranchName(e.target.value)} />
          </label>
          <label>Address
            <span className="field-helper">Keep it concise enough to appear in chat replies.</span>
            <input value={branchAddress} onChange={(e) => setBranchAddress(e.target.value)} />
          </label>
        </div>
        <div className="hours-builder">
          <div className="hours-period settings-hours-period">
            <div className="row-between">
              <strong>Morning hours</strong>
              <label className="check-row compact-check"><input type="checkbox" checked={morningEnabled} onChange={(e) => setMorningEnabled(e.target.checked)} /> Open in morning</label>
            </div>
            {morningEnabled ? <div className="time-range"><label>From<input type="time" value={morningFrom} onChange={(e) => setMorningFrom(e.target.value)} /></label><label>To<input type="time" value={morningTo} onChange={(e) => setMorningTo(e.target.value)} /></label></div> : <p className="muted">Morning period disabled.</p>}
          </div>
          <div className="hours-period settings-hours-period">
            <div className="row-between">
              <strong>Evening hours</strong>
              <label className="check-row compact-check"><input type="checkbox" checked={eveningEnabled} onChange={(e) => setEveningEnabled(e.target.checked)} /> Open in evening</label>
            </div>
            {eveningEnabled ? <div className="time-range"><label>From<input type="time" value={eveningFrom} onChange={(e) => setEveningFrom(e.target.value)} /></label><label>To<input type="time" value={eveningTo} onChange={(e) => setEveningTo(e.target.value)} /></label></div> : <p className="muted">Evening period disabled.</p>}
          </div>
          <div className="hours-preview settings-hours-preview">
            <p className="eyebrow">Hours preview</p>
            <div className="hours-preview-grid">{previewPeriods.length > 0 ? previewPeriods.map((period) => <div className="hours-preview-card" key={period.label}><strong>{period.label}</strong><span>{formatClockTime(period.from)} - {formatClockTime(period.to)}</span></div>) : <div className="hours-preview-card disabled"><strong>Closed</strong><span>No active periods selected</span></div>}</div>
          </div>
        </div>
        {branchStatus && <p className="settings-status success">{branchStatus}</p>}
        <div className="settings-actions">
          <button disabled={addingBranch || (!morningEnabled && !eveningEnabled)}>{addingBranch ? 'Adding...' : 'Add branch'}</button>
        </div>
      </form>

      <div className="card wide settings-branches-card">
        <div className="settings-card-head">
          <div>
            <p className="eyebrow">Saved locations</p>
            <h3>Current branches</h3>
            <p className="muted">Review the branch details your runtime agent can use for location, schedule, and contact responses.</p>
          </div>
        </div>
        <div className="branch-grid settings-branch-grid">
          {branches.length === 0 && <div className="settings-empty-state"><strong>No branches yet</strong><p>Add the first location above so the agent can answer branch and hours questions.</p></div>}
          {branches.map((branch) => {
            const periods = Array.isArray(branch.hours_json?.periods) ? branch.hours_json.periods as Array<{ from?: string; to?: string }> : [];
            return <div className="branch-card settings-branch-card" key={branch.id}>
              <button className="close-chip branch-close-chip" type="button" aria-label={`Delete ${branch.name}`} onClick={() => setPendingDeleteBranch(branch)}>x</button>
              <div className="branch-head">
                <div>
                  <strong>{branch.name}</strong>
                  <p>{branch.is_active === false ? 'Inactive branch' : 'Active branch'}</p>
                </div>
              </div>
              <div className="branch-meta">
                <div><small>Address</small><span>{branch.address || 'No address yet'}</span></div>
                <div><small>City</small><span>{branch.city || 'Not set'}</span></div>
              </div>
              <div className="branch-hours">
                <small>Hours</small>
                {periods.length > 0 ? periods.map((period, index) => <span className="branch-hour-pill" key={`${branch.id}-${index}`}>{formatClockTime(period.from || '')} - {formatClockTime(period.to || '')}</span>) : <span className="muted">No hours saved</span>}
              </div>
              <div className="button-row"><button className="secondary" type="button" onClick={() => openEditBranch(branch)}>Edit branch</button></div>
            </div>;
          })}
        </div>
      </div>
    </div>

    {editingBranch && <div className="confirm-overlay" role="dialog" aria-modal="true"><div className="confirm-card"><h3>Edit branch</h3><div className="form-stack"><label>Name<input value={editBranchName} onChange={(e) => setEditBranchName(e.target.value)} /></label><label>Address<input value={editBranchAddress} onChange={(e) => setEditBranchAddress(e.target.value)} /></label><div className="hours-period"><div className="row-between"><strong>Morning hours</strong><label className="check-row compact-check"><input type="checkbox" checked={editMorningEnabled} onChange={(e) => setEditMorningEnabled(e.target.checked)} /> Open in morning</label></div>{editMorningEnabled ? <div className="time-range"><label>From<input type="time" value={editMorningFrom} onChange={(e) => setEditMorningFrom(e.target.value)} /></label><label>To<input type="time" value={editMorningTo} onChange={(e) => setEditMorningTo(e.target.value)} /></label></div> : <p className="muted">Morning period disabled.</p>}</div><div className="hours-period"><div className="row-between"><strong>Evening hours</strong><label className="check-row compact-check"><input type="checkbox" checked={editEveningEnabled} onChange={(e) => setEditEveningEnabled(e.target.checked)} /> Open in evening</label></div>{editEveningEnabled ? <div className="time-range"><label>From<input type="time" value={editEveningFrom} onChange={(e) => setEditEveningFrom(e.target.value)} /></label><label>To<input type="time" value={editEveningTo} onChange={(e) => setEditEveningTo(e.target.value)} /></label></div> : <p className="muted">Evening period disabled.</p>}</div></div><div className="button-row"><button type="button" onClick={() => void saveBranchEdit()} disabled={savingBranchId === editingBranch.id}>{savingBranchId === editingBranch.id ? 'Saving...' : 'Save branch'}</button><button className="secondary" type="button" onClick={() => setEditingBranch(null)} disabled={savingBranchId === editingBranch.id}>Cancel</button></div></div></div>}
    {pendingDeleteBranch && <div className="confirm-overlay" role="dialog" aria-modal="true"><div className="confirm-card"><h3>Are you sure you want to delete this branch?</h3><p className="muted">{pendingDeleteBranch.name}</p><div className="button-row"><button onClick={() => void confirmDeleteBranch()} disabled={deletingBranchId === pendingDeleteBranch.id}>{deletingBranchId === pendingDeleteBranch.id ? 'Deleting...' : 'Accept'}</button><button className="secondary" onClick={() => setPendingDeleteBranch(null)} disabled={deletingBranchId === pendingDeleteBranch.id}>Cancel</button></div></div></div>}
  </section>;
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
  const [creatingStaff, setCreatingStaff] = useState(false);
  const [staffStatus, setStaffStatus] = useState<string | null>(null);

  const activeStaffCount = rows.filter((row) => row.is_active).length;
  const inactiveStaffCount = rows.length - activeStaffCount;
  const uniqueRoleCount = new Set(rows.flatMap((row) => row.roles)).size;
  const selectedRoleLabel = roles.split('_').join(' ').toLowerCase();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setStaffStatus(null);
    if (password.length < 8) {
      setFormError('Password must be at least 8 characters.');
      return;
    }
    setCreatingStaff(true);
    try {
      await api.createStaff(token, tenantSlug, { email, full_name: name, password, roles: [roles] });
      setEmail('');
      setName('');
      setPassword('');
      await reload();
      setStaffStatus('Staff user created.');
    } finally {
      setCreatingStaff(false);
    }
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

  return <section className="staff-shell">
    <div className="staff-hero">
      <div>
        <p className="eyebrow">Users and roles</p>
        <h2>Team access management</h2>
        <p className="muted">Create staff accounts, assign operational roles, and keep tenant access clear for the business workspace.</p>
      </div>
      <div className="staff-summary-grid" aria-label="Staff summary">
        <div><span>Total users</span><strong>{rows.length}</strong></div>
        <div><span>Active</span><strong>{activeStaffCount}</strong></div>
        <div><span>Inactive</span><strong>{inactiveStaffCount}</strong></div>
        <div><span>Roles</span><strong>{uniqueRoleCount}</strong></div>
      </div>
    </div>

    <div className="grid two staff-layout">
      <form className="card form-stack staff-form-card" onSubmit={submit}>
        <div className="staff-card-head">
          <div>
            <p className="eyebrow">Create access</p>
            <h3>Add staff user</h3>
            <p className="muted">Provision one team member at a time with the minimum role needed for their work.</p>
          </div>
        </div>
        <div className="staff-form-grid">
          <label>Email
            <span className="field-helper">Use the staff member&apos;s work email for login.</span>
            <input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </label>
          <label>Name
            <span className="field-helper">Shown in internal staff and audit views.</span>
            <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
          </label>
          <label>Password
            <span className="field-helper">Minimum 8 characters. Do not reuse shared credentials.</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          </label>
          <label>Role
            <span className="field-helper">Selected role: {selectedRoleLabel}.</span>
            <select value={roles} onChange={(e) => setRoles(e.target.value)}>{staffRoleOptions.map((role) => <option key={role} value={role}>{role.split('_').join(' ')}</option>)}</select>
          </label>
        </div>
        <div className="staff-role-note">
          <strong>Role scope</strong>
          <p>Roles control what staff can operate inside this tenant workspace. Keep access specific and review inactive users regularly.</p>
        </div>
        {boxError(formError)}
        {staffStatus && <p className="settings-status success">{staffStatus}</p>}
        <div className="staff-form-actions">
          <button disabled={creatingStaff}>{creatingStaff ? 'Creating...' : 'Add staff'}</button>
        </div>
      </form>

      <div className="card staff-list-card">
        <div className="staff-card-head">
          <div>
            <p className="eyebrow">Directory</p>
            <h3>Staff users</h3>
            <p className="muted">Monitor account status and role assignments for this tenant.</p>
          </div>
        </div>
        <div className="staff-grid">
          {rows.length === 0 && <div className="staff-empty-state"><strong>No staff users yet</strong><p>Add the first staff user to begin assigning operational access.</p></div>}
          {rows.map((row) => <div className="staff-card" key={row.id}>
            <button className="close-chip staff-close-chip" type="button" aria-label={`Delete ${row.full_name}`} onClick={() => setPendingDelete(row)}>x</button>
            <div className="staff-head">
              <div className={`staff-avatar ${row.is_active ? 'active' : 'inactive'}`} aria-hidden="true">{initialsFromName(row.full_name || row.email)}</div>
              <div>
                <strong>{row.full_name}</strong>
                <p>{row.email}</p>
              </div>
            </div>
            <div className="staff-meta">
              <div><small>User ID</small><span>#{row.id}</span></div>
              <div><small>Status</small><span className={row.is_active ? 'staff-status-pill active' : 'staff-status-pill inactive'}>{row.is_active ? 'Active' : 'Inactive'}</span></div>
            </div>
            <div className="staff-roles" aria-label={`${row.full_name} roles`}>
              {row.roles.length > 0 ? row.roles.map((role) => <span className="staff-role-pill" key={role}>{role.split('_').join(' ')}</span>) : <span className="staff-role-pill empty">No roles</span>}
            </div>
          </div>)}
        </div>
      </div>
    </div>

    {pendingDelete && <div className="confirm-overlay" role="dialog" aria-modal="true"><div className="confirm-card"><h3>Are you sure you want to delete this staff user?</h3><p className="muted">{pendingDelete.full_name} · {pendingDelete.email}</p><div className="button-row"><button onClick={() => void confirmDelete()} disabled={deletingId === pendingDelete.id}>{deletingId === pendingDelete.id ? 'Deleting...' : 'Accept'}</button><button className="secondary" onClick={() => setPendingDelete(null)} disabled={deletingId === pendingDelete.id}>Cancel</button></div></div></div>}
  </section>;
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
  const [smartImportOpen, setSmartImportOpen] = useState(false);
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

  useEffect(() => {
    if (!smartImportOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') setSmartImportOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [smartImportOpen]);

  return <section className={`knowledge-shell ${(wizardOpen || smartImportOpen) ? 'modal-open' : ''}`}>
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
        <div className="knowledge-action-stack">
          <div className="knowledge-primary-actions">
            <button onClick={openCreate}>Make new response</button>
            <button type="button" className="secondary knowledge-import-trigger" onClick={() => setSmartImportOpen(true)}>Upload your messages</button>
          </div>
          <p className="muted">Paste chats or upload files to generate drafts.</p>
        </div>
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

    {smartImportOpen && typeof document !== 'undefined' && createPortal(
      <div className="smart-import-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="smart-import-title" onMouseDown={(event) => {
        if (event.target === event.currentTarget) setSmartImportOpen(false);
      }}>
        <div className="smart-import-modal-window">
          <div className="smart-import-modal-head">
            <div>
              <p className="eyebrow">Smart import</p>
              <h3 id="smart-import-title">Upload your messages</h3>
              <p>Paste WhatsApp exports or upload TXT, CSV, or XLSX files. Nothing is saved until you approve.</p>
            </div>
            <button type="button" className="secondary knowledge-close-button" onClick={() => setSmartImportOpen(false)}>Close</button>
          </div>
          <SmartImportStudio token={token} tenantSlug={tenantSlug} reload={reload} />
        </div>
      </div>,
      document.body
    )}

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

function SmartImportStudio({ token, tenantSlug, reload }: { token: string; tenantSlug: string; reload: () => Promise<void> }) {
  const [pasteText, setPasteText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<SmartImportPreview | null>(null);
  const [rows, setRows] = useState<SmartImportRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resultMessage, setResultMessage] = useState<string | null>(null);
  const approvedCount = rows.filter((row) => row.decision === 'approved').length;
  const rejectedCount = rows.filter((row) => row.decision === 'rejected').length;
  const highConfidenceCount = rows.filter((row) => row.confidence >= 0.8 && !row.warnings.includes('needs_review')).length;

  async function runPreview(mode: 'paste' | 'file') {
    setLoading(true);
    setError(null);
    setResultMessage(null);
    try {
      const next = mode === 'file'
        ? file
          ? await api.smartImportPreviewFile(token, tenantSlug, file)
          : null
        : await api.smartImportPreviewText(token, tenantSlug, { text: pasteText, source_type: 'paste' });
      if (!next) {
        setError('Choose a file to preview.');
        return;
      }
      setPreview(next);
      setRows(next.rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to preview import.');
    } finally {
      setLoading(false);
    }
  }

  function updateRow(rowId: string, patch: Partial<SmartImportRow>) {
    setRows((current) => current.map((row) => row.row_id === rowId ? { ...row, ...patch } : row));
  }

  function updateEditable(rowId: string, patch: Partial<SmartImportRow['editable']>) {
    setRows((current) => current.map((row) => row.row_id === rowId ? { ...row, editable: { ...row.editable, ...patch } } : row));
  }

  function approveHighConfidence() {
    setRows((current) => current.map((row) => row.confidence >= 0.8 && !row.warnings.includes('needs_review') ? { ...row, decision: 'approved' } : row));
  }

  function rejectLowConfidence() {
    setRows((current) => current.map((row) => row.confidence < 0.6 || row.warnings.includes('needs_review') ? { ...row, decision: 'rejected' } : row));
  }

  function resetImport() {
    setPreview(null);
    setRows([]);
    setPasteText('');
    setFile(null);
    setError(null);
    setResultMessage(null);
  }

  async function confirmImport() {
    setApproving(true);
    setError(null);
    setResultMessage(null);
    try {
      const items = rows.map((row) => {
        const answer = row.editable.faq_answer.trim();
        const answerIsArabic = /[\u0600-\u06FF]/.test(answer);
        return {
          row_id: row.row_id,
          decision: row.decision,
          redacted_excerpt: row.redacted_excerpt,
          normalized_text: row.normalized_text,
          intent_code: row.editable.intent_code,
          intent_label: row.suggested_intent.label,
          create_intent: row.editable.create_intent,
          training_example_text: row.editable.training_example_text,
          keyword_phrases: row.editable.keyword_phrases,
          create_faq: row.editable.create_faq,
          faq_topic_key: row.editable.faq_topic_key,
          faq_question: row.editable.faq_question,
          faq_answer_ar: answerIsArabic ? answer : '',
          faq_answer_en: answerIsArabic ? '' : answer,
        };
      });
      const result = await api.smartImportApprove(token, tenantSlug, {
        source_type: preview?.source_type || 'preview',
        total_rows: preview?.total_rows || rows.length,
        items,
      });
      setResultMessage(`Imported ${result.approved_training_examples} training examples, ${result.approved_keywords} keywords, and ${result.approved_faq_items} FAQ items.`);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to confirm import.');
    } finally {
      setApproving(false);
    }
  }

  return <section className="smart-import-studio">
    <div className="smart-import-head">
      <div>
        <p className="eyebrow">Guided import flow</p>
        <h3>Turn customer messages into reviewable drafts</h3>
        <p className="muted">Preview first, approve only the useful suggestions, then import them into Knowledge & Responses.</p>
      </div>
      <div className="smart-import-summary">
        <div><span>Previewed</span><strong>{rows.length}</strong></div>
        <div><span>Approved</span><strong>{approvedCount}</strong></div>
        <div><span>Rejected</span><strong>{rejectedCount}</strong></div>
      </div>
    </div>

    <div className="smart-import-flow-steps" aria-label="Smart import workflow">
      <div className="active"><span>1</span><strong>Paste or upload</strong><small>Add exported chats or files</small></div>
      <div className={preview ? 'active' : ''}><span>2</span><strong>Preview suggestions</strong><small>Review confidence and warnings</small></div>
      <div className={approvedCount > 0 ? 'active' : ''}><span>3</span><strong>Approve and import</strong><small>Save only selected drafts</small></div>
    </div>

    <div className="smart-import-input-grid">
      <label>Paste raw chat or messages
        <textarea value={pasteText} onChange={(e) => setPasteText(e.target.value)} placeholder={'[5/20/26, 9:01 AM] Customer: كم السعر؟\nCustomer: I want to register\nعندي شكوى'} />
      </label>
      <div className="smart-import-upload-panel">
        <strong>Upload file</strong>
        <p className="muted">Use one-column CSV, TXT exports, or XLSX when backend support is available. Files are previewed only and not stored permanently.</p>
        <label className="smart-import-file-button">
          <input type="file" accept=".txt,.csv,.xlsx,text/plain,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event: ChangeEvent<HTMLInputElement>) => setFile(event.target.files?.[0] || null)} />
          <span>{file ? file.name : 'Choose TXT, CSV, or XLSX'}</span>
        </label>
        <div className="button-row">
          <button type="button" onClick={() => void runPreview('paste')} disabled={loading || !pasteText.trim()}>{loading ? 'Previewing...' : 'Preview pasted text'}</button>
          <button type="button" className="secondary" onClick={() => void runPreview('file')} disabled={loading || !file}>{loading ? 'Previewing...' : 'Preview file'}</button>
        </div>
      </div>
    </div>

    {error && <div className="error-box">{error}</div>}
    {resultMessage && <p className="success-text smart-import-result">{resultMessage}</p>}

    <div className="smart-import-actions">
      <div>
        <strong>{preview ? `${preview.previewed_rows} suggestions ready` : 'No preview yet'}</strong>
        <p className="muted">{preview ? `${preview.duplicate_rows} duplicates skipped from ${preview.total_rows} parsed rows. Preview cap: ${preview.max_rows}.` : 'Preview creates redacted drafts for admin review.'}</p>
      </div>
      <div className="button-row">
        <button type="button" className="secondary" onClick={approveHighConfidence} disabled={rows.length === 0}>Approve high confidence ({highConfidenceCount})</button>
        <button type="button" className="secondary" onClick={rejectLowConfidence} disabled={rows.length === 0}>Reject low confidence</button>
        <button type="button" className="secondary" onClick={resetImport} disabled={loading || approving || (!preview && !pasteText && !file)}>Clear</button>
        <button type="button" onClick={() => void confirmImport()} disabled={approving || approvedCount === 0}>{approving ? 'Importing...' : 'Confirm import'}</button>
      </div>
    </div>

    {rows.length === 0 && <div className="smart-import-empty">
      <span className="smart-import-empty-icon">1</span>
      <strong>Start with a paste or file preview</strong>
      <p className="muted">The studio redacts emails, phone numbers, and URLs, then suggests training examples, keywords, and FAQ drafts for approval. Nothing is saved until you confirm the import.</p>
    </div>}

    {rows.length > 0 && <div className="smart-import-list">
      {rows.map((row) => <article className={`smart-import-row decision-${row.decision}`} key={row.row_id}>
        <div className="smart-import-row-main">
          <div>
            <div className="smart-import-row-top">
              <span className="config-badge">{row.detected_language.toUpperCase()}</span>
              <span className={`smart-confidence ${row.confidence >= 0.8 ? 'high' : row.confidence >= 0.6 ? 'medium' : 'low'}`}>{Math.round(row.confidence * 100)}%</span>
              <span className="config-badge secondary-pill">{row.suggested_intent.code}</span>
              {!row.suggested_intent.existing && <span className="config-status-pill inactive">new intent candidate</span>}
            </div>
            <p className="smart-import-excerpt" dir="auto">{row.redacted_excerpt}</p>
            <p className="smart-import-normalized" dir="auto">{row.normalized_text}</p>
          </div>
          <div className="smart-import-decision">
            <button type="button" className={row.decision === 'approved' ? 'active' : ''} onClick={() => updateRow(row.row_id, { decision: row.decision === 'approved' ? 'pending' : 'approved' })}>Approve</button>
            <button type="button" className={row.decision === 'rejected' ? 'active reject' : ''} onClick={() => updateRow(row.row_id, { decision: row.decision === 'rejected' ? 'pending' : 'rejected' })}>Reject</button>
          </div>
        </div>

        <div className="smart-import-detail-grid">
          <label>Intent code
            <input value={row.editable.intent_code} onChange={(e) => updateEditable(row.row_id, { intent_code: normalizeIntentCode(e.target.value) })} />
          </label>
          <label>Keyword suggestions
            <input value={row.editable.keyword_phrases.join(', ')} onChange={(e) => updateEditable(row.row_id, { keyword_phrases: e.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} />
          </label>
          <label>Training example
            <input value={row.editable.training_example_text} onChange={(e) => updateEditable(row.row_id, { training_example_text: e.target.value })} />
          </label>
          <label>FAQ topic
            <input value={row.editable.faq_topic_key} onChange={(e) => updateEditable(row.row_id, { faq_topic_key: normalizeTopicKey(e.target.value) })} placeholder="pricing" />
          </label>
        </div>

        <div className="smart-import-options">
          <label className="check-row"><input type="checkbox" checked={row.editable.create_intent} onChange={(e) => updateEditable(row.row_id, { create_intent: e.target.checked })} disabled={row.suggested_intent.existing} /> Create new intent if missing</label>
          <label className="check-row"><input type="checkbox" checked={row.editable.create_faq} onChange={(e) => updateEditable(row.row_id, { create_faq: e.target.checked })} /> Create FAQ item with approved answer</label>
          {row.editable.create_faq && <label className="smart-import-answer">Official answer
            <textarea value={row.editable.faq_answer} onChange={(e) => updateEditable(row.row_id, { faq_answer: e.target.value })} placeholder="Needs official answer" />
          </label>}
        </div>

        <div className="smart-import-meta">
          <span>{row.suggested_faq_topic?.existing ? `Links to FAQ: ${row.suggested_faq_topic.topic_key}` : row.suggested_faq_topic ? `FAQ draft: ${row.suggested_faq_topic.topic_key}` : 'No FAQ suggestion'}</span>
          <span>{row.routing_hint.behavior} · {row.routing_hint.reason}</span>
        </div>
        {row.warnings.length > 0 && <div className="chip-cloud">
          {row.warnings.map((warning) => <span key={warning} className="config-chip secondary-chip">{warning}</span>)}
        </div>}
      </article>)}
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
  const enabledIntentCount = intents.filter((intent) => intent.enabled).length;
  const handoffRouteCount = routing.filter((route) => route.handoff_required || route.response_behavior === 'immediate_handoff' || route.response_behavior === 'offer_handoff').length;
  const highPriorityRouteCount = routing.filter((route) => route.priority === 'high' || route.priority === 'urgent').length;
  const keywordCount = intents.reduce((count, intent) => count + intent.keywords.length, 0);

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

  return <section className="intents-shell">
    <div className="intents-hero">
      <div>
        <p className="eyebrow">Intents and routing</p>
        <h2>Classification rules and handoff control</h2>
        <p className="muted">Configure intent labels, multilingual keywords, response sources, ownership, escalation, and human handoff behavior for this tenant.</p>
      </div>
      <div className="intents-summary-grid" aria-label="Intent routing summary">
        <div><span>Total intents</span><strong>{intents.length}</strong></div>
        <div><span>Enabled</span><strong>{enabledIntentCount}</strong></div>
        <div><span>Handoff routes</span><strong>{handoffRouteCount}</strong></div>
        <div><span>High priority</span><strong>{highPriorityRouteCount}</strong></div>
        <div><span>Keywords</span><strong>{keywordCount}</strong></div>
      </div>
    </div>

    <div className="config-page config-page-two intents-workspace">
    <form className="card config-editor-card intents-editor-card" onSubmit={submit}>
      <div className="config-section-head">
        <div>
          <p className="eyebrow">Rule editor</p>
          <h3>{editingId ? 'Edit tenant intent' : 'Create tenant intent'}</h3>
          <p className="muted">Keep classification, answer source, and routing decisions in one controlled workflow.</p>
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
        <div className="config-language-head"><strong>Routing behavior</strong><span className={`intent-route-badge ${responseBehavior === 'normal' ? 'bot' : responseBehavior === 'offer_handoff' ? 'offer' : 'handoff'}`}>{responseBehavior === 'normal' ? 'Bot controlled' : responseBehavior === 'offer_handoff' ? 'Optional handoff' : 'Human handoff'}</span></div>
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
          <p className="eyebrow">Routing library</p>
          <h3>{sortedIntents.length} tenant intents</h3>
          <p className="muted">Scan enabled state, response source, ownership, keywords, and escalation posture.</p>
        </div>
      </div>
      <div className="config-card-list">
        {sortedIntents.length === 0 && <div className="intent-empty-state"><strong>No intents yet</strong><p>Create the first tenant intent to start routing customer messages to bot answers or staff handoff.</p></div>}
        {sortedIntents.map((intent) => {
          const route = routingByIntent.get(intent.code);
          const arKeywords = intent.keywords.filter((item) => item.lang === 'ar');
          const enKeywords = intent.keywords.filter((item) => item.lang === 'en');
          const routeBehavior = route?.response_behavior || (route?.handoff_required ? 'immediate_handoff' : 'normal');
          const routeClass = routeBehavior === 'offer_handoff' ? 'offer' : routeBehavior === 'immediate_handoff' ? 'handoff' : 'bot';
          const priorityClass = route?.priority === 'urgent' ? 'urgent' : route?.priority === 'high' ? 'high' : 'normal';
          return <article className={`config-item-card intent-item-card route-${routeClass} priority-${priorityClass}`} key={intent.id}>
            <div className="config-item-head">
              <div>
                <strong>{intent.label}</strong>
                <p className="config-code-line">{intent.code}</p>
                <div className="config-inline-meta">
                  <span className="config-badge">{intentLanguageLabel(intent.supported_languages)}</span>
                  <span className={`config-status-pill ${intent.enabled ? 'active' : 'inactive'}`}>{intent.enabled ? 'enabled' : 'disabled'}</span>
                  <span className="config-badge secondary-pill">{intent.response_mode === 'faq' ? `FAQ: ${intent.default_response_topic_key || 'not linked'}` : intent.response_mode === 'business_settings' ? `Settings auto: ${intent.default_response_topic_key || 'dynamic'}` : 'Custom response'}</span>
                  <span className={`intent-route-badge ${routeClass}`}>{routeBehavior === 'offer_handoff' ? 'Offer handoff' : routeBehavior === 'immediate_handoff' ? 'Immediate handoff' : 'Bot answer only'}</span>
                  <span className={`intent-priority-badge ${priorityClass}`}>{route?.priority || 'normal'}</span>
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
  const channelOptions = ['whatsapp', 'telegram', 'email', 'instagram', 'facebook', 'web_chat'];
  const futureAdapters = new Set<string>();
  const [channel, setChannel] = useState('whatsapp');
  const [enabled, setEnabled] = useState('true');
  const [liveSendEnabled, setLiveSendEnabled] = useState('false');
  const [phoneNumberId, setPhoneNumberId] = useState('');
  const [accessToken, setAccessToken] = useState('');
  const [verifyToken, setVerifyToken] = useState('');
  const [appSecret, setAppSecret] = useState('');
  const [botToken, setBotToken] = useState('');
  const [smtpHost, setSmtpHost] = useState('');
  const [smtpPort, setSmtpPort] = useState('');
  const [smtpUsername, setSmtpUsername] = useState('');
  const [smtpPassword, setSmtpPassword] = useState('');
  const [smtpFromEmail, setSmtpFromEmail] = useState('');
  const [smtpFromName, setSmtpFromName] = useState('');
  const [smtpUseTls, setSmtpUseTls] = useState('true');
  const [smtpUseSsl, setSmtpUseSsl] = useState('false');
  const [emailInboundSecret, setEmailInboundSecret] = useState('');
  const [imapHost, setImapHost] = useState('');
  const [imapPort, setImapPort] = useState('');
  const [imapUsername, setImapUsername] = useState('');
  const [imapPassword, setImapPassword] = useState('');
  const [imapMailbox, setImapMailbox] = useState('');
  const [imapUseSsl, setImapUseSsl] = useState('true');
  const [metaPageAccessToken, setMetaPageAccessToken] = useState('');
  const [metaAppSecret, setMetaAppSecret] = useState('');
  const [metaVerifyToken, setMetaVerifyToken] = useState('');
  const [metaWebhookSecret, setMetaWebhookSecret] = useState('');
  const [metaPageId, setMetaPageId] = useState('');
  const [metaInstagramBusinessAccountId, setMetaInstagramBusinessAccountId] = useState('');
  const [metaGraphApiVersion, setMetaGraphApiVersion] = useState('');
  const [savingChannel, setSavingChannel] = useState(false);
  const [channelMessage, setChannelMessage] = useState<string | null>(null);
  const [testConsoleOpen, setTestConsoleOpen] = useState(false);
  const [testChannel, setTestChannel] = useState('web_chat');
  const [testSessionId, setTestSessionId] = useState<string | null>(null);
  const [testInput, setTestInput] = useState('');
  const [testMessages, setTestMessages] = useState<Array<{ id: string; role: 'customer' | 'agent' | 'system'; text: string }>>([]);
  const [testResult, setTestResult] = useState<ChannelTestConsoleResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [testingChannel, setTestingChannel] = useState(false);
  const testInputRef = useRef<HTMLInputElement | null>(null);
  const testInboxRef = useRef<HTMLDivElement | null>(null);

  const configuredCount = rows.filter((row) => ['connected', 'configured', 'active'].includes(row.status)).length;
  const credentialCount = rows.filter((row) => row.has_credentials).length;
  const liveChannelCount = rows.filter((row) => !futureAdapters.has(row.channel_type) && row.public_config?.live_send_enabled === true).length;
  const selectedChannelRow = rows.find((row) => row.channel_type === channel);
  const selectedIsFutureAdapter = futureAdapters.has(channel);
  const controlsLocked = selectedIsFutureAdapter;

  const testableChannels = channelOptions.map((channelType) => {
    const row = rows.find((item) => item.channel_type === channelType);
    const implemented = !futureAdapters.has(channelType);
    const enabledFlag = row?.public_config?.enabled === true;
    const statusReady = row ? ['configured', 'connected', 'active'].includes(row.status) : false;
    let reason = '';
    if (!implemented) reason = 'Adapter not implemented';
    else if (!row) reason = 'Not configured for this tenant';
    else if (!enabledFlag) reason = 'Disabled for this tenant';
    else if (!statusReady) reason = `Status: ${row.status}`;
    return { channelType, row, available: implemented && Boolean(row) && enabledFlag && statusReady, reason };
  });

  useEffect(() => {
    const firstAvailable = testableChannels.find((item) => item.available)?.channelType || 'web_chat';
    if (!testableChannels.some((item) => item.channelType === testChannel && item.available)) {
      setTestChannel(firstAvailable);
    }
  }, [rows, testChannel]);

  useEffect(() => {
    if (!testConsoleOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.setTimeout(() => testInputRef.current?.focus(), 80);
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') setTestConsoleOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [testConsoleOpen]);

  useEffect(() => {
    if (!testConsoleOpen) return;
    const node = testInboxRef.current;
    if (node) node.scrollTop = node.scrollHeight;
    if (!testingChannel) testInputRef.current?.focus();
  }, [testMessages, testingChannel, testConsoleOpen]);

  useEffect(() => {
    const current = rows.find((row) => row.channel_type === channel);
    const publicConfig = current?.public_config || {};
    if (current) {
      setEnabled(publicConfig.enabled === false ? 'false' : 'true');
      setLiveSendEnabled(publicConfig.live_send_enabled === true ? 'true' : 'false');
      setPhoneNumberId('');
      setAccessToken('');
      setVerifyToken('');
      setAppSecret('');
      setBotToken('');
      setSmtpHost('');
      setSmtpPort('');
      setSmtpUsername('');
      setSmtpPassword('');
      setSmtpFromEmail('');
      setSmtpFromName('');
      setSmtpUseTls('true');
      setSmtpUseSsl('false');
      setEmailInboundSecret('');
      setImapHost('');
      setImapPort('');
      setImapUsername('');
      setImapPassword('');
      setImapMailbox('');
      setImapUseSsl('true');
      setMetaPageAccessToken('');
      setMetaAppSecret('');
      setMetaVerifyToken('');
      setMetaWebhookSecret('');
      setMetaPageId('');
      setMetaInstagramBusinessAccountId('');
      setMetaGraphApiVersion('');
      return;
    }
    if (channel === 'telegram') {
      setEnabled('true');
      setLiveSendEnabled('false');
      setPhoneNumberId('');
      setAccessToken('');
      setVerifyToken('');
      setAppSecret('');
      setBotToken('');
      setSmtpHost('');
      setSmtpPort('');
      setSmtpUsername('');
      setSmtpPassword('');
      setSmtpFromEmail('');
      setSmtpFromName('');
      setSmtpUseTls('true');
      setSmtpUseSsl('false');
      setEmailInboundSecret('');
      setImapHost('');
      setImapPort('');
      setImapUsername('');
      setImapPassword('');
      setImapMailbox('');
      setImapUseSsl('true');
      setMetaPageAccessToken('');
      setMetaAppSecret('');
      setMetaVerifyToken('');
      setMetaWebhookSecret('');
      setMetaPageId('');
      setMetaInstagramBusinessAccountId('');
      setMetaGraphApiVersion('');
      return;
    }
    if (channel === 'whatsapp') {
      setEnabled('true');
      setLiveSendEnabled('false');
      setPhoneNumberId('');
      setAccessToken('');
      setVerifyToken('');
      setAppSecret('');
      setBotToken('');
      setSmtpHost('');
      setSmtpPort('');
      setSmtpUsername('');
      setSmtpPassword('');
      setSmtpFromEmail('');
      setSmtpFromName('');
      setSmtpUseTls('true');
      setSmtpUseSsl('false');
      setEmailInboundSecret('');
      setImapHost('');
      setImapPort('');
      setImapUsername('');
      setImapPassword('');
      setImapMailbox('');
      setImapUseSsl('true');
      setMetaPageAccessToken('');
      setMetaAppSecret('');
      setMetaVerifyToken('');
      setMetaWebhookSecret('');
      setMetaPageId('');
      setMetaInstagramBusinessAccountId('');
      setMetaGraphApiVersion('');
      return;
    }
    setEnabled('false');
    setLiveSendEnabled('false');
    setPhoneNumberId('');
    setAccessToken('');
    setVerifyToken('');
    setAppSecret('');
    setBotToken('');
    setSmtpHost('');
    setSmtpPort('');
    setSmtpUsername('');
    setSmtpPassword('');
    setSmtpFromEmail('');
    setSmtpFromName('');
    setSmtpUseTls('true');
    setSmtpUseSsl('false');
    setEmailInboundSecret('');
    setImapHost('');
    setImapPort('');
    setImapUsername('');
    setImapPassword('');
    setImapMailbox('');
    setImapUseSsl('true');
    setMetaPageAccessToken('');
    setMetaAppSecret('');
    setMetaVerifyToken('');
    setMetaWebhookSecret('');
    setMetaPageId('');
    setMetaInstagramBusinessAccountId('');
    setMetaGraphApiVersion('');
  }, [channel, rows]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSavingChannel(true);
    setChannelMessage(null);
    const publicConfig: Record<string, unknown> = {
      ...(selectedChannelRow?.public_config || {}),
      enabled: controlsLocked ? false : enabled === 'true',
      live_send_enabled: controlsLocked ? false : liveSendEnabled === 'true',
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

    if (channel === 'email') {
      const hasEmailCredentialUpdate = [smtpHost, smtpPort, smtpUsername, smtpPassword, smtpFromEmail, smtpFromName, emailInboundSecret, imapHost, imapPort, imapUsername, imapPassword, imapMailbox].some((value) => value.trim());
      if (hasEmailCredentialUpdate) {
        if (smtpHost.trim()) credentials.smtp_host = smtpHost.trim();
        if (smtpPort.trim()) credentials.smtp_port = smtpPort.trim();
        if (smtpUsername.trim()) credentials.smtp_username = smtpUsername.trim();
        if (smtpPassword.trim()) credentials.smtp_password = smtpPassword.trim();
        if (smtpFromEmail.trim()) credentials.smtp_from_email = smtpFromEmail.trim();
        if (smtpFromName.trim()) credentials.smtp_from_name = smtpFromName.trim();
        if (emailInboundSecret.trim()) credentials.inbound_webhook_secret = emailInboundSecret.trim();
        if (imapHost.trim()) credentials.imap_host = imapHost.trim();
        if (imapPort.trim()) credentials.imap_port = imapPort.trim();
        if (imapUsername.trim()) credentials.imap_username = imapUsername.trim();
        if (imapPassword.trim()) credentials.imap_password = imapPassword.trim();
        if (imapMailbox.trim()) credentials.imap_mailbox = imapMailbox.trim();
        credentials.use_tls = smtpUseTls === 'true';
        credentials.use_ssl = smtpUseSsl === 'true';
        credentials.imap_use_ssl = imapUseSsl === 'true';
      }
    }

    if (channel === 'instagram' || channel === 'facebook') {
      const hasMetaCredentialUpdate = [
        metaPageAccessToken,
        metaAppSecret,
        metaVerifyToken,
        metaWebhookSecret,
        metaPageId,
        metaInstagramBusinessAccountId,
        metaGraphApiVersion,
      ].some((value) => value.trim());
      if (hasMetaCredentialUpdate) {
        if (metaPageAccessToken.trim()) credentials.page_access_token = metaPageAccessToken.trim();
        if (metaAppSecret.trim()) credentials.app_secret = metaAppSecret.trim();
        if (metaVerifyToken.trim()) credentials.verify_token = metaVerifyToken.trim();
        if (metaWebhookSecret.trim()) credentials.webhook_secret = metaWebhookSecret.trim();
        if (metaPageId.trim()) credentials.page_id = metaPageId.trim();
        if (metaInstagramBusinessAccountId.trim()) credentials.instagram_business_account_id = metaInstagramBusinessAccountId.trim();
        if (metaGraphApiVersion.trim()) credentials.graph_api_version = metaGraphApiVersion.trim();
      }
    }

    try {
      await api.saveChannel(token, tenantSlug, channel, { status: derivedSaveStatus(), public_config: publicConfig, credentials });
      await reload();
      setChannelMessage('Channel settings saved. Credential values remain hidden after storage.');
    } finally {
      setSavingChannel(false);
    }
  }

  function derivedSaveStatus() {
    const currentStatus = selectedChannelRow?.status || '';
    const implementedReadyStatuses = new Set(['configured', 'connected', 'active']);
    if (selectedIsFutureAdapter) return 'future';
    if (enabled !== 'true') return currentStatus === 'future' ? 'future' : 'not_connected';
    if (channel === 'web_chat') return 'configured';
    if (channel === 'email') return 'configured';
    if (channel === 'instagram' || channel === 'facebook') return 'configured';
    if (channel === 'telegram') {
      if (selectedChannelRow?.has_credentials || botToken.trim()) {
        return implementedReadyStatuses.has(currentStatus) ? currentStatus : 'configured';
      }
      return currentStatus || 'not_connected';
    }
    if (channel === 'whatsapp') {
      return implementedReadyStatuses.has(currentStatus) ? currentStatus : 'configured';
    }
    return currentStatus || 'not_connected';
  }

  function selectedPreviewRow(): Channel {
    const base = selectedChannelRow || {
      channel_type: channel,
      status: 'not_connected',
      public_config: {},
      has_credentials: false,
    };
    return {
      ...base,
      status: derivedSaveStatus(),
      public_config: {
        ...(base.public_config || {}),
        enabled: controlsLocked ? false : enabled === 'true',
        live_send_enabled: controlsLocked ? false : liveSendEnabled === 'true',
      },
    };
  }

  function hasSafeConfigValue(row: Channel, key: string) {
    const value = row.public_config?.[key];
    return typeof value === 'string' ? value.trim().length > 0 : Boolean(value);
  }

  function hiddenConfigured(value: boolean, missing = 'Not configured') {
    return value ? 'Configured, hidden' : missing;
  }

  function channelLabel(channelType: string) {
    if (channelType === 'web_chat') return 'Web Chat';
    if (channelType === 'facebook') return 'Facebook Messenger';
    return channelType.split('_').join(' ');
  }

  function channelHeadline(row: Channel) {
    const enabledFlag = row.public_config?.enabled === true;
    const liveFlag = row.public_config?.live_send_enabled === true;
    const readyStatus = ['connected', 'configured', 'active'].includes(row.status);

    if (row.channel_type === 'telegram') {
      if (enabledFlag && liveFlag && row.has_credentials && readyStatus) return 'Demo channel ready';
      if (enabledFlag && row.has_credentials) return 'Working for testing';
      return enabledFlag ? 'Telegram setup pending' : 'Disabled for tenant';
    }

    if (row.channel_type === 'whatsapp') {
      const hasRoutingId = Boolean(row.provider_channel_id) || hasSafeConfigValue(row, 'phone_number_id');
      if (enabledFlag && liveFlag && row.has_credentials && hasRoutingId && readyStatus) return 'Meta credentials stored';
      return 'Production channel pending';
    }

    if (row.channel_type === 'web_chat') {
      if (enabledFlag && liveFlag && readyStatus) return 'Available for testing';
      if (enabledFlag && readyStatus) return 'First-party demo channel';
      return 'First-party demo setup pending';
    }

    if (row.channel_type === 'email') {
      if (enabledFlag && liveFlag && row.has_credentials && readyStatus) return 'Production-connectable email channel';
      if (enabledFlag && row.has_credentials && readyStatus) return 'SMTP and IMAP credentials stored';
      return enabledFlag ? 'Email setup pending' : 'Disabled for tenant';
    }

    if (row.channel_type === 'instagram' || row.channel_type === 'facebook') {
      if (enabledFlag && liveFlag && row.has_credentials && readyStatus) return 'Ready for testing after Meta setup';
      if (enabledFlag && row.has_credentials && readyStatus) return 'Credential-ready Meta channel';
      return enabledFlag ? 'Requires Meta app/page credentials' : 'Disabled for tenant';
    }

    return 'Future adapter';
  }

  function channelDescription(row: Channel) {
    if (row.channel_type === 'telegram') return 'Telegram can be used for local/free demo testing.';
    if (row.channel_type === 'whatsapp') return 'WhatsApp requires official Meta credentials before production live send.';
    if (row.channel_type === 'web_chat') return 'First-party demo channel for tenant website testing. No external provider credentials required.';
    if (row.channel_type === 'email') return 'SMTP outbound plus IMAP polling for production-capable inbound email.';
    if (row.channel_type === 'instagram') return 'Meta social messaging channel. Live use may require Meta permissions, webhook setup, and app review.';
    if (row.channel_type === 'facebook') return 'Meta social messaging channel. Live use may require Meta permissions, webhook setup, and app review.';
    return 'Planned adapter. Credential setup is not available on this screen yet.';
  }

  function channelBadgeClass(row: Channel) {
    const headline = channelHeadline(row);
    if (headline.includes('ready') || headline.includes('Working') || headline === 'Meta credentials stored' || headline === 'Available for testing' || headline === 'Production-connectable email channel') return 'connected';
    if (headline === 'Future adapter') return 'future';
    if (row.public_config?.enabled === false) return 'disabled';
    return 'pending';
  }

  function setupItems(row: Channel) {
    const enabledFlag = row.public_config?.enabled === true;
    const liveFlag = row.public_config?.live_send_enabled === true;
    const statusReady = ['connected', 'configured', 'active'].includes(row.status);
    const hasRoutingId = Boolean(row.provider_channel_id) || hasSafeConfigValue(row, 'phone_number_id');
    const hasWabaId = Boolean(row.provider_account_id) || hasSafeConfigValue(row, 'waba_id');

    if (row.channel_type === 'telegram') {
      return [
        { label: 'Runtime status', value: statusReady && enabledFlag ? 'Enabled' : enabledFlag ? `Status: ${row.status}` : 'Disabled' },
        { label: 'Bot credentials', value: row.has_credentials ? 'Stored securely' : 'Missing bot token' },
        { label: 'Provider routing ID', value: hasRoutingId ? 'Configured, hidden' : 'Not required for polling/demo routing' },
        { label: 'Live send', value: liveFlag ? 'Enabled for testing' : 'Off' },
      ];
    }

    if (row.channel_type === 'whatsapp') {
      return [
        { label: 'Runtime status', value: statusReady && enabledFlag ? 'Enabled' : enabledFlag ? `Status: ${row.status}` : 'Disabled' },
        { label: 'Phone number ID', value: hiddenConfigured(hasRoutingId) },
        { label: 'Access token', value: row.has_credentials ? 'Credential bundle stored; not itemized by API' : 'Not stored' },
        { label: 'Verify token', value: row.has_credentials ? 'Credential bundle stored; not itemized by API' : 'Not stored' },
        { label: 'App secret', value: row.has_credentials ? 'Credential bundle stored; not itemized by API' : 'Not stored' },
        { label: 'WABA ID', value: hiddenConfigured(hasWabaId, 'Optional / not reported') },
        { label: 'Live send', value: liveFlag ? 'Enabled' : 'Off until Meta setup is ready' },
        { label: 'Public HTTPS webhook URL', value: 'Required later' },
        { label: 'Approved templates', value: 'Required later' },
      ];
    }

    if (row.channel_type === 'web_chat') {
      return [
        { label: 'Runtime status', value: statusReady && enabledFlag ? 'Enabled' : enabledFlag ? `Status: ${row.status}` : 'Enable when ready' },
        { label: 'Credentials', value: 'Not required' },
        { label: 'Tenant endpoint', value: `/channels/web-chat/${tenantSlug}/message` },
        { label: 'Visitor identity', value: 'Generated or supplied by widget' },
        { label: 'Embed widget', value: 'Later' },
        { label: 'Live send', value: liveFlag ? 'On for local/demo testing' : 'Off' },
      ];
    }

    if (row.channel_type === 'email') {
      return [
        { label: 'Runtime status', value: statusReady && enabledFlag ? 'Enabled' : enabledFlag ? `Status: ${row.status}` : 'Disabled' },
        { label: 'SMTP credentials', value: row.has_credentials ? 'Stored securely' : 'Missing SMTP credentials' },
        { label: 'Outbound send', value: liveFlag && row.has_credentials ? 'Ready when SMTP accepts mail' : 'Stored only until SMTP is ready' },
        { label: 'Inbound test endpoint', value: `/channels/email/${tenantSlug}/inbound-test` },
        { label: 'IMAP poll endpoint', value: `/channels/email/${tenantSlug}/poll-once` },
        { label: 'Inbound secret', value: row.has_credentials ? 'Optional secret may be stored' : 'Optional for local testing' },
        { label: 'Production inbound', value: row.has_credentials ? 'IMAP polling credentials can be stored' : 'Requires IMAP credentials' },
      ];
    }

    if (row.channel_type === 'instagram' || row.channel_type === 'facebook') {
      const accountLabel = row.channel_type === 'instagram' ? 'Instagram business account ID' : 'Page ID';
      return [
        { label: 'Runtime status', value: statusReady && enabledFlag ? 'Enabled' : enabledFlag ? `Status: ${row.status}` : 'Disabled' },
        { label: 'Meta credentials', value: row.has_credentials ? 'Stored securely' : 'Missing Meta credentials' },
        { label: accountLabel, value: row.has_credentials ? 'Stored securely if provided' : 'Required before live testing' },
        { label: 'Inbound test endpoint', value: `/channels/${row.channel_type}/${tenantSlug}/inbound-test` },
        { label: 'Real webhook endpoint', value: `/channels/${row.channel_type}/webhook` },
        { label: 'Provider sender identity', value: 'Stored from inbound test sender ID' },
        { label: 'Live send', value: liveFlag && row.has_credentials ? 'On after Meta setup' : 'Stored only until credentials are ready' },
        { label: 'Meta permissions', value: 'May require webhook setup and app review' },
      ];
    }

    return [
      { label: 'Runtime status', value: 'Planned' },
      { label: 'Credentials', value: 'Not supported yet' },
      { label: 'Provider routing', value: 'Future adapter' },
      { label: 'Live send', value: 'Unavailable' },
    ];
  }

  function resetTestConsole() {
    setTestSessionId(null);
    setTestMessages([]);
    setTestResult(null);
    setTestError(null);
    setTestInput('');
  }

  async function sendTestMessage(messageText: string) {
    const message = messageText.trim();
    if (!message || testingChannel) return;
    const localId = `${Date.now()}`;
    setTestingChannel(true);
    setTestError(null);
    setTestInput('');
    setTestMessages((items) => [...items, { id: `customer-${localId}`, role: 'customer', text: message }]);
    try {
      const result = await api.testChannel(token, tenantSlug, { channel_type: testChannel, session_id: testSessionId, message });
      setTestResult(result);
      setTestSessionId(result.session_id);
      setTestMessages((items) => [
        ...items,
        {
          id: `agent-${localId}`,
          role: result.reply ? 'agent' : 'system',
          text: result.reply || (result.handoff ? 'No auto-reply. Conversation moved to human handoff.' : 'No auto-reply returned.'),
        },
      ]);
    } catch (error) {
      const text = error instanceof Error ? error.message : 'Channel test failed';
      setTestError(text);
      setTestMessages((items) => [...items, { id: `system-${localId}`, role: 'system', text }]);
    } finally {
      setTestingChannel(false);
      window.setTimeout(() => testInputRef.current?.focus(), 0);
    }
  }

  async function submitTestMessage(e: FormEvent) {
    e.preventDefault();
    await sendTestMessage(testInput);
  }

  return <section className="channels-shell">
    <div className="channels-hero">
      <div>
        <p className="eyebrow">Channel settings</p>
        <h2>Tenant communication channels</h2>
        <p className="muted">Manage channel availability, live-send posture, and encrypted provider credentials without exposing raw secret values.</p>
      </div>
      <div className="channels-hero-side">
        <div className="channels-summary-grid" aria-label="Channel settings summary">
          <div><span>Configured</span><strong>{configuredCount}</strong></div>
          <div><span>Credentials</span><strong>{credentialCount}</strong></div>
          <div><span>Live send</span><strong>{liveChannelCount}</strong></div>
        </div>
        <button className="channel-test-launch" type="button" onClick={() => setTestConsoleOpen(true)}>Test channel</button>
      </div>
    </div>

    <div className="grid two channels-layout">
      <form className="card form-stack channel-form-card" onSubmit={submit}>
        <div className="channel-card-head">
          <div>
            <p className="eyebrow">Secure setup</p>
            <h3>Tenant-scoped channel config</h3>
            <p className="muted">Update one channel at a time. Existing credential-like values are masked and should only be replaced when rotating configuration.</p>
          </div>
          <span className={`channel-state-badge ${channelBadgeClass(selectedPreviewRow())}`}>{channelHeadline(selectedPreviewRow())}</span>
        </div>
        <div className="channel-form-grid">
          <label>Channel
            <span className="field-helper">Choose the tenant channel to configure.</span>
            <select value={channel} onChange={(e) => setChannel(e.target.value)}>{channelOptions.map((option) => <option key={option} value={option}>{channelLabel(option)}</option>)}</select>
          </label>
          <div className="channel-readonly-status">
            <span>Derived status</span>
            <strong>{derivedSaveStatus()}</strong>
            <p>Status is calculated from adapter support, enablement, credentials, routing, and live-send posture.</p>
          </div>
          <div className="two-field-row">
            <div className={`channel-toggle-field ${controlsLocked ? 'disabled' : ''}`}>
              <span>Enabled</span>
              <span className="field-helper">Controls whether the tenant can use this channel.</span>
              <button className={`toggle-switch ${enabled === 'true' ? 'on' : ''}`} type="button" role="switch" aria-checked={enabled === 'true'} disabled={controlsLocked} onClick={() => setEnabled(enabled === 'true' ? 'false' : 'true')}>
                <span className="toggle-track"><i /></span>
                <strong>{enabled === 'true' ? 'Enabled' : 'Disabled'}</strong>
              </button>
            </div>
            <div className={`channel-toggle-field ${controlsLocked ? 'disabled' : ''}`}>
              <span>Live send</span>
              <span className="field-helper">Only enable after provider credentials and testing are ready.</span>
              <button className={`toggle-switch ${liveSendEnabled === 'true' ? 'on' : ''}`} type="button" role="switch" aria-checked={liveSendEnabled === 'true'} disabled={controlsLocked} onClick={() => setLiveSendEnabled(liveSendEnabled === 'true' ? 'false' : 'true')}>
                <span className="toggle-track"><i /></span>
                <strong>{liveSendEnabled === 'true' ? 'On' : 'Off'}</strong>
              </button>
            </div>
          </div>
        </div>
        {channel === 'whatsapp' && <div className="channel-secret-grid">
          <label>Phone number ID
            <span className="field-helper">Stored value is hidden. Enter a replacement only when updating this provider setting.</span>
            <input type="password" placeholder={selectedChannelRow?.public_config?.phone_number_id ? 'Saved value hidden' : 'Enter provider value'} value={phoneNumberId} onChange={(e) => setPhoneNumberId(e.target.value)} autoComplete="off" />
          </label>
          <label>Access token
            <span className="field-helper">Encrypted after save. The current token is never displayed.</span>
            <input type="password" placeholder="Paste replacement token" value={accessToken} onChange={(e) => setAccessToken(e.target.value)} autoComplete="off" />
          </label>
          <label>Verify token
            <span className="field-helper">Encrypted after save and hidden from status cards.</span>
            <input type="password" placeholder="Paste replacement verify token" value={verifyToken} onChange={(e) => setVerifyToken(e.target.value)} autoComplete="off" />
          </label>
          <label>App secret
            <span className="field-helper">Encrypted after save. Do not share this outside the tenant admin workflow.</span>
            <input type="password" placeholder="Paste replacement app secret" value={appSecret} onChange={(e) => setAppSecret(e.target.value)} autoComplete="off" />
          </label>
        </div>}
        {channel === 'telegram' && <div className="channel-secret-grid"><label>Bot token
          <span className="field-helper">Encrypted after save. The current bot token is never displayed.</span>
          <input type="password" placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'Paste bot token'} value={botToken} onChange={(e) => setBotToken(e.target.value)} autoComplete="off" />
        </label></div>}
        {channel === 'email' && <div className="channel-secret-grid">
          <label>SMTP host
            <span className="field-helper">Encrypted after save. Enter a replacement only when updating email settings.</span>
            <input placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'smtp.example.com'} value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} autoComplete="off" />
          </label>
          <label>SMTP port
            <span className="field-helper">Usually 587 for TLS or 465 for SSL.</span>
            <input inputMode="numeric" placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : '587'} value={smtpPort} onChange={(e) => setSmtpPort(e.target.value)} autoComplete="off" />
          </label>
          <label>SMTP username
            <span className="field-helper">Encrypted after save and never shown back in the UI.</span>
            <input placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'SMTP username'} value={smtpUsername} onChange={(e) => setSmtpUsername(e.target.value)} autoComplete="off" />
          </label>
          <label>SMTP password
            <span className="field-helper">Encrypted after save. The current password is never displayed.</span>
            <input type="password" placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'SMTP password'} value={smtpPassword} onChange={(e) => setSmtpPassword(e.target.value)} autoComplete="new-password" />
          </label>
          <label>From email
            <span className="field-helper">The sender address used for tenant email replies.</span>
            <input type="email" placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'support@business.com'} value={smtpFromEmail} onChange={(e) => setSmtpFromEmail(e.target.value)} autoComplete="off" />
          </label>
          <label>From name
            <span className="field-helper">Optional display name for outbound email.</span>
            <input placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'Business Support'} value={smtpFromName} onChange={(e) => setSmtpFromName(e.target.value)} autoComplete="off" />
          </label>
          <label>Use TLS
            <span className="field-helper">StartTLS is typical for port 587.</span>
            <select value={smtpUseTls} onChange={(e) => setSmtpUseTls(e.target.value)}><option value="true">true</option><option value="false">false</option></select>
          </label>
          <label>Use SSL
            <span className="field-helper">Usually true only for port 465.</span>
            <select value={smtpUseSsl} onChange={(e) => setSmtpUseSsl(e.target.value)}><option value="false">false</option><option value="true">true</option></select>
          </label>
          <label>Inbound webhook secret
            <span className="field-helper">Optional for provider-neutral inbound testing. Stored encrypted if entered.</span>
            <input type="password" placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'Optional test secret'} value={emailInboundSecret} onChange={(e) => setEmailInboundSecret(e.target.value)} autoComplete="new-password" />
          </label>
          <label>IMAP host
            <span className="field-helper">Used by the protected poll-once endpoint for production inbound email.</span>
            <input placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'imap.example.com'} value={imapHost} onChange={(e) => setImapHost(e.target.value)} autoComplete="off" />
          </label>
          <label>IMAP port
            <span className="field-helper">Usually 993 for SSL.</span>
            <input inputMode="numeric" placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : '993'} value={imapPort} onChange={(e) => setImapPort(e.target.value)} autoComplete="off" />
          </label>
          <label>IMAP username
            <span className="field-helper">Encrypted after save and never shown back in the UI.</span>
            <input placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'IMAP username'} value={imapUsername} onChange={(e) => setImapUsername(e.target.value)} autoComplete="off" />
          </label>
          <label>IMAP password
            <span className="field-helper">Encrypted after save. The current password is never displayed.</span>
            <input type="password" placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'IMAP password'} value={imapPassword} onChange={(e) => setImapPassword(e.target.value)} autoComplete="new-password" />
          </label>
          <label>IMAP mailbox
            <span className="field-helper">Defaults to INBOX when omitted.</span>
            <input placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'INBOX'} value={imapMailbox} onChange={(e) => setImapMailbox(e.target.value)} autoComplete="off" />
          </label>
          <label>IMAP SSL
            <span className="field-helper">Usually true for port 993.</span>
            <select value={imapUseSsl} onChange={(e) => setImapUseSsl(e.target.value)}><option value="true">true</option><option value="false">false</option></select>
          </label>
        </div>}
        {(channel === 'instagram' || channel === 'facebook') && <div className="channel-secret-grid">
          <label>Page access token
            <span className="field-helper">Encrypted after save. The current token is never displayed.</span>
            <input type="password" placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'Paste page access token'} value={metaPageAccessToken} onChange={(e) => setMetaPageAccessToken(e.target.value)} autoComplete="new-password" />
          </label>
          <label>App secret
            <span className="field-helper">Encrypted after save and used for future Meta webhook signature checks.</span>
            <input type="password" placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'Paste app secret'} value={metaAppSecret} onChange={(e) => setMetaAppSecret(e.target.value)} autoComplete="new-password" />
          </label>
          <label>Verify token
            <span className="field-helper">Encrypted after save. Used later when enabling real Meta webhook verification.</span>
            <input type="password" placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'Paste verify token'} value={metaVerifyToken} onChange={(e) => setMetaVerifyToken(e.target.value)} autoComplete="new-password" />
          </label>
          <label>Inbound test secret
            <span className="field-helper">Optional provider-neutral test secret. Stored encrypted if entered.</span>
            <input type="password" placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'Optional test secret'} value={metaWebhookSecret} onChange={(e) => setMetaWebhookSecret(e.target.value)} autoComplete="new-password" />
          </label>
          <label>Page ID
            <span className="field-helper">Required for Facebook Messenger live testing. Optional context for Instagram setup.</span>
            <input placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'Meta page ID'} value={metaPageId} onChange={(e) => setMetaPageId(e.target.value)} autoComplete="off" />
          </label>
          <label>Instagram business account ID
            <span className="field-helper">Required for Instagram live testing. Leave blank for Facebook-only setup.</span>
            <input placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'Instagram business account ID'} value={metaInstagramBusinessAccountId} onChange={(e) => setMetaInstagramBusinessAccountId(e.target.value)} autoComplete="off" />
          </label>
          <label>Graph API version
            <span className="field-helper">Optional. Defaults safely on the backend when omitted.</span>
            <input placeholder={selectedChannelRow?.has_credentials ? 'Saved value hidden' : 'v20.0'} value={metaGraphApiVersion} onChange={(e) => setMetaGraphApiVersion(e.target.value)} autoComplete="off" />
          </label>
        </div>}
        {channel === 'telegram' && <div className="channel-help-note neutral"><strong>Testing channel</strong><p>Telegram can be used for local/free demo testing. A provider routing ID is not required unless a specific routing method is added later.</p></div>}
        {channel === 'whatsapp' && <div className="channel-help-note"><strong>Production channel</strong><p>WhatsApp requires official Meta credentials before production live send. Saved values stay hidden and tenant-scoped.</p></div>}
        {channel === 'web_chat' && <div className="channel-help-note neutral"><strong>First-party demo channel</strong><p>Use <code>/channels/web-chat/{tenantSlug}/message</code> with the tenant slug and a visitor ID. A full embeddable widget can be added later.</p></div>}
        {channel === 'email' && <div className="channel-help-note neutral"><strong>Production-connectable email channel</strong><p>Use SMTP for outbound and the protected <code>/channels/email/{tenantSlug}/poll-once</code> endpoint for IMAP inbound polling. The inbound-test route remains available for local testing.</p></div>}
        {(channel === 'instagram' || channel === 'facebook') && <div className="channel-help-note neutral"><strong>Credential-ready Meta channel</strong><p>Use <code>/channels/{channel}/{tenantSlug}/inbound-test</code> for provider-neutral testing. Live use may require Meta permissions, webhook setup, and app review.</p></div>}
        {selectedIsFutureAdapter && <div className="channel-help-note neutral"><strong>Adapter not implemented yet</strong><p>This channel is represented in the platform roadmap, but live enablement is locked until a backend adapter exists.</p></div>}
        {channelMessage && <p className="settings-status success">{channelMessage}</p>}
        <div className="channel-form-actions">
          <button disabled={savingChannel || controlsLocked}>{savingChannel ? 'Saving...' : controlsLocked ? 'Adapter not implemented' : 'Save encrypted config'}</button>
        </div>
      </form>

      <div className="card channel-list-card">
        <div className="channel-card-head">
          <div>
            <p className="eyebrow">Connection posture</p>
            <h3>Channels</h3>
            <p className="muted">Safe status overview only. Raw provider identifiers, tokens, and secrets are never shown here.</p>
          </div>
        </div>
        <div className="channel-table">
          {channelOptions.map((channelType) => {
            const row = rows.find((item) => item.channel_type === channelType) || { channel_type: channelType, status: ['whatsapp', 'web_chat', 'email', 'instagram', 'facebook'].includes(channelType) ? 'configured' : channelType === 'telegram' ? 'not_connected' : 'future', public_config: {}, has_credentials: false };
            const statusClass = channelBadgeClass(row);
            const headline = channelHeadline(row);
            return <div className="channel-status-card" key={row.channel_type}>
              <div className="channel-status-head">
                <div className={`status-dot ${statusClass === 'connected' ? 'on' : statusClass === 'future' ? 'idle' : 'off'}`} />
                <div>
                  <strong>{channelLabel(row.channel_type)}</strong>
                  <p>{channelDescription(row)}</p>
                </div>
                <span className={`channel-state-badge ${statusClass}`}>{headline}</span>
              </div>
              <div className="channel-status-grid">
                {setupItems(row).map((item) => <div key={`${row.channel_type}-${item.label}`}><small>{item.label}</small><span>{item.value}</span></div>)}
              </div>
            </div>;
          })}
        </div>
      </div>
    </div>
    {testConsoleOpen && typeof document !== 'undefined' && createPortal(
      <div className="channel-test-overlay" role="dialog" aria-modal="true" aria-labelledby="channel-test-title" onMouseDown={(event) => {
        if (event.target === event.currentTarget) setTestConsoleOpen(false);
      }}>
        <div className="channel-test-window">
          <div className="channel-test-titlebar">
            <div>
              <h3 id="channel-test-title">Channel Test Console</h3>
              <p>Dry-run inbox for tenant-scoped agent replies.</p>
            </div>
            <button className="secondary" type="button" onClick={() => setTestConsoleOpen(false)}>Close</button>
          </div>
          <div className="channel-test-body">
            <aside className="channel-test-sidebar">
              <div>
                <p className="eyebrow">Select channel</p>
                <p className="muted">Only enabled, implemented tenant channels are available for dry-run testing.</p>
              </div>
              <div className="channel-test-picker">
                {testableChannels.map((item) => <button
                  type="button"
                  key={item.channelType}
                  disabled={!item.available || testingChannel}
                  className={testChannel === item.channelType ? 'active' : ''}
                  onClick={() => {
                    setTestChannel(item.channelType);
                    resetTestConsole();
                  }}
                >
                  <span>{channelLabel(item.channelType)}</span>
                  <small>{item.available ? channelHeadline(item.row as Channel) : item.reason}</small>
                </button>)}
              </div>
              <button className="secondary" type="button" onClick={resetTestConsole} disabled={testingChannel}>Reset session</button>
            </aside>
            <div className="channel-test-inbox">
              <div className="channel-test-status">
                <div><span>Channel</span><strong>{channelLabel(testChannel)}</strong></div>
                <div><span>State</span><strong>{testResult?.state || 'Ready'}</strong></div>
                <div><span>Handoff</span><strong>{testResult ? (testResult.handoff ? 'Yes' : 'No') : 'No'}</strong></div>
                <div><span>Last status</span><strong>{testError ? 'Rejected' : testingChannel ? 'Testing' : testResult ? 'Dry-run stored' : 'Idle'}</strong></div>
              </div>
              <div className="virtual-inbox" aria-live="polite" ref={testInboxRef}>
                {testMessages.length === 0 ? <div className="channel-test-empty">
                  <strong>Start a virtual customer chat</strong>
                  <p>Messages are stored with a synthetic test identity and outbound provider APIs are bypassed.</p>
                </div> : testMessages.map((item) => <div className={`test-bubble ${item.role}`} key={item.id}>
                  <span>{item.role === 'customer' ? 'Customer' : item.role === 'agent' ? 'Agent' : 'System'}</span>
                  <p>{item.text}</p>
                  {item.role === 'system' && testResult?.handoff && item.text.includes('human handoff') && <button className="return-to-bot-button" type="button" onClick={() => void sendTestMessage('bot')} disabled={testingChannel}>Return to bot</button>}
                </div>)}
              </div>
              {testError && <p className="settings-status error">{testError}</p>}
              <form className="channel-test-compose" onSubmit={submitTestMessage}>
                <input ref={testInputRef} value={testInput} onChange={(event) => setTestInput(event.target.value)} placeholder="Type a fake customer message..." disabled={testingChannel} />
                <button type="submit" disabled={testingChannel || !testInput.trim()}>{testingChannel ? 'Testing...' : 'Send test'}</button>
              </form>
              <p className="channel-test-footnote">Session: {testSessionId || 'new'} · Source: channel_test_console · No secrets or raw provider payloads shown.</p>
            </div>
          </div>
        </div>
      </div>,
      document.body
    )}
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
  return <div className="list">{rows.length === 0 && <p className="muted">No rows yet.</p>}{rows.map((r, idx) => <DiagnosticOutput key={idx} title={`Row ${idx + 1}`} description="Safe row details with credential-like values hidden." data={r as Record<string, unknown>} />)}</div>;
}

function SimpleTable<T extends object>({ title, rows }: { title: string; rows: T[] }) {
  const keys = useMemo(() => Array.from(new Set(rows.flatMap((r) => Object.keys(r)))).slice(0, 8), [rows]);
  return <section className="card audit-panel">
    <div className="system-panel-head">
      <div>
        <p className="eyebrow">Audit</p>
        <h3>{title}</h3>
        <p className="muted">Tenant-scoped administrative activity for review and support diagnostics.</p>
      </div>
      <span className="audit-count-pill">{rows.length} rows</span>
    </div>
    {rows.length === 0 ? <div className="system-empty-state"><strong>No audit entries yet</strong><p>Activity will appear here after tenant actions are recorded.</p></div> : <div className="table-wrap audit-table-wrap"><table><thead><tr>{keys.map((k) => <th key={k}>{prettifyKeyLabel(k)}</th>)}</tr></thead><tbody>{rows.map((r, i) => { const obj = r as Record<string, unknown>; return <tr key={i}>{keys.map((k) => <td key={k}>{typeof obj[k] === 'object' ? <code className="audit-cell-code">{formatDiagnosticValue(obj[k])}</code> : formatDiagnosticValue(obj[k])}</td>)}</tr>; })}</tbody></table></div>}
  </section>;
}
