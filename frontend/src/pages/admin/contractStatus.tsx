import type { ContractStatus, ServiceContract } from '../../api/types'

// How a service stands against the access contract (docs/17-access-contract.md), in words
// an administrator can act on. The backend check lives in backend/app/access_contract.py.
export const CONTRACT_LABEL: Record<ContractStatus, string> = {
  enforces: 'Follows MM OS',
  drift: 'Permission list differs',
  no_manifest: 'Uses its own roles',
  unreachable: 'Unreachable',
}

const CHIP: Record<ContractStatus, string> = {
  enforces: 'chip pet',
  drift: 'chip wn',
  no_manifest: 'chip',
  unreachable: 'chip or',
}

export const CONTRACT_HINT: Record<ContractStatus, string> = {
  enforces: 'People can do exactly what their role allows here, nothing more.',
  drift: 'The service checks a different list of permissions from the one MM OS holds. Use "Import from service" on Service roles to line them up.',
  no_manifest: 'The service decides what people can do from the role name alone, so the permissions ticked in MM OS are not what it enforces.',
  unreachable: 'MM OS could not reach the service to ask. Check that it is running.',
}

export function ContractBadge({ status, title }: { status: ContractStatus; title?: string }) {
  return <span className={CHIP[status]} title={title ?? CONTRACT_HINT[status]}>{CONTRACT_LABEL[status]}</span>
}

export function ContractDetail({ c }: { c: ServiceContract }) {
  return (
    <div style={{ fontSize: 12.5 }}>
      <p className="muted" style={{ margin: '6px 0' }}>{CONTRACT_HINT[c.status]}</p>
      {c.added.length ? <p style={{ margin: '4px 0' }}>Only the service has: <span className="cond">{c.added.join(', ')}</span></p> : null}
      {c.removed.length ? <p style={{ margin: '4px 0' }}>Only MM OS has: <span className="cond">{c.removed.join(', ')}</span></p> : null}
      {c.detail ? <p className="muted cond" style={{ margin: '4px 0', wordBreak: 'break-word' }}>{c.detail}</p> : null}
    </div>
  )
}
