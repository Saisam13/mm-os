// Derives Roboto Condensed initials for an in-house service mark so a newly
// registered service is never missing one (brand/UI-DECISIONS.md § Service
// list). "ATT Platform" -> ATT (the name already opens with an acronym),
// "Item Code Studio" -> ICS, "Service Desk" -> SD, "Analytics Hub" -> AH.
const STOPWORDS = new Set(['the', 'of', 'and', 'for', 'a', 'an'])

export function deriveInitials(name: string): string {
  const words = name.split(/\s+/).filter(Boolean)
  if (words.length === 0) return '?'

  const first = words[0]
  if (words.length > 1 && /^[A-Z0-9]{2,4}$/.test(first)) return first

  if (words.length === 1) {
    if (/^[A-Z0-9]{2,5}$/.test(first)) return first.slice(0, 4)
    return first.slice(0, 3).toUpperCase()
  }

  const significant = words.filter((w) => !STOPWORDS.has(w.toLowerCase()))
  const source = significant.length ? significant : words
  return source.slice(0, 4).map((w) => w[0]?.toUpperCase() ?? '').join('')
}
