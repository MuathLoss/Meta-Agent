import { useEffect, useMemo, useState, type ChangeEvent } from 'react';
import { api, type SmartImportRow, type SmartImportPreview, type IntentItem, type ImportJob, type ImportJobSummary, type ImportGrouping } from '../services/api';
const normalizeIntentCode = (value: string) => value.trim().toUpperCase().replace(/[^A-Z0-9_]+/g, '_');
const normalizeTopicKey = (value: string) => value.trim().toLowerCase().replace(/[^a-z0-9_]+/g, '_');

type SmartImportFilter = 'all' | 'high' | 'review';

function isHighConfidenceSmartRow(row: SmartImportRow) {
  return row.confidence >= 0.8 && !row.warnings.includes('needs_review');
}

export function SmartImportStudio({ token, tenantSlug, reload, intents, onDirtyChange }: { onDirtyChange: (dirty: boolean) => void; token: string; tenantSlug: string; reload: () => Promise<void>; intents: IntentItem[] }) {
  const [pasteText, setPasteText] = useState('');
  const [job, setJob] = useState<ImportJob | null>(null);
  const [title, setTitle] = useState('Message import');
  const [history, setHistory] = useState<ImportJobSummary[]>([]);
  const [savingDraft, setSavingDraft] = useState(false);
  const [dirty, setDirty] = useState(false);
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);
  const [undoTarget, setUndoTarget] = useState<ImportJobSummary | null>(null);
  const [grouping, setGrouping] = useState<ImportGrouping | null>(null);
  const [groupIndex, setGroupIndex] = useState<number | null>(null);
  const completedJob = Boolean(job && job.status !== 'draft');
  async function refreshHistory() { setHistory(await api.importJobs(token, tenantSlug)); }
  useEffect(() => { void refreshHistory().catch(() => setError('Import history is unavailable. Apply the database update before using saved reviews.')); }, [token, tenantSlug]);
  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [dirty]);
  async function saveDraft() {
    if (!preview || completedJob) return null;
    setSavingDraft(true); setError(null);
    try {
      const data = {title, source_type: preview.source_type, preview: {...preview, rows}, rows, revision: job?.revision};
      const saved = job ? await api.updateImportJob(token, tenantSlug, job.id, data) : await api.createImportJob(token, tenantSlug, data);
      setJob(saved); setDirty(false); setResultMessage('Review saved. You can close this window and resume from import history.');
      await refreshHistory(); return saved;
    } catch(e) {setError(e instanceof Error ? e.message : 'Could not save review.'); return null;}
    finally {setSavingDraft(false);}
  }
  async function openSaved(saved: ImportJobSummary) {
    if (dirty && !window.confirm('Open another review? Unsaved corrections will be lost. Save the review first to keep them.')) return;
    setLoading(true); setError(null);
    try { const full = await api.importJob(token, tenantSlug, saved.id); setJob(full); setTitle(full.title); setPreview(full.preview); setRows(full.rows); setDirty(false); setGrouping(null); setGroupIndex(null); setResultMessage(full.status === 'imported' ? 'This import is complete. Its saved review is read-only.' : null); }
    catch(e) {setError(e instanceof Error ? e.message : 'Could not open review.');} finally {setLoading(false);}
  }
  async function undoSaved() {
    if (!undoTarget) return;
    setSavingDraft(true); setError(null);
    try {await api.undoImportJob(token, tenantSlug, undoTarget.id, undoTarget.revision); if (job?.id === undoTarget.id) {setJob({...job, status: 'undone', revision: job.revision + 1}); setDirty(false);} setUndoTarget(null); setResultMessage('Import undone. Later edits were protected.'); await refreshHistory(); await reload();}
    catch(e) {setError(e instanceof Error ? e.message : 'Could not undo import.');} finally {setSavingDraft(false);}
  }
  async function groupRows() {
    const saved = dirty || !job ? await saveDraft() : job;
    if (!saved) return;
    setLoading(true); setError(null);
    try {setGrouping(await api.groupImportJob(token, tenantSlug, saved.id)); setGroupIndex(null);}
    catch(e) {setError(e instanceof Error ? e.message : 'Could not group messages.');} finally {setLoading(false);}
  }

  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<SmartImportPreview | null>(null);
  const [rows, setRows] = useState<SmartImportRow[]>([]);
  const [confidenceFilter, setConfidenceFilter] = useState<SmartImportFilter>('all');
  const [loading, setLoading] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resultMessage, setResultMessage] = useState<string | null>(null);
  const approvedCount = rows.filter((row) => row.decision === 'approved').length;
  const rejectedCount = rows.filter((row) => row.decision === 'rejected').length;
  const highConfidenceCount = rows.filter((row) => isHighConfidenceSmartRow(row)).length;
  const needsReviewCount = rows.filter((row) => !isHighConfidenceSmartRow(row)).length;
  const existingIntentCodes = useMemo(() => new Set(intents.map((intent) => intent.code)), [intents]);
  const visibleRows = rows.filter((row) => {
    if (groupIndex !== null && grouping && !grouping.groups[groupIndex]?.row_ids.includes(row.row_id)) return false;
    if (confidenceFilter === 'high') return isHighConfidenceSmartRow(row);
    if (confidenceFilter === 'review') return !isHighConfidenceSmartRow(row);
    return true;
  });

  async function runPreview(mode: 'paste' | 'file') {
    if (dirty && !window.confirm('Replace this preview? Save your current review first to keep corrections.')) return;
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
      setJob(null); setDirty(true); setGrouping(null); setGroupIndex(null);
      setPreview(next);
      setRows(next.rows);
      setConfidenceFilter('all');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to preview import.');
    } finally {
      setLoading(false);
    }
  }

  function updateRow(rowId: string, patch: Partial<SmartImportRow>) {
    if (completedJob) return; setDirty(true);
    setRows((current) => current.map((row) => row.row_id === rowId ? { ...row, ...patch } : row));
  }

  function updateEditable(rowId: string, patch: Partial<SmartImportRow['editable']>) {
    if (completedJob) return; setDirty(true);
    setRows((current) => current.map((row) => row.row_id === rowId ? { ...row, editable: { ...row.editable, ...patch } } : row));
  }

  function resetImport() {
    if (dirty && !window.confirm('Clear unsaved corrections? Save your review first to keep them.')) return;
    setJob(null); setDirty(false); setGrouping(null); setGroupIndex(null);
    setPreview(null);
    setRows([]);
    setPasteText('');
    setFile(null);
    setError(null);
    setResultMessage(null);
    setConfidenceFilter('all');
  }

  async function confirmImport() {
    const savedJob = await saveDraft();
    if (!savedJob) return;
    setApproving(true);
    setError(null);
    setResultMessage(null);
    try {
      const items = rows.map((row) => {
        const answer = row.editable.faq_answer.trim();
        const answerIsArabic = /[\u0600-\u06FF]/.test(answer);
        const correctedIntent = intents.find((intent) => intent.code === row.editable.intent_code);
        return {
          row_id: row.row_id,
          decision: row.decision,
          redacted_excerpt: row.redacted_excerpt,
          normalized_text: row.normalized_text,
          intent_code: row.editable.intent_code,
          intent_label: correctedIntent?.label || row.editable.intent_code.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase()),
          create_intent: row.editable.create_intent,
          training_example_text: row.editable.training_example_text,
          keyword_phrases: row.editable.keyword_phrases,
          routing_behavior: row.editable.routing_behavior,
          apply_routing: row.editable.apply_routing === true,
          create_faq: row.editable.create_faq,
          faq_topic_key: row.editable.faq_topic_key,
          faq_question: row.editable.faq_question,
          faq_answer_ar: answerIsArabic ? answer : '',
          faq_answer_en: answerIsArabic ? '' : answer,
        };
      });
      const result = await api.smartImportApprove(token, tenantSlug, {
        job_id: savedJob.id, revision: savedJob.revision,
        source_type: preview?.source_type || 'preview',
        total_rows: preview?.total_rows || rows.length,
        items,
      });
      setJob({...savedJob, status: 'imported', revision: result.revision}); setDirty(false); await refreshHistory();
      const duplicateSummary = preview?.duplicate_rows ? ` ${preview.duplicate_rows} duplicate rows were skipped during preview.` : '';
      setResultMessage(`Saved ${result.approved_training_examples} training examples, ${result.approved_keywords} keywords, ${result.approved_faq_items} FAQ items, and ${result.approved_intents} topics. ${result.approved_routing_rules} handoff choices saved; ${result.skipped_duplicates} existing items kept. ${result.skipped_rows} rows skipped.${duplicateSummary}`);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to confirm import.');
    } finally {
      setApproving(false);
    }
  }

  return <section className="smart-import-studio" data-unsaved={dirty ? 'true' : 'false'}>
    <details className="import-history"><summary>Saved reviews & import history ({history.length})</summary>
      {history.length === 0 && <p className="muted">Saved reviews and completed imports will appear here.</p>}
      {history.map(entry => <div className="import-history-row" key={entry.id}><div><strong>{entry.title}</strong><small>{entry.row_count} messages · {entry.status === 'draft' ? 'Saved review' : entry.status === 'undone' ? 'Undone' : 'Imported'} · {entry.updated_at ? new Date(entry.updated_at).toLocaleDateString() : ''}</small></div><div className="button-row"><button className="secondary" onClick={() => void openSaved(entry)} disabled={loading || savingDraft}>{entry.status === 'draft' ? 'Resume review' : 'View'}</button>{entry.status === 'imported' && <button className="secondary" onClick={() => setUndoTarget(entry)} disabled={savingDraft}>Undo import</button>}</div></div>)}
    </details>
    {undoTarget && <div className="error-box" role="alert"><strong>Undo “{undoTarget.title}”?</strong><p>This removes items added by this import and restores its handoff changes. If any item was edited later, nothing will be undone.</p><div className="button-row"><button onClick={() => void undoSaved()} disabled={savingDraft}>Confirm undo</button><button className="secondary" onClick={() => setUndoTarget(null)}>Cancel</button></div></div>}
    {preview && <div className="import-draft-toolbar"><label>Review name<input value={title} disabled={completedJob} onChange={e => {setTitle(e.target.value); setDirty(true);}} maxLength={160} /></label><button className="secondary" onClick={() => void saveDraft()} disabled={savingDraft || completedJob || loading}>{savingDraft ? 'Saving…' : dirty ? 'Save review' : job ? 'Review saved' : 'Save review'}</button><button className="secondary" onClick={() => void groupRows()} disabled={loading || savingDraft || completedJob}>Group similar messages</button></div>}
    {grouping && <><p className="muted" role="status">{grouping.message}</p><div className="import-groups"><button className="secondary" onClick={() => setGroupIndex(null)}>All groups</button>{grouping.groups.map((g, i) => <button className={groupIndex === i ? '' : 'secondary'} key={i} onClick={() => setGroupIndex(i)}>{g.label} ({g.row_ids.length})</button>)}</div></>}

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
        <p className="muted">Use TXT, CSV, or XLSX files, up to 2 MB and 500 messages. Raw files are not kept. You can save a redacted review to finish later.</p>
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
      <div className="smart-import-action-panel">
        <div className="smart-import-filter-tabs" aria-label="Filter smart import suggestions">
          {([
            ['all', `All (${rows.length})`],
            ['high', `High confidence (${highConfidenceCount})`],
            ['review', `Needs review (${needsReviewCount})`],
          ] as Array<[SmartImportFilter, string]>).map(([filter, label]) => <button key={filter} type="button" className={confidenceFilter === filter ? 'active' : ''} onClick={() => setConfidenceFilter(filter)} disabled={rows.length === 0}>{label}</button>)}
        </div>
        <button type="button" className="secondary" onClick={resetImport} disabled={loading || approving || (!preview && !pasteText && !file)}>Clear</button>
        <button type="button" onClick={() => void confirmImport()} disabled={approving || savingDraft || completedJob || approvedCount === 0}>{approving ? 'Importing...' : 'Confirm import'}</button>
      </div>
    </div>

    {rows.length === 0 && <div className="smart-import-empty">
      <span className="smart-import-empty-icon">1</span>
      <strong>Start with a paste or file preview</strong>
      <p className="muted">The studio redacts emails, phone numbers, and URLs, then suggests training examples, keywords, and FAQ drafts for approval. Your knowledge changes only when you confirm the import.</p>
    </div>}

    {rows.length > 0 && visibleRows.length === 0 && <div className="smart-import-empty compact">
      <strong>No suggestions in this view</strong>
      <p className="muted">Switch filters to review the remaining suggestions.</p>
    </div>}

    {visibleRows.length > 0 && <div className="smart-import-list">
      {visibleRows.map((row) => {
        const correctedIntentExists = existingIntentCodes.has(row.editable.intent_code);
        const protectedIntent = row.warnings.includes('protected_handoff_intent') || ['COMPLAINT', 'HUMAN_REQUEST'].includes(row.suggested_intent.code);
        const sensitiveIntent = !protectedIntent && ['PAYMENT_TRANSFER', 'CERTIFICATES'].includes(row.suggested_intent.code);
        return <article className={`smart-import-row decision-${row.decision}`} key={row.row_id}>
        <div className="smart-import-row-main">
          <div>
            <div className="smart-import-row-top">
              <span className="config-badge">{row.detected_language.toUpperCase()}</span>
              <span className={`smart-confidence ${row.confidence >= 0.8 ? 'high' : row.confidence >= 0.6 ? 'medium' : 'low'}`}>{Math.round(row.confidence * 100)}%</span>
              <span className="config-badge secondary-pill">{row.editable.intent_code || row.suggested_intent.code}</span>
              {correctedIntentExists ? <span className="config-status-pill active">Existing topic</span> : <span className="config-status-pill inactive">New intent candidate</span>}
            </div>
            <p className="smart-import-intent-note">{correctedIntentExists ? 'This will improve the existing intent with new examples and keywords.' : 'This can create a new intent only if you keep the checkbox enabled.'}</p>
            <p className="smart-import-excerpt" dir="auto">{row.redacted_excerpt}</p>
            <p className="smart-import-normalized" dir="auto">{row.normalized_text}</p>
          </div>
          <div className="smart-import-decision">
            <button type="button" className={row.decision === 'approved' ? 'active' : ''} onClick={() => updateRow(row.row_id, { decision: row.decision === 'approved' ? 'pending' : 'approved' })}>Approve</button>
            <button type="button" className={row.decision === 'rejected' ? 'active reject' : ''} onClick={() => updateRow(row.row_id, { decision: row.decision === 'rejected' ? 'pending' : 'rejected' })}>Reject</button>
          </div>
        </div>

        <details><summary>Edit topic, keywords, and handoff</summary><fieldset disabled={completedJob} style={{border: 0, padding: 0, margin: 0}}><div className="smart-import-detail-grid">
          <label>Existing intent
            <select value={correctedIntentExists ? row.editable.intent_code : ''} onChange={(e) => {
              const nextIntent = intents.find((intent) => intent.code === e.target.value);
              updateEditable(row.row_id, {
                intent_code: e.target.value,
                faq_topic_key: nextIntent?.default_response_topic_key || row.editable.faq_topic_key,
                create_intent: false,
              });
            }}>
              <option value="">Custom / new intent</option>
              {intents.map((intent) => <option key={intent.id} value={intent.code}>{intent.code} - {intent.label}</option>)}
            </select>
          </label>
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
          <label>Handoff behavior
            <select value={protectedIntent ? 'immediate_handoff' : row.editable.routing_behavior} onChange={(e) => updateEditable(row.row_id, { routing_behavior: e.target.value })} disabled={protectedIntent}>
              <option value="normal">Bot can answer normally</option>
              <option value="offer_handoff">Offer handoff</option>
              <option value="immediate_handoff">Immediate handoff</option>
            </select>
          </label>
        </div>

        </fieldset></details>
        <fieldset disabled={completedJob} style={{border: 0, padding: 0, margin: 0}}><div className="smart-import-options">
          <label className="check-row"><input type="checkbox" checked={row.editable.apply_routing === true} onChange={e => updateEditable(row.row_id, {apply_routing: e.target.checked})} /> Save this handoff choice to the topic</label>
          <label className="check-row"><input type="checkbox" checked={row.editable.create_intent} onChange={(e) => updateEditable(row.row_id, { create_intent: e.target.checked })} disabled={correctedIntentExists} /> Create new intent if missing</label>
          <label className="check-row"><input type="checkbox" checked={row.editable.create_faq} onChange={(e) => updateEditable(row.row_id, { create_faq: e.target.checked })} /> Create FAQ item with approved answer</label>
          {row.editable.create_faq && <label className="smart-import-answer">Official answer
            <textarea value={row.editable.faq_answer} onChange={(e) => updateEditable(row.row_id, { faq_answer: e.target.value })} placeholder="Needs official answer" />
          </label>}
        </div>

        </fieldset>
        <div className="smart-import-meta">
          <span>{row.suggested_faq_topic?.existing ? `Links to FAQ: ${row.suggested_faq_topic.topic_key}` : row.suggested_faq_topic ? `FAQ draft: ${row.suggested_faq_topic.topic_key}` : 'No FAQ suggestion'}</span>
          <span>{protectedIntent ? 'immediate_handoff' : row.editable.routing_behavior} · {row.routing_hint.reason}</span>
        </div>
        {protectedIntent && <div className="smart-import-safety-note">Protected handoff intent. Complaint and explicit human-request imports stay immediate handoff.</div>}
        {sensitiveIntent && <div className="smart-import-safety-note warning">Sensitive topic. You can edit the suggested behavior, but handoff changes are saved only when you select “Save this handoff choice”.</div>}
        {row.warnings.length > 0 && <div className="chip-cloud">
          {row.warnings.map((warning) => <span key={warning} className="config-chip secondary-chip">{warning}</span>)}
        </div>}
      </article>;
      })}
    </div>}
  </section>;
}
