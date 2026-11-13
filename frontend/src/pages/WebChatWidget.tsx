import { useEffect, useState, type FormEvent } from 'react';
import { api, widgetBaseUrl, type WidgetSettings, type WidgetSettingsResult } from '../services/api';

const EMPTY: WidgetSettings = { allowed_websites: [], welcome_ar: '', welcome_en: '', language: 'auto', position: 'right' };

// The "put the chat on your website" step of the Web chat channel.
export function WebChatWidget({ token, tenantSlug, refreshKey }: { token: string; tenantSlug: string; refreshKey: unknown }) {
  const [result, setResult] = useState<WidgetSettingsResult | null>(null);
  const [form, setForm] = useState<WidgetSettings>(EMPTY);
  const [websites, setWebsites] = useState('');
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  function apply(next: WidgetSettingsResult) {
    setResult(next);
    setForm(next.settings);
    setWebsites(next.settings.allowed_websites.join('\n'));
    setDirty(false);
  }

  useEffect(() => {
    api.widgetSettings(token, tenantSlug).then(apply).catch(() => setError('Could not load the website chat settings. Refresh and try again.'));
  }, [token, tenantSlug, refreshKey]);

  function change<K extends keyof WidgetSettings>(key: K, value: WidgetSettings[K]) {
    setForm({ ...form, [key]: value });
    setDirty(true);
    setNotice(null);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const allowed_websites = websites.split(/[\n,]+/).map(line => line.trim()).filter(Boolean);
      apply(await api.saveWidgetSettings(token, tenantSlug, { ...form, allowed_websites }));
      setNotice('Website chat settings saved.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the website chat settings.');
    } finally {
      setBusy(false);
    }
  }

  const base = widgetBaseUrl();
  const workspace = result?.workspace || tenantSlug;
  const embedCode = `<script src="${base}/widget.js" data-workspace="${workspace}" async></script>`;
  const previewUrl = `${base}/widget/${encodeURIComponent(workspace)}/preview`;
  const status = result?.status;
  const live = Boolean(status?.channel_enabled && status?.workspace_published);

  async function copy() {
    try {
      await navigator.clipboard.writeText(embedCode);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError('Copying was blocked by the browser. Select the code and copy it instead.');
    }
  }

  return (
    <section className="channel-setup-layout widget-setup">
      <form className="card form-stack" onSubmit={save}>
        <div className="step-heading"><span>4</span><div>
          <h3>Put the chat on your website</h3>
          <p className="muted">Visitors chat with your agent from a button in the corner of your website. When a visitor asks for a person, the chat appears in your inbox and your replies show up in their chat window.</p>
        </div></div>
        {error && <div className="error-box" role="alert">{error}</div>}
        {notice && <div className="connection-check" role="status">{notice}</div>}
        <label>Websites that may show the chat
          <textarea value={websites} onChange={e => { setWebsites(e.target.value); setDirty(true); setNotice(null); }} rows={3} placeholder={'https://www.your-website.com\nhttps://booking.your-website.com'} spellCheck={false} />
          <small className="muted">One address per line. Other websites cannot show your chat. Include both versions if your site works with and without "www".</small>
        </label>
        <div className="channel-fields">
          <label>Welcome message (Arabic)
            <textarea dir="rtl" rows={2} maxLength={300} value={form.welcome_ar} onChange={e => change('welcome_ar', e.target.value)} placeholder="مرحباً! كيف نقدر نساعدك اليوم؟" />
          </label>
          <label>Welcome message (English)
            <textarea rows={2} maxLength={300} value={form.welcome_en} onChange={e => change('welcome_en', e.target.value)} placeholder="Hi! How can we help you today?" />
          </label>
          <label>Chat language
            <select value={form.language} onChange={e => change('language', e.target.value as WidgetSettings['language'])}>
              <option value="auto">Match the website and visitor</option>
              <option value="ar">Arabic</option>
              <option value="en">English</option>
            </select>
          </label>
          <label>Button position
            <select value={form.position} onChange={e => change('position', e.target.value as WidgetSettings['position'])}>
              <option value="right">Bottom right</option>
              <option value="left">Bottom left</option>
            </select>
          </label>
        </div>
        <small className="muted">The chat uses your business name, logo, and brand colour from Business settings.</small>
        <div className="button-row"><button disabled={busy || !dirty}>{busy ? 'Saving…' : 'Save website chat'}</button><span className="muted">{dirty ? 'Unsaved changes' : 'Saved'}</span></div>
      </form>
      <aside className="channel-checks-stack">
        <section className="card">
          <div className="step-heading"><span>5</span><div><h3>Add the code to your website</h3><p className="muted">Paste this just before <code>&lt;/body&gt;</code> on every page, or give it to your web developer.</p></div></div>
          <ul className="setup-check-list">
            <li><span className={status?.channel_enabled ? 'check-done' : ''}>{status?.channel_enabled ? '✓' : '○'}</span>Web chat is enabled<small>{status?.channel_enabled ? 'Done' : 'Step 1 above'}</small></li>
            <li><span className={status?.workspace_published ? 'check-done' : ''}>{status?.workspace_published ? '✓' : '○'}</span>Workspace is published<small>{status?.workspace_published ? 'Done' : 'Setup guide'}</small></li>
            <li><span className={status?.has_websites ? 'check-done' : ''}>{status?.has_websites ? '✓' : '○'}</span>Your website is listed<small>{status?.has_websites ? 'Done' : 'Add it here'}</small></li>
          </ul>
          <pre className="embed-code" aria-label="Website code"><code>{embedCode}</code></pre>
          <div className="button-row">
            <button type="button" className="secondary" onClick={() => void copy()}>{copied ? 'Copied' : 'Copy code'}</button>
            {live
              ? <a className="button-link secondary" href={previewUrl} target="_blank" rel="noreferrer">Open a preview ↗</a>
              : <span className="muted">The preview opens once web chat is enabled and the workspace is published.</span>}
          </div>
          {live && !status?.has_websites && <p className="muted">Until you list your website, the chat appears only in the preview.</p>}
        </section>
      </aside>
    </section>
  );
}
