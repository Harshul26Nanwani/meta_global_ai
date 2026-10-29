import { useEffect, useMemo, useRef, useState } from 'react'
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

type RunItem = {
  id: string
  parent_run_id?: string | null
  scenario_id?: string
  started_at: string
  status: string
  task_description?: string
  agent_version?: string
  event_count?: number
  failed_event_count?: number
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
  const [runs, setRuns] = useState<RunItem[]>([])
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [events, setEvents] = useState<EventItem[]>([])
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null)
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [apiStatus, setApiStatus] = useState<'checking' | 'connected' | 'offline'>('checking')
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [diagnosisLoading, setDiagnosisLoading] = useState(false)
  const [diagnosisMessage, setDiagnosisMessage] = useState('')
  const [detailsError, setDetailsError] = useState('')
  const [replayState, setReplayState] = useState<{ loading: boolean; message: string; status?: string }>({ loading: false, message: '' })
  const activeRunIdRef = useRef<string | null>(null)

  useEffect(() => {
    const load = async () => {
      try {
        const runsResponse = await fetch('/api/runs')
        if (runsResponse.ok) {
          setApiStatus('connected')
          const runsPayload = await runsResponse.json()
          const nextRuns: RunItem[] = runsPayload.runs || []
          const sessions = nextRuns.filter((run) => !run.parent_run_id)
          setRuns(sessions)
          if (sessions.length > 0) {
            const bestInitialRun = sessions.find((run) => (run.failed_event_count || 0) > 0)
              || sessions.find((run) => (run.event_count || 0) > 0)
              || sessions[0]
            activeRunIdRef.current = bestInitialRun.id
            setActiveRunId(bestInitialRun.id)
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
    activeRunIdRef.current = activeRunId
    if (!activeRunId) {
      return
    }

    const controller = new AbortController()
    const loadDetails = async () => {
      setDetailsLoading(true)
      setDetailsError('')
      setEvents([])
      setDiagnosis(null)
      setComparison(null)
      setSelectedEventId(null)
      setDiagnosisMessage('')
      setDiagnosisLoading(false)
      setReplayState({ loading: false, message: '' })
      try {
        const [eventsResponse, diagnosisResponse, comparisonResponse] = await Promise.all([
          fetch(`/api/runs/${activeRunId}/events`, { signal: controller.signal }),
          fetch(`/api/runs/${activeRunId}/diagnosis`, { signal: controller.signal }),
          fetch(`/api/runs/${activeRunId}/comparison`, { signal: controller.signal }),
        ])

        if (!eventsResponse.ok) {
          throw new Error('Unable to load run events.')
        }
        const eventPayload = await eventsResponse.json()
        setEvents((eventPayload.events || []).map((event: EventItem) => ({
          ...event,
          input_payload: parseRecord(event.input_payload),
          output_payload: parseRecord(event.output_payload),
        })))

        if (diagnosisResponse.ok) {
          const diagnosisPayload = await diagnosisResponse.json()
          setDiagnosis(diagnosisPayload)
        } else if (diagnosisResponse.status !== 404) {
          throw new Error('Unable to load run diagnosis.')
        }

        if (!comparisonResponse.ok) {
          throw new Error('Unable to load replay history.')
        }
        const comparisonPayload = await comparisonResponse.json()
        setComparison({
          ...comparisonPayload,
          replays: (comparisonPayload.replays || []).map((replay: ReplayResult) => ({
            ...replay,
            assertion_results: parseRecord(replay.assertion_results),
            state_diff: parseRecord(replay.state_diff),
          })),
        })
      } catch (error) {
        if (!controller.signal.aborted) {
          const message = error instanceof Error ? error.message : 'Unable to load run details.'
          setDetailsError(message)
          console.warn(message, error)
        }
      } finally {
        if (!controller.signal.aborted) {
          setDetailsLoading(false)
        }
      }
    }

    loadDetails()
    return () => controller.abort()
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
  const latestReplayIsObserved = latestReplay
    ? parseRecord(latestReplay.state_diff).execution_mode === 'playwright_observed'
    : false

  const handleDiagnose = async () => {
    if (!activeRunId || events.length === 0) {
      return
    }

    const runId = activeRunId
    setDiagnosisLoading(true)
    setDiagnosisMessage('')
    try {
      const response = await fetch(`/api/runs/${runId}/diagnose`, { method: 'POST' })
      const payload = await response.json()
      if (!response.ok) {
        throw new Error(payload.detail || 'Diagnosis failed.')
      }
      if (activeRunIdRef.current === runId) {
        setDiagnosis(payload)
        setDiagnosisMessage('Diagnosis completed.')
      }
    } catch (error) {
      if (activeRunIdRef.current === runId) {
        setDiagnosisMessage(error instanceof Error ? error.message : 'Diagnosis failed.')
      }
    } finally {
      if (activeRunIdRef.current === runId) {
        setDiagnosisLoading(false)
      }
    }
  }

  const handleReplay = async () => {
    if (!activeRunId || !diagnosis) {
      return
    }

    const runId = activeRunId
    const correctionType = diagnosis.recommended_correction
    setReplayState({ loading: true, message: 'Running replay…' })

    try {
      const response = await fetch(`/api/runs/${runId}/replay`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          correction: { type: correctionType, target: 'cart_check' },
        }),
      })

      const payload = await response.json()
      if (!response.ok) {
        throw new Error(payload.detail || 'Replay failed.')
      }

      if (activeRunIdRef.current === runId) {
        setComparison((current) => ({
          ...(current || { original_run_id: runId }),
          original_run_id: runId,
          replays: [payload, ...(current?.replays || [])],
        }))
        setReplayState({
          loading: false,
          message: payload.verification_status === 'verified'
            ? 'Browser replay verified against the storefront.'
            : 'Replay completed, but verification did not pass.',
          status: payload.verification_status,
        })
      }
    } catch (error) {
      if (activeRunIdRef.current === runId) {
        setReplayState({
          loading: false,
          message: error instanceof Error ? error.message : 'Replay failed.',
        })
      }
    }
  }

  const activeRun = runs.find((run) => run.id === activeRunId)
  const runDateLabel = activeRun ? new Date(activeRun.started_at).toLocaleString() : 'No run selected'

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
            <p>Inspect trace evidence, diagnose failures, and verify corrections in a browser replay.</p>
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
                  onClick={() => {
                    activeRunIdRef.current = run.id
                    setActiveRunId(run.id)
                  }}
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
              {detailsLoading ? (
                <div className="timeline-empty">Loading trace…</div>
              ) : timelineEntries.length > 0 ? timelineEntries.map((entry) => (
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
                <h2>{diagnosis?.summary || (diagnosisLoading ? 'Analyzing recorded evidence…' : 'Diagnosis not run')}</h2>
                {diagnosis ? (
                  <span className="classification-tag">{diagnosis.classification}</span>
                ) : (
                  <button type="button" className="replay-button diagnose-button" onClick={handleDiagnose} disabled={diagnosisLoading || detailsLoading || events.length === 0}>
                    {diagnosisLoading ? 'Diagnosing…' : 'Run diagnosis'}
                  </button>
                )}
              </div>
              {diagnosis ? (
                <div className="diagnosis-details">
                  <div><span>Likely divergence</span><strong>{diagnosis.suspected_divergence_event_id}</strong></div>
                  <div><span>Confidence</span><strong>{diagnosis.confidence_estimate || 'Not provided'}</strong></div>
                  <div><span>Suggested correction</span><strong>{diagnosis.recommended_correction}</strong></div>
                </div>
              ) : (
                <p className="diagnosis-prompt">{events.length ? 'Run a diagnosis to analyze this trace and unlock a supported replay.' : 'A diagnosis will be available when this run has recorded events.'}</p>
              )}
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
              {diagnosisMessage && <p className="diagnosis-message">{diagnosisMessage}</p>}
              {detailsError && <p className="diagnosis-message error">{detailsError}</p>}
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
                  <button type="button" className="replay-button" onClick={handleReplay} disabled={replayState.loading || detailsLoading || !activeRunId || !diagnosis}>
                    {replayState.loading ? 'Replaying…' : 'Replay with verification'}
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
                    <strong>{latestReplay ? latestReplayIsObserved ? latestReplay.verification_status : 'legacy / unverified' : 'Not run'}</strong>
                    <p>{latestReplay?.correction_applied || selectedRun.correction}</p>
                    {latestReplay && latestReplayIsObserved ? (
                      <div className="assertion-list">
                        {Object.entries(parseRecord(latestReplay.assertion_results)).map(([assertion, result]) => (
                          <div key={assertion}>
                            <span>{assertion.replaceAll('_', ' ')}</span>
                            <b className={result === true ? 'assertion-pass' : 'assertion-fail'}>{result === true ? 'PASS' : result === false ? 'FAIL' : String(result)}</b>
                          </div>
                        ))}
                      </div>
                    ) : <span className="comparison-foot">{latestReplay ? 'This stored result predates browser-observed replay evidence.' : 'A replay result will appear here.'}</span>}
                  </div>
                </div>
                {latestReplay && latestReplayIsObserved && (
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
