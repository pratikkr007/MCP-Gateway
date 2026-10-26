const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? ''

/** URL that MCP clients (Claude Code, Cursor) connect to. */
export const GATEWAY_MCP_URL: string =
  import.meta.env.VITE_GATEWAY_MCP_URL ?? `${API_BASE_URL}/mcp/mcp`

export type AuthMode = 'api-key' | 'admin-token'
export type UserRole = 'admin' | 'member'
export type UpstreamAuthMode = 'none' | 'bearer' | 'custom_header'

export interface AuthConfig {
  mode: AuthMode
  credential: string
}

export interface UserProfile {
  username: string
  name: string
  role: UserRole
  user_id: string
  email: string
}

/** Shape returned by GET /admin/upstreams (credentials are never included). */
export interface Upstream {
  name: string
  url: string
  enabled: boolean
  created_at: string
  auth_mode: UpstreamAuthMode
  custom_header_name: string | null
  timeout_seconds: number
  connection_status: string
  consecutive_failures: number
  last_checked_at: string | null
  last_success_at: string | null
  last_discovery_at: string | null
  last_error: string | null
  circuit_open_until: string | null
  hasCredential: boolean
}

/** Shape returned by GET /admin/upstream-status. */
export interface UpstreamStatus {
  name: string
  enabled: boolean
  status: string
  consecutive_failures: number
  last_checked_at: string | null
  last_success_at: string | null
  last_discovery_at: string | null
  last_error: string | null
  circuit_open_until: string | null
}

export interface GatewayTool {
  gateway_name: string
  upstream_server: string
  upstream_tool: string
}

/** Tool details returned by GET /api/tools for any signed-in user. */
export interface MemberTool extends GatewayTool {
  description: string | null
  input_schema: Record<string, unknown>
}

export interface UpstreamCreateInput {
  name: string
  url: string
  enabled?: boolean
  auth_mode?: UpstreamAuthMode
  /** Omit for "no credential". Never read back from the server. */
  credential?: string
  custom_header_name?: string
  timeout_seconds?: number
}

/**
 * PATCH semantics on the backend:
 *  - credential omitted  -> keep the stored credential
 *  - credential ""       -> clear the stored credential
 *  - credential "xyz"    -> replace it
 */
export type UpstreamUpdateInput = Partial<Omit<UpstreamCreateInput, 'name'>>

/** GET /admin/users */
export interface ApiUser {
  user_id: string
  username: string
  email: string
  role: UserRole
  created_at: string
  active_keys: number
  total_keys: number
  last_used_at: string | null
}

/** GET /admin/keys and GET /api/me/keys (admin list also has user fields). */
export interface ApiKeyRecord {
  key_id: number
  user_id?: string
  username?: string
  label: string
  key_prefix: string | null
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
  revoked: number
}

/** Returned once when a key is created. The raw key is never available again. */
export interface IssuedKey {
  key_id: number
  user_id: string
  label: string
  api_key: string
  warning: string
}

export interface UserCreateInput {
  username: string
  email?: string
  role: UserRole
}

/** Effect applied by a tool permission rule. */
export type PermissionEffect = 'allow' | 'deny'

/** Tool permission returned by the admin permissions API. */
export interface ToolPermission {
  id: number
  subject_type: 'role' | 'user'
  subject: string
  subject_label: string
  server_name: string
  /** '*' means every tool on the server. */
  tool_name: string
  effect: PermissionEffect
  created_at: string
}

/** Input used to create or update a tool permission rule. */
export interface ToolPermissionInput {
  subject_type: 'role' | 'user'
  subject: string
  server_name: string
  tool_name: string
  effect: PermissionEffect
}

export interface AuditEvent {
  id: number
  user_id: string
  username: string | null
  server_name: string
  tool_name: string
  started_at: string | null
  timestamp: string
  duration_ms: number
  outcome: string
  error_message: string | null
}

export interface AuditPageResult {
  total: number
  limit: number
  offset: number
  audit: AuditEvent[]
}

export interface AuditQuery {
  username?: string
  server_name?: string
  tool_name?: string
  outcome?: string
  limit?: number
  offset?: number
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

let authConfig: AuthConfig = {
  mode: 'api-key',
  credential: '',
}

let unauthorizedHandler: (() => void) | null = null

export function setAuth(config: AuthConfig) {
  authConfig = {
    mode: config.mode,
    credential: config.credential.trim(),
  }
}

export function getAuth() {
  return authConfig
}

/** Called when any request (except /api/me) returns 401 while signed in. */
export function setUnauthorizedHandler(handler: (() => void) | null) {
  unauthorizedHandler = handler
}

function extractMessage(body: string, fallback: string): string {
  if (!body) return fallback

  try {
    const parsed = JSON.parse(body)
    const detail = parsed?.detail

    if (typeof detail === 'string') return detail

    // FastAPI/Pydantic validation errors (422)
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          const where = Array.isArray(item?.loc)
            ? item.loc.filter((part: unknown) => part !== 'body').join('.')
            : ''
          return where ? `${where}: ${item?.msg}` : String(item?.msg ?? item)
        })
        .join('; ')
    }

    if (typeof parsed?.message === 'string') return parsed.message
  } catch {
    // Not JSON; fall through to the raw text.
  }

  return body.slice(0, 300)
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers)

  headers.set('Accept', 'application/json')

  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  // Remove stale credentials before applying the active credential.
  headers.delete('X-Admin-Token')
  headers.delete('X-API-Key')
  headers.delete('Authorization')

  const credential = authConfig.credential.trim()
  const isAdminEndpoint = path === '/admin' || path.startsWith('/admin/')
  const isHealthEndpoint = path === '/health'

  if (credential && !isHealthEndpoint) {
    if (authConfig.mode === 'admin-token' && isAdminEndpoint) {
      headers.set('X-Admin-Token', credential)
    } else if (authConfig.mode === 'api-key') {
      headers.set('X-API-Key', credential)
    }
  }

  let response: Response

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers,
    })
  } catch {
    throw new ApiError(
      0,
      `Cannot reach the gateway${API_BASE_URL ? ` at ${API_BASE_URL}` : ''}.`,
    )
  }

  if (!response.ok) {
    const body = await response.text()
    const message = extractMessage(body, response.statusText)

    if (
      response.status === 401 &&
      credential &&
      path !== '/api/me' &&
      unauthorizedHandler
    ) {
      unauthorizedHandler()
    }

    throw new ApiError(response.status, message)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export const api = {
  health: () =>
    apiRequest<{
      status: string
      service?: string
      registered_tools?: number
    }>('/health'),

  me: () => apiRequest<Record<string, unknown>>('/api/me'),

  // ---- MCP servers (admin) ----
  upstreams: () =>
    apiRequest<{ upstreams: Upstream[] }>('/admin/upstreams'),

  upstreamStatus: () =>
    apiRequest<{ upstreams: UpstreamStatus[] }>('/admin/upstream-status'),

  // Admin-only tool listing for the Servers page.
  tools: () => apiRequest<{ tools: GatewayTool[] }>('/admin/tools'),

  // Any signed-in user (admin or member).
  // Includes tool descriptions and input schemas.
  myTools: () => apiRequest<{ tools: MemberTool[] }>('/api/tools'),

  createUpstream: (input: UpstreamCreateInput) =>
    apiRequest<unknown>('/admin/upstreams', {
      method: 'POST',
      body: JSON.stringify(input),
    }),

  // The backend exposes PATCH (not PUT) for edits and enable/disable.
  updateUpstream: (name: string, input: UpstreamUpdateInput) =>
    apiRequest<unknown>(`/admin/upstreams/${encodeURIComponent(name)}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    }),

  deleteUpstream: (name: string) =>
    apiRequest<unknown>(`/admin/upstreams/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  refreshTools: () =>
    apiRequest<{ upstreams_discovered: number; tools_registered: number }>(
      '/admin/refresh-tools',
      { method: 'POST' },
    ),

  // ---- Tool permissions (admin) ----
  permissions: () =>
    apiRequest<{ permissions: ToolPermission[] }>('/admin/permissions'),

  setPermission: (input: ToolPermissionInput) =>
    apiRequest<ToolPermission>('/admin/permissions', {
      method: 'PUT',
      body: JSON.stringify(input),
    }),

  deletePermission: (id: number) =>
    apiRequest<{ message: string }>(`/admin/permissions/${id}`, {
      method: 'DELETE',
    }),

  effectivePermissions: (userId: string) =>
    apiRequest<{
      user_id: string
      username: string
      role: UserRole
      allowed: string[]
      denied: string[]
    }>(`/admin/permissions/effective/${encodeURIComponent(userId)}`),

  // ---- Team members (admin) ----
  listUsers: () => apiRequest<{ users: ApiUser[] }>('/admin/users'),

  createUser: (input: UserCreateInput) =>
    apiRequest<{ user_id: string; username: string; role: UserRole }>(
      '/admin/users',
      { method: 'POST', body: JSON.stringify(input) },
    ),

  updateUserRole: (userId: string, role: UserRole) =>
    apiRequest<{ user_id: string; role: UserRole }>(
      `/admin/users/${encodeURIComponent(userId)}`,
      { method: 'PATCH', body: JSON.stringify({ role }) },
    ),

  deleteUser: (userId: string) =>
    apiRequest<{ message: string }>(
      `/admin/users/${encodeURIComponent(userId)}`,
      { method: 'DELETE' },
    ),

  // ---- API keys (admin: any user) ----
  // `adminKeys` is the method name used by the Team & API Keys page.
  // Keep `listKeys` as an alias for compatibility with any existing callers.
  adminKeys: () => apiRequest<{ keys: ApiKeyRecord[] }>('/admin/keys'),
  listKeys: () => apiRequest<{ keys: ApiKeyRecord[] }>('/admin/keys'),

  createKey: (userId: string, label = 'default') =>
    apiRequest<IssuedKey>(
      `/admin/users/${encodeURIComponent(userId)}/keys`,
      { method: 'POST', body: JSON.stringify({ label }) },
    ),

  revokeKey: (keyId: number) =>
    apiRequest<{ message: string }>(`/admin/keys/${keyId}/revoke`, {
      method: 'POST',
    }),

  // ---- API keys (any signed-in user: own keys only) ----
  myKeys: () => apiRequest<{ keys: ApiKeyRecord[] }>('/api/me/keys'),

  createMyKey: (label = 'default') =>
    apiRequest<IssuedKey>('/api/me/keys', {
      method: 'POST',
      body: JSON.stringify({ label }),
    }),

  revokeMyKey: (keyId: number) =>
    apiRequest<{ message: string }>(`/api/me/keys/${keyId}/revoke`, {
      method: 'POST',
    }),

  // ---- Audit (admin) ----
  audit: (query: AuditQuery = {}) => {
    const params = new URLSearchParams()

    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== '') {
        params.set(key, String(value))
      }
    }

    return apiRequest<AuditPageResult>(`/admin/audit?${params.toString()}`)
  },

  // ---- Chat (any signed-in user) ----
  chat: (message: string, history?: Array<Record<string, string>>) =>
    apiRequest<unknown>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ message, history }),
    }),
}
