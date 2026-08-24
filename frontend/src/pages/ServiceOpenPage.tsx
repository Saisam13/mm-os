import React from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { canEmbed } from '../lib/useLaunchService'

// The embedded view for a service the backend marked `embed` and that
// actually can be framed (see lib/useLaunchService.ts canEmbed — protocol
// mismatch or an unknown/removed slug both bounce back to /services rather
// than show a blank panel). MM OS chrome stays up via ProtectedLayout's
// TopNav; the name and an explicit new-tab control sit right above the
// frame so nothing about where the click lands is a surprise.
export function ServiceOpenPage() {
  const { me } = useAuth()
  const { slug } = useParams<{ slug: string }>()
  const service = me?.services.find((s) => s.slug === slug)

  if (!service || !canEmbed(service)) {
    return <Navigate to="/services" replace />
  }

  return (
    <div className="page">
      <div className="head">
        <h1>{service.name}</h1>
        <div className="row-actions">
          <a className="btn-q" href={service.base_url} target="_blank" rel="noopener noreferrer">
            Open in new tab
          </a>
          <Link className="btn-q" to="/services">
            Back to Services
          </Link>
        </div>
      </div>
      <div className="card" style={{ padding: 0 }}>
        <iframe
          src={service.base_url}
          title={service.name}
          style={{ width: '100%', height: 'calc(100vh - 220px)', border: 0, display: 'block' }}
        />
      </div>
    </div>
  )
}
