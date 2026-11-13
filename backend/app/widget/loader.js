/*
 * Website chat widget loader.
 *
 * Paste on every page, just before </body>:
 *   <script src="https://YOUR-PLATFORM/api/widget.js" data-workspace="your-workspace" async></script>
 *
 * The conversation runs inside a frame served by the platform, so the website's own
 * scripts and styles cannot read or change it. The chat button appears only after that
 * frame has loaded, which happens only on websites the workspace has allowed.
 * Styles are set through the DOM (not <style> tags) so strict website security
 * policies do not block them.
 */
(function () {
  'use strict';

  var script = document.currentScript;
  if (!script) {
    var candidates = document.querySelectorAll('script[data-workspace]');
    script = candidates[candidates.length - 1];
  }
  if (!script || window.__agentWorkspaceChatLoaded) return;

  var workspace = String(script.getAttribute('data-workspace') || '').trim().toLowerCase();
  if (!/^[a-z0-9][a-z0-9-]{1,119}$/.test(workspace)) {
    if (window.console) console.warn('Chat widget: data-workspace is missing or invalid.');
    return;
  }
  window.__agentWorkspaceChatLoaded = true;

  var scriptUrl = new URL(script.src, window.location.href);
  var platformOrigin = scriptUrl.origin;
  var base = scriptUrl.href.split('?')[0].replace(/\/widget\.js$/, '');
  var hostLang = String(document.documentElement.getAttribute('lang') || navigator.language || '').slice(0, 2).toLowerCase();
  var frameUrl = base + '/widget/' + encodeURIComponent(workspace) + '/frame' + (hostLang ? '?hl=' + encodeURIComponent(hostLang) : '');

  var config = null;
  var isOpen = false;
  var mobile = window.matchMedia ? window.matchMedia('(max-width: 480px)') : null;
  var Z = '2147483000';

  function css(el, styles) {
    for (var key in styles) {
      if (Object.prototype.hasOwnProperty.call(styles, key)) el.style.setProperty(key, styles[key], 'important');
    }
    return el;
  }

  var ICON_CHAT = 'M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2z';
  var ICON_CLOSE = 'M6 6l12 12M18 6L6 18';

  function svgIcon(path, filled) {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '26');
    svg.setAttribute('height', '26');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    var p = document.createElementNS(ns, 'path');
    p.setAttribute('d', path);
    p.setAttribute('fill', filled ? 'currentColor' : 'none');
    p.setAttribute('stroke', 'currentColor');
    p.setAttribute('stroke-width', filled ? '0' : '2.4');
    p.setAttribute('stroke-linecap', 'round');
    svg.appendChild(p);
    return svg;
  }

  var host = document.createElement('div');
  host.setAttribute('data-agent-workspace-chat', '');
  var root = host.attachShadow ? host.attachShadow({ mode: 'closed' }) : host;

  var panel = css(document.createElement('div'), {
    position: 'fixed', bottom: '96px', width: '380px', height: '600px', 'max-height': 'calc(100vh - 120px)',
    'border-radius': '16px', overflow: 'hidden', 'box-shadow': '0 12px 40px rgba(0,0,0,0.22)',
    background: '#ffffff', 'z-index': Z, display: 'none', opacity: '0', transform: 'translateY(12px)',
    transition: 'opacity 160ms ease, transform 160ms ease'
  });

  var frame = document.createElement('iframe');
  frame.src = frameUrl;
  frame.title = 'Chat';
  frame.setAttribute('allow', 'clipboard-write');
  frame.setAttribute('referrerpolicy', 'origin');
  css(frame, { width: '100%', height: '100%', border: '0', display: 'block', background: '#ffffff' });
  panel.appendChild(frame);

  var launcher = css(document.createElement('button'), {
    position: 'fixed', bottom: '20px', width: '60px', height: '60px', 'border-radius': '50%', border: '0',
    padding: '0', margin: '0', cursor: 'pointer', display: 'none', 'align-items': 'center', 'justify-content': 'center',
    'box-shadow': '0 6px 20px rgba(0,0,0,0.25)', 'z-index': Z, transition: 'transform 120ms ease'
  });
  launcher.type = 'button';
  launcher.setAttribute('aria-expanded', 'false');
  launcher.setAttribute('aria-haspopup', 'dialog');

  var badge = css(document.createElement('span'), {
    position: 'absolute', top: '-2px', right: '-2px', 'min-width': '20px', height: '20px', padding: '0 5px',
    'border-radius': '10px', background: '#d93025', color: '#ffffff', font: '600 12px/20px system-ui, sans-serif',
    'text-align': 'center', display: 'none', 'box-sizing': 'border-box'
  });
  badge.setAttribute('aria-hidden', 'true');

  function setLauncherIcon() {
    while (launcher.firstChild) launcher.removeChild(launcher.firstChild);
    launcher.appendChild(isOpen ? svgIcon(ICON_CLOSE, false) : svgIcon(ICON_CHAT, true));
    launcher.appendChild(badge);
    var label = config ? (isOpen ? config.strings.close : config.strings.launcher) : 'Chat';
    launcher.setAttribute('aria-label', label);
    launcher.title = label;
  }

  function layout() {
    var side = config && config.position === 'left' ? 'left' : 'right';
    var other = side === 'left' ? 'right' : 'left';
    launcher.style.setProperty(side, '20px', 'important');
    launcher.style.setProperty(other, 'auto', 'important');
    if (mobile && mobile.matches) {
      css(panel, { top: '0', bottom: '0', left: '0', right: '0', width: '100%', height: '100%', 'max-height': 'none', 'border-radius': '0' });
      launcher.style.setProperty('display', isOpen ? 'none' : (config ? 'flex' : 'none'), 'important');
    } else {
      css(panel, { top: 'auto', bottom: '96px', width: '380px', height: '600px', 'max-height': 'calc(100vh - 120px)', 'border-radius': '16px' });
      panel.style.setProperty(side, '20px', 'important');
      panel.style.setProperty(other, 'auto', 'important');
      launcher.style.setProperty('display', config ? 'flex' : 'none', 'important');
    }
  }

  function post(message) {
    if (frame.contentWindow) frame.contentWindow.postMessage(message, platformOrigin);
  }

  function setOpen(next) {
    if (!config || next === isOpen) return;
    isOpen = next;
    launcher.setAttribute('aria-expanded', String(isOpen));
    setLauncherIcon();
    layout();
    if (isOpen) {
      panel.style.setProperty('display', 'block', 'important');
      window.requestAnimationFrame(function () {
        css(panel, { opacity: '1', transform: 'translateY(0)' });
      });
      post({ source: 'agent-workspace-chat', type: 'open' });
    } else {
      css(panel, { opacity: '0', transform: 'translateY(12px)' });
      window.setTimeout(function () { if (!isOpen) panel.style.setProperty('display', 'none', 'important'); }, 170);
      post({ source: 'agent-workspace-chat', type: 'close' });
      launcher.focus();
    }
  }

  launcher.addEventListener('click', function () { setOpen(!isOpen); });
  launcher.addEventListener('keydown', function (event) { if (event.key === 'Escape') setOpen(false); });
  launcher.addEventListener('mouseenter', function () { launcher.style.setProperty('transform', 'scale(1.06)', 'important'); });
  launcher.addEventListener('mouseleave', function () { launcher.style.setProperty('transform', 'none', 'important'); });
  if (mobile) {
    if (mobile.addEventListener) mobile.addEventListener('change', layout);
    else if (mobile.addListener) mobile.addListener(layout);
  }

  window.addEventListener('message', function (event) {
    if (event.origin !== platformOrigin || event.source !== frame.contentWindow) return;
    var data = event.data;
    if (!data || data.source !== 'agent-workspace-chat') return;
    if (data.type === 'ready' && data.config) {
      config = data.config;
      launcher.style.setProperty('background', config.color, 'important');
      launcher.style.setProperty('color', config.text_color, 'important');
      frame.title = config.title || 'Chat';
      setLauncherIcon();
      layout();
    } else if (data.type === 'close') {
      setOpen(false);
    } else if (data.type === 'unread') {
      var count = Math.max(0, Math.min(99, Number(data.count) || 0));
      badge.textContent = String(count);
      badge.style.setProperty('display', count && !isOpen ? 'block' : 'none', 'important');
    }
  });

  setLauncherIcon();
  root.appendChild(panel);
  root.appendChild(launcher);

  function mount() { document.body.appendChild(host); }
  if (document.body) mount();
  else document.addEventListener('DOMContentLoaded', mount);
})();
