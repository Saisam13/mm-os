# embed.js — the MM OS bar

One file, no build step, no dependencies. MM OS serves it at `GET /embed.js`; every service
includes it with a single tag:

```html
<script src="https://os.m-mines.com/embed.js" defer></script>
```

That's the whole integration — see `docs/05-service-integration.md`. It reads its own MM OS
origin from that `src` attribute and the current service from `location.hostname`; nothing
else to configure. It renders inside a shadow root, adds one global (`window.MMOS`), and
attaches exactly one listener to the host document (Cmd/Ctrl-K — inert while the visitor is
typing in a host input).

## Automated check (DOM-free)

```
node packages/embed/test/smoke.js
```

No browser and no jsdom — a ~150-line hand-rolled DOM stub in `test/smoke.js` runs the real,
unmodified `embed.js` inside Node's `vm` module and asserts on origin/slug derivation,
idempotency, the `/api/me` success and failure paths, and the Cmd-K input guard. Exits
non-zero on any failure.

## Manual check (needs a real browser)

The stub DOM above has no CSSOM, so these need eyes on an actual page:

1. Open any HTML page, add `<script src="/embed.js" defer></script>` pointing at a running
   MM OS (or `examples/echo-service`, which serves its own stub and includes the tag).
2. Confirm the bar renders at the top, in a shadow root (`document.getElementById("mmos-embed-bar").shadowRoot`
   in devtools should return a real shadow root, and none of the bar's classes should appear
   in the page's own computed-style rules).
3. Toggle OS dark mode / `prefers-reduced-motion` and reload — the bar should follow both.
4. Press Cmd/Ctrl-K outside any input — the switcher opens; focus a host `<input>` and press
   it again — nothing happens.
5. Resize the host page — the bar must never push content down by more than its own ~38px.
