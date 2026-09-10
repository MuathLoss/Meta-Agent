export type Membership = { tenant_id: number; tenant_slug: string; tenant_name: string; roles: string[] };
export type SessionState = {
  access_token: string;
  token_type: string;
  user: { id: number; email: string; full_name: string; is_platform_admin: boolean };
  memberships: Membership[];
};

export type TenantProfile = {
  id: number;
  slug: string;
  display_name: string;
  legal_name?: string | null;
  country: string;
  timezone: string;
  default_lang: string;
  status: string;
  roles: string[];
  brand: { logo_url?: string | null; primary_color: string; support_email?: string | null; support_phone?: string | null };
};
export type Readiness = { is_ready: boolean; items: Array<{ key: string; label: string; passed: boolean; detail?: string | null }> };
export type Analytics = { customers: number; conversations: number; messages: number; open_tickets: number; conversation_states?: Record<string, number> };
export type Branch = { id: number; name: string; address?: string | null; city?: string | null; maps_url?: string | null; hours_json: Record<string, unknown>; is_active: boolean };
export type StaffUser = { id: number; email: string; full_name: string; is_active: boolean; roles: string[] };
export type FaqItem = { id: number; topic_key: string; question_ar?: string | null; english_question?: string | null; arabic_answer: string; english_answer?: string | null; status: string };
export type IntentKeywordItem = { id: number; phrase: string; weight: number; lang: string };
export type IntentItem = {
  id: number;
  code: string;
  label: string;
  is_universal: boolean;
  enabled: boolean;
  supported_languages: string;
  response_mode: string;
  default_response_topic_key?: string | null;
  custom_response_ar?: string | null;
  custom_response_en?: string | null;
  keywords: IntentKeywordItem[];
};
export type RoutingRule = {
  id: number;
  intent_code: string;
  primary_owner_role: string;
  notify_roles_json: string[];
  escalation_json: Record<string, unknown>;
  handoff_required: boolean;
  ticket_type?: string | null;
  priority: string;
  response_behavior: string;
  followup_question_ar?: string | null;
  followup_question_en?: string | null;
};
export type Channel = {
  channel_type: string;
  status: string;
  public_config: Record<string, unknown>;
  provider_channel_id?: string | null;
  provider_account_id?: string | null;
  has_credentials: boolean;
};
export type ChannelTestConsoleResult = {
  session_id: string;
  channel_type: string;
  conversation_id?: string | null;
  reply?: string | null;
  state?: string | null;
  handoff: boolean;
  intent?: string | null;
  notes: string[];
};
export type InboxItem = { id: number; customer_id: number; customer_phone: string; customer_name?: string | null; state: string; channel_type: string; owner_type?: string | null; owner_ref?: string | null; last_intent?: string | null; metadata_json?: Record<string, unknown>; last_message?: string | null; updated_at?: string | null };
export type ConversationDetail = { conversation: { id: number; state: string; channel_type: string; owner_type?: string | null; owner_ref?: string | null; last_intent?: string | null; metadata_json?: Record<string, unknown> }; customer: { id: number; phone: string; name?: string | null; email?: string | null; tags_json: string[]; opt_in: boolean }; messages: Array<{ id: number; direction: string; text?: string | null; intent_code?: string | null; created_at?: string | null }> };
export type ConversationReplyResult = { status: string; conversation_id: number; message_id: number; send_status?: string | null };
export type Customer = { id: number; phone: string; name?: string | null; email?: string | null; preferred_lang: string; tags_json: string[]; opt_in: boolean };
export type Ticket = { id: number; conversation_id: number; ticket_type: string; priority: string; assigned_to?: string | null; status: string; details_json: Record<string, unknown> };
export type Broadcast = {
  id: number;
  title: string;
  status: string;
  channel_type: string;
  template_ref?: string | null;
  message_text?: string | null;
  audience_type?: string;
  schedule_at?: string | null;
  created_at?: string | null;
};
export type BroadcastRecipient = {
  id: number;
  customer_id: number;
  status: string;
  provider_message_id?: string | null;
  delivered_at?: string | null;
};
export type BusinessSetting = { id: number; key: string; value_json: Record<string, unknown> };
export type TrainingExample = { id: number; raw_text: string; normalized_text: string; labeled_intent?: string | null; source: string };
export type AuditLog = { id: number; actor_user_id?: number | null; action: string; entity_type: string; entity_id?: string | null; details_json: Record<string, unknown>; created_at?: string | null };
export type SmartImportRow = {
  row_id: string;
  source_index: number;
  source_type: string;
  redacted_excerpt: string;
  normalized_text: string;
  detected_language: string;
  suggested_intent: { code: string; label: string; existing: boolean };
  confidence: number;
  suggested_keywords: string[];
  suggested_faq_topic?: { topic_key: string; question: string; answer: string; existing: boolean; confidence: number } | null;
  routing_hint: { behavior: string; owner_role?: string | null; reason: string };
  warnings: string[];
  decision: 'pending' | 'approved' | 'rejected';
  editable: {
    training_example_text: string;
    intent_code: string;
    keyword_phrases: string[];
    faq_topic_key: string;
    faq_question: string;
    faq_answer: string;
    routing_behavior: string;
    create_intent: boolean;
    create_faq: boolean;
    apply_routing?: boolean;
  };
};
export type SmartImportPreview = {
  source_type: string;
  total_rows: number;
  previewed_rows: number;
  duplicate_rows: number;
  max_rows: number;
  rows: SmartImportRow[];
  notes: string[];
};
export type SmartImportApproveResult = {
  job_id: number;
  revision: number;
  approved_routing_rules: number;
  skipped_duplicates: number;
  status: string;
  approved_training_examples: number;
  approved_keywords: number;
  approved_faq_items: number;
  approved_intents: number;
  skipped_rows: number;
  error_count: number;
  errors: Array<{ row_id: string; detail: string }>;
};
export type RuntimeClassification = { intent: Record<string, unknown>; route: Record<string, unknown>; inside_working_hours: boolean };
export type UatCase = { id: string; message: string; expected_intent?: string | null; expected_action?: string | null; note?: string | null };
export type UatResult = UatCase & { actual_intent: string; actual_action: string; confidence: number; matched_phrases: string[]; mixed: boolean; passed: boolean; route: Record<string, unknown> };
export type UatRun = { mode: string; inside_working_hours: boolean; passed: number; total: number; results: UatResult[] };
export type DeploymentChecklist = { tenant: string; environment: string; passed: number; total: number; ready_for_live_whatsapp: boolean; items: Array<{ key: string; label: string; passed: boolean; detail?: string | null }> };
export type DeploymentEnvironment = { items: Array<{ key: string; purpose: string; secret: boolean; configured: boolean; value_preview: string }> };
export type WhatsappGoLivePackage = { tenant: string; required_items: Array<{ key: string; label: string; provided_by: string }>; rule: string };
export type WhatsappFixture = UatCase & { payload: Record<string, unknown>; raw_body: string; x_hub_signature_256?: string | null };
export type AcceptanceSummary = { tenant: string; environment: string; project_status: string; passed: number; total: number; items: Array<{ key: string; label: string; passed: boolean; detail?: string | null }>; counts: Record<string, number> };
export type GoLiveBlockers = { tenant: string; blocked: boolean; blockers: Array<{ key: string; label: string; passed: boolean; detail?: string | null }>; expected_remaining_external_blockers: string[] };
export type HandoffPackage = { tenant: string; product: string; status: string; included_capabilities: string[]; not_included_until_client_supplies: string[]; recommended_next_steps: string[] };

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

export function resolveAssetUrl(path?: string | null) {
  if (!path) return null;
  if (/^https?:\/\//i.test(path) || path.startsWith('data:')) return path;
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}

type ApiOptions = RequestInit & { token?: string; tenantSlug?: string };

async function request<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (!(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (options.token) headers.set('Authorization', `Bearer ${options.token}`);
  if (options.tenantSlug) headers.set('X-Tenant-Slug', options.tenantSlug);
  const supportReason = sessionStorage.getItem('supportAccessReason');
  if (options.token && supportReason) headers.set('X-Support-Access-Reason', supportReason);
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const text = await res.text();
    let detail: string | null = null;
    try {
      const parsed = JSON.parse(text) as { detail?: string | Array<{msg?: string}> };
      detail = Array.isArray(parsed.detail) ? parsed.detail.map(e => e.msg || 'Invalid value').join('. ') : parsed.detail || null;
    } catch {}
    throw new Error(detail || text || `Request failed with ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function login(email: string, password: string, tenantSlug: string) {
  return request<SessionState>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password, tenant_slug: tenantSlug || undefined }) });
}
export function signupBusiness(payload: { business_name: string; tenant_slug: string; admin_name: string; admin_email: string; admin_password: string; support_email?: string; support_phone?: string; timezone?: string; default_lang?: string }) {
  return request<SessionState>('/auth/signup-business', { method: 'POST', body: JSON.stringify(payload) });
}
export function getMe(token: string) { return request<SessionState['user'] & { memberships: Membership[] }>('/auth/me', { token }); }

function auth(token: string, tenantSlug: string): Pick<ApiOptions, 'token' | 'tenantSlug'> { return { token, tenantSlug }; }

export type ImportJobSummary = {id: number; title: string; source_type: string; status: string; revision: number; row_count: number; updated_at?: string | null; result?: Record<string, unknown>};
export type ImportJob = ImportJobSummary & {preview: SmartImportPreview | null; rows: SmartImportRow[]};
export type ImportDraft = {title: string; source_type: string; revision?: number; preview: SmartImportPreview; rows: SmartImportRow[]};
export type ImportGrouping = {assisted: boolean; message: string; groups: Array<{label: string; row_ids: string[]}>};
export type ChannelHealth = {channel_type: string; ready: boolean; checks: Array<{key: string; label: string; passed: boolean}>; missing: string[]; automatic_polling?: boolean | null; verification?: {status: string; message: string; checked_at?: string} | null};
export const api = {
  importJobs: (token: string, tenantSlug: string) => request<ImportJobSummary[]>('/imports/smart/jobs', auth(token, tenantSlug)),
  importJob: (token: string, tenantSlug: string, id: number) => request<ImportJob>(`/imports/smart/jobs/${id}`, auth(token, tenantSlug)),
  createImportJob: (token: string, tenantSlug: string, data: ImportDraft) => request<ImportJob>('/imports/smart/jobs', {method: 'POST', body: JSON.stringify(data), ...auth(token, tenantSlug)}),
  updateImportJob: (token: string, tenantSlug: string, id: number, data: ImportDraft) => request<ImportJob>(`/imports/smart/jobs/${id}`, {method: 'PUT', body: JSON.stringify(data), ...auth(token, tenantSlug)}),
  undoImportJob: (token: string, tenantSlug: string, id: number, revision: number) => request<ImportJobSummary>(`/imports/smart/jobs/${id}/undo`, {method: 'POST', body: JSON.stringify({revision}), ...auth(token, tenantSlug)}),
  groupImportJob: (token: string, tenantSlug: string, id: number) => request<ImportGrouping>(`/imports/smart/jobs/${id}/assist`, {method: 'POST', ...auth(token, tenantSlug)}),
  channelReadiness: (token: string, tenantSlug: string) => request<ChannelHealth[]>('/channels/readiness', auth(token, tenantSlug)),
  verifyChannel: (token: string, tenantSlug: string, kind: string) => request<{status: string; message: string; checked_at: string}>(`/channels/${kind}/verify`, {method: 'POST', ...auth(token, tenantSlug)}),
  tenant: (token: string, tenantSlug: string) => request<TenantProfile>('/tenants/current', auth(token, tenantSlug)),
  readiness: (token: string, tenantSlug: string) => request<Readiness>('/onboarding/readiness', auth(token, tenantSlug)),
  publish: (token: string, tenantSlug: string) => request<{ published: boolean }>('/onboarding/publish', { method: 'POST', ...auth(token, tenantSlug) }),
  analytics: (token: string, tenantSlug: string) => request<Analytics>('/dashboard/analytics/summary', auth(token, tenantSlug)),
  inbox: (token: string, tenantSlug: string) => request<InboxItem[]>('/dashboard/inbox', auth(token, tenantSlug)),
  conversation: (token: string, tenantSlug: string, id: number) => request<ConversationDetail>(`/dashboard/conversations/${id}`, auth(token, tenantSlug)),
  replyToConversation: (token: string, tenantSlug: string, id: number, text: string) => request<ConversationReplyResult>(`/dashboard/conversations/${id}/reply`, { method: 'POST', body: JSON.stringify({ text }), ...auth(token, tenantSlug) }),
  handoff: (token: string, tenantSlug: string, id: number, owner_ref = 'OPERATIONS_STAFF') => request(`/dashboard/conversations/${id}/handoff`, { method: 'POST', body: JSON.stringify({ owner_ref }), ...auth(token, tenantSlug) }),
  resolve: (token: string, tenantSlug: string, id: number) => request(`/dashboard/conversations/${id}/resolve`, { method: 'POST', body: JSON.stringify({ note: 'Resolved from dashboard' }), ...auth(token, tenantSlug) }),
  reopen: (token: string, tenantSlug: string, id: number) => request(`/dashboard/conversations/${id}/reopen`, { method: 'POST', ...auth(token, tenantSlug) }),
  customers: (token: string, tenantSlug: string) => request<Customer[]>('/dashboard/customers', auth(token, tenantSlug)),
  tickets: (token: string, tenantSlug: string) => request<Ticket[]>('/dashboard/tickets', auth(token, tenantSlug)),
  updateTicket: (token: string, tenantSlug: string, id: number, payload: Partial<Ticket>) => request(`/tickets/${id}`, { method: 'PUT', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  broadcasts: (token: string, tenantSlug: string) => request<Broadcast[]>('/broadcasts', auth(token, tenantSlug)),
  createBroadcast: (token: string, tenantSlug: string, payload: { title: string; template_ref?: string | null; audience_type?: string; channel_type?: string; payload?: Record<string, unknown> }) => request('/broadcasts', { method: 'POST', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  updateBroadcast: (token: string, tenantSlug: string, id: number, payload: { title?: string; template_ref?: string | null; audience_type?: string; channel_type?: string; payload?: Record<string, unknown> }) => request(`/broadcasts/${id}`, { method: 'PUT', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  sendBroadcast: (token: string, tenantSlug: string, id: number) => request<{ broadcast_id: number; status: string; total_recipients: number; created_recipients: number; failed_recipients: number; sent_recipients: number; channel_type?: string | null }>(`/broadcasts/${id}/send`, { method: 'POST', ...auth(token, tenantSlug) }),
  deleteBroadcast: (token: string, tenantSlug: string, id: number) => request<{ deleted: boolean; id: number }>(`/broadcasts/${id}`, { method: 'DELETE', ...auth(token, tenantSlug) }),
  broadcastRecipients: (token: string, tenantSlug: string, id: number) => request<BroadcastRecipient[]>(`/broadcasts/${id}/recipients`, auth(token, tenantSlug)),
  branches: (token: string, tenantSlug: string) => request<Branch[]>('/branches', auth(token, tenantSlug)),
  createBranch: (token: string, tenantSlug: string, payload: Omit<Branch, 'id'>) => request('/branches', { method: 'POST', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  updateBranch: (token: string, tenantSlug: string, id: number, payload: Partial<Branch>) => request(`/branches/${id}`, { method: 'PUT', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  deleteBranch: (token: string, tenantSlug: string, id: number) => request<{ status: string; branch_id: number }>(`/branches/${id}`, { method: 'DELETE', ...auth(token, tenantSlug) }),
  settings: (token: string, tenantSlug: string) => request<BusinessSetting[]>('/settings/business', auth(token, tenantSlug)),
  saveSetting: (token: string, tenantSlug: string, key: string, value_json: Record<string, unknown>) => request(`/settings/business/${key}`, { method: 'PUT', body: JSON.stringify({ key, value_json }), ...auth(token, tenantSlug) }),
  updateProfile: (token: string, tenantSlug: string, payload: Partial<TenantProfile> & Record<string, unknown>) => request('/settings/profile', { method: 'PUT', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  uploadProfileLogo: (token: string, tenantSlug: string, file: File) => {
    const body = new FormData();
    body.append('file', file);
    return request<{ status: string; logo_url: string }>('/settings/profile/logo', { method: 'POST', body, ...auth(token, tenantSlug) });
  },
  deleteAccount: (token: string, tenantSlug: string, password: string) => request<{ status: string; deleted_tenant: { id: number; slug: string }; deleted_user: boolean }>('/auth/account', { method: 'DELETE', body: JSON.stringify({ password }), ...auth(token, tenantSlug) }),
  staff: (token: string, tenantSlug: string) => request<StaffUser[]>('/staff', auth(token, tenantSlug)),
  createStaff: (token: string, tenantSlug: string, payload: { email: string; full_name: string; password: string; roles: string[] }) => request('/staff', { method: 'POST', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  deleteStaff: (token: string, tenantSlug: string, userId: number) => request<{ status: string; user_id: number }>(`/staff/${userId}`, { method: 'DELETE', ...auth(token, tenantSlug) }),
  faq: (token: string, tenantSlug: string) => request<FaqItem[]>('/faq', auth(token, tenantSlug)),
  createFaq: (token: string, tenantSlug: string, payload: Omit<FaqItem, 'id'>) => request('/faq', { method: 'POST', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  updateFaq: (token: string, tenantSlug: string, id: number, payload: Partial<FaqItem>) => request(`/faq/${id}`, { method: 'PUT', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  deleteFaq: (token: string, tenantSlug: string, id: number) => request(`/faq/${id}`, { method: 'DELETE', ...auth(token, tenantSlug) }),
  deleteFaqPermanently: (token: string, tenantSlug: string, id: number) => request(`/faq/${id}/permanent`, { method: 'DELETE', ...auth(token, tenantSlug) }),
  intents: (token: string, tenantSlug: string) => request<IntentItem[]>('/intents', auth(token, tenantSlug)),
  createIntent: (token: string, tenantSlug: string, payload: Omit<IntentItem, 'id' | 'keywords'>) => request('/intents', { method: 'POST', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  updateIntent: (token: string, tenantSlug: string, id: number, payload: Partial<Omit<IntentItem, 'id' | 'keywords'>>) => request(`/intents/${id}`, { method: 'PUT', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  deleteIntent: (token: string, tenantSlug: string, id: number) => request(`/intents/${id}`, { method: 'DELETE', ...auth(token, tenantSlug) }),
  deleteKnowledgeItem: (token: string, tenantSlug: string, intentCode: string, topicKey?: string | null) => request(`/knowledge-items/${encodeURIComponent(intentCode)}${topicKey ? `?topic_key=${encodeURIComponent(topicKey)}` : ''}`, { method: 'DELETE', ...auth(token, tenantSlug) }),
  createKeyword: (token: string, tenantSlug: string, payload: { intent_code: string; phrase: string; weight?: number; lang?: string }) => request('/intent-keywords', { method: 'POST', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  deleteKeyword: (token: string, tenantSlug: string, keywordId: number) => request(`/intent-keywords/${keywordId}`, { method: 'DELETE', ...auth(token, tenantSlug) }),
  routingRules: (token: string, tenantSlug: string) => request<RoutingRule[]>('/routing-rules', auth(token, tenantSlug)),
  saveRoutingRule: (token: string, tenantSlug: string, intentCode: string, payload: Omit<RoutingRule, 'id'>) => request(`/routing-rules/${intentCode}`, { method: 'PUT', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  channels: (token: string, tenantSlug: string) => request<Channel[]>('/channels', auth(token, tenantSlug)),
  saveChannel: (token: string, tenantSlug: string, channel: string, payload: { status: string; public_config: Record<string, unknown>; credentials?: Record<string, unknown> | null }) => request<Channel>(`/channels/${channel}/settings`, { method: 'PUT', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  testChannel: (token: string, tenantSlug: string, payload: { channel_type: string; session_id?: string | null; message: string }) => request<ChannelTestConsoleResult>('/channels/test-console/message', { method: 'POST', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  trainingExamples: (token: string, tenantSlug: string) => request<TrainingExample[]>('/training-examples', auth(token, tenantSlug)),
  createTrainingExample: (token: string, tenantSlug: string, payload: { raw_text: string; labeled_intent?: string | null }) => request('/training-examples', { method: 'POST', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  smartImportPreviewText: (token: string, tenantSlug: string, payload: { text: string; source_type?: string }) => request<SmartImportPreview>('/imports/smart/preview-text', { method: 'POST', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  smartImportPreviewFile: (token: string, tenantSlug: string, file: File) => {
    const body = new FormData();
    body.append('file', file);
    return request<SmartImportPreview>('/imports/smart/preview-file', { method: 'POST', body, ...auth(token, tenantSlug) });
  },
  smartImportApprove: (token: string, tenantSlug: string, payload: { job_id?: number; revision?: number; source_type: string; total_rows: number; items: Array<Record<string, unknown>> }) => request<SmartImportApproveResult>('/imports/smart/approve', { method: 'POST', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  auditLogs: (token: string, tenantSlug: string) => request<AuditLog[]>('/audit-logs', auth(token, tenantSlug)),
  previewInbound: (token: string, tenantSlug: string, text: string, customer_phone = '0500000000') => request<{ decision: Record<string, unknown> }>('/dashboard/preview/inbound', { method: 'POST', body: JSON.stringify({ customer_phone, text, channel_type: 'whatsapp' }), ...auth(token, tenantSlug) }),
  saveOnboardingStep: (token: string, tenantSlug: string, step: number, data: Record<string, unknown>) => request<{ saved: boolean; step: number }>("/onboarding/step/" + step, { method: "POST", body: JSON.stringify({ data }), ...auth(token, tenantSlug) }),
  runtimeClassify: (token: string, tenantSlug: string, message: string) => request<RuntimeClassification>('/runtime/classify', { method: 'POST', body: JSON.stringify({ message }), ...auth(token, tenantSlug) }),
  runtimeScenario: (token: string, tenantSlug: string, message: string, customer_phone = '0550000000') => request<{ decision: Record<string, unknown> }>('/runtime/scenario', { method: 'POST', body: JSON.stringify({ message, customer_phone, channel_type: 'whatsapp' }), ...auth(token, tenantSlug) }),
  uatCases: (token: string, tenantSlug: string) => request<{ cases: UatCase[] }>('/uat/academy-cases', auth(token, tenantSlug)),
  runAcademyUat: (token: string, tenantSlug: string) => request<UatRun>('/uat/run-academy-cases', { method: 'POST', ...auth(token, tenantSlug) }),
  customUat: (token: string, tenantSlug: string, payload: { message: string; expected_intent?: string | null; expected_action?: string | null }) => request<UatResult>('/uat/custom', { method: 'POST', body: JSON.stringify(payload), ...auth(token, tenantSlug) }),
  deploymentChecklist: (token: string, tenantSlug: string) => request<DeploymentChecklist>('/deployment/checklist', auth(token, tenantSlug)),
  deploymentEnvironment: (token: string, tenantSlug: string) => request<DeploymentEnvironment>('/deployment/environment', auth(token, tenantSlug)),
  whatsappGoLivePackage: (token: string, tenantSlug: string) => request<WhatsappGoLivePackage>('/deployment/whatsapp-go-live-package', auth(token, tenantSlug)),
  whatsappFixtures: (token: string, tenantSlug: string) => request<{ mode: string; tenant: string; phone_number_id: string; signature_available: boolean; cases: WhatsappFixture[] }>('/uat/whatsapp-fixtures', auth(token, tenantSlug)),
  simulateWhatsappFixture: (token: string, tenantSlug: string, caseId: string) => request<{ ok: boolean; mode: string; normalized: Record<string, unknown>; result: UatResult }>(`/uat/whatsapp-fixtures/${caseId}/simulate`, { method: 'POST', ...auth(token, tenantSlug) }),
  acceptanceSummary: (token: string, tenantSlug: string) => request<AcceptanceSummary>('/acceptance/summary', auth(token, tenantSlug)),
  goLiveBlockers: (token: string, tenantSlug: string) => request<GoLiveBlockers>('/acceptance/go-live-blockers', auth(token, tenantSlug)),
  handoffPackage: (token: string, tenantSlug: string) => request<HandoffPackage>('/acceptance/handoff-package', auth(token, tenantSlug)),
};

export function getReadiness(token: string, tenantSlug: string) { return api.readiness(token, tenantSlug); }
export function getAnalytics(token: string, tenantSlug: string) { return api.analytics(token, tenantSlug); }
export function previewInbound(token: string, tenantSlug: string, text: string) { return api.previewInbound(token, tenantSlug, text); }
