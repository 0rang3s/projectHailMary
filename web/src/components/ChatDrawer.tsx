import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { askQuestion, getAudienceAlert, getReport } from '../api'
import { shortDate } from '../format'
import type { Audience, AudienceAlert, InferResponse, ToolUse } from '../types'
import InferAnswer from './InferAnswer'

const SUGGESTED = [
  'Which lifeline is in the most trouble?',
  'What changed between Apr 30 and May 19?',
  'Is the Fort Albany airstrip getting better or worse?',
]

// While testing, keep this false: with no history, repeated questions are answered from the
// server cache. Set it to true if you want follow-up questions to remember earlier turns.
const SEND_HISTORY = false

const AUDIENCES: { id: Audience; label: string }[] = [
  { id: 'coordinator', label: 'Coordinator' },
  { id: 'community', label: 'Community' },
  { id: 'pilots', label: 'Pilots' },
]

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  tools?: ToolUse[]
  dates?: string[]
  data?: InferResponse
  pending?: boolean
}

interface Props {
  open: boolean
  selected: string
  onClose: () => void
}

export default function ChatDrawer({ open, selected, onClose }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [audience, setAudience] = useState<Audience>('coordinator')
  const [alert, setAlert] = useState<AudienceAlert | null>(null)
  const [alertError, setAlertError] = useState<string | null>(null)
  const [alertLoading, setAlertLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [reportState, setReportState] = useState<'idle' | 'loading' | 'error'>('idle')
  const scroller = useRef<HTMLDivElement>(null)
  const alertCache = useRef<Record<string, AudienceAlert>>({})

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }, [messages, busy])

  useEffect(() => {
    if (selected === 'normal') {
      setAlert(null)
      setAlertError(null)
      return
    }
    const key = `${selected}:${audience}`
    const cached = alertCache.current[key]
    if (cached) {
      setAlert(cached)
      setAlertError(null)
      return
    }
    let cancel = false
    setAlertLoading(true)
    setAlertError(null)
    getAudienceAlert(selected, audience)
      .then((result) => {
        alertCache.current[key] = result
        if (!cancel) setAlert(result)
      })
      .catch((error: Error) => {
        if (!cancel) setAlertError(error.message)
      })
      .finally(() => {
        if (!cancel) setAlertLoading(false)
      })
    return () => {
      cancel = true
    }
  }, [selected, audience])

  async function send(question: string) {
    const text = question.trim()
    if (!text || busy) return
    const history: { role: 'user' | 'assistant'; content: string }[] = SEND_HISTORY
      ? messages
          .filter((message) => !message.pending)
          .map((message) => ({ role: message.role, content: message.content }))
      : []
    const userId = crypto.randomUUID()
    setMessages((current) => [
      ...current,
      { id: userId, role: 'user', content: text },
      { id: `${userId}-pending`, role: 'assistant', content: '', pending: true },
    ])
    setDraft('')
    setBusy(true)
    try {
      const result = await askQuestion(text, history)
      setMessages((current) =>
        current.map((message) =>
          message.id === `${userId}-pending`
            ? {
                ...message,
                pending: false,
                content: result.summary,
                data: result,
                tools: result.tools_used,
                dates: result.dates_cited,
              }
            : message,
        ),
      )
    } catch (error) {
      const message = error instanceof Error ? error.message : 'The question failed.'
      setMessages((current) =>
        current.map((item) =>
          item.id === `${userId}-pending` ? { ...item, pending: false, content: message } : item,
        ),
      )
    } finally {
      setBusy(false)
    }
  }

  async function downloadReport() {
    setReportState('loading')
    try {
      const markdown = await getReport()
      const blob = new Blob([markdown], { type: 'text/markdown' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'cut-off-situation-report.md'
      link.click()
      URL.revokeObjectURL(url)
      setReportState('idle')
    } catch {
      setReportState('error')
    }
  }

  async function copyAlert() {
    if (!alert) return
    await navigator.clipboard.writeText(alert.text)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  if (!open) return null

  return (
    <aside className="pointer-events-auto absolute bottom-[10.75rem] right-4 top-[6.5rem] z-20 flex w-[22rem] max-w-[calc(100vw-2rem)] flex-col rounded-2xl border border-white/10 bg-slate-950/80 shadow-2xl backdrop-blur-md">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
        <h2 className="text-base font-semibold text-white">Ask Cut Off</h2>
        <button type="button" onClick={onClose} className="text-sm text-slate-300 hover:text-white">
          Close
        </button>
      </div>

      <div ref={scroller} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {messages.length === 0 && (
          <p className="text-sm leading-relaxed text-slate-300">
            Ask about water, ice, and the airstrips, causeway, and towns. Answers use only the radar results.
          </p>
        )}
        {messages.map((message) => (
          <div key={message.id} className={message.role === 'user' ? 'flex justify-end' : ''}>
            <div
              className={`max-w-[95%] break-words rounded-2xl px-3 py-2 text-sm leading-relaxed ${
                message.role === 'user' ? 'bg-sky-400 text-slate-950' : 'bg-white/5 text-slate-100'
              }`}
            >
              {message.pending ? (
                <span className="inline-flex gap-1">
                  <Dot />
                  <Dot />
                  <Dot />
                </span>
              ) : message.role === 'assistant' ? (
                message.data ? (
                  <InferAnswer data={message.data} />
                ) : (
                  <div className="answer">
                    <ReactMarkdown>{message.content}</ReactMarkdown>
                  </div>
                )
              ) : (
                message.content
              )}
              {!message.pending && message.role === 'assistant' && !message.data && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {(message.tools ?? []).map((tool, index) => (
                    <span key={`${tool.name}-${index}`} className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] text-slate-300">
                      {tool.name}
                    </span>
                  ))}
                  {(message.dates ?? []).map((date) => (
                    <span key={date} className="rounded-full bg-sky-400/15 px-2 py-0.5 text-[11px] text-sky-200">
                      {date}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="space-y-2 border-t border-white/10 px-4 py-3">
        <div className="flex flex-wrap gap-1.5">
          {SUGGESTED.map((question) => (
            <button
              key={question}
              type="button"
              onClick={() => send(question)}
              disabled={busy}
              className="rounded-full border border-white/10 px-2.5 py-1 text-left text-xs text-slate-200 hover:bg-white/10 disabled:opacity-40"
            >
              {question}
            </button>
          ))}
        </div>
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            void send(draft)
          }}
        >
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask about this flood"
            className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500 focus:border-sky-400"
          />
          <button
            type="submit"
            disabled={busy || !draft.trim()}
            className="rounded-xl bg-sky-400 px-3 py-2 text-sm font-medium text-slate-950 disabled:opacity-40"
          >
            Send
          </button>
        </form>
      </div>

      <div className="max-h-[42%] space-y-2 overflow-y-auto border-t border-white/10 px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-medium text-white">Alert</h3>
          {selected !== 'normal' && <span className="text-xs text-slate-400">{shortDate(selected)}</span>}
        </div>
        <div className="grid grid-cols-3 gap-1 rounded-full bg-white/5 p-1">
          {AUDIENCES.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setAudience(item.id)}
              className={`rounded-full px-2 py-1 text-xs font-medium ${
                audience === item.id ? 'bg-sky-400 text-slate-950' : 'text-slate-300'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
        {selected === 'normal' && (
          <p className="text-sm text-slate-300">Pick a flood date for an alert. August 7 is the normal river.</p>
        )}
        {selected !== 'normal' && alertLoading && <div className="h-16 animate-pulse rounded-xl bg-white/10" />}
        {selected !== 'normal' && alertError && <p className="text-sm text-red-200">{alertError}</p>}
        {selected !== 'normal' && alert && !alertLoading && (
          <div className="rounded-xl bg-white/5 p-3 text-sm leading-relaxed text-slate-100">
            {alert.text}
            <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
              <span>source: {alert.source === 'llm' ? 'AI' : 'template'}</span>
              <button type="button" onClick={() => void copyAlert()} className="text-sky-300 hover:text-sky-200">
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          </div>
        )}
        <button
          type="button"
          onClick={() => void downloadReport()}
          disabled={reportState === 'loading'}
          className="w-full rounded-xl border border-white/10 px-3 py-2 text-sm font-medium text-white hover:bg-white/10 disabled:opacity-50"
        >
          {reportState === 'loading' ? 'Preparing report…' : 'Download situation report'}
        </button>
        {reportState === 'error' && <p className="text-xs text-red-200">The report could not be downloaded.</p>}
      </div>
    </aside>
  )
}

function Dot() {
  return <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-300" />
}