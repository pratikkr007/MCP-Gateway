import { useEffect, useState } from 'react'

import type { FormEvent } from 'react'

import {

  Activity,

  Bot,

  Boxes,


  Command,

  KeyRound,

  LayoutDashboard,

  Lock,

  LogOut,

  Menu,

  MessageSquare,


  Plus,


  RefreshCw,

  ScrollText,

  Server,

  ShieldCheck,


  Users,

  X,

} from 'lucide-react'

import {

  api,

  getAuth,

  setAuth,

  setUnauthorizedHandler,


} from './api'

import ServersPage from './ServersPage'
import { DataTable, EmptyState, ErrorBanner, StatusBadge } from './interface'
import PermissionsPage from './PermissionsPage'
import './App.css'



type Page =

  | 'Overview'

  | 'MCP Servers'

  | 'Tools'

  | 'AI Chat'

  | 'Team & API Keys'

  | 'Tool Permissions'

  | 'Audit Logs'



type RecordData = Record<string, any>



type ToolCallInfo = {

  tool: string

  arguments?: Record<string, unknown>

  result?: string

  error?: string

  isError?: boolean

}



type ChatMessage = {

  role: string

  content: string

  toolCalls?: ToolCallInfo[]

}



type UserRole = 'admin' | 'member'



type UserProfile = {

  name: string

  username: string

  role: UserRole

  user_id: string

  email: string

}



const navigation: { label: Page; icon: typeof LayoutDashboard }[] = [

  { label: 'Overview', icon: LayoutDashboard },

  { label: 'MCP Servers', icon: Server },

  { label: 'Tools', icon: Boxes },

  { label: 'AI Chat', icon: MessageSquare },

  { label: 'Team & API Keys', icon: Users },

  { label: 'Tool Permissions', icon: Lock },

  { label: 'Audit Logs', icon: ScrollText },

]



// /admin/* endpoints return 403 for members, so these pages are admin-only.

const ADMIN_ONLY_PAGES: Page[] = [

  'MCP Servers',

  'Team & API Keys',

  'Tool Permissions',

  'Audit Logs',

]





function errMsg(error: unknown, fallback: string): string {

  return error instanceof Error ? error.message : fallback

}



function pretty(value: unknown): string {

  return JSON.stringify(value, null, 2) ?? 'No data returned'

}



function asRecord(value: unknown): RecordData {

  if (value && typeof value === 'object' && !Array.isArray(value)) {

    return value as RecordData

  }

  return {}

}



function asArray(value: unknown): RecordData[] {

  if (Array.isArray(value)) {

    return value.filter(

      (item) => item !== null && typeof item === 'object',

    ) as RecordData[]

  }



  const record = asRecord(value)



  for (const item of Object.values(record)) {

    if (Array.isArray(item)) {

      return item.filter(

        (entry) => entry !== null && typeof entry === 'object',

      ) as RecordData[]

    }

  }



  return []

}



function normalizeRole(value: unknown): UserRole {

  return String(value ?? '').trim().toLowerCase() === 'admin'

    ? 'admin'

    : 'member'

}



function parseUserProfile(value: unknown): UserProfile {

  const response = asRecord(value)

  const record = asRecord(response.user ?? response.profile ?? response)



  const username = String(

    record.username ??

      record.name ??

      record.full_name ??

      record.email ??

      'Gateway user',

  )



  return {

    username,

    name: String(

      record.name ??

        record.full_name ??

        record.username ??

        record.email ??

        username,

    ),

    role: normalizeRole(record.role),

    user_id: String(record.user_id ?? record.id ?? ''),

    email: String(record.email ?? ''),

  }

}


function formatAgentResponse(value: unknown): string {
  let result = value

  if (typeof result === 'string') {
    const original = result

    try {
      result = JSON.parse(result)
    } catch {
      return original
    }
  }

  const response = asRecord(result)

  if (typeof response.answer === 'string') {
    return response.answer
  }

  if (typeof response.message === 'string') {
    return response.message
  }

  if (response.result !== undefined) {
    return formatAgentResponse(response.result)
  }

  if (typeof response.content === 'string') {
    return response.content
  }

  return typeof result === 'string' ? result : pretty(result)
}

/** Pull the list of tools the agent called out of the /api/chat response. */
function extractToolCalls(value: unknown): ToolCallInfo[] {
  let result = value

  if (typeof result === 'string') {
    try {
      result = JSON.parse(result)
    } catch {
      return []
    }
  }

  const calls = asRecord(result).tool_calls

  if (!Array.isArray(calls)) return []

  return calls
    .filter((item) => item !== null && typeof item === 'object')
    .map((item) => {
      const call = item as RecordData

      return {
        tool: String(call.tool ?? 'unknown tool'),
        arguments:
          call.arguments && typeof call.arguments === 'object'
            ? (call.arguments as Record<string, unknown>)
            : undefined,
        result: typeof call.result === 'string' ? call.result : undefined,
        error: typeof call.error === 'string' ? call.error : undefined,
        isError: Boolean(call.isError),
      }
    })
}

/* ------------------------------------------------------------------ */

/* MCP Servers page (admin)                                            */

/* ------------------------------------------------------------------ */



/* Read-only tables for the other admin pages                          */

/* ------------------------------------------------------------------ */



function ResourceTable({
  page,
  data,
  onAddMember,
  onIssueKey,
  onRevokeKey,
}: {
  page: Page
  data: unknown
  onAddMember: () => void
  onIssueKey: (userId: string, username: string) => void
  onRevokeKey: (keyId: number, label: string) => void
}) {

  const record = asRecord(data)



  if (page === 'Tools') {

    const tools = asArray(record.tools ?? data)



    if (tools.length === 0) {

      return (

        <EmptyState message="No tools discovered yet. Verify that your MCP servers are running." />

      )

    }



    const groups = new Map<string, RecordData[]>()



    tools.forEach((tool) => {

      const server = String(

        tool.upstream_server ?? tool.server ?? 'Unknown server',

      )



      groups.set(server, [...(groups.get(server) ?? []), tool])

    })



    return (

      <div className="resource-cards">

        {[...groups.entries()].map(([server, serverTools]) => (

          <section className="resource-card" key={server}>

            <div className="resource-card-heading">

              <h3>{server}</h3>

              <span>

                {serverTools.length}{' '}

                {serverTools.length === 1 ? 'tool' : 'tools'}

              </span>

            </div>



            {serverTools.map((tool, index) => {

              const name = String(

                tool.gateway_name ?? tool.name ?? `Tool ${index + 1}`,

              )



              return (

                <details

                  className="tool-item"

                  key={`${server}-${name}-${index}`}

                >

                  <summary>

                    <span>

                      <strong>{name}</strong>

                      <small>

                        {String(tool.upstream_tool ?? tool.name ?? '')}

                      </small>

                    </span>

                    <span className="tool-expand">View details</span>

                  </summary>



                  <div className="tool-details">

                    <p>

                      {String(

                        tool.description ??

                          'No description provided by this server.',

                      )}

                    </p>



                    <p>

                      <strong>Gateway name:</strong> {name}

                    </p>



                    <p>

                      <strong>Upstream server:</strong> {server}

                    </p>



                    <p>

                      <strong>Upstream tool:</strong>{' '}

                      {String(tool.upstream_tool ?? tool.name ?? '—')}

                    </p>



                    <p>

                      <strong>Input schema</strong>

                    </p>



                    <pre>

                      {pretty(tool.input_schema ?? tool.inputSchema ?? {})}

                    </pre>

                  </div>

                </details>

              )

            })}

          </section>

        ))}

      </div>

    )

  }



  if (page === 'Audit Logs') {

    const events = asArray(

      record.audit ?? record.logs ?? record.events ?? data,

    )



    if (events.length === 0) {

      return <EmptyState message="No audit events found for this query." />

    }



    return (

      <DataTable>

        <thead>

          <tr>

            <th>Time</th>

            <th>User</th>

            <th>Server</th>

            <th>Tool</th>

            <th>Duration</th>

            <th>Outcome</th>

          </tr>

        </thead>



        <tbody>

          {events.map((event, index) => {

            const outcome = String(

              event.outcome ?? event.status ?? 'unknown',

            ).toLowerCase()



            const failed = ['failed', 'failure', 'error', 'fail'].includes(outcome)

            const displayedOutcome =
              outcome === 'denied' ? 'denied' : failed ? 'failed' : outcome



            return (

              <tr key={String(event.id ?? index)}>

                <td>

                  {String(

                    event.timestamp ??

                      event.started_at ??

                      event.created_at ??

                      '—',

                  )}

                </td>

                <td>{String(event.username ?? event.user_id ?? '—')}</td>

                <td>{String(event.server_name ?? '—')}</td>

                <td>{String(event.tool_name ?? '—')}</td>

                <td>

                  {event.duration_ms == null ? '—' : `${event.duration_ms} ms`}

                </td>

                <td>

                  <StatusBadge value={displayedOutcome} />



                  {event.error_message && (

                    <details className="inline-error">

                      <summary>Error details</summary>

                      <p>{String(event.error_message)}</p>

                    </details>

                  )}

                </td>

              </tr>

            )

          })}

        </tbody>

      </DataTable>

    )

  }



  if (page === 'Team & API Keys') {

    const identity = record

    const users = asArray(record.users)

    const keys = asArray(record.keys ?? record.api_keys)



    return (

      <div className="resource-cards">

        <section className="resource-card identity-card">

          <div className="resource-card-heading">

            <h3>Signed-in account</h3>

            <ShieldCheck size={20} />

          </div>



          <p>

            <strong>Username:</strong>{' '}

            {String(identity.username ?? identity.name ?? '—')}

          </p>



          <p>

            <strong>Role:</strong> {String(identity.role ?? '—')}

          </p>



          <p>

            <strong>User ID:</strong>{' '}

            {String(identity.user_id ?? identity.id ?? '—')}

          </p>

        </section>



        <section className="resource-card">
          <div className="resource-card-heading">
            <h3>Team members</h3>
            <div className="resource-card-actions">
              <button className="button button-primary" type="button" onClick={onAddMember}>
                <Plus size={16} /> Add Member
              </button>
              <Users size={19} />
            </div>
          </div>
          {users.length > 0 ? (
            <DataTable>
              <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Actions</th></tr></thead>
              <tbody>
                {users.map((user, index) => {
                  const userId = String(user.user_id ?? user.id ?? '')
                  const username = String(user.username ?? user.name ?? 'member')
                  return (
                    <tr key={userId || index}>
                      <td>{username}</td>
                      <td>{String(user.email ?? '—')}</td>
                      <td><StatusBadge value={user.role ?? 'member'} /></td>
                      <td>
                        <button className="button button-secondary" type="button" disabled={!userId} onClick={() => onIssueKey(userId, username)}>
                          <KeyRound size={15} /> Issue key
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </DataTable>
          ) : (
            <EmptyState message="No team members found. Refresh the page or add a member." />
          )}
        </section>

        <section className="resource-card">
          <div className="resource-card-heading">
            <h3>API keys</h3>
            <KeyRound size={19} />
          </div>
          {keys.length > 0 ? (
            <DataTable>
              <thead><tr><th>Label</th><th>Owner</th><th>Created</th><th>Status</th><th>Actions</th></tr></thead>
              <tbody>
                {keys.map((key, index) => {
                  const keyId = Number(key.key_id ?? key.id)
                  const revoked = Number(key.revoked) === 1 || Boolean(key.revoked_at)
                  return (
                    <tr key={String(key.key_id ?? key.id ?? index)}>
                      <td>{String(key.label ?? key.name ?? 'API key')}</td>
                      <td>{String(key.username ?? key.owner ?? '—')}</td>
                      <td>{String(key.created_at ?? '—')}</td>
                      <td><StatusBadge value={revoked ? 'revoked' : key.active === false ? 'disabled' : (key.status ?? 'active')} /></td>
                      <td>{revoked ? <span>—</span> : <button className="button button-secondary" type="button" disabled={!Number.isFinite(keyId)} onClick={() => onRevokeKey(keyId, String(key.label ?? 'API key'))}>Revoke</button>}</td>
                    </tr>
                  )
                })}
              </tbody>
            </DataTable>
          ) : (
            <EmptyState message="No API keys found. Issue a key for a team member to get started." />
          )}
        </section>

      </div>

    )

  }



  return <EmptyState message="No data to display." />

}



/* ------------------------------------------------------------------ */

/* App                                                                 */

/* ------------------------------------------------------------------ */



function App() {

  const [page, setPage] = useState<Page>('Overview')

  const [credential, setCredential] = useState('')

  const [connected, setConnected] = useState(false)

  const [error, setError] = useState('')

  const [loading, setLoading] = useState(false)

  const [data, setData] = useState<unknown>(null)

  const [chat, setChat] = useState('')

  const [messages, setMessages] = useState<ChatMessage[]>([])

  const [mobileOpen, setMobileOpen] = useState(false)

  const [user, setUser] = useState<UserProfile | null>(null)

  const [refreshTick, setRefreshTick] = useState(0)
  const [teamActionLoading, setTeamActionLoading] = useState(false)
  const [teamNotice, setTeamNotice] = useState('')



  const isAdmin = user?.role === 'admin'



  // Members only see Overview and AI Chat.

  const visibleNavigation = navigation.filter(

    ({ label }) => !ADMIN_ONLY_PAGES.includes(label) || isAdmin,

  )



  // Render-time guard: a member can never see an admin page,

  // even if page state is changed some other way.

  const activePage: Page =

    ADMIN_ONLY_PAGES.includes(page) && !isAdmin ? 'Overview' : page



  function signOut(message = '') {

    setAuth({ mode: 'api-key', credential: '' })

    setCredential('')

    setConnected(false)

    setData(null)

    setUser(null)

    setError(message)

    setMessages([])

    setPage('Overview')

    setMobileOpen(false)

  }



  // If any request is rejected with 401 (revoked or invalid key), sign out.

  useEffect(() => {

    setUnauthorizedHandler(() =>

      signOut('Your API key is invalid or has been revoked. Please sign in again.'),

    )



    return () => setUnauthorizedHandler(null)

  }, [])



  async function loadPage(target: Page = page) {

    if (!getAuth().credential) {

      signOut()

      return

    }



    setLoading(true)

    setError('')



    // 1) Always re-read identity and role. A failure here means auth is bad.

    let profile: UserProfile

    let profileResponse: Record<string, unknown>



    try {

      profileResponse = await api.me()

      profile = parseUserProfile(profileResponse)

      setUser(profile)

    } catch (e) {

      setLoading(false)

      signOut(errMsg(e, 'Authentication failed'))

      return

    }



    // 2) Block admin pages for members.

    if (ADMIN_ONLY_PAGES.includes(target) && profile.role !== 'admin') {

      setLoading(false)

      setPage('Overview')

      return

    }



    // 3) Load page data. A failure here keeps the user signed in.

    try {

      let result: unknown = null



      switch (target) {

        case 'Overview':

          result = await api.health()

          break



        case 'MCP Servers':

        case 'Tool Permissions':

          // These pages fetch their own data; just ask them to reload.

          setRefreshTick((tick) => tick + 1)

          break



        case 'Tools':

          result = await api.myTools()

          break





        case 'AI Chat':

          result = {

            message: 'Enter a message below to chat with the gateway agent.',

          }

          break



        case 'Team & API Keys': {
          const [usersResponse, keysResponse] = await Promise.all([api.listUsers(), api.adminKeys()])
          result = { ...profileResponse, users: usersResponse.users ?? [], keys: keysResponse.keys ?? [] }
          break
        }



        case 'Audit Logs':

          result = await api.audit()

          break

      }



      setData(result)

    } catch (e) {

      setError(errMsg(e, 'Request failed'))

      setData(null)

    } finally {

      setLoading(false)

    }

  }



  // Load when the page changes or right after a successful sign-in.

  useEffect(() => {

    if (connected) {

      void loadPage(page)

    }



    // eslint-disable-next-line react-hooks/exhaustive-deps

  }, [page, connected])



  async function connect() {

    const apiKey = credential.trim()



    if (!apiKey) {

      setError('Enter a registered individual API key.')

      return

    }



    setLoading(true)

    setError('')

    setConnected(false)

    setData(null)

    setUser(null)



    setAuth({ mode: 'api-key', credential: apiKey })



    try {

      const profile = parseUserProfile(await api.me())



      setUser(profile)



      // Members must not start on an admin-only page.

      if (profile.role !== 'admin' && ADMIN_ONLY_PAGES.includes(page)) {

        setPage('Overview')

      }



      // The effect above loads the page once `connected` flips to true.

      setConnected(true)

    } catch (e) {

      setAuth({ mode: 'api-key', credential: '' })

      setConnected(false)

      setData(null)

      setUser(null)

      setError(errMsg(e, 'Authentication failed'))

    } finally {

      setLoading(false)

    }

  }



  async function addTeamMember() {
    const username = window.prompt('Enter a username for the new member:')?.trim()
    if (!username) return
    const email = window.prompt('Enter the member email (optional):')?.trim() ?? ''
    setTeamActionLoading(true)
    setError('')
    setTeamNotice('')
    try {
      const created = await api.createUser({ username, email: email || undefined, role: 'member' })
      setTeamNotice(`Member "${created.username ?? username}" created successfully.`)
      await loadPage('Team & API Keys')
    } catch (e) {
      setError(errMsg(e, 'Could not create member'))
    } finally {
      setTeamActionLoading(false)
    }
  }

  async function issueTeamKey(userId: string, username: string) {
    const label = window.prompt(`Enter a label for ${username}'s API key:`, `${username}-key`)?.trim()
    if (!label) return
    setTeamActionLoading(true)
    setError('')
    setTeamNotice('')
    try {
      const issued = await api.createKey(userId, label)
      window.prompt('API key created. Copy it now; it cannot be displayed again:', issued.api_key)
      setTeamNotice(`API key "${issued.label ?? label}" issued to ${username}. Copy it from the prompt if you have not already.`)
      await loadPage('Team & API Keys')
    } catch (e) {
      setError(errMsg(e, 'Could not issue API key'))
    } finally {
      setTeamActionLoading(false)
    }
  }

  async function revokeTeamKey(keyId: number, label: string) {
    if (!window.confirm(`Revoke API key "${label}"? Any client using it will lose access.`)) return
    setTeamActionLoading(true)
    setError('')
    setTeamNotice('')
    try {
      await api.revokeKey(keyId)
      setTeamNotice(`API key "${label}" revoked.`)
      await loadPage('Team & API Keys')
    } catch (e) {
      setError(errMsg(e, 'Could not revoke API key'))
    } finally {
      setTeamActionLoading(false)
    }
  }

  async function sendChat(event: FormEvent) {

    event.preventDefault()



    if (!chat.trim() || loading) return



    const message = chat.trim()



    // Send recent turns so the agent remembers the conversation.

    const history = messages.slice(-12).map((item) => ({

      role: item.role === 'You' ? 'user' : 'assistant',

      content: item.content,

    }))



    setMessages((old) => [...old, { role: 'You', content: message }])

    setChat('')

    setLoading(true)

    setError('')



    try {

      const result = await api.chat(message, history)



      setMessages((old) => [

        ...old,

        {

          role: 'Agent',

          content: formatAgentResponse(result),

          toolCalls: extractToolCalls(result),

        },

      ])

    } catch (e) {

      setError(errMsg(e, 'Chat failed'))

    } finally {

      setLoading(false)

    }

  }



  const health = asRecord(data)

  const displayName = user?.name ?? user?.username ?? 'Gateway user'



  return (

    <div className="app-shell">

      <aside className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}>

        <div className="brand">

          <div className="brand-mark">

            <Command size={22} />

          </div>



          <div>

            <strong>Team Gateway</strong>

            <span>MCP CONTROL PLANE</span>

          </div>



          <button

            className="icon-button mobile-close"

            onClick={() => setMobileOpen(false)}

            aria-label="Close menu"

          >

            <X />

          </button>

        </div>



        <div className="workspace-label">WORKSPACE</div>



        <div className="workspace">

          <div className="workspace-avatar">T</div>

          <div>

            <strong>Team workspace</strong>

            <span>Local environment</span>

          </div>

        </div>



        <nav>

          {visibleNavigation.map(({ label, icon: Icon }) => (

            <button

              key={label}

              className={`nav-item ${activePage === label ? 'nav-active' : ''}`}

              onClick={() => {

                if (ADMIN_ONLY_PAGES.includes(label) && !isAdmin) {

                  setError('Access denied. Admin privileges are required.')

                  setPage('Overview')

                  setMobileOpen(false)

                  return

                }



                setPage(label)

                setMobileOpen(false)

              }}

            >

              <Icon size={18} />

              <span>{label}</span>

              {label === 'AI Chat' && <span className="nav-dot" />}

            </button>

          ))}

        </nav>



        <div className="sidebar-bottom">

          <div className="connection-mini">

            <span className={`status-dot ${connected ? 'online' : ''}`} />

            {connected ? 'Gateway connected' : 'Not connected'}

          </div>



          <button

            className="nav-item"

            onClick={() => void loadPage(page)}

            disabled={loading || !connected}

          >

            <RefreshCw size={18} />

            <span>Refresh current page</span>

          </button>



          <div className="profile">

            <div className="profile-avatar">

              {connected && user ? (

                displayName.charAt(0).toUpperCase()

              ) : (

                <ShieldCheck size={18} />

              )}

            </div>



            <div>

              <strong>{connected ? displayName : 'Signed out'}</strong>



              <span>

                {connected && user

                  ? `${user.role === 'admin' ? 'Admin' : 'Member'} · Authenticated`

                  : 'Signed out'}

              </span>

            </div>



            <button

              className="icon-button"

              onClick={() => signOut()}

              title="Disconnect"

              aria-label="Disconnect"

            >

              <LogOut size={17} />

            </button>

          </div>

        </div>

      </aside>



      {mobileOpen && (

        <button

          className="mobile-backdrop"

          onClick={() => setMobileOpen(false)}

          aria-label="Close navigation"

        />

      )}



      <main className="main-panel">

        <header className="topbar">

          <button

            className="icon-button mobile-menu"

            onClick={() => setMobileOpen(true)}

            aria-label="Open menu"

          >

            <Menu />

          </button>



          <div className="breadcrumbs">

            <span>Workspace</span>

            <span>/</span>

            <strong>{activePage}</strong>

          </div>



          <div className="topbar-right">

            <span className="environment-pill">

              <span />

              LOCAL DEV

            </span>



            <button

              className="icon-button"

              onClick={() => void loadPage(page)}

              title="Refresh"

              aria-label="Refresh"

              disabled={loading || !connected}

            >

              <RefreshCw size={18} />

            </button>

          </div>

        </header>



        <div className="page-content">

          <div className="page-heading">

            <div>

              <div className="eyebrow">TEAM MCP GATEWAY</div>

              <h1>{activePage}</h1>

              <p>

                {activePage === 'Overview'

                  ? 'Monitor your MCP infrastructure from one place.'

                  : `Manage and inspect ${activePage.toLowerCase()} for your workspace.`}

              </p>

            </div>



            <button

              className="button button-secondary"

              onClick={() => void loadPage(page)}

              disabled={loading || !connected}

            >

              <RefreshCw size={16} />

              Refresh

            </button>

          </div>



          {!getAuth().credential || !connected ? (

            <section className="panel auth-panel">

              <div className="auth-icon">

                <KeyRound size={25} />

              </div>



              <h2>Connect to your gateway</h2>



              <p>

                Sign in with a registered individual API key. The admin

                bootstrap token is for initial administration, not a normal

                dashboard user session.

              </p>



              {error && (

                <ErrorBanner message={error} onDismiss={() => setError('')} />

              )}



              <form

                onSubmit={(event) => {

                  event.preventDefault()

                  void connect()

                }}

                className="auth-form"

              >

                <label>

                  Individual API key

                  <input

                    type="password"

                    value={credential}

                    onChange={(event) => setCredential(event.target.value)}

                    placeholder="Paste your registered API key"

                    autoComplete="off"

                    required

                  />

                </label>



                <button

                  className="button button-primary"

                  disabled={loading}

                  type="submit"

                >

                  <ShieldCheck size={17} />

                  {loading ? 'Validating…' : 'Connect securely'}

                </button>

              </form>



              <small>

                The key is held in memory for this browser session and is

                validated against a protected endpoint before the dashboard

                opens.

              </small>

            </section>

          ) : (

            <>

              {error && (

                <ErrorBanner message={error} onDismiss={() => setError('')} />

              )}



              {activePage === 'Overview' ? (

                <div className="overview-grid">

                  <section className="welcome-card">

                    <div className="welcome-copy">

                      <span className="welcome-label">

                        <Activity size={15} />

                        GATEWAY STATUS

                      </span>



                      <h2>

                        Your MCP workspace,

                        <br />

                        all in one place.

                      </h2>



                      <p>

                        Manage upstream servers, discover tools, and interact

                        with your AI agent.

                      </p>



                      {isAdmin && (

                        <button

                          className="button button-light"

                          onClick={() => setPage('MCP Servers')}

                        >

                          Explore servers <Server size={16} />

                        </button>

                      )}

                    </div>



                    <div className="welcome-art">

                      <div className="orbit orbit-one" />

                      <div className="orbit orbit-two" />

                      <div className="orbit-core">

                        <Command size={34} />

                      </div>

                      <div className="orbit-node node-one">

                        <Server size={18} />

                      </div>

                      <div className="orbit-node node-two">

                        <Bot size={18} />

                      </div>

                      <div className="orbit-node node-three">

                        <Boxes size={18} />

                      </div>

                    </div>

                  </section>



                  <section className="stat-card">

                    <div className="stat-top">

                      <span>Gateway health</span>

                      <Activity size={18} />

                    </div>



                    <div className="stat-value">

                      {health.status

                        ? String(health.status).toLowerCase() === 'healthy'

                          ? 'Reachable'

                          : String(health.status)

                        : 'Unknown'}

                    </div>



                    <div className="stat-foot">

                      <span

                        className={`status-dot ${connected ? 'online' : ''}`}

                      />

                      {connected

                        ? 'Authenticated; health endpoint responded'

                        : 'Connect to check health'}

                    </div>

                  </section>



                  <section className="stat-card">

                    <div className="stat-top">

                      <span>Signed in as</span>

                      <ShieldCheck size={18} />

                    </div>



                    <div className="stat-value">{displayName}</div>

                    <div className="stat-foot">

                      {isAdmin ? 'Admin role' : 'Member role'}

                    </div>

                  </section>



                  <section className="panel data-panel">

                    <div className="panel-heading">

                      <div>

                        <h3>Gateway health</h3>

                        <p>Current status and registered tools</p>

                      </div>

                      <span className="live-tag">LIVE DATA</span>

                    </div>



                    {loading ? (

                      <p className="health-loading">

                        Checking gateway health…

                      </p>

                    ) : (

                      <div className="health-summary">

                        <div className="health-status-row">

                          <div className="health-status-icon">

                            <Activity size={24} />

                          </div>



                          <div className="health-status-info">

                            <strong className="health-status-title">

                              {String(health.status ?? 'Unknown')}

                            </strong>

                            <p>Gateway service status</p>

                          </div>



                          <StatusBadge value={health.status ?? 'unknown'} />

                        </div>



                        <div className="health-metrics">

                          <div className="health-metric">

                            <span>Service</span>

                            <strong>{String(health.service ?? '—')}</strong>

                          </div>



                          <div className="health-metric">

                            <span>Registered tools</span>

                            <strong>

                              {health.registered_tools == null

                                ? '—'

                                : String(health.registered_tools)}

                            </strong>

                          </div>

                        </div>

                      </div>

                    )}

                  </section>



                  <section className="quick-actions">

                    <h3>Quick actions</h3>



                    {visibleNavigation

                      .filter((item) => item.label !== 'Overview')

                      .map(({ label, icon: Icon }) => (

                        <button

                          key={label}

                          className="quick-action"

                          onClick={() => setPage(label)}

                        >

                          <span className="quick-icon">

                            <Icon size={18} />

                          </span>

                          <span>{label}</span>

                          <Plus size={16} />

                        </button>

                      ))}

                  </section>

                </div>

              ) : activePage === 'MCP Servers' ? (

                <ServersPage refreshTick={refreshTick} />

              ) : activePage === 'Tool Permissions' ? (

                <PermissionsPage refreshTick={refreshTick} />

              ) : activePage === 'AI Chat' ? (

                <section className="panel chat-panel">

                  <div className="panel-heading">

                    <div>

                      <h3>

                        <Bot size={19} /> Gateway AI assistant

                      </h3>

                      <p>Send a message to the configured chat agent.</p>

                    </div>

                    <span className="live-tag">CONNECTED</span>

                  </div>



                  <div className="chat-messages">

                    {messages.length === 0 && (

                      <div className="chat-empty">

                        <div className="auth-icon">

                          <MessageSquare size={24} />

                        </div>

                        <h3>What would you like to do?</h3>

                        <p>

                          Ask about products, orders, inventory, or your

                          connected MCP tools.

                        </p>

                      </div>

                    )}



                    {messages.map((item, index) => (

                      <div

                        className={`chat-message ${

                          item.role === 'You' ? 'chat-user' : 'chat-agent'

                        }`}

                        key={`${item.role}-${index}`}

                      >

                        <strong>{item.role}</strong>



                        {item.toolCalls && item.toolCalls.length > 0 && (

                          <details className="tool-item">

                            <summary>

                              <span>

                                <strong>

                                  Tools called ({item.toolCalls.length})

                                </strong>

                                <small>

                                  {item.toolCalls

                                    .map((call) => call.tool)

                                    .join(', ')}

                                </small>

                              </span>

                              <span className="tool-expand">View details</span>

                            </summary>



                            <div className="tool-details">

                              {item.toolCalls.map((call, callIndex) => (

                                <div key={`${call.tool}-${callIndex}`}>

                                  <p>

                                    <strong>{call.tool}</strong>{' '}

                                    {call.error || call.isError

                                      ? '(failed)'

                                      : '(ok)'}

                                  </p>

                                  <pre>{pretty(call.arguments ?? {})}</pre>

                                  {(call.error || call.result) && (

                                    <pre>{call.error ?? call.result}</pre>

                                  )}

                                </div>

                              ))}

                            </div>

                          </details>

                        )}



                        <pre>{item.content}</pre>

                      </div>

                    ))}



                    {loading && (

                      <div className="chat-message chat-agent">

                        <strong>Agent</strong>

                        <p className="chat-thinking">Thinking…</p>

                      </div>

                    )}

                  </div>



                  <form className="chat-form" onSubmit={sendChat}>

                    <input

                      value={chat}

                      onChange={(event) => setChat(event.target.value)}

                      placeholder="Ask the gateway to do something…"

                      aria-label="Message to the gateway agent"

                    />



                    <button

                      className="button button-primary"

                      disabled={loading || !chat.trim()}

                      type="submit"

                    >

                      <MessageSquare size={17} />

                      Send

                    </button>

                  </form>

                </section>

              ) : (

                              
              <section className="panel data-panel">
                <div className="panel-heading">
                  <div>
                    <h3>{activePage}</h3>
                    <p>
                      {activePage === 'Tools' &&
                        'Tools grouped by their MCP server'}
                      {activePage === 'Audit Logs' &&
                        'Recent gateway tool-call activity'}
                      {activePage === 'Team & API Keys' &&
                        'Account, team members and API-key status'}
                    </p>
                  </div>

                  <span className="live-tag">LIVE DATA</span>
                </div>

                {activePage === 'Team & API Keys' && teamNotice && (
                  <p className="success-message" role="status">
                    {teamNotice}
                  </p>
                )}

                {activePage === 'Team & API Keys' && error && (
                  <p className="error-message" role="alert">
                    {error}
                  </p>
                )}

                {loading ? (
                  <p className="health-loading">Loading data...</p>
                ) : (
                  <>
                    {activePage === 'Team & API Keys' && teamActionLoading && (
                      <p role="status">Processing team action...</p>
                    )}

                    <ResourceTable
                      page={activePage}
                      data={data}
                      onAddMember={() => void addTeamMember()}
                      onIssueKey={(userId, username) =>
                        void issueTeamKey(userId, username)
                      }
                      onRevokeKey={(keyId, label) =>
                        void revokeTeamKey(keyId, label)
                      }
                    />
                  </>
                )}
              </section>


              )}

            </>

          )}



          <footer className="footer">

            <span>

              <span className={`status-dot ${connected ? 'online' : ''}`} />

              Team MCP Gateway

            </span>

            <span>Local development · Backend API :8081</span>

          </footer>

        </div>

      </main>

    </div>

  )

}



export default App