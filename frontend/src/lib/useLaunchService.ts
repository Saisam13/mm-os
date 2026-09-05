import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { MeService } from '../api/types'

// ── Token handoff — ON ──────────────────────────────────────────────────
// MM OS is the identity provider for the integrated services: it mints a
// short-lived token and the service accepts it at `/_mmos/accept#token=…`.
// The actual mint-and-hand-off happens *inside the embed* now — the
// Dashboard mints the token for the active app and points its iframe at the
// launch URL (see pages/Dashboard.tsx). So `launch()` here no longer
// redirects the whole window; it just routes the click to the right place:
//   • embeddable services  → open inside MM OS (Dashboard mints + frames)
//   • external services    → a new tab to the service's own sign-in
// This flag stays exported for callers that still reference it.
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

// Shared by the Services page tiles and the command palette. It routes a
// launch to the right surface — it no longer redirects the whole window and
// no longer forces a new tab for embeddable services:
//   • external service            → new tab (its own sign-in owns the session)
//   • everything else (embed /     → open inside MM OS on the Dashboard, which
//     handoff / blocked-embed)       mints a token and frames the service, or
//                                     shows its "opens in its own window" panel.
// The authenticated mint-and-hand-off now lives in pages/Dashboard.tsx.
export function useLaunchService() {
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<{ slug: string; message: string } | null>(null)
  const navigate = useNavigate()

  const launch = useCallback((service: MeService) => {
    setError(null)

    // Genuinely external services keep their own session — open their own
    // sign-in in a new tab, never inside MM OS.
    if (service.launch_mode === 'external') {
      openNewTab(service.base_url)
      return
    }

    // Embeddable (and other internal) services open inside MM OS. The
    // Dashboard decides whether to frame the service (minting a token for
    // the authenticated handoff) or show the "opens in its own window"
    // panel — the Services tiles and the Dashboard now behave identically.
    navigate(`/dashboard?app=${service.slug}`)
  }, [navigate])

  const clearError = useCallback(() => setError(null), [])

  return { launch, pending, error, clearError }
}
