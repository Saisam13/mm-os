import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { mmosApi } from '../api'
import type { MeService } from '../api/types'
import { ApiRequestError } from '../api/types'

// ── Token handoff — OFF for today's demo ────────────────────────────────
// Owner's call: SSO into the other services is off the table for now. Each
// service keeps its own sign-in; MM OS is the directory, not (yet) the
// identity provider for them. So `launch()` below no longer calls
// `/api/token/service`, builds a `#token=` URL, or redirects through
// `/_mmos/accept` — it just opens the service.
//
// The old path is kept, not deleted, behind this flag. The backend
// endpoints it calls are untouched and still work. To re-enable it: flip
// this to `true`. Nothing else needs to change.
export const TOKEN_HANDOFF_ENABLED = true

// A service only renders embedded in MM OS if the backend marked it
// `embed` *and* the browser will actually load the frame. Real header
// checks against the live services (25 Aug): Item Code Studio has no
// X-Frame-Options and is https — embeddable. ATT is frameable too but is
// still plain http — if MM OS itself is on https, the browser drops an
// http iframe as mixed content and the panel goes silently blank, which
// is worse than a new tab in front of an audience. ERPNext sends
// X-Frame-Options: SAMEORIGIN — never embeddable, `launch_mode` reflects
// that as `external`. So: trust `launch_mode`, but also refuse to embed
// an http target from an https page.
export function canEmbed(service: MeService): boolean {
  if (service.launch_mode !== 'embed') return false
  try {
    const target = new URL(service.base_url, window.location.href)
    if (window.location.protocol === 'https:' && target.protocol === 'http:') return false
    return true
  } catch {
    return false
  }
}

function openNewTab(url: string) {
  window.open(url, '_blank', 'noopener,noreferrer')
}

// Shared by the Services page rows and the command palette. With token
// handoff off, this either sends the browser to a new tab for the
// service's own login (external / handoff / mixed-content-blocked embed)
// or navigates within MM OS to the embedded view (genuinely frameable
// services). See TOKEN_HANDOFF_ENABLED above to restore the old
// mint-token-and-redirect flow.
export function useLaunchService() {
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<{ slug: string; message: string } | null>(null)
  const navigate = useNavigate()

  // `newTab` forces a separate window regardless of embeddability. The
  // Services page passes it so every launch there opens a new tab — the
  // deliberate contrast with the Dashboard, which embeds frameable services.
  const launch = useCallback(async (service: MeService, opts?: { newTab?: boolean }) => {
    setError(null)

    if (!TOKEN_HANDOFF_ENABLED) {
      if (opts?.newTab) {
        openNewTab(service.base_url)
      } else if (canEmbed(service)) {
        navigate(`/services/open/${service.slug}`)
      } else {
        openNewTab(service.base_url)
      }
      return
    }

    // -- token-handoff path (disabled via TOKEN_HANDOFF_ENABLED above) --
    if (service.launch_mode === 'external') {
      window.location.href = service.base_url
      return
    }
    setPending(service.slug)
    try {
      const token = await mmosApi.mintServiceToken(service.slug)
      window.location.href = token.launch_url
    } catch (e) {
      const message = e instanceof ApiRequestError
        ? (e.status === 403 ? 'You cannot open this yet — the access was removed.' : e.message)
        : 'Could not reach MM OS to open this service.'
      setError({ slug: service.slug, message })
    } finally {
      setPending(null)
    }
  }, [navigate])

  const clearError = useCallback(() => setError(null), [])

  return { launch, pending, error, clearError }
}
