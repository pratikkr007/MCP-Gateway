import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Pencil, Plus, Power, RefreshCw, Trash2, X } from 'lucide-react'
import { api, type UpstreamAuthMode } from './api'
import {
  DataTable,
  EmptyState,
  ErrorBanner,
  StatusBadge,
  errMsg,
} from './interface'

const SERVER_POLL_MS = 10_000

type ServerStatus = 'connected' | 'unreachable' | 'disabled' | 'unknown'



type ServerRow = {

  name: string

  url: string

  enabled: boolean

  status: ServerStatus

  authMode: UpstreamAuthMode

  headerName: string

  timeout: number

  hasCredential: boolean

  lastError: string | null

  lastChecked: string | null

  tools: string[]

}



type FormMode = { type: 'create' } | { type: 'edit'; server: ServerRow }



// Backend values: connected | error | circuit_open | disabled | unknown

function deriveStatus(enabled: boolean, raw: unknown): ServerStatus {

  const value = String(raw ?? '').toLowerCase()



  if (!enabled || value === 'disabled') return 'disabled'

  if (value === 'connected') return 'connected'

  if (value === 'error' || value === 'circuit_open') return 'unreachable'



  return 'unknown'

}



function sortServers(rows: ServerRow[]): ServerRow[] {

  return [...rows].sort((a, b) => {

    const aFirst = a.name.toLowerCase() === 'woocommerce'

    const bFirst = b.name.toLowerCase() === 'woocommerce'



    if (aFirst !== bFirst) return aFirst ? -1 : 1



    return a.name.localeCompare(b.name)

  })

}



function credentialLabel(server: ServerRow): { kind: string; state: string } {

  if (server.authMode === 'none') {

    return { kind: 'No authentication', state: '' }

  }



  return {

    kind:

      server.authMode === 'bearer'

        ? 'Bearer token'

        : `Header: ${server.headerName || 'custom'}`,

    state: server.hasCredential ? 'Credential set' : 'Credential not set',

  }

}



function formatTime(value: string | null): string {

  if (!value) return 'never'



  const date = new Date(value)



  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString()

}



function ServerForm({

  mode,

  onClose,

  onSaved,

}: {

  mode: FormMode

  onClose: () => void

  onSaved: () => Promise<void>

}) {

  const server = mode.type === 'edit' ? mode.server : null

  const isEdit = server !== null



  const [name, setName] = useState(server?.name ?? '')

  const [url, setUrl] = useState(server?.url ?? '')

  const [authMode, setAuthMode] = useState<UpstreamAuthMode>(

    server?.authMode ?? 'none',

  )

  const [headerName, setHeaderName] = useState(server?.headerName ?? '')

  const [credential, setCredential] = useState('')

  const [clearCredential, setClearCredential] = useState(false)

  const [timeout, setTimeoutValue] = useState(server?.timeout ?? 20)

  const [saving, setSaving] = useState(false)

  const [formError, setFormError] = useState('')



  async function submit(event: FormEvent) {

    event.preventDefault()

    setFormError('')



    const trimmedUrl = url.trim()

    const trimmedCredential = credential.trim()



    if (!isEdit && name.trim().length < 2) {

      setFormError('Name must be at least 2 characters.')

      return

    }



    if (!/^https?:\/\//i.test(trimmedUrl)) {

      setFormError('URL must start with http\:// or https\://')

      return

    }



    if (authMode === 'custom_header' && !headerName.trim()) {

      setFormError('Enter the header name to send the credential in.')

      return

    }



    const keepsExistingCredential =

      isEdit && server.hasCredential && !clearCredential



    if (

      authMode !== 'none' &&

      !trimmedCredential &&

      !keepsExistingCredential

    ) {

      setFormError(

        'Enter a credential, or choose "None" as the credential type.',

      )

      return

    }



    setSaving(true)



    try {

      if (isEdit) {

        await api.updateUpstream(server.name, {

          url: trimmedUrl,

          auth_mode: authMode,

          custom_header_name:

            authMode === 'custom_header' ? headerName.trim() : undefined,

          timeout_seconds: timeout,

          // undefined keeps the stored value, "" clears it.

          credential: clearCredential ? '' : trimmedCredential || undefined,

        })

      } else {

        await api.createUpstream({

          name: name.trim(),

          url: trimmedUrl,

          enabled: true,

          auth_mode: authMode,

          credential:

            authMode === 'none' ? undefined : trimmedCredential || undefined,

          custom_header_name:

            authMode === 'custom_header' ? headerName.trim() : undefined,

          timeout_seconds: timeout,

        })

      }



      await onSaved()

      onClose()

    } catch (e) {

      setFormError(errMsg(e, 'Could not save the server.'))

      setSaving(false)

    }

  }



  return (

    <div className="modal-backdrop" onMouseDown={saving ? undefined : onClose}>

      <div

        className="modal"

        role="dialog"

        aria-modal="true"

        aria-label={isEdit ? `Edit ${server.name}` : 'Add MCP server'}

        onMouseDown={(event) => event.stopPropagation()}

      >

        <div className="modal-header">

          <h3>{isEdit ? `Edit ${server.name}` : 'Add MCP server'}</h3>

          <button

            className="icon-button"

            onClick={onClose}

            disabled={saving}

            aria-label="Close"

            type="button"

          >

            <X size={18} />

          </button>

        </div>



        {formError && <div className="form-error">{formError}</div>}



        <form className="form-grid" onSubmit={submit}>

          <label className="field">

            Name

            <input

              value={name}

              onChange={(event) => setName(event.target.value)}

              placeholder="e.g. notes"

              disabled={isEdit || saving}

              maxLength={50}

              required

            />

            {isEdit && (

              <small className="muted">The name cannot be changed.</small>

            )}

          </label>



          <label className="field">

            Streamable HTTP URL

            <input

              value={url}

              onChange={(event) => setUrl(event.target.value)}

              placeholder="http\://my-server.default.svc:8000/mcp"

              disabled={saving}

              required

            />

          </label>



          <label className="field">

            Credential type

            <select

              value={authMode}

              onChange={(event) =>

                setAuthMode(event.target.value as UpstreamAuthMode)

              }

              disabled={saving}

            >

              <option value="none">None</option>

              <option value="bearer">Bearer token</option>

              <option value="custom_header">Custom header</option>

            </select>

          </label>



          {authMode === 'custom_header' && (

            <label className="field">

              Header name

              <input

                value={headerName}

                onChange={(event) => setHeaderName(event.target.value)}

                placeholder="X-Api-Key"

                disabled={saving}

              />

            </label>

          )}



          {authMode !== 'none' && (

            <label className="field">

              {authMode === 'bearer' ? 'Token' : 'Header value'}

              <input

                type="password"

                value={credential}

                onChange={(event) => setCredential(event.target.value)}

                placeholder={

                  isEdit && server.hasCredential

                    ? 'A credential is set. Leave blank to keep it.'

                    : 'Paste the credential'

                }

                autoComplete="new-password"

                disabled={saving || clearCredential}

              />

              <small className="muted">

                Stored encrypted on the server. It is never shown again.

              </small>

            </label>

          )}



          {isEdit && server.hasCredential && authMode !== 'none' && (

            <label className="checkbox-row">

              <input

                type="checkbox"

                checked={clearCredential}

                onChange={(event) => setClearCredential(event.target.checked)}

                disabled={saving}

              />

              Remove the stored credential

            </label>

          )}



          <label className="field">

            Timeout (seconds)

            <input

              type="number"

              min={1}

              max={120}

              value={timeout}

              onChange={(event) => setTimeoutValue(Number(event.target.value))}

              disabled={saving}

            />

            <small className="muted">

              The gateway may cap this with its own limits.

            </small>

          </label>



          <div className="modal-actions">

            <button

              className="button button-secondary"

              type="button"

              onClick={onClose}

              disabled={saving}

            >

              Cancel

            </button>

            <button

              className="button button-primary"

              type="submit"

              disabled={saving}

            >

              {saving

                ? isEdit

                  ? 'Saving…'

                  : 'Connecting…'

                : isEdit

                  ? 'Save changes'

                  : 'Add server'}

            </button>

          </div>

        </form>

      </div>

    </div>

  )

}



export default function ServersPage({ refreshTick }: { refreshTick: number }) {

  const [servers, setServers] = useState<ServerRow[]>([])

  const [loading, setLoading] = useState(true)

  const [checking, setChecking] = useState(false)

  const [busyName, setBusyName] = useState<string | null>(null)

  const [error, setError] = useState('')

  const [form, setForm] = useState<FormMode | null>(null)

  const [deleting, setDeleting] = useState<ServerRow | null>(null)

  const alive = useRef(true)



  useEffect(() => {

    alive.current = true

    return () => {

      alive.current = false

    }

  }, [])



  const load = useCallback(async (silent: boolean) => {

    if (!silent) setLoading(true)



    try {

      const [upstreamResult, statusResult, toolsResult] =

        await Promise.allSettled([

          api.upstreams(),

          api.upstreamStatus(),

          api.tools(),

        ])



      if (upstreamResult.status === 'rejected') throw upstreamResult.reason



      const liveByName = new Map(

        (statusResult.status === 'fulfilled'

          ? statusResult.value.upstreams

          : []

        ).map((item) => [item.name, item]),

      )



      const toolsByServer = new Map<string, string[]>()



      if (toolsResult.status === 'fulfilled') {

        for (const tool of toolsResult.value.tools) {

          toolsByServer.set(tool.upstream_server, [

            ...(toolsByServer.get(tool.upstream_server) ?? []),

            tool.upstream_tool,

          ])

        }

      }



      const rows: ServerRow[] = upstreamResult.value.upstreams.map((item) => {

        const live = liveByName.get(item.name)

        const enabled = live?.enabled ?? item.enabled



        return {

          name: item.name,

          url: item.url,

          enabled,

          status: deriveStatus(

            enabled,

            live?.status ?? item.connection_status,

          ),

          authMode: item.auth_mode ?? 'none',

          headerName: item.custom_header_name ?? '',

          timeout: item.timeout_seconds ?? 20,

          hasCredential: Boolean(item.hasCredential),

          lastError: live?.last_error ?? item.last_error ?? null,

          lastChecked: live?.last_checked_at ?? item.last_checked_at ?? null,

          tools: enabled ? (toolsByServer.get(item.name) ?? []) : [],

        }

      })



      if (alive.current) {

        setServers(sortServers(rows))

        setError('')

      }

    } catch (e) {

      if (alive.current) setError(errMsg(e, 'Could not load MCP servers.'))

    } finally {

      if (alive.current && !silent) setLoading(false)

    }

  }, [])



  // Initial load and manual refresh from the page header.

  useEffect(() => {

    void load(false)

  }, [load, refreshTick])



  // Auto-refresh status while the page is open.

  // Auto-refresh status while the page is open.
useEffect(() => {
  const id = window.setInterval(() => {
    if (!document.hidden) void load(true)
  }, SERVER_POLL_MS)

  return () => window.clearInterval(id)
}, [load])



  async function runAction(name: string, action: () => Promise<unknown>) {

    setBusyName(name)

    setError('')



    try {

      await action()

      await load(true)

    } catch (e) {

      if (alive.current) setError(errMsg(e, 'The request failed.'))

    } finally {

      if (alive.current) setBusyName(null)

    }

  }



  async function checkNow() {

    setChecking(true)

    setError('')



    try {

      await api.refreshTools()

      await load(true)

    } catch (e) {

      if (alive.current) setError(errMsg(e, 'Could not re-check servers.'))

    } finally {

      if (alive.current) setChecking(false)

    }

  }



  async function confirmDelete() {

    if (!deleting) return



    const target = deleting



    await runAction(target.name, () => api.deleteUpstream(target.name))

    setDeleting(null)

  }



  const connectedCount = servers.filter((s) => s.status === 'connected').length

  const unreachableCount = servers.filter(

    (s) => s.status === 'unreachable',

  ).length

  const disabledCount = servers.filter((s) => s.status === 'disabled').length



  return (

    <section className="panel data-panel">

      <div className="panel-heading">

        <div>

          <h3>MCP servers</h3>

          <p>

            {servers.length} registered · {connectedCount} connected ·{' '}

            {unreachableCount} unreachable · {disabledCount} disabled

          </p>

        </div>



        <div className="servers-toolbar">

          <span className="live-tag">AUTO-REFRESH {SERVER_POLL_MS / 1000}s</span>



          <button

            className="button button-secondary button-small"

            onClick={() => void checkNow()}

            disabled={checking}

          >

            <RefreshCw size={15} />

            {checking ? 'Checking…' : 'Check now'}

          </button>



          <button

            className="button button-primary button-small"

            onClick={() => setForm({ type: 'create' })}

          >

            <Plus size={15} />

            Add server

          </button>

        </div>

      </div>



      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}



      {loading ? (

        <p className="health-loading">Loading MCP servers…</p>

      ) : servers.length === 0 ? (

        <EmptyState message="No MCP servers registered yet. Use “Add server” to connect one." />

      ) : (

        <DataTable>

          <thead>

            <tr>

              <th>Server</th>

              <th>Endpoint</th>

              <th>Status</th>

              <th>Tools</th>

              <th>Credential</th>

              <th>Actions</th>

            </tr>

          </thead>

          <tbody>

            {servers.map((server) => {

              const credential = credentialLabel(server)

              const busy = busyName === server.name



              return (

                <tr key={server.name}>

                  <td>

                    <strong>{server.name}</strong>

                    {server.name.toLowerCase() === 'woocommerce' && (

                      <small className="table-subtitle">Primary store</small>

                    )}

                  </td>



                  <td className="cell-url">{server.url}</td>



                  <td>

                    <StatusBadge value={server.status} />

                    <small className="table-subtitle">

                      Checked {formatTime(server.lastChecked)}

                    </small>



                    {server.status === 'unreachable' && server.lastError && (

                      <details className="inline-error">

                        <summary>Error details</summary>

                        <p>{server.lastError}</p>

                      </details>

                    )}

                  </td>



                  <td>

                    {server.tools.length > 0 ? (

                      <details>

                        <summary>

                          {server.tools.length}{' '}

                          {server.tools.length === 1 ? 'tool' : 'tools'}

                        </summary>

                        <div className="chip-list">

                          {server.tools.map((tool) => (

                            <span className="chip" key={tool}>

                              {tool}

                            </span>

                          ))}

                        </div>

                      </details>

                    ) : (

                      <span className="muted">

                        {server.status === 'disabled'

                          ? 'Hidden while disabled'

                          : 'None'}

                      </span>

                    )}

                  </td>



                  <td>

                    <div>{credential.kind}</div>

                    {credential.state && (

                      <small className="table-subtitle">

                        {credential.state}

                      </small>

                    )}

                  </td>



                  <td>

                    <div className="row-actions">

                      <button

                        className="button button-secondary button-small"

                        onClick={() =>

                          void runAction(server.name, () =>

                            api.updateUpstream(server.name, {

                              enabled: !server.enabled,

                            }),

                          )

                        }

                        disabled={busy}

                        title={server.enabled ? 'Disable server' : 'Enable server'}

                      >

                        <Power size={14} />

                        {busy

                          ? 'Working…'

                          : server.enabled

                            ? 'Disable'

                            : 'Enable'}

                      </button>



                      <button

                        className="icon-button"

                        onClick={() => setForm({ type: 'edit', server })}

                        disabled={busy}

                        title="Edit server"

                        aria-label={`Edit ${server.name}`}

                      >

                        <Pencil size={16} />

                      </button>



                      <button

                        className="icon-button icon-danger"

                        onClick={() => setDeleting(server)}

                        disabled={busy}

                        title="Remove server"

                        aria-label={`Remove ${server.name}`}

                      >

                        <Trash2 size={16} />

                      </button>

                    </div>

                  </td>

                </tr>

              )

            })}

          </tbody>

        </DataTable>

      )}



      {form && (

        <ServerForm

          mode={form}

          onClose={() => setForm(null)}

          onSaved={() => load(true)}

        />

      )}



      {deleting && (

        <div

          className="modal-backdrop"

          onMouseDown={busyName ? undefined : () => setDeleting(null)}

        >

          <div

            className="modal modal-small"

            role="alertdialog"

            aria-modal="true"

            onMouseDown={(event) => event.stopPropagation()}

          >

            <div className="modal-header">

              <h3>Remove “{deleting.name}”?</h3>

            </div>



            <p>

              This removes the server and its {deleting.tools.length} tool

              {deleting.tools.length === 1 ? '' : 's'} from the gateway for

              everyone, including the chat agent and external MCP clients. The

              stored credential is deleted too. This cannot be undone.

            </p>



            <div className="modal-actions">

              <button

                className="button button-secondary"

                onClick={() => setDeleting(null)}

                disabled={busyName !== null}

              >

                Cancel

              </button>

              <button

                className="button button-danger"

                onClick={() => void confirmDelete()}

                disabled={busyName !== null}

              >

                {busyName ? 'Removing…' : 'Remove server'}

              </button>

            </div>

          </div>

        </div>

      )}

    </section>

  )

}



/* ------------------------------------------------------------------ */
