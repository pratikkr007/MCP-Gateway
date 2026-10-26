import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import { api, type AuditPageResult } from './api'
import {
  DataTable,
  EmptyState,
  ErrorBanner,
  StatusBadge,
  errMsg,
  formatDateTime,
  useAlive,
} from './interface'

const PAGE_SIZES = [25, 50, 100]
const AUTO_REFRESH_MS = 10_000

type Filters = {
  username: string
  server_name: string
  tool_name: string
  outcome: string
}

const NO_FILTERS: Filters = {
  username: '',
  server_name: '',
  tool_name: '',
  outcome: '',
}

function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${ms} ms`
}

function badgeFor(outcome: string): string {
  if (outcome === 'success') return 'success'
  if (outcome === 'timeout') return 'timeout'
  return 'failed'
}

export default function AuditPage({ refreshTick }: { refreshTick: number }) {
  const alive = useAlive()
  const requestId = useRef(0)

  const [filters, setFilters] = useState<Filters>(NO_FILTERS)
  const [offset, setOffset] = useState(0)
  const [limit, setLimit] = useState(25)
  const [result, setResult] = useState<AuditPageResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [auto, setAuto] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [base, setBase] = useState<{
    users: string[]
    servers: string[]
    tools: string[]
  }>({ users: [], servers: [], tools: [] })

  // Options for the filter dropdowns.
  useEffect(() => {
    void (async () => {
      const [users, servers, tools] = await Promise.allSettled([
        api.listUsers(),
        api.upstreams(),
        api.myTools(),
      ])

      if (!alive.current) return

      setBase({
        users:
          users.status === 'fulfilled'
            ? users.value.users.map((user) => user.username)
            : [],
        servers:
          servers.status === 'fulfilled'
            ? servers.value.upstreams.map((server) => server.name)
            : [],
        tools:
          tools.status === 'fulfilled'
            ? tools.value.tools.map((tool) => tool.upstream_tool)
            : [],
      })
    })()
  }, [alive, refreshTick])

  // Include values already seen in the log (for example deleted users).
  const options = useMemo(() => {
    const seen = result?.audit ?? []

    const merge = (known: string[], extra: (string | null)[]) =>
      [...new Set([...known, ...extra.filter((v): v is string => Boolean(v))])]
        .sort((a, b) => a.localeCompare(b))

    return {
      users: merge(base.users, seen.map((event) => event.username)),
      servers: merge(base.servers, seen.map((event) => event.server_name)),
      tools: merge(base.tools, seen.map((event) => event.tool_name)),
    }
  }, [base, result])

  const load = useCallback(
    async (silent: boolean) => {
      const id = ++requestId.current

      if (!silent) setLoading(true)

      try {
        const data = await api.audit({ ...filters, limit, offset })

        if (!alive.current || id !== requestId.current) return

        setResult(data)
        setUpdatedAt(new Date())
        setError('')
      } catch (e) {
        if (alive.current && id === requestId.current) {
          setError(errMsg(e, 'Could not load the audit log.'))
        }
      } finally {
        if (alive.current && id === requestId.current && !silent) {
          setLoading(false)
        }
      }
    },
    [alive, filters, limit, offset],
  )

  useEffect(() => {
    void load(false)
  }, [load, refreshTick])

  useEffect(() => {
    if (!auto) return

    const id = window.setInterval(() => {
      if (!document.hidden) void load(true)
    }, AUTO_REFRESH_MS)

    return () => window.clearInterval(id)
  }, [auto, load])

  function setFilter(key: keyof Filters, value: string) {
    setFilters((current) => ({ ...current, [key]: value }))
    setOffset(0)
    setExpanded(new Set())
  }

  function toggle(id: number) {
    setExpanded((current) => {
      const next = new Set(current)

      if (next.has(id)) next.delete(id)
      else next.add(id)

      return next
    })
  }

  const events = result?.audit ?? []
  const total = result?.total ?? 0
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + limit, total)
  const hasFilters = Object.values(filters).some(Boolean)

  return (
    <section className="panel data-panel">
      <div className="panel-heading">
        <div>
          <h3>Audit log</h3>
          <p>
            Every tool call: who, which server and tool, when, how long and
            whether it succeeded.
          </p>
        </div>

        <div className="servers-toolbar">
          <label className="checkbox-row compact">
            <input
              type="checkbox"
              checked={auto}
              onChange={(event) => setAuto(event.target.checked)}
            />
            Auto-refresh {AUTO_REFRESH_MS / 1000}s
          </label>

          <button
            className="button button-secondary button-small"
            onClick={() => void load(false)}
            disabled={loading}
          >
            <RefreshCw size={15} />
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}

      <div className="filter-bar">
        <label className="field">
          User
          <select
            value={filters.username}
            onChange={(event) => setFilter('username', event.target.value)}
          >
            <option value="">All users</option>
            {options.users.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          Server
          <select
            value={filters.server_name}
            onChange={(event) => setFilter('server_name', event.target.value)}
          >
            <option value="">All servers</option>
            {options.servers.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          Tool
          <select
            value={filters.tool_name}
            onChange={(event) => setFilter('tool_name', event.target.value)}
          >
            <option value="">All tools</option>
            {options.tools.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          Outcome
          <select
            value={filters.outcome}
            onChange={(event) => setFilter('outcome', event.target.value)}
          >
            <option value="">All outcomes</option>
            <option value="success">Success</option>
            <option value="error">Failed</option>
            <option value="timeout">Timeout</option>
          </select>
        </label>

        <button
          className="button button-secondary button-small"
          onClick={() => {
            setFilters(NO_FILTERS)
            setOffset(0)
          }}
          disabled={!hasFilters}
        >
          Clear filters
        </button>
      </div>

      {loading && !result ? (
        <p className="health-loading">Loading audit log…</p>
      ) : events.length === 0 ? (
        <EmptyState
          message={
            hasFilters
              ? 'No audit events match these filters.'
              : 'No tool calls have been recorded yet.'
          }
        />
      ) : (
        <DataTable>
          <thead>
            <tr>
              <th aria-label="Expand" />
              <th>Time</th>
              <th>User</th>
              <th>Server</th>
              <th>Tool</th>
              <th>Duration</th>
              <th>Outcome</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => {
              const open = expanded.has(event.id)

              return (
                <Fragment key={event.id}>
                  <tr>
                    <td>
                      <button
                        className="icon-button"
                        onClick={() => toggle(event.id)}
                        aria-label={open ? 'Hide details' : 'Show details'}
                        aria-expanded={open}
                      >
                        {open ? (
                          <ChevronDown size={16} />
                        ) : (
                          <ChevronRight size={16} />
                        )}
                      </button>
                    </td>
                    <td>
                      {formatDateTime(event.started_at ?? event.timestamp, '—')}
                    </td>
                    <td>{event.username ?? event.user_id}</td>
                    <td>{event.server_name}</td>
                    <td>
                      <code className="mono">{event.tool_name}</code>
                    </td>
                    <td>{formatDuration(event.duration_ms)}</td>
                    <td>
                      <StatusBadge value={badgeFor(event.outcome)} />
                    </td>
                  </tr>

                  {open && (
                    <tr className="expanded-row">
                      <td colSpan={7}>
                        <div className="audit-details">
                          <div>
                            <span>User ID</span>
                            <code className="mono">{event.user_id}</code>
                          </div>
                          <div>
                            <span>Started</span>
                            {formatDateTime(event.started_at, '—')}
                          </div>
                          <div>
                            <span>Finished</span>
                            {formatDateTime(event.timestamp, '—')}
                          </div>
                          <div>
                            <span>Raw outcome</span>
                            {event.outcome}
                          </div>
                        </div>

                        {event.error_message ? (
                          <pre className="audit-error">
                            {event.error_message}
                          </pre>
                        ) : (
                          <p className="muted">No error message recorded.</p>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </DataTable>
      )}

      <div className="pager">
        <span className="muted">
          {total === 0
            ? '0 events'
            : `Showing ${from}–${to} of ${total}`}
          {updatedAt && ` · updated ${updatedAt.toLocaleTimeString()}`}
        </span>

        <div className="pager-controls">
          <label className="checkbox-row compact">
            Per page
            <select
              value={limit}
              onChange={(event) => {
                setLimit(Number(event.target.value))
                setOffset(0)
              }}
            >
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>

          <button
            className="button button-secondary button-small"
            onClick={() => setOffset(Math.max(0, offset - limit))}
            disabled={offset === 0 || loading}
          >
            Previous
          </button>
          <button
            className="button button-secondary button-small"
            onClick={() => setOffset(offset + limit)}
            disabled={offset + limit >= total || loading}
          >
            Next
          </button>
        </div>
      </div>
    </section>
  )
}