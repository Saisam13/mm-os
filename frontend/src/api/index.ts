// The one place that decides real client vs. dev fixture. VITE_USE_MOCK is
// also gated on DEV so a production build can never ship the mock even if
// the flag were left on by accident — satisfies agents/A3-shell.md's
// "must not survive into the production build path" requirement.
import type { MmosApi } from './contract'
import { client } from './client'

let api: MmosApi

if (import.meta.env.DEV && import.meta.env.VITE_USE_MOCK === 'true') {
  // Dynamic import keeps the mock module out of the production bundle graph;
  // combined with the DEV gate above, Vite/Rollup tree-shakes it entirely
  // out of `vite build` output.
  const mod = await import('./mock')
  api = mod.mock
} else {
  api = client
}

export const mmosApi: MmosApi = api
export * from './types'
export type { MmosApi } from './contract'
