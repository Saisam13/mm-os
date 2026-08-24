# 06 · Network and security

MM OS is **not internet-facing**. Reachable from the office LAN and over WireGuard, nothing else.

## Two independent enforcement points

Defence in depth means a single misconfiguration should not open the door.

**1. VPS firewall** — the real boundary. Only 80/443 from office egress IPs and the VPN
subnet, and the WireGuard port itself:

```bash
ufw default deny incoming
ufw allow 22/tcp                        # keep your own key-only SSH reachable
ufw allow 51820/udp                     # WireGuard
ufw allow from 10.8.0.0/24  to any port 443 proto tcp   # VPN clients
ufw allow from <OFFICE_IP>/32 to any port 443 proto tcp # office static IP
ufw enable
```

**2. Application middleware** — belt to the firewall braces, and the thing that keeps it true
when someone edits the firewall in a hurry:

```env
NETWORK_MODE=private
ALLOWED_CIDRS=10.8.0.0/24,192.168.29.0/24,127.0.0.1/32
TRUSTED_PROXY_COUNT=1
```

Requests from outside `ALLOWED_CIDRS` get `403 network_denied` before routing. Going
internet-facing later is `NETWORK_MODE=public` — one variable, no code change.

`TRUSTED_PROXY_COUNT` matters: behind Coolify, the client IP comes from `X-Forwarded-For`,
and the app must take the **Nth from the right**, not the first. Trusting the leftmost value
lets a caller spoof any IP they like, which turns the allowlist into decoration.

## WireGuard

`wg-easy` as a Coolify container gives a web admin UI and QR codes for phones.

- one peer per **person**, never per device-type, named by employee code (`MM32-laptop`, `MM32-phone`) — because offboarding means deleting peers, and you cannot delete what you cannot attribute
- `AllowedIPs = 10.8.0.0/24` on clients (split tunnel — only MM OS traffic goes over the VPN, so normal browsing and video calls are unaffected)
- peer config issued by IT, never emailed as a plain attachment
- audit the peer list against `employees.status = 'active'` monthly; this is the manual step this choice costs you, and it is the step that gets skipped

## The Google OIDC wrinkle — read before configuring anything

This is the one genuine cost of going private, and it fails confusingly if unplanned.

Google will not redirect to `.local` hostnames or bare private IPs, and it will not accept an
unverified domain as a redirect URI. But the redirect happens **in the browser**, and the
browser is the thing on your network — Google itself never has to resolve or reach your host.
So:

1. **Use a real subdomain of a domain you own:** `os.m-mines.com`.
2. **Split-horizon DNS.** Internally, `os.m-mines.com` resolves to the private address
   (`10.8.0.1` or the LAN IP). Publicly it resolves to nothing at all, or is simply absent.
   Configure this on the office DNS resolver and in the WireGuard peer DNS setting.
3. **TLS via DNS-01, not HTTP-01.** Let's Encrypt HTTP-01 requires public reachability on
   port 80, which you no longer have. Use the DNS-01 challenge against your DNS provider API
   (Caddy and Traefik both support this natively, and Coolify can be pointed at it). Renewal
   then needs no inbound connectivity whatsoever.
4. Register `https://os.m-mines.com/api/auth/google/callback` as the authorised redirect URI
   in the Google Cloud console.

Result: employees get a valid padlock, Google OIDC works normally, and nothing is exposed to
the internet. If DNS-01 cannot be arranged with the current DNS provider, the fallback is an
internal CA — but that means installing a root certificate on every device, and Google OIDC
still works because Google never inspects your certificate. Prefer DNS-01.

## Because it is private, these things are true

- credential phishing stops being the top risk — a stolen Google password is useless without network access
- brute-force and bot traffic effectively vanish
- unpatched-service exposure drops from critical to serious

## And these things are now the top risks instead

| Risk | Mitigation |
|---|---|
| A compromised laptop on the VPN is inside everything | MFA still enforced on Google; disk encryption on company machines; deny-list revocation |
| VPN peer list rots and ex-employees keep access | monthly peer-vs-`employees.status` audit — put it in the calendar, not in someone's memory |
| People route around the friction (sharing sheets over WhatsApp) | this is the real adoption risk of a private deployment; watch for it and fix with usability, not policy |
| The VPS itself is on the public internet even if MM OS is not | key-only SSH, fail2ban, unattended-upgrades, Coolify kept current |

## Baseline hardening

- HSTS, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`
- CSP on the shell: `default-src 'self'`; `connect-src 'self'`; `frame-ancestors 'none'`
- `embed.js` is served with `Access-Control-Allow-Origin` restricted to registered service origins — the switcher lists your whole service map, which is not information to hand out freely
- cookies: `HttpOnly`, `Secure`, `SameSite=Lax`, `Domain=.m-mines.com`
- rate limits: 5/15min on PIN login, 60/min on `/api/token/service`, 600/min on `/api/me`
- secrets as mounted files in Coolify, not env vars, for the signing key
- `pg_dump` nightly, encrypted, off the VPS; **restore-tested quarterly** — an untested backup is a rumour

## Audit expectations

Every one of these writes an `audit_log` row: login success and failure, token issue, grant
create and delete, user activate and deactivate, PIN set and reset, service create and key
rotation, LLM enable and disable, admin employee import. Queryable in the admin UI by actor,
action and date range. That table is the answer to "who gave Prashanth item-code access and
when", which is the question that eventually gets asked.
