import { useEffect, useMemo, useState } from 'react'
import './App.css'

type EventItem = {
  id: string
  run_id: string
  sequence_number: number
  event_type: string
  status: string
  timestamp?: string
  input_payload: Record<string, unknown> | string
  output_payload: Record<string, unknown> | string
}

type Diagnosis = {
  run_id: string
  summary: string
  suspected_divergence_event_id: string
  supporting_event_ids: string[]
  classification: string
  confidence_estimate?: string
  recommended_correction: string
  replay_plan?: Record<string, unknown>
}

type ReplayResult = {
  replay_run_id?: string
  verification_status: string
  correction_applied?: string
  assertion_results: Record<string, unknown> | string
  state_diff: Record<string, unknown> | string
}

type Comparison = {
  original_run_id: string
  replays: ReplayResult[]
}

const parseRecord = (value: unknown): Record<string, unknown> => {
  if (typeof value === 'string') {
    try {
      const parsed: unknown = JSON.parse(value)
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? parsed as Record<string, unknown>
        : {}
    } catch {
      return {}
    }
  }

  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

const formatRecord = (value: unknown) => JSON.stringify(parseRecord(value), null, 2)

const emptyRun = {
  status: 'no run',
  task: 'Select a recorded run to inspect its evidence.',
  agent: '—',
  scenario: 'No run selected',
  divergence: '—',
  classification: 'awaiting evidence',
  correction: '—',
  replayStatus: 'not run',
}

const navItems = ['session', 'history', 'logs', 'settings']

function App() {
  const [runs, setRuns] = useState<any[]>([])
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [events, setEvents] = useState<EventItem[]>([])
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null)
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [apiStatus, setApiStatus] = useState<'checking' | 'connected' | 'offline'>('checking')
  const [replayState, setReplayState] = useState<{ loading: boolean; message: string; status?: string }>({ loading: false, message: '' })

  useEffect(() => {
    const load = async () => {
      try {
        const runsResponse = await fetch('/api/runs')
        if (runsResponse.ok) {
          setApiStatus('connected')
          const runsPayload = await runsResponse.json()
          const nextRuns = runsPayload.runs || []
          const sessions = nextRuns.filter((run: { parent_run_id?: string | null }) => !run.parent_run_id)
          setRuns(sessions)
          if (sessions.length > 0) {
            setActiveRunId(sessions[0].id)
            return
          }
        } else {
          setApiStatus('offline')
        }
      } catch (error) {
        setApiStatus('offline')
        console.warn('Backend unavailable; run history could not be loaded.', error)
      }
    }

    load()
  }, [])

  useEffect(() => {
    if (!activeRunId) {
      return
    }

    const loadDetails = async () => {
      setEvents([])
      setDiagnosis(null)
      setComparison(null)
      setSelectedEventId(null)
      try {
        const [eventsResponse, diagnosisResponse, comparisonResponse] = await Promise.all([
          fetch(`/api/runs/${activeRunId}/events`),
          fetch(`/api/runs/${activeRunId}/diagnosis`),
          fetch(`/api/runs/${activeRunId}/comparison`),
        ])

        if (eventsResponse.ok) {
          const eventPayload = await eventsResponse.json()
          setEvents((eventPayload.events || []).map((event: EventItem) => ({
            ...event,
            input_payload: parseRecord(event.input_payload),
            output_payload: parseRecord(event.output_payload),
          })))
        }

        if (diagnosisResponse.ok) {
          const diagnosisPayload = await diagnosisResponse.json()
          setDiagnosis(diagnosisPayload)
        }

        if (comparisonResponse.ok) {
          const comparisonPayload = await comparisonResponse.json()
          setComparison({
            ...comparisonPayload,
            replays: (comparisonPayload.replays || []).map((replay: ReplayResult) => ({
              ...replay,
              assertion_results: parseRecord(replay.assertion_results),
              state_diff: parseRecord(replay.state_diff),
            })),
          })
        }
      } catch (error) {
        console.warn('Unable to load detailed run data.', error)
      }
    }

    loadDetails()
  }, [activeRunId])

  const selectedRun = useMemo(() => {
    if (runs.length === 0) {
      return emptyRun
    }

    const latest = runs.find((run) => run.id === activeRunId) || runs[0]
    const latestReplay = comparison?.replays?.[0]
    return {
      status: latest.status,
      task: latest.task_description || 'Task description unavailable',
      agent: latest.agent_version || 'Unknown agent',
      scenario: latest.scenario_id || 'Unlabeled scenario',
      divergence: diagnosis?.suspected_divergence_event_id || 'Not identified',
      classification: diagnosis?.classification || 'Awaiting diagnosis',
      correction: diagnosis?.recommended_correction || 'Not provided',
      replayStatus: latestReplay?.verification_status || 'Not run',
    }
  }, [activeRunId, diagnosis, runs, comparison])

  const timelineEntries = events
  const selectedEvent = timelineEntries.find((event) => event.id === selectedEventId)
    || timelineEntries.find((event) => event.id === diagnosis?.suspected_divergence_event_id)
    || timelineEntries[0]
  const latestReplay = comparison?.replays?.[0]

  const handleReplay = async () => {
    if (!activeRunId) {
      return
    }

    const correctionType = diagnosis?.recommended_correction || 'add_verification_step'
    setReplayState({ loading: true, message: 'Running replay…' })

    try {
      const response = await fetch(`/api/runs/${activeRunId}/replay`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          correction: { type: correctionType, target: 'cart_check' },
          allowlist: [correctionType],
        }),
      })

      const payload = await response.json()
      if (!response.ok) {
        throw new Error(payload.detail || 'Replay failed.')
      }

      const nextReplayList = comparison?.replays ? [payload, ...comparison.replays] : [payload]
      setComparison({ ...(comparison || { original_run_id: activeRunId }), original_run_id: activeRunId, replays: nextReplayList })
      setReplayState({ loading: false, message: 'Replay succeeded.', status: payload.verification_status })
    } catch (error) {
      setReplayState({
        loading: false,
        message: error instanceof Error ? error.message : 'Replay failed.',
      })
    }
  }

  const runDateLabel = runs.length > 0 && activeRunId
    ? new Date((runs.find((run) => run.id === activeRunId)?.started_at || Date.now())).toLocaleString()
    : '10/28/2026, 4:41:48 PM'

  return (
    <div className="traceback-app-shell">
      <aside className="traceback-sidebar">
        <div className="sidebar-brand">
          <div className="brand-mark">T</div>
          <span>TraceBack</span>
        </div>

        <nav className="sidebar-nav" aria-label="Sidebar nav">
          <button className="nav-button active" type="button">◉</button>
          <button className="nav-button" type="button">◌</button>
          <button className="nav-button" type="button">◫</button>
          <button className="nav-button" type="button">◍</button>
        </nav>

        <div className="sidebar-section-label">DEMOS</div>
        <div className="sidebar-section">
          {navItems.map((item, index) => (
            <div key={item} className={`nav-item ${index === 0 ? 'selected' : ''}`}>
              <span>{item}</span>
            </div>
          ))}
        </div>
      </aside>

      <main className="traceback-main-panel">
        <header className="traceback-header">
          <div>
            <h1>Agent Trace Replay</h1>
            <p>Scrub completed agent sessions. Every step carries its NLP, implied IR, and timing.</p>
          </div>
          <div className="header-status-group">
            <span className={`connection-status ${apiStatus}`}><i />{apiStatus === 'connected' ? 'API connected' : apiStatus === 'offline' ? 'API offline' : 'Connecting'}</span>
            <span className="session-count">{runs.length} {runs.length === 1 ? 'session' : 'sessions'}</span>
          </div>
        </header>

        <div className="session-board">
          <div className="session-list-panel">
            <div className="session-list-header">SESSIONS</div>
            <div className="session-list">
              {runs.map((run) => (
                <button
                  key={run.id}
                  type="button"
                  className={`session-item ${activeRunId === run.id ? 'selected' : ''}`}
                  onClick={() => setActiveRunId(run.id)}
                >
                  <div className={`session-dot ${run.status === 'failed' ? 'failed' : ''}`} aria-hidden="true" />
                  <div className="session-meta">
                    <strong>{run.scenario_id || 'Unlabeled scenario'}</strong>
                    <span>{new Date(run.started_at).toLocaleString()}</span>
                  </div>
                </button>
              ))}
              {runs.length === 0 && (
                <div className="session-empty">
                  <strong>{apiStatus === 'offline' ? 'Backend unavailable' : 'No recorded runs'}</strong>
                  <span>{apiStatus === 'offline' ? 'Start the API to load run history.' : 'Run the demo agent to create the first trace.'}</span>
                </div>
              )}
            </div>
          </div>

          <div className="details-panel">
            <div className="details-header-row">
              <div className="run-title">{selectedRun.scenario} · {runDateLabel}</div>
              <div className="run-meta">
                <span>{timelineEntries.filter((entry) => entry.status === 'success').length} passed</span>
                <span>{timelineEntries.filter((entry) => entry.status === 'failure').length} failed</span>
                <span>{timelineEntries.length} steps</span>
              </div>
            </div>

            <div className="timeline-track" aria-label="Run event timeline">
              {timelineEntries.length > 0 ? timelineEntries.map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  className={`timeline-block ${entry.status === 'failure' ? 'failure' : 'success'} ${selectedEvent?.id === entry.id ? 'selected' : ''}`}
                  style={{ flex: 1 }}
                  title={`${entry.event_type} · ${entry.status}`}
                  aria-label={`Select event ${entry.sequence_number}: ${entry.event_type}, ${entry.status}`}
                  aria-pressed={selectedEvent?.id === entry.id}
                  onClick={() => setSelectedEventId(entry.id)}
                />
              )) : (
                <div className="timeline-empty">No events recorded for this run.</div>
              )}
            </div>

            <div className="timeline-labels">
              {timelineEntries.map((entry) => (
                <button key={entry.id} type="button" onClick={() => setSelectedEventId(entry.id)}>
                  <span>{String(entry.sequence_number).padStart(2, '0')}</span>
                  {entry.event_type.replaceAll('_', ' ')}
                </button>
              ))}
            </div>

            <section className="root-cause-panel">
              <div className="section-kicker">DIAGNOSIS</div>
              <div className="root-cause-heading">
                <h2>{diagnosis?.summary || 'Diagnosis is not available yet'}</h2>
                <span className="classification-tag">{diagnosis?.classification || 'Awaiting evidence'}</span>
              </div>
              <div className="diagnosis-details">
                <div><span>Likely divergence</span><strong>{diagnosis?.suspected_divergence_event_id || 'Not identified'}</strong></div>
                <div><span>Confidence</span><strong>{diagnosis?.confidence_estimate || 'Not provided'}</strong></div>
                <div><span>Suggested correction</span><strong>{diagnosis?.recommended_correction || 'Not provided'}</strong></div>
              </div>
              <div className="evidence-chain">
                <span className="evidence-label">Evidence</span>
                {diagnosis?.supporting_event_ids?.length ? diagnosis.supporting_event_ids.map((eventId) => {
                  const evidenceEvent = timelineEntries.find((event) => event.id === eventId)
                  return (
                    <button
                      key={eventId}
                      type="button"
                      className="evidence-chip"
                      onClick={() => setSelectedEventId(eventId)}
                    >
                      {evidenceEvent ? `#${evidenceEvent.sequence_number} ${evidenceEvent.event_type.replaceAll('_', ' ')}` : eventId}
                    </button>
                  )
                }) : <span className="muted-value">No supporting events</span>}
              </div>
            </section>

            <div className="investigation-grid">
              <section className="event-inspector">
                <div className="panel-heading">
                  <div>
                    <div className="section-kicker">SELECTED EVENT</div>
                    <h2>{selectedEvent?.event_type.replaceAll('_', ' ') || 'No event selected'}</h2>
                  </div>
                  {selectedEvent && <span className={`event-status ${selectedEvent.status}`}>{selectedEvent.status}</span>}
                </div>
                {selectedEvent ? (
                  <>
                    <div className="event-id-line">#{selectedEvent.sequence_number} · {selectedEvent.id}</div>
                    <div className="payload-columns">
                      <div><h3>Input</h3><pre>{formatRecord(selectedEvent.input_payload)}</pre></div>
                      <div><h3>Output</h3><pre>{formatRecord(selectedEvent.output_payload)}</pre></div>
                    </div>
                  </>
                ) : <p className="muted-value">This run has no event payloads to inspect.</p>}
              </section>

              <section className="replay-comparison">
                <div className="panel-heading">
                  <div>
                    <div className="section-kicker">REPLAY COMPARISON</div>
                    <h2>Original vs corrected</h2>
                  </div>
                  <button type="button" className="replay-button" onClick={handleReplay} disabled={replayState.loading || !activeRunId}>
                    {replayState.loading ? 'Replaying…' : 'Run verified replay'}
                  </button>
                </div>
                <div className="comparison-columns">
                  <div className="comparison-state original-state">
                    <span className="comparison-label">ORIGINAL RUN</span>
                    <strong>{selectedRun.status}</strong>
                    <p>{diagnosis?.summary || selectedRun.task}</p>
                    <span className="comparison-foot">{timelineEntries.filter((event) => event.status === 'failure').length} failed events · {timelineEntries.length} total</span>
                  </div>
                  <div className="comparison-state replay-state">
                    <span className="comparison-label">LATEST REPLAY</span>
                    <strong>{latestReplay?.verification_status || 'Not run'}</strong>
                    <p>{latestReplay?.correction_applied || selectedRun.correction}</p>
                    {latestReplay ? (
                      <div className="assertion-list">
                        {Object.entries(parseRecord(latestReplay.assertion_results)).map(([assertion, result]) => (
                          <div key={assertion}>
                            <span>{assertion.replaceAll('_', ' ')}</span>
                            <b className={result === true ? 'assertion-pass' : 'assertion-fail'}>{result === true ? 'PASS' : result === false ? 'FAIL' : String(result)}</b>
                          </div>
                        ))}
                      </div>
                    ) : <span className="comparison-foot">A replay result will appear here.</span>}
                  </div>
                </div>
                {latestReplay && (
                  <details className="state-diff-details">
                    <summary>Inspect replay state diff</summary>
                    <pre>{formatRecord(latestReplay.state_diff)}</pre>
                  </details>
                )}
                {replayState.message && <p className={`replay-inline ${replayState.status || ''}`}>{replayState.message}</p>}
              </section>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

export default App
