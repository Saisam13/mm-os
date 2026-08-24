/*! MM OS embed bar — packages/embed/embed.js
 * One file, no build step, no dependencies. Included by every service as:
 *   <script src="https://os.m-mines.com/embed.js" defer></script>
 * Zero config: MM OS origin comes from this script's own `src`; the current service comes
 * from `location.hostname`. Renders in a shadow root so host CSS can't touch it either way.
 * Contract: docs/05-service-integration.md. See handoff/a4-integration.md for deviations.
 */
(function () {
  "use strict";
  if (window.MMOS && window.MMOS.__embedded) return;
  window.MMOS = { __embedded: true, version: "1" };

  var scriptEl = document.currentScript || (function () {
    var a = document.getElementsByTagName("script");
    return a[a.length - 1];
  })();
  var OS_ORIGIN = (function () {
    try { return new URL(scriptEl.getAttribute("src"), location.href).origin; }
    catch (e) { return location.origin; }
  })();
  var SLUG = (location.hostname.split(".")[0] || "service").toLowerCase();
  window.MMOS.origin = OS_ORIGIN; // exposed for debugging and for the smoke test
  window.MMOS.slug = SLUG;

  var CSS =
    ':host{all:initial}*{box-sizing:border-box;margin:0;padding:0}' +
    '.bar,.ovl{--nv:#002060;--pt:#005D7F;--pt1:#DFEDF3;--or:#FF6A00;--tx:#C4D3DD;--td:#7C93A6;--ln:#123055;--sf:#0B2A4A;--r:5px}' +
    '@media(prefers-color-scheme:light){.bar,.ovl{--sf:#fff;--nv:#F0F4FA;--tx:#0E1B26;--td:#5C6E7E;--ln:#D2DBE6}}' +
    '.bar{display:flex;align-items:center;gap:10px;height:38px;padding:0 12px;background:var(--nv);color:var(--tx);' +
    'font:13px/1.3 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;' +
    'border-bottom:1px solid var(--ln);position:relative;z-index:2147483000}' +
    '.lnk{display:flex;align-items:center;gap:7px;color:var(--tx);text-decoration:none;font-weight:600;white-space:nowrap}' +
    '.lnk:hover{color:#fff}.mk{width:16px;height:16px;flex:0 0 16px}' +
    '.sw{display:flex;align-items:center;gap:6px;background:transparent;border:1px solid var(--ln);color:var(--td);' +
    'border-radius:999px;padding:4px 10px;font:inherit;cursor:pointer}' +
    '.sw:hover{border-color:var(--pt);color:var(--tx)}' +
    '.sw kbd{font:11px/1 inherit;border:1px solid var(--ln);border-radius:3px;padding:1px 4px;color:var(--td)}' +
    '.sp{flex:1}.tk{display:inline-flex;align-items:center;gap:5px;color:var(--td);text-decoration:none;font-weight:500;white-space:nowrap}' +
    '.tk b{color:var(--or);font-weight:700}' +
    '.us{display:flex;align-items:center;gap:7px;white-space:nowrap}' +
    '.av{width:20px;height:20px;border-radius:50%;background:var(--pt);color:#fff;display:grid;place-items:center;font-size:10px;font-weight:700;flex:0 0 20px}' +
    '.ro{color:var(--td);font-size:11px;text-transform:uppercase;letter-spacing:.04em}' +
    '.ovl{position:fixed;inset:0;background:rgba(6,26,34,.5);display:none;align-items:flex-start;justify-content:center;padding-top:12vh;z-index:2147483001}' +
    '.ovl.on{display:flex}' +
    '.pl{width:min(480px,92vw);background:var(--sf);border:1px solid var(--ln);border-radius:10px;overflow:hidden;' +
    'box-shadow:0 20px 50px rgba(0,0,0,.35);color:var(--tx)}' +
    '.pl input{width:100%;border:none;border-bottom:1px solid var(--ln);background:transparent;color:inherit;padding:12px 14px;font:14px inherit}' +
    '.pl input:focus{outline:none}.pll{max-height:300px;overflow-y:auto;padding:6px}' +
    '.pli{display:flex;align-items:center;gap:10px;width:100%;border:none;background:transparent;color:inherit;text-align:left;' +
    'padding:8px 10px;border-radius:var(--r);font:13.5px inherit;cursor:pointer}' +
    '.pli:hover,.pli.sel{background:var(--pt1);color:var(--pt)}' +
    '.ple{padding:16px 14px;color:var(--td);font-size:13px}' +
    '@media(prefers-reduced-motion:no-preference){.ovl{transition:none}}' +
    '.fb{color:var(--td)}';

  var BAR_HTML =
    '<div class="bar"><a class="lnk" href="' + OS_ORIGIN + '">' +
    '<svg class="mk" viewBox="0 0 34 34" aria-hidden="true">' +
    '<circle cx="11" cy="17" r="7.4" fill="none" stroke="currentColor" stroke-width="2.6"/>' +
    '<path d="M7.6 17h6.8M11 13.6v6.8" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/>' +
    '<circle cx="25" cy="17" r="7.4" fill="none" stroke="currentColor" stroke-width="2.6"/>' +
    '<path d="M21.6 17h6.8" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></svg>' +
    "<span>MM OS</span></a>" +
    '<div class="mid"></div><div class="sp"></div><div class="right"></div></div>' +
    '<div class="ovl" data-act="ovl"><div class="pl" role="dialog" aria-label="Go to a service">' +
    '<input data-act="q" placeholder="Go to a service…" autocomplete="off">' +
    '<div class="pll" data-act="list"></div></div></div>';

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function initials(name) {
    var p = String(name || "").trim().split(/\s+/).filter(Boolean);
    if (!p.length) return "?";
    return (p[0][0] + (p[1] ? p[1][0] : "")).toUpperCase();
  }

  function mount() {
    var host = document.createElement("div");
    host.id = "mmos-embed-bar";
    document.body.insertBefore(host, document.body.firstChild);
    var shadow = host.attachShadow({ mode: "open" });
    var style = document.createElement("style");
    style.textContent = CSS;
    shadow.appendChild(style);
    var wrap = document.createElement("div");
    wrap.innerHTML = BAR_HTML;
    shadow.appendChild(wrap);
    loadMe(shadow);
  }

  function loadMe(shadow) {
    fetch(OS_ORIGIN + "/api/me", { credentials: "include" })
      .then(function (r) { if (!r.ok) throw new Error("status " + r.status); return r.json(); })
      .then(function (data) { renderReady(shadow, data); })
      .catch(function () {
        var right = shadow.querySelector(".right");
        if (right) right.innerHTML = '<span class="fb">Not signed in to MM OS</span>';
      });
  }

  function renderReady(shadow, data) {
    var user = data.user || {}, services = data.services || [], badges = data.badges || {};
    var mine = null;
    for (var i = 0; i < services.length; i++) {
      if (services[i].slug === SLUG) { mine = services[i]; break; }
    }

    shadow.querySelector(".mid").innerHTML =
      '<button class="sw" data-act="open-switch" type="button"><span>Switch service</span><kbd>' +
      (navigator.platform && navigator.platform.indexOf("Mac") !== -1 ? "⌘K" : "Ctrl K") +
      "</kbd></button>";

    var n = badges.servicedesk_open || 0;
    var html = "";
    if (n > 0) {
      html += '<a class="tk" data-act="desk" href="#"><b>' + n + "</b><span>open ticket" +
        (n === 1 ? "" : "s") + "</span></a>";
    }
    html += '<div class="us"><span class="av">' + esc(initials(user.name)) + "</span><span>" +
      esc(user.name || "") + "</span>" +
      (mine && mine.role ? '<span class="ro">' + esc(mine.role) + "</span>" : "") + "</div>";
    shadow.querySelector(".right").innerHTML = html;

    var deskSvc = null;
    for (var j = 0; j < services.length; j++) {
      if (services[j].slug === "desk" || services[j].category === "servicedesk") { deskSvc = services[j]; break; }
    }
    var deskLink = shadow.querySelector('[data-act="desk"]');
    if (deskLink) {
      deskLink.addEventListener("click", function (e) {
        e.preventDefault();
        goTo(deskSvc || { slug: "desk", base_url: OS_ORIGIN, launch_mode: "handoff" });
      });
    }
    wireSwitcher(shadow, services);
  }

  function goTo(svc) {
    if (!svc) return;
    if (svc.launch_mode !== "handoff") { location.href = svc.base_url; return; }
    fetch(OS_ORIGIN + "/api/token/service", {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: svc.slug }),
    })
      .then(function (r) { if (!r.ok) throw new Error("token issue failed"); return r.json(); })
      .then(function (data) { location.href = data.launch_url; })
      .catch(function () { location.href = svc.base_url; });
  }

  function wireSwitcher(shadow, services) {
    var ovl = shadow.querySelector('[data-act="ovl"]');
    var input = shadow.querySelector('[data-act="q"]');
    var list = shadow.querySelector('[data-act="list"]');
    var openBtn = shadow.querySelector('[data-act="open-switch"]');
    var selected = 0, visible = services;

    function render() {
      if (!visible.length) { list.innerHTML = '<div class="ple">No matching services.</div>'; return; }
      list.innerHTML = visible.map(function (s, i) {
        return '<button class="pli' + (i === selected ? " sel" : "") + '" data-idx="' + i +
          '" type="button"><span>' + esc(s.name) + "</span></button>";
      }).join("");
      var btns = list.querySelectorAll(".pli");
      for (var i = 0; i < btns.length; i++) {
        btns[i].addEventListener("click", function () {
          var idx = parseInt(this.getAttribute("data-idx"), 10);
          close(); goTo(visible[idx]);
        });
      }
    }
    function open() {
      visible = services; selected = 0; input.value = "";
      render();
      ovl.classList.add("on");
      setTimeout(function () { input.focus(); }, 0);
    }
    function close() { ovl.classList.remove("on"); }

    if (openBtn) openBtn.addEventListener("click", open);
    ovl.addEventListener("click", function (e) { if (e.target === ovl) close(); });
    input.addEventListener("input", function () {
      var q = input.value.toLowerCase();
      visible = services.filter(function (s) {
        return s.name.toLowerCase().indexOf(q) !== -1 || s.slug.toLowerCase().indexOf(q) !== -1;
      });
      selected = 0; render();
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { close(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); selected = Math.min(selected + 1, visible.length - 1); render(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); selected = Math.max(selected - 1, 0); render(); }
      else if (e.key === "Enter") { e.preventDefault(); if (visible[selected]) { close(); goTo(visible[selected]); } }
    });

    // The only listener attached to the HOST document. Never fires while the visitor is
    // typing into one of the host page's own inputs.
    document.addEventListener("keydown", function (e) {
      var k = (e.key || "").toLowerCase();
      if (k !== "k" || !(e.metaKey || e.ctrlKey)) return;
      var a = document.activeElement;
      if (a && (a.tagName === "INPUT" || a.tagName === "TEXTAREA" || a.isContentEditable)) return;
      e.preventDefault();
      open();
    });
    window.MMOS.openSwitcher = open;
  }

  // The contract requires `defer` on the <script> tag (docs/05-service-integration.md),
  // so `document.body` always exists by the time this runs — no DOMContentLoaded listener
  // needed. That keeps the Cmd/Ctrl-K handler the *only* listener this script ever attaches
  // to the host document.
  mount();
})();
