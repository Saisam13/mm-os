import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { mmosApi } from '../api'
import type { Me } from '../api'
import { ApiRequestError } from '../api/types'

interface AuthState {
  me: Me | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  signOut: () => Promise<void>
}

const AuthCtx = createContext<AuthState | null>(null)

// Fetches /api/me once on mount and holds it in context, per agents/A3-shell.md:
// "An AuthProvider fetching /api/me once and holding it in context; a 401
// anywhere returns the user here." Individual pages that get a 401 from any
// other call should invoke refresh() (which will clear `me`) rather than
// rolling their own redirect.
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await mmosApi.getMe()
      setMe(result)
    } catch (e) {
      setMe(null)
      if (!(e instanceof ApiRequestError && e.status === 401)) {
        setError(e instanceof Error ? e.message : 'Could not reach MM OS.')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const signOut = useCallback(async () => {
    try {
      await mmosApi.logout()
    } finally {
      setMe(null)
    }
  }, [])

  return <AuthCtx.Provider value={{ me, loading, error, refresh, signOut }}>{children}</AuthCtx.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
