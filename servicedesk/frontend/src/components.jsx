export function StatusPill({ status }) {
  return <span className={`pill status-${status}`}>{status.replaceAll("_", " ")}</span>;
}

export function PrivatePill() {
  return <span className="pill private">Private</span>;
}

export function age(iso) {
  const ms = Date.now() - new Date(iso).getTime();
  const hours = Math.floor(ms / 3_600_000);
  if (hours < 1) return "<1h";
  if (hours < 48) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

export function Ref({ children }) {
  return <span className="ref cond">{children}</span>;
}

// The three request types (scope decision, 25 Aug 2026): automation is its own `kind`;
// software/hardware are both `kind: "support"`, told apart by `service_slug`.
export function requestTypeLabel(t) {
  if (t.kind === "automation") return "Automation";
  if (t.service_slug === "hardware") return "Hardware issue";
  if (t.service_slug === "software") return "Software issue";
  return "Support";
}
