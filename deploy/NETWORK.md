# Network runbook: private posture, concretely

The *why* of every decision here is in `docs/06-network-security.md` — read that first. This
file is only the *how*: the exact commands and configs for the VPS. It does not restate the
rationale.

## 1 · `ufw`

Run on the VPS directly (not inside a container):

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp                                          # key-only SSH — confirm this first
ufw allow 51820/udp                                        # WireGuard
ufw allow from 10.8.0.0/24  to any port 443 proto tcp       # VPN clients
ufw allow from <OFFICE_STATIC_IP>/32 to any port 443 proto tcp   # office egress IP
ufw enable
ufw status verbose                                          # confirm before you disconnect
```

Replace `<OFFICE_STATIC_IP>` with the real value — ask whoever holds the office ISP contract;
it must be a static IP, not the current DHCP lease. Port 443 only: Coolify's Traefik
terminates TLS there, nothing needs 80 open at the firewall (see §4, DNS-01 needs no inbound
port at all). **Test the SSH rule from a second terminal before closing your first session** —
`ufw enable` on a misconfigured rule set is the classic way to lock yourself out of a VPS.

## 2 · `wg-easy` as a Coolify container

1. Coolify → **New Resource → Docker Image** → `ghcr.io/wg-easy/wg-easy` (pin an exact tag in
   Coolify's image field, not `:latest`).
2. Required env: `WG_HOST=<VPS public IP>`, `PASSWORD_HASH=<bcrypt of the admin UI password>`,
   `WG_DEFAULT_ADDRESS=10.8.0.x`, `WG_DEFAULT_DNS=<office DNS resolver IP>` (this is what makes
   split-horizon DNS in §3 apply to VPN clients without any per-device config).
3. Expose UDP `51820` on the container, matching the `ufw allow 51820/udp` rule above.
4. **One peer per person, named by employee code** — `MM32-laptop`, `MM32-phone`, not
   `johns-macbook`. Offboarding is "delete every peer with this employee code," which only
   works if the name carries the code.
5. Each peer's `AllowedIPs` in the generated config must read `10.8.0.0/24` — wg-easy's
   default peer template already scopes to the VPN subnet (split tunnel); verify a generated
   config before handing it out, since a full-tunnel (`0.0.0.0/0`) peer sends someone's entire
   internet through the VPS.
6. Hand out configs in person or via a password manager's secure-note share — never a plain
   email attachment (a WireGuard config *is* the credential, no second factor exists for it).

## 3 · Split-horizon DNS for `os.m-mines.com`

Internally, `os.m-mines.com` must resolve to the VPS's private address (its `10.8.0.1`
WireGuard address, or its LAN IP if the office reaches it that way) — publicly it should
resolve to nothing.

- **On the office DNS resolver** (whatever answers office LAN queries — a router's DNS
  forwarder, a Pi-hole, an internal BIND/dnsmasq instance): add a local A record
  `os.m-mines.com → 10.8.0.1` (or the LAN IP) that overrides whatever the public zone says.
- **On the `wg-easy` peer DNS setting** (`WG_DEFAULT_DNS` above): point VPN clients at that
  same office resolver, so a laptop on the VPN — not physically in the office — still resolves
  `os.m-mines.com` privately instead of falling through to the public DNS provider.
- **In the public DNS zone** for `m-mines.com` (wherever it's hosted — Cloudflare, Route 53,
  the registrar's own DNS): either omit the `os` record entirely, or point it at nothing
  routable. Do not publish the VPS's real IP in public DNS for this hostname — the whole
  point of split-horizon is that the public answer and the private answer differ.
- Verify from both sides after setup: `dig os.m-mines.com` from inside the office/VPN should
  return the private address; from an outside network (e.g. mobile data with WiFi off) it
  should return nothing or NXDOMAIN.

## 4 · TLS via DNS-01

HTTP-01 needs a publicly reachable port 80, which this deployment does not have. Use DNS-01
against whatever provider hosts the `m-mines.com` DNS zone.

**If Coolify is fronting with its built-in Traefik:** Coolify supports DNS-01 providers
natively in its **Server → Proxy → SSL/TLS** settings — select the DNS provider, paste the API
token (scoped to DNS-edit only, not full account access), and set the domain to
`os.m-mines.com`. Coolify then issues and renews via DNS-01 with no inbound connectivity
needed at all.

**If running Caddy directly instead** (e.g. bypassing Coolify's proxy), the equivalent
`Caddyfile`:

```
os.m-mines.com {
    tls {
        dns cloudflare {env.CF_API_TOKEN}
    }
    reverse_proxy localhost:8000
}
```

(swap the `dns cloudflare` provider plugin for whatever `m-mines.com`'s actual DNS host is —
Caddy needs the matching `xcaddy`-built module for that provider if it isn't Cloudflare).

**If running Traefik directly:**

```yaml
certificatesResolvers:
  dns01:
    acme:
      email: itadmin@m-mines.com
      storage: /letsencrypt/acme.json
      dnsChallenge:
        provider: cloudflare          # match the real provider
        delayBeforeCheck: 30s
```

with the provider's API token supplied via the environment variable that provider's Traefik
plugin expects (e.g. `CF_DNS_API_TOKEN` for Cloudflare) — check Traefik's DNS provider table
for the exact variable name if the provider is not Cloudflare, they are not uniform.

**Register the redirect URI** in the Google Cloud console once the certificate is live:
`https://os.m-mines.com/api/auth/google/callback` (see `deploy/COOLIFY.md` §5).

**If DNS-01 cannot be arranged** with the current DNS provider (no API access, registrar
doesn't support it), fall back to an internal CA: generate a root cert, install it on every
company device's trust store, issue a leaf cert for `os.m-mines.com` from it. Google OIDC
still works — Google never inspects your certificate, only the browser does, and the browser
already trusts your installed root. This is strictly worse operationally (a new device needs
the root cert pushed before its browser will trust the login page) — prefer DNS-01.

## 5 · Monthly VPN-peer-versus-active-employees audit

Put this in the calendar as a recurring task, not in someone's memory (`docs/06`'s own
warning: this is the step that gets skipped).

**Checklist:**

- [ ] Export the current `wg-easy` peer list (its API or admin UI — `GET /api/wireguard/client`
      on a wg-easy instance, or the UI's client list).
- [ ] Export `employees` where `status = 'active'` from MM OS.
- [ ] Every peer's employee-code prefix must appear in the active list. Any peer whose code is
      not active gets deleted in `wg-easy` immediately — not disabled, deleted.
- [ ] Every active employee who is supposed to have VPN access has at least one peer. A
      missing peer isn't a security problem but is worth catching (it means someone can't work).
- [ ] Record the audit date and who ran it somewhere durable (the audit log is for MM OS
      application events, not this manual step — a shared doc or ticket is fine).

**A rough diff command**, run against MM OS's Postgres directly (adjust the query to however
`mmos-client-py`/the admin API actually names the WireGuard-peer-to-employee link — if there
is no stored linkage yet, cross-check by employee code embedded in each peer's name, per §2):

```bash
psql "$MMOS_DATABASE_URL" -Atc \
  "SELECT employee_code FROM employees WHERE status = 'active' ORDER BY 1" \
  > /tmp/active-employees.txt

# from the wg-easy admin API, extract just the employee-code prefix of each peer name
# (e.g. "MM32-laptop" -> "MM32"), one per line, sorted+uniq'd, into /tmp/vpn-peers.txt

comm -13 /tmp/active-employees.txt /tmp/vpn-peers.txt   # peers with no matching active employee
comm -23 /tmp/active-employees.txt /tmp/vpn-peers.txt   # active employees with no peer at all
```

This could not be run here — there is no live MM OS database or wg-easy instance reachable
from the build machine. See `handoff/a6-infra.md` under `## Not done`.
