import { useEffect, useState, type FormEvent } from 'react';
import { api, type Channel, type ChannelHealth, type ChannelTestConsoleResult } from '../services/api';

type Field = { key: string; label: string; hint?: string; secret?: boolean; optional?: boolean };
const metaFields: Field[] = [
  {key:'page_access_token',label:'Page access token',secret:true},
  {key:'app_secret',label:'App secret',secret:true},
  {key:'verify_token',label:'Webhook verification token',secret:true,hint:'Use the same value when configuring your Meta webhook.'},
];
const definitions: Record<string, {name: string; intro: string; fields: Field[]; link?: string}> = {
  telegram: {name:'Telegram',intro:'Open the official BotFather in Telegram, choose your bot, and copy its current API token. Local startup checks for new messages while it is running.',link:'https://core.telegram.org/bots#how-do-i-create-a-bot',fields:[{key:'bot_token',label:'Bot token',secret:true,hint:'If the old token was rejected, paste a new token from BotFather here.'}]},
  web_chat: {name:'Web chat',intro:'No provider account is needed for a virtual test. A website widget still needs to be connected before visitors can use it.',fields:[]},
  whatsapp: {name:'WhatsApp',intro:'Use your WhatsApp Business account details from the Meta developer dashboard. Public HTTPS hosting and webhook setup are needed for real inbound messages.',link:'https://developers.facebook.com/docs/whatsapp/cloud-api/get-started',fields:[{key:'phone_number_id',label:'Phone number ID'},{key:'access_token',label:'Access token',secret:true},...metaFields.filter(f=>f.key!=='page_access_token')]},
  email: {name:'Email',intro:'Use the sending (SMTP) and receiving (IMAP) settings supplied by your email provider. An app password may be needed.',fields:[{key:'smtp_host',label:'Sending server (SMTP)',hint:'For example, smtp.your-provider.com'},{key:'smtp_username',label:'Sending username'},{key:'smtp_password',label:'Sending password',secret:true},{key:'smtp_from_email',label:'Sender email'},{key:'imap_host',label:'Receiving server (IMAP)'},{key:'imap_username',label:'Receiving username'},{key:'imap_password',label:'Receiving password',secret:true}]},
  instagram: {name:'Instagram',intro:'Connect your professional Instagram account through your Meta app. Public HTTPS hosting, a subscribed webhook, and the required messaging permissions are needed.',link:'https://developers.facebook.com/docs/instagram-platform',fields:[{key:'instagram_business_account_id',label:'Instagram business account ID'},...metaFields]},
  facebook: {name:'Messenger',intro:'Use the Facebook Page and messaging permissions configured in your Meta app. Public HTTPS hosting and webhook setup are needed for real messages.',link:'https://developers.facebook.com/docs/messenger-platform',fields:[{key:'page_id',label:'Facebook Page ID'},...metaFields]},
};
const emailExtras: Field[] = [{key:'smtp_port',label:'SMTP port',hint:'587 for STARTTLS, or 465 for SSL',optional:true},{key:'smtp_from_name',label:'Sender name',optional:true},{key:'imap_port',label:'IMAP port',hint:'Usually 993',optional:true},{key:'imap_mailbox',label:'Mailbox',hint:'Defaults to INBOX',optional:true},{key:'inbound_webhook_secret',label:'Inbound test secret',secret:true,optional:true}];

export function ChannelsPage({rows,token,tenantSlug,reload}:{rows:Channel[];token:string;tenantSlug:string;reload:()=>Promise<void>}) {
  const [kind,setKind]=useState('telegram');
  const [health,setHealth]=useState<ChannelHealth[]>([]);
  const [values,setValues]=useState<Record<string,string>>({});
  const [enabled,setEnabled]=useState(true);
  const [live,setLive]=useState(false);
  const [dirty,setDirty]=useState(false);
  const [busy,setBusy]=useState<string|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [notice,setNotice]=useState<string|null>(null);
  const [message,setMessage]=useState('Hello, can you help me?');
  const [test,setTest]=useState<ChannelTestConsoleResult|null>(null);
  const row=rows.find(r=>r.channel_type===kind);
  const check=health.find(r=>r.channel_type===kind);
  const definition=definitions[kind];
  const verified=check?.verification?.status==='credentials_verified';
  const virtualReady=Boolean(row?.public_config?.enabled===true && ['configured','connected','active'].includes(row.status));
  async function loadHealth(){setHealth(await api.channelReadiness(token,tenantSlug));}
  useEffect(()=>{void loadHealth().catch(()=>setError('Could not load channel checks. Refresh and try again.'));},[token,tenantSlug,rows]);
  useEffect(()=>{setValues({});setEnabled(row?.public_config?.enabled!==false);setLive(row?.public_config?.live_send_enabled===true);setDirty(false);setTest(null);setError(null);setNotice(null);},[kind,row]);
  useEffect(()=>{if(!dirty)return;const guard=(e:BeforeUnloadEvent)=>e.preventDefault();window.addEventListener('beforeunload',guard);return()=>window.removeEventListener('beforeunload',guard);},[dirty]);
  function choose(next:string){if(dirty&&!window.confirm('Discard unsaved channel changes?'))return;setKind(next);}
  function field(f:Field){const stored=check?.checks.find(c=>c.key===f.key)?.passed;return <label key={f.key}>{f.label}{f.optional?' (optional)':''}<input type={f.secret?'password':f.key==='smtp_from_email'?'email':'text'} value={values[f.key]||''} onChange={e=>{setValues({...values,[f.key]:e.target.value});setDirty(true);}} placeholder={stored?'Saved — leave blank to keep':'Enter '+f.label.toLowerCase()} autoComplete={f.secret?'new-password':'off'} maxLength={4000}/>{f.hint&&<small>{f.hint}</small>}{stored&&<small className="success-text">Saved securely</small>}</label>;}
  async function save(e:FormEvent){e.preventDefault();setBusy('save');setError(null);setNotice(null);try{
    const credentials=Object.fromEntries(Object.entries(values).filter(([,v])=>v.trim()).map(([k,v])=>[k,v.trim()]));
    await api.saveChannel(token,tenantSlug,kind,{status:enabled?'configured':'not_connected',public_config:{enabled,live_send_enabled:live},credentials});
    setDirty(false);await reload();await loadHealth();setNotice('Settings saved. Check the connection next.');
  }catch(e){setError(e instanceof Error?e.message:'Could not save this channel.');}finally{setBusy(null);}}
  async function verify(){setBusy('verify');setError(null);setNotice(null);try{const result=await api.verifyChannel(token,tenantSlug,kind);await loadHealth();setNotice(result.message);}catch(e){setError(e instanceof Error?e.message:'Connection check failed.');}finally{setBusy(null);}}
  async function testReply(e:FormEvent){e.preventDefault();setBusy('test');setError(null);try{setTest(await api.testChannel(token,tenantSlug,{channel_type:kind,message}));}catch(e){setError(e instanceof Error?e.message:'Could not run this test.');}finally{setBusy(null);}}
  return <section className="channel-workspace">
    <header className="workspace-page-heading"><div><p className="eyebrow">Connect with customers</p><h2>Your channels</h2><p className="muted">Start with one channel. Save its details, check the connection, then try an answer.</p></div></header>
    <div className="channel-picker-cards" aria-label="Choose a channel">{Object.entries(definitions).map(([key,info])=>{const h=health.find(c=>c.channel_type===key);return <button type="button" className={kind===key?'selected':'secondary'} aria-pressed={kind===key} key={key} onClick={()=>choose(key)} disabled={!!busy}><strong>{info.name}</strong><small>{h?.verification?.status==='credentials_verified'?'Connection checked':h?.ready?'Details saved':'Needs setup'}</small></button>;})}</div>
    {error&&<div className="error-box" role="alert">{error}</div>}{notice&&<div className="connection-check" role="status">{notice}</div>}
    <div className="channel-setup-layout">
      <form className="card form-stack" onSubmit={save}>
        <div className="step-heading"><span>1</span><div><h3>Connect {definition.name}</h3><p className="muted">{definition.intro}</p>{definition.link&&<a href={definition.link} target="_blank" rel="noreferrer">Provider setup guide ↗</a>}</div></div>
        {definition.fields.length>0&&<p className="muted">Saved details stay hidden. Fill only the fields you want to add or replace.</p>}
        <div className="channel-fields">{definition.fields.map(field)}</div>
        {(kind==='email'||['whatsapp','instagram','facebook'].includes(kind))&&<details className="advanced-fields"><summary>Advanced provider settings</summary><div className="channel-fields">{kind==='email'?<>{emailExtras.map(field)}<label>Sending security<select value={values.use_ssl===undefined?'':'custom'} onChange={e=>{const ssl=e.target.value==='ssl';setValues({...values,use_ssl:String(ssl),use_tls:String(!ssl),smtp_port:ssl?'465':'587'});setDirty(true);}}><option value="" disabled>Keep saved settings (default STARTTLS)</option><option value="tls">STARTTLS · port 587</option><option value="ssl">SSL · port 465</option>{values.use_ssl!==undefined&&<option value="custom">{values.use_ssl==='true'?'SSL · port 465':'STARTTLS · port 587'}</option>}</select></label></>:<>{field({key:'graph_api_version',label:'Meta API version',optional:true,hint:'Use a version supported by your Meta app.'})}<p className="muted">After HTTPS hosting is ready, register the public callback ending in <code>/channels/{kind}/webhook</code>. Match the verification token above and subscribe to messaging events.</p></>}</div></details>}
        <div className="channel-switch-row"><label><input type="checkbox" checked={enabled} onChange={e=>{setEnabled(e.target.checked);setDirty(true);}}/>Enable this channel</label><small>Allows this workspace to receive and process messages.</small></div>
        <details className="advanced-fields"><summary>Live customer replies {live?'· on':'· off'}</summary><p className="muted">Turn this on when you are ready to send real replies. Verify delivery with your own test account before inviting customers.</p><label className="checkbox-label"><input type="checkbox" checked={live} onChange={e=>{setLive(e.target.checked);setDirty(true);}}/>Allow live customer replies</label></details>
        <div className="button-row"><button disabled={!!busy}>{busy==='save'?'Saving…':'Save channel'}</button><span className="muted">{dirty?'Unsaved changes':row?'Saved settings':'New channel'}</span></div>
      </form>
      <aside className="channel-checks-stack">
        <section className="card"><div className="step-heading"><span>2</span><div><h3>Check the connection</h3><p className="muted">Confirm the saved details without sending a customer message.</p></div></div>
          <ul className="setup-check-list">{check?.checks.map(c=><li key={c.key}><span className={c.passed?'check-done':''}>{c.passed?'✓':'○'}</span>{c.label}<small>{c.passed?'Saved':'Missing'}</small></li>)}</ul>
          {check?.verification&&<div className="connection-check"><strong>{verified?'Connection passed':'Needs attention'}</strong><p>{check.verification.message}</p>{check.verification.checked_at&&<small>Checked {new Date(check.verification.checked_at).toLocaleString()}</small>}</div>}
          {kind==='email'&&<p className="muted">Automatic email checking is {check?.automatic_polling?'on.':'off. Enable the email worker in your local or staging configuration for real inbound delivery.'}</p>}
          <button className="secondary" type="button" disabled={!!busy||dirty||!row} onClick={()=>void verify()}>{busy==='verify'?'Checking…':'Check saved connection'}</button>{dirty&&<small className="muted">Save your changes before checking.</small>}
        </section>
        <form className="card form-stack" onSubmit={testReply}><div className="step-heading"><span>3</span><div><h3>Try an answer</h3><p className="muted">A virtual test. Nothing is added to your inbox or sent to a provider.</p></div></div><label>Customer message<textarea value={message} onChange={e=>{setMessage(e.target.value);setTest(null);}} maxLength={4000}/></label><button className="secondary" disabled={!!busy||!virtualReady||!message.trim()||dirty}>{busy==='test'?'Testing…':'Preview reply'}</button>{!virtualReady&&<small className="muted">Save and enable this channel to run a virtual test.</small>}{test&&<div className="test-answer" role="status"><strong>{test.handoff?'Team handoff':'Agent reply'}</strong><p dir="auto">{test.reply||'A team member takes over. No automatic answer.'}</p></div>}</form>
      </aside>
    </div>
  </section>;
}
