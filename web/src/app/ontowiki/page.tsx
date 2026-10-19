import type { Metadata } from 'next'
import timeline from '@/data/ontowiki-timeline.json'
import { TimelineDemo } from '@/components/ontowiki/TimelineDemo'
import type { TimelineData } from '@/lib/ontowiki/timeline'

export const metadata: Metadata = {
  title: 'OntoWiki timeline',
  description: 'Scrub a bi-temporal knowledge graph compiled under an ontology. Contradictions stay red.',
}

export default function OntoWikiPage() {
  return <TimelineDemo data={timeline as TimelineData} />
}
