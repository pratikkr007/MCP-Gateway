import { useCallback, useEffect, useMemo, useState } from 'react'
import { RefreshCw, Search } from 'lucide-react'
import { api, type MemberTool } from './api'
import {
  CopyButton,
  EmptyState,
  ErrorBanner,
  errMsg,
  pretty,
  useAlive,
} from './interface'

type Param = {
  name: string
  type: string
  required: boolean
  description: string
}

function schemaParams(schema: Record<string, unknown> | undefined): Param[] {
  const properties = (schema?.properties ?? {}) as Record<string, any>
  const required = new Set<string>(
    Array.isArray(schema?.required) ? (schema?.required as string[]) : [],
  )

  return Object.entries(properties).map(([name, detail]) => {
    let type = 'any'

    if (typeof detail?.type === 'string') {
      type = detail.type
    } else if (Array.isArray(detail?.type)) {
      type = detail.type.join(' | ')
    } else if (Array.isArray(detail?.anyOf)) {
      type =
        detail.anyOf
          .map((item: any) => item?.type)
          .filter(Boolean)
          .join(' | ') || 'any'
    }

    return {
      name,
      type,
      required: required.has(name),
      description: String(detail?.description ?? detail?.title ?? ''),
    }
  })
}

export default function ToolsPage({ refreshTick }: { refreshTick: number }) {
  const alive = useAlive()
  const [tools, setTools] = useState<MemberTool[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')

  const load = useCallback(async () => {
    setLoading(true)

    try {
      const result = await api.myTools()

      if (alive.current) {
        setTools(result.tools)
        setError('')
      }
    } catch (e) {
      if (alive.current) setError(errMsg(e, 'Could not load tools.'))
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [alive])

  useEffect(() => {
    void load()
  }, [load, refreshTick])

  // Upstream tool names that exist on more than one server.
  const duplicates = useMemo(() => {
    const byName = new Map<string, Set<string>>()

    for (const tool of tools) {
      const servers = byName.get(tool.upstream_tool) ?? new Set<string>()
      servers.add(tool.upstream_server)
      byName.set(tool.upstream_tool, servers)
    }

    return [...byName.entries()]
      .filter(([, servers]) => servers.size > 1)
      .map(([name, servers]) => ({ name, servers: [...servers].sort() }))
  }, [tools])

  const duplicateNames = useMemo(
    () => new Set(duplicates.map((item) => item.name)),
    [duplicates],
  )

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const map = new Map<string, MemberTool[]>()

    for (const tool of tools) {
      const haystack =
        `${tool.gateway_name} ${tool.upstream_tool} ${tool.description ?? ''}`.toLowerCase()

      if (needle && !haystack.includes(needle)) continue

      map.set(tool.upstream_server, [
        ...(map.get(tool.upstream_server) ?? []),
        tool,
      ])
    }

    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [tools, query])

  const exampleTool = tools[0]
  const visibleCount = groups.reduce((sum, [, list]) => sum + list.length, 0)

  return (
    <section className="panel data-panel">
      <div className="panel-heading">
        <div>
          <h3>Available tools</h3>
          <p>
            {tools.length} {tools.length === 1 ? 'tool' : 'tools'} from{' '}
            {new Set(tools.map((tool) => tool.upstream_server)).size} enabled
            server(s). Tools from disabled servers are hidden.
          </p>
        </div>

        <div className="servers-toolbar">
          <button
            className="button button-secondary button-small"
            onClick={() => void load()}
            disabled={loading}
          >
            <RefreshCw size={15} />
            {loading ? 'Loading…' : 'Reload'}
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}

      <div className="info-box">
        <strong>How tool names are made unique</strong>
        <p>
          Every tool is exposed through the gateway as{' '}
          <code className="mono">&lt;server&gt;__&lt;tool&gt;</code> (server
          name, two underscores, tool name). Characters other than letters,
          digits and underscores are replaced with <code>_</code>. Two servers
          can therefore each have a tool called{' '}
          <code className="mono">{exampleTool?.upstream_tool ?? 'search'}</code>{' '}
          without clashing
          {exampleTool && (
            <>
              : this one is exposed as{' '}
              <code className="mono">{exampleTool.gateway_name}</code>
            </>
          )}
          . Always call the full gateway name from an MCP client.
        </p>

        {duplicates.length > 0 && (
          <p>
            <strong>Same upstream name on several servers:</strong>{' '}
            {duplicates.map((item) => (
              <span className="chip" key={item.name}>
                {item.name} → {item.servers.join(', ')}
              </span>
            ))}
          </p>
        )}
      </div>

      <div className="tool-search">
        <Search size={16} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search by tool name or description…"
          aria-label="Search tools"
        />
      </div>

      {loading && tools.length === 0 ? (
        <p className="health-loading">Loading tools…</p>
      ) : tools.length === 0 ? (
        <EmptyState message="No tools available. An admin needs to register and enable an MCP server." />
      ) : visibleCount === 0 ? (
        <EmptyState message="No tools match your search." />
      ) : (
        <div className="resource-cards">
          {groups.map(([server, serverTools]) => (
            <section className="resource-card" key={server}>
              <div className="resource-card-heading">
                <h3>{server}</h3>
                <span>
                  {serverTools.length}{' '}
                  {serverTools.length === 1 ? 'tool' : 'tools'}
                </span>
              </div>

              {serverTools.map((tool) => {
                const params = schemaParams(tool.input_schema)

                return (
                  <details className="tool-item" key={tool.gateway_name}>
                    <summary>
                      <span>
                        <strong>{tool.gateway_name}</strong>
                        <small>
                          upstream name: {tool.upstream_tool}
                          {duplicateNames.has(tool.upstream_tool) &&
                            ' · also on another server'}
                        </small>
                      </span>
                      <span className="tool-expand">View details</span>
                    </summary>

                    <div className="tool-details">
                      <p>
                        {tool.description ??
                          'No description provided by this server.'}
                      </p>

                      <p>
                        <strong>Gateway name:</strong>{' '}
                        <code className="mono">{tool.gateway_name}</code>{' '}
                        <CopyButton text={tool.gateway_name} />
                      </p>

                      <p>
                        <strong>Routed to:</strong> {server} →{' '}
                        <code className="mono">{tool.upstream_tool}</code>
                      </p>

                      <p>
                        <strong>Parameters</strong>
                      </p>

                      {params.length === 0 ? (
                        <p className="muted">This tool takes no parameters.</p>
                      ) : (
                        <div className="table-wrap">
                          <table className="data-table schema-table">
                            <thead>
                              <tr>
                                <th>Name</th>
                                <th>Type</th>
                                <th>Required</th>
                                <th>Description</th>
                              </tr>
                            </thead>
                            <tbody>
                              {params.map((param) => (
                                <tr key={param.name}>
                                  <td>
                                    <code className="mono">{param.name}</code>
                                  </td>
                                  <td>{param.type}</td>
                                  <td>{param.required ? 'Yes' : 'No'}</td>
                                  <td>{param.description || '—'}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}

                      <details className="schema-raw">
                        <summary>Raw input schema (JSON)</summary>
                        <pre>{pretty(tool.input_schema ?? {})}</pre>
                      </details>
                    </div>
                  </details>
                )
              })}
            </section>
          ))}
        </div>
      )}
    </section>
  )
}