export type TimelineNode = {
  id: string
  label: string
  type: string
  firstSeen: string
}

export type TimelineClaim = {
  id: string
  source: string
  target: string
  predicate: string
  subject: string
  object: string
  validFrom: string
  validTo: string | null
  ingestedAt: string
  invalidatedAt: string | null
  status: string
  quote: string
  episode: string
  episodeTitle: string
  reviewAfter: string | null
}

export type TimelineData = {
  ontology: string
  clock: string
  ticks: string[]
  nodes: TimelineNode[]
  claims: TimelineClaim[]
  contradictions: { id: string; claimA: string; claimB: string; detectedAt: string }[]
  lint: {
    kind: string
    severity: string
    message: string
    suggestion: string
    claimIds: string[]
    paths: string[]
    visibleFrom: string
  }[]
}

export type ViewLink = {
  id: string
  source: string
  target: string
  label: string
  kind: 'claim' | 'contradiction'
  claimId?: string
  tone: 'active' | 'contradiction' | 'stale' | 'history'
  quote?: string
  episode?: string
  validFrom?: string
  validTo?: string | null
  predicate?: string
  subject?: string
  object?: string
}

export type ViewGraph = {
  nodes: TimelineNode[]
  links: ViewLink[]
  contradictionCount: number
}

const TONES = {
  active: 'rgba(28, 25, 23, 0.55)',
  contradiction: '#dc2626',
  stale: '#a8a29e',
  history: '#d6d3d1',
} as const

export const TONE_COLOR = TONES

export function visibleClaimIds(data: TimelineData, time: string, showHistory = false): string[] {
  return data.claims
    .filter((claim) => {
      if (claim.ingestedAt > time) return false
      if (claim.invalidatedAt && claim.invalidatedAt <= time && !showHistory) return false
      return true
    })
    .map((claim) => claim.id)
}

export function contradictionPairsAt(data: TimelineData, time: string, showHistory = false): [string, string][] {
  const visible = new Set(visibleClaimIds(data, time, showHistory))
  return data.contradictions
    .filter((row) => visible.has(row.claimA) && visible.has(row.claimB))
    .map((row) => [row.claimA, row.claimB])
}

export function graphAt(data: TimelineData, time: string, showHistory = false): ViewGraph {
  const visibleIds = new Set(visibleClaimIds(data, time, showHistory))
  const pairs = contradictionPairsAt(data, time, showHistory)
  const contradicted = new Set(pairs.flat())
  const claims = data.claims.filter((claim) => visibleIds.has(claim.id))
  const nodeIds = new Set<string>()
  for (const claim of claims) {
    nodeIds.add(claim.source)
    nodeIds.add(claim.target)
  }
  const nodes = data.nodes.filter((node) => nodeIds.has(node.id))
  const links: ViewLink[] = claims.map((claim) => {
    const dead = Boolean(claim.invalidatedAt && claim.invalidatedAt <= time)
    let tone: ViewLink['tone'] = 'active'
    if (contradicted.has(claim.id)) tone = 'contradiction'
    else if (dead) tone = 'history'
    else if (claim.reviewAfter && claim.reviewAfter <= time) tone = 'stale'
    return {
      id: claim.id,
      source: claim.source,
      target: claim.target,
      label: claim.predicate,
      kind: 'claim',
      claimId: claim.id,
      tone,
      quote: claim.quote,
      episode: claim.episode,
      validFrom: claim.validFrom,
      validTo: claim.validTo,
      predicate: claim.predicate,
      subject: claim.subject,
      object: claim.object,
    }
  })
  const byId = new Map(claims.map((claim) => [claim.id, claim]))
  for (const [left, right] of pairs) {
    const a = byId.get(left)
    const b = byId.get(right)
    if (!a || !b) continue
    const source = a.target === b.target ? a.source : a.target
    const target = a.target === b.target ? b.source : b.target
    links.push({
      id: `x-${left}-${right}`,
      source,
      target,
      label: 'CONTRADICTION',
      kind: 'contradiction',
      tone: 'contradiction',
    })
  }
  return { nodes, links, contradictionCount: pairs.length }
}

export function lintAt(data: TimelineData, time: string) {
  return data.lint.filter((finding) => finding.visibleFrom <= time)
}
