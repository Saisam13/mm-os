import { useCallback, useState } from 'react'
import { mmosApi } from '../api'
import type { MeService } from '../api/types'
import { ApiRequestError } from '../api/types'

// Shared by the Services page rows and the command palette: mint a token
// for handoff/embed services, or go straight to base_url for external ones
// (ERPNext, Twenty own their sign-in — see docs/01-architecture.md). Shows
// progress while minting and surfaces a real error rather than a crash when
// a grant was pulled after /api/me was fetched (agents/A3-shell.md Acceptance).
export function useLaunchService() {
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<{ slug: string; message: string } | null>(null)

  const launch = useCallback(async (service: MeService) => {
    setError(null)
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
  }, [])

  const clearError = useCallback(() => setError(null), [])

  return { launch, pending, error, clearError }
}
