// Neither /api/public/services nor the per-item shape inside /api/me carries
// an explicit "in-house vs third-party" flag (see handoff/a3-shell.md
// "Assumptions"). We infer it:
//   - the public endpoint gives session_owner ('mmos' = in-house, 'service' = third-party)
//   - /api/me gives launch_mode ('external' = third-party, 'handoff'/'embed' = in-house)
// Both line up with backend/app/models.py Service.launch_mode's check constraint.
import type { LaunchMode } from '../api/types'

export function kindFromSessionOwner(owner: 'mmos' | 'service'): 'in-house' | 'third-party' {
  return owner === 'mmos' ? 'in-house' : 'third-party'
}

export function kindFromLaunchMode(mode: LaunchMode): 'in-house' | 'third-party' {
  return mode === 'external' ? 'third-party' : 'in-house'
}
