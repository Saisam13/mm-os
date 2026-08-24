/*
 * DOM-free smoke test for packages/embed/embed.js.
 *
 * No browser, no jsdom (embed.js must ship with zero dependencies, and that discipline
 * extends to how it's tested — this is plain Node + a hand-rolled DOM stub just big enough
 * for the script's actual selector usage). Runs the real, unmodified embed.js source inside
 * a `vm` sandbox and asserts on its observable behaviour:
 *
 *   - loads without throwing, exposes exactly one global (`window.MMOS`)
 *   - is idempotent when included twice
 *   - derives the MM OS origin from its own <script src>, and the service slug from hostname
 *   - degrades to the "not signed in" fallback when /api/me fails
 *   - renders the user/role/ticket-count bar when /api/me succeeds
 *   - the Cmd/Ctrl-K handler does nothing while the visitor is typing in a host input, and
 *     opens the switcher otherwise
 *
 * Run: node packages/embed/test/smoke.js  (exits non-zero on any failure)
 *
 * What this does NOT cover — verify by eye per README.md "Manual check": shadow-root style
 * isolation against real host CSS, dark/light + reduced-motion media queries, and the
 * palette's visual layout. A hand-rolled DOM has no CSSOM, so those need a real browser.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const SRC = fs.readFileSync(path.join(__dirname, "..", "embed.js"), "utf8");

// ── a hand-rolled DOM, just big enough for embed.js's actual selector usage ──────────────
function matchesSelector(el, sel) {
  if (sel[0] === ".") return el.classSet.has(sel.slice(1));
  const m = sel.match(/^\[data-act="([^"]+)"\]$/);
  if (m) return el.attrs["data-act"] === m[1];
  return false;
}
function collectAll(el) {
  let acc = [el];
  for (const c of el.children) acc = acc.concat(collectAll(c));
  return acc;
}
function queryAll(root, sel) {
  let all = [];
  for (const c of root.children) all = all.concat(collectAll(c));
  return all.filter((el) => matchesSelector(el, sel));
}
function parseFragment(html) {
  const out = [];
  const tagRe = /<([a-z][a-z0-9]*)((?:\s+[a-zA-Z-]+(?:="[^"]*")?)*)\s*\/?>/g;
  let m;
  while ((m = tagRe.exec(html))) {
    const attrs = {};
    const attrRe = /([a-zA-Z-]+)(?:="([^"]*)")?/g;
    let am;
    while ((am = attrRe.exec(m[2]))) attrs[am[1]] = am[2] === undefined ? "" : am[2];
    out.push(makeElement(m[1], attrs));
  }
  return out;
}
function makeElement(tag, attrs) {
  const el = {
    tag: tag,
    attrs: attrs || {},
    classSet: new Set(((attrs && attrs["class"]) || "").split(/\s+/).filter(Boolean)),
    children: [],
    listeners: {},
    value: "",
    _html: "",
    getAttribute(name) {
      return name in el.attrs ? el.attrs[name] : null;
    },
    setAttribute(name, v) {
      el.attrs[name] = v;
    },
    addEventListener(type, fn) {
      (el.listeners[type] = el.listeners[type] || []).push(fn);
    },
    appendChild(child) {
      el.children.push(child);
      return child;
    },
    querySelector(sel) {
      return queryAll(el, sel)[0] || null;
    },
    querySelectorAll(sel) {
      return queryAll(el, sel);
    },
    classList: {
      add: (c) => el.classSet.add(c),
      remove: (c) => el.classSet.delete(c),
    },
    focus() {},
  };
  Object.defineProperty(el, "innerHTML", {
    get() {
      return el._html;
    },
    set(html) {
      el._html = html;
      el.children = parseFragment(html);
    },
  });
  Object.defineProperty(el, "className", {
    get() {
      return Array.from(el.classSet).join(" ");
    },
  });
  Object.defineProperty(el, "textContent", {
    set(v) {
      el._text = v;
    },
    get() {
      return el._text || "";
    },
  });
  return el;
}

function buildContext({ scriptSrc, hostname, fetchImpl, activeElementTag }) {
  const body = makeElement("body", {});
  body.firstChild = null;
  body.insertBefore = (child) => {
    body.children.unshift(child);
    body.firstChild = child;
  };

  const documentListeners = {};
  const activeElement = { tagName: activeElementTag || "BODY", isContentEditable: false };

  const doc = {
    body,
    activeElement,
    currentScript: scriptSrc ? { getAttribute: (n) => (n === "src" ? scriptSrc : null) } : null,
    createElement(tag) {
      if (tag === "div") {
        const d = makeElement("div", {});
        d.attachShadow = () => {
          d.shadowRoot = makeElement("shadow-root", {});
          return d.shadowRoot;
        };
        return d;
      }
      return makeElement(tag, {});
    },
    getElementsByTagName(tag) {
      if (tag === "script" && scriptSrc === undefined) {
        return [{ getAttribute: () => "https://os.m-mines.com/embed.js" }];
      }
      return [];
    },
    addEventListener(type, fn) {
      (documentListeners[type] = documentListeners[type] || []).push(fn);
    },
  };

  const location = { hostname: hostname, href: "https://" + hostname + "/", origin: "https://" + hostname };
  const navigator = { platform: "TestNode" };

  const sandbox = {
    document: doc,
    navigator,
    URL,
    console,
    setTimeout,
    fetch: fetchImpl,
  };
  sandbox.window = sandbox;
  sandbox.location = location;
  sandbox.window.location = location;
  vm.createContext(sandbox);
  return { sandbox, documentListeners, activeElement, body };
}

const tests = [];
function run(name, fn) {
  // Registers the test; `main()` below awaits each one in turn so an assertion that fails
  // after an `await` (every one of tests 3-5 has one) is actually caught before the final
  // summary prints, instead of racing it.
  tests.push([name, fn]);
}

// ── 1. loads cleanly, exposes exactly one global, derives origin + slug ────────────────
run("loads without throwing and derives origin + slug from the page it's embedded in", () => {
  const { sandbox } = buildContext({
    scriptSrc: "https://os.m-mines.com/embed.js",
    hostname: "itemcode.m-mines.com",
    fetchImpl: () => Promise.reject(new Error("no network in this test")),
  });
  vm.runInContext(SRC, sandbox);
  assert.strictEqual(sandbox.MMOS.__embedded, true);
  assert.strictEqual(sandbox.MMOS.version, "1");
  assert.strictEqual(sandbox.MMOS.origin, "https://os.m-mines.com");
  assert.strictEqual(sandbox.MMOS.slug, "itemcode");
});

// ── 2. idempotent: including the tag twice must not throw or double-mount ──────────────
run("is idempotent when the script tag is included twice", () => {
  const { sandbox } = buildContext({
    scriptSrc: "https://os.m-mines.com/embed.js",
    hostname: "att.m-mines.com",
    fetchImpl: () => Promise.reject(new Error("no network")),
  });
  vm.runInContext(SRC, sandbox);
  const before = sandbox.MMOS;
  vm.runInContext(SRC, sandbox); // second inclusion
  assert.strictEqual(sandbox.MMOS, before, "second run must not replace window.MMOS");
});

// ── 3. degrades to the fallback link when /api/me fails ─────────────────────────────────
run('falls back to "not signed in" when /api/me fails', async () => {
  const { sandbox, body } = buildContext({
    scriptSrc: "https://os.m-mines.com/embed.js",
    hostname: "echo.m-mines.com",
    fetchImpl: () => Promise.reject(new Error("network down")),
  });
  vm.runInContext(SRC, sandbox);
  await new Promise((r) => setTimeout(r, 0)); // let the fetch .catch() settle
  const host = body.children[0];
  const shadow = host.shadowRoot;
  const right = shadow.querySelector(".right");
  assert.ok(right, "the .right slot must exist even on fallback");
  assert.ok(right.innerHTML.indexOf("Not signed in") !== -1);
});

// ── 4. renders name, per-service role and ticket count on a successful /api/me ──────────
run("renders user, role-in-this-service and open ticket count on success", async () => {
  const meResponse = {
    user: { name: "Prashanth V" },
    services: [
      { slug: "echo", name: "Echo Service", role: "admin", launch_mode: "handoff", base_url: "https://echo.m-mines.com" },
      { slug: "desk", name: "Service Desk", role: "requester", launch_mode: "handoff", base_url: "https://os.m-mines.com" },
    ],
    badges: { servicedesk_open: 3 },
  };
  const { sandbox, body } = buildContext({
    scriptSrc: "https://os.m-mines.com/embed.js",
    hostname: "echo.m-mines.com",
    fetchImpl: () => Promise.resolve({ ok: true, json: () => Promise.resolve(meResponse) }),
  });
  vm.runInContext(SRC, sandbox);
  await new Promise((r) => setTimeout(r, 0));
  const shadow = body.children[0].shadowRoot;
  const right = shadow.querySelector(".right");
  assert.ok(right.innerHTML.indexOf("Prashanth V") !== -1, "name must render");
  assert.ok(right.innerHTML.indexOf("admin") !== -1, "role in THIS service (echo) must render, not desk's");
  assert.ok(right.innerHTML.indexOf(">3<") !== -1, "open ticket count must render");
});

// ── 5. Cmd/Ctrl-K: silent while typing, opens the switcher otherwise ────────────────────
run("Cmd/Ctrl-K does not fire while the visitor is typing in a host input", async () => {
  const meResponse = {
    user: { name: "Demo" },
    services: [{ slug: "echo", name: "Echo Service", role: "viewer", launch_mode: "handoff", base_url: "https://echo.m-mines.com" }],
    badges: {},
  };
  const { sandbox, documentListeners, activeElement } = buildContext({
    scriptSrc: "https://os.m-mines.com/embed.js",
    hostname: "echo.m-mines.com",
    fetchImpl: () => Promise.resolve({ ok: true, json: () => Promise.resolve(meResponse) }),
    activeElementTag: "INPUT",
  });
  vm.runInContext(SRC, sandbox);
  await new Promise((r) => setTimeout(r, 0));

  const handlers = documentListeners["keydown"] || [];
  assert.ok(handlers.length >= 1, "must attach exactly one keydown listener to the host document");

  let prevented = false;
  const evt = { key: "k", ctrlKey: true, preventDefault: () => (prevented = true) };
  handlers.forEach((h) => h(evt));
  assert.strictEqual(prevented, false, "must not intercept Ctrl-K while an INPUT is focused");

  activeElement.tagName = "BODY";
  handlers.forEach((h) => h(evt));
  assert.strictEqual(prevented, true, "must open the switcher when focus is not in an input");
});

async function main() {
  for (const [name, fn] of tests) {
    try {
      await fn();
      console.log("ok  -", name);
    } catch (e) {
      console.error("FAIL -", name);
      console.error(e);
      process.exitCode = 1;
    }
  }
  if (process.exitCode) {
    console.error("\nembed.js smoke test: FAILED");
  } else {
    console.log("\nembed.js smoke test: all checks passed");
  }
}

main();
