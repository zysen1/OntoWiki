import { describe, expect, it } from 'vitest'
import { contradictionPairsAt, graphAt, lintAt, visibleClaimIds, type TimelineData } from './timeline'

const data: TimelineData = {
  ontology: 'mini',
  clock: 'source-published-date',
  ticks: ['2020-01-01', '2024-01-01'],
  nodes: [
    { id: 'ada', label: 'Ada', type: 'Person', firstSeen: '2020-01-01' },
    { id: 'paris', label: 'Paris', type: 'City', firstSeen: '2020-01-01' },
    { id: 'lyon', label: 'Lyon', type: 'City', firstSeen: '2024-01-01' },
  ],
  claims: [
    {
      id: 'old',
      source: 'ada',
      target: 'paris',
      predicate: 'LIVES_IN',
      subject: 'Ada',
      object: 'Paris',
      validFrom: '2020-01-01',
      validTo: '2024-01-01',
      ingestedAt: '2020-01-01',
      invalidatedAt: '2024-01-01',
      status: 'superseded',
      quote: 'Ada lived in Paris.',
      episode: 'a.md',
      episodeTitle: 'A',
      reviewAfter: null,
    },
    {
      id: 'now',
      source: 'ada',
      target: 'lyon',
      predicate: 'LIVES_IN',
      subject: 'Ada',
      object: 'Lyon',
      validFrom: '2024-01-01',
      validTo: null,
      ingestedAt: '2024-01-01',
      invalidatedAt: null,
      status: 'active',
      quote: 'Ada lives in Lyon.',
      episode: 'b.md',
      episodeTitle: 'B',
      reviewAfter: '2024-06-01',
    },
    {
      id: 'like-a',
      source: 'ada',
      target: 'paris',
      predicate: 'LIKES',
      subject: 'Ada',
      object: 'Paris',
      validFrom: '2020-01-01',
      validTo: null,
      ingestedAt: '2020-01-01',
      invalidatedAt: null,
      status: 'contradicted',
      quote: 'Ada likes Paris.',
      episode: 'a.md',
      episodeTitle: 'A',
      reviewAfter: null,
    },
    {
      id: 'like-b',
      source: 'ada',
      target: 'lyon',
      predicate: 'LIKES',
      subject: 'Ada',
      object: 'Lyon',
      validFrom: '2024-01-01',
      validTo: null,
      ingestedAt: '2024-01-01',
      invalidatedAt: null,
      status: 'contradicted',
      quote: 'Ada likes Lyon.',
      episode: 'b.md',
      episodeTitle: 'B',
      reviewAfter: null,
    },
  ],
  contradictions: [{ id: 'c1', claimA: 'like-a', claimB: 'like-b', detectedAt: '2024-01-01' }],
  lint: [
    {
      kind: 'contradiction',
      severity: 'error',
      message: 'likes both',
      suggestion: 'review',
      claimIds: ['like-a', 'like-b'],
      paths: [],
      visibleFrom: '2024-01-01',
    },
    {
      kind: 'orphan',
      severity: 'warn',
      message: 'loose page',
      suggestion: 'link it',
      claimIds: [],
      paths: ['loose.md'],
      visibleFrom: '2020-01-01',
    },
  ],
}

describe('timeline scrubber', () => {
  it('hides claims that have not been ingested yet', () => {
    expect(visibleClaimIds(data, '2020-06-01')).toEqual(['old', 'like-a'])
    expect(contradictionPairsAt(data, '2020-06-01')).toEqual([])
  })

  it('drops superseded claims and paints contradictions red once both are known', () => {
    expect(visibleClaimIds(data, '2024-06-01')).toEqual(['now', 'like-a', 'like-b'])
    const view = graphAt(data, '2024-06-01')
    expect(view.contradictionCount).toBe(1)
    const red = view.links.filter((link) => link.tone === 'contradiction')
    expect(red.length).toBeGreaterThan(0)
    expect(view.links.some((link) => link.kind === 'contradiction')).toBe(true)
    expect(view.links.find((link) => link.claimId === 'now')?.tone).toBe('stale')
  })

  it('can keep superseded edges as history', () => {
    expect(visibleClaimIds(data, '2024-06-01', true)).toContain('old')
    expect(graphAt(data, '2024-06-01', true).links.find((link) => link.claimId === 'old')?.tone).toBe('history')
  })

  it('reveals lint findings only after their visible date', () => {
    expect(lintAt(data, '2020-06-01').map((finding) => finding.kind)).toEqual(['orphan'])
    expect(lintAt(data, '2024-06-01')).toHaveLength(2)
  })
})
