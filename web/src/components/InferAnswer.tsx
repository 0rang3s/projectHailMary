import type { InferResponse } from '../types'

const BADGE: Record<string, string> = {
  low: 'bg-amber-400/20 text-amber-200',
  medium: 'bg-sky-400/20 text-sky-200',
  high: 'bg-emerald-400/20 text-emerald-200',
}

export default function InferAnswer({ data }: { data: InferResponse }) {
  return (
    <div className="space-y-3">
      <p>{data.summary}</p>

      {data.summary_warning && <p className="text-xs text-amber-300">⚠ {data.summary_warning}</p>}

      {data.claims.map((c, i) => (
        <div key={i} className="space-y-1.5 rounded-xl border border-white/10 bg-white/5 p-2.5">
          <div className="flex items-center gap-2">
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${BADGE[c.confidence] ?? BADGE.low}`}>
              {c.confidence} confidence
            </span>
            {!c.grounded_in_docs && c.claim.startsWith('Unsourced hypothesis') && (
                <span className="text-[11px] text-slate-400">no document source</span>
            )}
          </div>
          <p>{c.claim}</p>
          {c.alternative && <p className="text-xs text-slate-400">Another possibility: {c.alternative}</p>}
          {c.would_change_if && <p className="text-xs text-slate-400">Would change if: {c.would_change_if}</p>}
          {c.note && <p className="text-xs text-amber-300">{c.note}</p>}
          <div className="flex flex-wrap gap-1">
            {c.evidence.map((e) => (
              <span key={e} className="break-all rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-slate-300">
                {e}
              </span>
            ))}
          </div>
        </div>
      ))}

      {data.not_known.length > 0 && (
        <div className="text-xs text-slate-300">
          <p className="font-medium text-slate-200">What we can't tell</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {data.not_known.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-[11px] text-slate-500">
        {data.verified ? 'Figures checked against radar results' : 'Some figures or claims could not be fully checked'}
      </p>
    </div>
  )
}