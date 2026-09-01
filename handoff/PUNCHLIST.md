# MM OS — live punch-list (owner-reported + found)

Running list of issues/gaps to work through. Newest context at top of each section.

## In progress / cutover (root cause of several "rough" symptoms)
- [ ] **Set service keys + deploy retrofits** (Step 3-4). Until done, embedded services load unauthenticated → look rough. Affects servicedesk, saleshub, itemcode.
- [ ] **Service Desk should embed inside MM OS**, not open separately. Needs launch_mode=embed + its retrofit deployed + a key. (owner, explicit)

## UX / consistency (owner: "discuss later, keep in list")
- [ ] **Consistent UI across ALL services** — each service (Service Desk, Item Code, Sales Hub) has its own look; owner wants the MM OS design language applied *inside* each service too. Big cross-service effort; deferred but tracked.
- [ ] Services admin: **rotate-key is hard to find** — it's inside the per-service detail panel; surface it better / make the row-opens-panel affordance clearer.
- [ ] General **polish inconsistency** across pages (owner-reported). Itemise per page.

## Admin IA (proposed, owner approved direction)
- [ ] **Settings page** (new) — General/branding, Services & Links (incl. external URLs), Security, AI. Split OS-config OUT of Access.
- [ ] **People scoping** — regular users see only their **own department**; admins see full org + hierarchy. (owner confirmed "own dept")
- [ ] **External links** (ERPNext, Twenty, any URL) addable via Settings → Services & Links.

## Functional gaps (to be itemised)
- [ ] Owner reports "a lot of functionality gaps" visible in the live app — need specific pointers or a systematic review to enumerate, then fix.
