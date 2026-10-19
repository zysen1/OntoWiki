'use client'

import * as React from 'react'
import dynamic from 'next/dynamic'
import { Pause, Play } from 'lucide-react'
import {
  TONE_COLOR,
  graphAt,
  lintAt,
  type TimelineData,
  type ViewLink,
} from '@/lib/ontowiki/timeline'

const ForceGraph2D = dynamic(() => import('react-force-graph-2d'), { ssr: false })

const NODE_COLOR: Record<string, string> = {
  Paper: '#1c1917',
  Concept: '#b45309',
  Method: '#0f766e',
  Task: '#44403c',
  System: '#9a3412',
  Literal: '#78716c',
  Person: '#1c1917',
  City: '#0f766e',
}

type Props = {
  data: TimelineData
}

export function TimelineDemo({ data }: Props) {
  const ticks = data.ticks
  const [index, setIndex] = React.useState(ticks.length - 1)
  const [playing, setPlaying] = React.useState(false)
  const [showHistory, setShowHistory] = React.useState(false)
  const [selected, setSelected] = React.useState<string | null>(null)
  const wrapRef = React.useRef<HTMLDivElement>(null)
  const [size, setSize] = React.useState({ width: 640, height: 480 })

  const time = ticks[index] ?? ticks[0]
  const view = React.useMemo(() => graphAt(data, time, showHistory), [data, time, showHistory])
  const findings = React.useMemo(() => lintAt(data, time), [data, time])
  const claimLinks = React.useMemo(
    () => view.links.filter((link) => link.kind === 'claim'),
    [view],
  )
  const selectedLink = claimLinks.find((link) => link.claimId === selected)
  const graphData = React.useMemo(
    () => ({
      nodes: view.nodes.map((node) => ({ ...node })),
      links: view.links.map((link) => ({ ...link })),
    }),
    [view],
  )

  React.useEffect(() => {
    if (selected && !claimLinks.some((link) => link.claimId === selected)) setSelected(null)
  }, [claimLinks, selected])

  React.useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (rect && rect.width > 0 && rect.height > 0) {
        setSize({ width: rect.width, height: rect.height })
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  React.useEffect(() => {
    if (!playing) return
    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % ticks.length)
    }, 900)
    return () => window.clearInterval(timer)
  }, [playing, ticks.length])

  const onKey = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowRight') setIndex((current) => Math.min(ticks.length - 1, current + 1))
    if (event.key === 'ArrowLeft') setIndex((current) => Math.max(0, current - 1))
  }

  return (
    <div className="min-h-svh bg-background text-foreground" onKeyDown={onKey}>
      <header className="flex items-end justify-between gap-6 border-b border-border px-6 py-4 lg:px-10">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">OntoWiki · built on llmwiki</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">The graph, as it was known</h1>
        </div>
        <p className="hidden max-w-sm text-right text-sm text-muted-foreground sm:block">
          Scrub the date. Nodes appear when a source is compiled in. Red edges are contradictions that were kept, not overwritten.
        </p>
      </header>

      <div className="grid lg:min-h-[calc(100svh-9.5rem)] lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div ref={wrapRef} className="relative h-[58vh] min-h-[320px] overflow-hidden bg-[#f4f0e8] lg:h-auto lg:min-h-[calc(100svh-9.5rem)] dark:bg-[#161311]">
          <ForceGraph2D
            width={size.width}
            height={size.height}
            graphData={graphData}
            nodeRelSize={5}
            nodeLabel={(node) => (node as { label: string }).label}
            nodeColor={(node) => NODE_COLOR[(node as { type: string }).type] ?? '#44403c'}
            linkColor={(link) => TONE_COLOR[(link as ViewLink).tone]}
            linkWidth={(link) => ((link as ViewLink).tone === 'contradiction' ? 2.4 : 1)}
            linkLineDash={(link) => ((link as ViewLink).tone === 'history' || (link as ViewLink).tone === 'stale' ? [4, 3] : null)}
            linkDirectionalArrowLength={3.5}
            linkDirectionalArrowRelPos={1}
            linkHoverPrecision={12}
            onLinkClick={(link) => {
              const claimId = (link as ViewLink).claimId
              if (claimId) setSelected(claimId)
            }}
            onNodeClick={(node) => {
              const id = String((node as { id?: string }).id ?? '')
              const match = claimLinks.find((link) => link.source === id || link.target === id)
              if (match?.claimId) setSelected(match.claimId)
            }}
            cooldownTicks={80}
          />
          <div className="pointer-events-none absolute left-4 top-4 flex flex-wrap gap-2 text-xs">
            <Legend swatch="#1c1917" label="paper" />
            <Legend swatch="#b45309" label="concept" />
            <Legend swatch="#0f766e" label="method" />
            <Legend swatch="#dc2626" label="contradiction" />
            <Legend swatch="#a8a29e" label="stale" />
          </div>
          <p className="absolute bottom-3 left-4 text-xs text-stone-600 dark:text-stone-400">
            {view.nodes.length} entities · {view.links.filter((link) => link.kind === 'claim').length} claims ·{' '}
            <span className="text-red-600">{view.contradictionCount} contradiction{view.contradictionCount === 1 ? '' : 's'}</span>
          </p>
        </div>

        <aside className="flex flex-col gap-4 border-t border-border p-5 lg:border-l lg:border-t-0">
          <div>
            <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">As of</p>
            <p className="mt-1 font-mono text-lg">{time}</p>
          </div>
          {selectedLink ? (
            <figure className="rounded-md border border-border bg-card p-3">
              <figcaption className="text-xs uppercase tracking-wide text-muted-foreground">
                {selectedLink.predicate} · {selectedLink.tone}
              </figcaption>
              <p className="mt-2 text-sm font-medium">
                {selectedLink.subject} → {selectedLink.object}
              </p>
              <blockquote className="mt-2 text-sm leading-relaxed text-foreground/90">“{selectedLink.quote}”</blockquote>
              <p className="mt-2 text-xs text-muted-foreground">
                {selectedLink.episode} · valid {selectedLink.validFrom} .. {selectedLink.validTo ?? 'open'}
              </p>
            </figure>
          ) : (
            <p className="text-sm text-muted-foreground">Click an edge to read its quote and the source it was taken from.</p>
          )}
          <div className="min-h-0 flex-1 overflow-auto">
            <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">Claims at this date</p>
            <ul className="mt-2 max-h-48 space-y-1 overflow-auto">
              {claimLinks.map((link) => (
                <li key={link.id}>
                  <button
                    type="button"
                    onClick={() => link.claimId && setSelected(link.claimId)}
                    className={`w-full rounded-md border px-2 py-1.5 text-left text-sm ${
                      link.claimId === selected ? 'border-foreground' : 'border-border'
                    } ${link.tone === 'contradiction' ? 'text-red-700 dark:text-red-300' : ''}`}
                  >
                    <span className="font-medium">{link.subject}</span>
                    <span className="text-muted-foreground"> {link.predicate} </span>
                    <span>{link.object}</span>
                  </button>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-xs uppercase tracking-[0.16em] text-muted-foreground">Lint, for review</p>
            <ul className="mt-2 space-y-2">
              {findings.length === 0 && <li className="text-sm text-muted-foreground">Nothing to review at this date.</li>}
              {findings.map((finding) => (
                <li
                  key={`${finding.kind}-${finding.message}`}
                  className={`rounded-md border px-3 py-2 text-sm ${finding.kind === 'contradiction' ? 'border-red-300 text-red-800 dark:border-red-900 dark:text-red-300' : 'border-border'}`}
                >
                  <span className="text-xs uppercase tracking-wide">{finding.kind}</span>
                  <p className="mt-1">{finding.message}</p>
                </li>
              ))}
            </ul>
          </div>
        </aside>
      </div>

      <footer className="sticky bottom-0 flex items-center gap-4 border-t border-border bg-background/95 px-6 py-3 backdrop-blur lg:px-10">
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1.5 text-sm"
          onClick={() => setPlaying((value) => !value)}
          aria-pressed={playing}
        >
          {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
          {playing ? 'Pause' : 'Play'}
        </button>
        <input
          className="h-1 flex-1 accent-stone-800"
          type="range"
          min={0}
          max={Math.max(0, ticks.length - 1)}
          value={index}
          aria-label="Knowledge date"
          onChange={(event) => {
            setPlaying(false)
            setIndex(Number(event.target.value))
          }}
        />
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={showHistory}
            onChange={(event) => setShowHistory(event.target.checked)}
          />
          History
        </label>
      </footer>
    </div>
  )
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-white/80 px-2 py-1 text-stone-700 dark:bg-stone-900/80 dark:text-stone-300">
      <span className="inline-block size-2 rounded-full" style={{ background: swatch }} />
      {label}
    </span>
  )
}
