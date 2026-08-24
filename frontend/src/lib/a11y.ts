import type React from 'react'

// "The whole tile grid is navigable without a mouse — plant staff use
// shared terminals with poor trackpads" (agents/A3-shell.md). Applied here
// to the admin tables' clickable rows, which are otherwise mouse-only.
export function rowActivation(onActivate: () => void) {
  return {
    tabIndex: 0,
    role: 'button' as const,
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        onActivate()
      }
    },
  }
}
