/* Website chat widget: the conversation shown inside the institution's website. */
(function () {
  'use strict';

  var cfg = JSON.parse(document.getElementById('widget-config').textContent);
  var t = cfg.strings;
  var base = window.location.pathname.replace(/\/widget\/[^/]+\/frame\/?$/, '');
  var endpoint = base + '/channels/web-chat/' + encodeURIComponent(cfg.slug);
  var storageKey = 'agent-workspace-chat:' + cfg.slug;
  var SOURCE = 'agent-workspace-chat';
  var URL_RE = /(https?:\/\/[^\s<>"']+)/g;

  var log = document.getElementById('chat-log');
  var form = document.getElementById('chat-form');
  var input = document.getElementById('chat-input');
  var send = document.getElementById('chat-send');
  var statusLine = document.getElementById('chat-status');
  var closeButton = document.getElementById('chat-close');

  var visitorId = loadVisitorId();
  var lastId = 0;
  var hasConversation = false;
  var isOpen = false;
  var unread = 0;
  var sending = false;
  var pollTimer = null;
  var available = true;
  var historyLoaded = false;
  var seen = {};

  // ---- setup -------------------------------------------------------------
  document.documentElement.style.setProperty('--brand', cfg.color);
  document.documentElement.style.setProperty('--brand-text', cfg.text_color);
  document.getElementById('chat-title').textContent = cfg.title;
  document.getElementById('chat-subtitle').textContent = t.subtitle;
  if (cfg.logo) {
    var logo = document.getElementById('chat-logo');
    logo.src = base + cfg.logo;
    logo.hidden = false;
  }
  closeButton.setAttribute('aria-label', t.close);
  closeButton.title = t.close;
  input.placeholder = t.placeholder;
  input.setAttribute('aria-label', t.placeholder);
  send.setAttribute('aria-label', t.send);
  send.title = t.send;
  addBubble({ from: 'agent', text: cfg.welcome }, 'welcome');

  // ---- visitor identity --------------------------------------------------
  function randomId() {
    var alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    var bytes = new Uint8Array(40);
    window.crypto.getRandomValues(bytes);
    var id = 'wv';
    for (var i = 0; i < bytes.length; i++) id += alphabet.charAt(bytes[i] % alphabet.length);
    return id;
  }
  function loadVisitorId() {
    try {
      var saved = window.localStorage.getItem(storageKey);
      if (saved && /^wv[A-Za-z0-9]{40}$/.test(saved)) return saved;
    } catch (e) { /* storage blocked: keep the chat for this page only */ }
    return null;
  }
  function ensureVisitorId() {
    if (visitorId) return visitorId;
    visitorId = randomId();
    try { window.localStorage.setItem(storageKey, visitorId); } catch (e) { /* page-only chat */ }
    return visitorId;
  }
  function forgetVisitorId() {
    visitorId = null;
    try { window.localStorage.removeItem(storageKey); } catch (e) { /* ignore */ }
  }

  // ---- rendering ---------------------------------------------------------
  function appendText(container, text) {
    var lines = String(text).split('\n');
    for (var l = 0; l < lines.length; l++) {
      if (l > 0) container.appendChild(document.createElement('br'));
      var parts = lines[l].split(URL_RE);
      for (var i = 0; i < parts.length; i++) {
        var part = parts[i];
        if (!part) continue;
        if (i % 2 === 1) {
          var trailing = part.match(/[.,;:!?)،؛]+$/);
          var href = trailing ? part.slice(0, -trailing[0].length) : part;
          var a = document.createElement('a');
          a.href = href;
          a.textContent = href;
          a.target = '_blank';
          a.rel = 'noopener noreferrer';
          container.appendChild(a);
          if (trailing) container.appendChild(document.createTextNode(trailing[0]));
        } else {
          container.appendChild(document.createTextNode(part));
        }
      }
    }
  }

  function addBubble(message, extraClass) {
    var row = document.createElement('div');
    row.className = 'msg msg-' + message.from + (extraClass ? ' ' + extraClass : '');
    if (message.from === 'team') {
      var label = document.createElement('span');
      label.className = 'msg-label';
      label.textContent = t.team;
      row.appendChild(label);
    }
    var bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.setAttribute('dir', 'auto');
    appendText(bubble, message.text);
    row.appendChild(bubble);
    log.appendChild(row);
    scrollToEnd();
    return row;
  }

  var typingRow = null;
  function showTyping(show) {
    if (show && !typingRow) {
      typingRow = document.createElement('div');
      typingRow.className = 'msg msg-agent typing';
      typingRow.setAttribute('aria-label', t.typing);
      var bubble = document.createElement('div');
      bubble.className = 'bubble';
      for (var i = 0; i < 3; i++) bubble.appendChild(document.createElement('span'));
      typingRow.appendChild(bubble);
      log.appendChild(typingRow);
      scrollToEnd();
    } else if (!show && typingRow) {
      typingRow.parentNode.removeChild(typingRow);
      typingRow = null;
    }
  }

  function setStatus(text, kind) {
    statusLine.textContent = text || '';
    statusLine.className = 'chat-status' + (kind ? ' ' + kind : '');
    statusLine.hidden = !text;
  }

  function showState(state) {
    if (state === 'HUMAN_HANDOFF') setStatus(t.handoff, 'info');
    else if (statusLine.className.indexOf('info') !== -1) setStatus('');
  }

  function removePending() {
    var pending = log.querySelectorAll('.pending');
    for (var i = 0; i < pending.length; i++) pending[i].parentNode.removeChild(pending[i]);
  }

  // ---- talking to the platform -------------------------------------------
  function toParent(message) {
    message.source = SOURCE;
    window.parent.postMessage(message, '*');
  }

  function setUnread(count) {
    unread = count;
    toParent({ type: 'unread', count: unread });
  }

  function sync() {
    if (!visitorId || !available) return Promise.resolve();
    var url = endpoint + '/messages?visitor_id=' + encodeURIComponent(visitorId) + '&after=' + lastId;
    return fetch(url, { headers: { Accept: 'application/json' }, cache: 'no-store' })
      .then(function (response) {
        if (response.status === 400) { forgetVisitorId(); return null; }
        if (response.status === 403 || response.status === 404) { setUnavailable(); return null; }
        if (!response.ok) return null;
        return response.json();
      })
      .then(function (data) {
        if (!data) return;
        var messages = data.messages || [];
        if (messages.length) removePending();
        var incoming = 0;
        for (var i = 0; i < messages.length; i++) {
          var message = messages[i];
          if (seen[message.id]) continue;
          seen[message.id] = true;
          addBubble(message);
          lastId = Math.max(lastId, message.id);
          hasConversation = true;
          if (message.from !== 'visitor') incoming++;
        }
        // Earlier messages loaded when the page opens are not new to the visitor.
        if (incoming && !isOpen && historyLoaded) setUnread(unread + incoming);
        showState(data.state);
      })
      .catch(function () { /* offline: try again on the next round */ });
  }

  function schedule(delay) {
    window.clearTimeout(pollTimer);
    if (!hasConversation || document.hidden || !available) return;
    pollTimer = window.setTimeout(function () {
      sync().then(function () { schedule(isOpen ? 4000 : 15000); });
    }, delay);
  }

  function setUnavailable() {
    available = false;
    input.disabled = true;
    send.disabled = true;
    setStatus(t.error_unavailable, 'error');
  }

  function submit(event) {
    if (event) event.preventDefault();
    var text = input.value.trim();
    if (!text || sending || !available) return;
    sending = true;
    send.disabled = true;
    setStatus('');
    var pendingRow = addBubble({ from: 'visitor', text: text }, 'pending');
    input.value = '';
    autosize();
    showTyping(true);
    fetch(endpoint + '/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ visitor_id: ensureVisitorId(), message: text })
    })
      .then(function (response) {
        if (response.ok) {
          hasConversation = true;
          return sync();
        }
        if (pendingRow.parentNode) pendingRow.parentNode.removeChild(pendingRow);
        input.value = text;
        autosize();
        if (response.status === 429) setStatus(t.error_rate, 'error');
        else if (response.status === 403 || response.status === 404) setUnavailable();
        else setStatus(t.error_send, 'error');
      })
      .catch(function () {
        if (pendingRow.parentNode) pendingRow.parentNode.removeChild(pendingRow);
        input.value = text;
        autosize();
        setStatus(t.error_send, 'error');
      })
      .then(function () {
        showTyping(false);
        scrollToEnd();
        sending = false;
        send.disabled = !available;
        schedule(4000);
        input.focus();
      });
  }

  function autosize() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight + 2, 120) + 'px';
    input.style.overflowY = input.scrollHeight > 118 ? 'auto' : 'hidden';
  }

  function scrollToEnd() {
    log.scrollTop = log.scrollHeight;
  }

  // ---- events ------------------------------------------------------------
  form.addEventListener('submit', submit);
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', function (event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) submit(event);
  });
  closeButton.addEventListener('click', function () { toParent({ type: 'close' }); });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') toParent({ type: 'close' });
  });
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) sync().then(function () { schedule(isOpen ? 4000 : 15000); });
  });
  window.addEventListener('message', function (event) {
    if (event.source !== window.parent) return;
    var data = event.data;
    if (!data || data.source !== SOURCE) return;
    if (data.type === 'open') {
      isOpen = true;
      setUnread(0);
      window.setTimeout(function () {
        // Messages that arrived while the panel was hidden could not scroll it.
        scrollToEnd();
        input.focus();
      }, 60);
      sync().then(function () { schedule(4000); });
    } else if (data.type === 'close') {
      isOpen = false;
      schedule(15000);
    }
  });

  // Load an earlier conversation from this browser, then announce the widget.
  sync().then(function () {
    historyLoaded = true;
    schedule(15000);
  });
  toParent({
    type: 'ready',
    config: {
      color: cfg.color,
      text_color: cfg.text_color,
      position: cfg.position,
      title: cfg.title,
      strings: { launcher: t.launcher, close: t.close }
    }
  });
})();
