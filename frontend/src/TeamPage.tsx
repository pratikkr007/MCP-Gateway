import { Fragment, useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  ChevronDown,
  ChevronRight,
  KeyRound,
  Plus,
  Trash2,
  UserPlus,
  Users,
} from 'lucide-react'
import {
  GATEWAY_MCP_URL,
  api,
  type ApiKeyRecord,
  type ApiUser,
  type IssuedKey,
  type UserRole,
} from './api'
import {
  CopyButton,
  DataTable,
  EmptyState,
  ErrorBanner,
  Modal,
  StatusBadge,
  errMsg,
  formatDateTime,
  useAlive,
} from './interface'

type Me = { user_id: string; username: string; role: UserRole }

/* ------------------------------------------------------------------ */
/* Shared pieces                                                       */
/* ------------------------------------------------------------------ */

function KeyTable({
  keys,
  busyId,
  onRevoke,
}: {
  keys: ApiKeyRecord[]
  busyId: number | null
  onRevoke: (key: ApiKeyRecord) => void
}) {
  if (keys.length === 0) {
    return <EmptyState message="No API keys yet." />
  }

  return (
    <DataTable>
      <thead>
        <tr>
          <th>Label</th>
          <th>Key</th>
          <th>Created</th>
          <th>Last used</th>
          <th>Status</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {keys.map((key) => {
          const revoked = Boolean(key.revoked)

          return (
            <tr key={key.key_id}>
              <td>{key.label}</td>
              <td>
                <code className="mono">
                  {key.key_prefix ?? 'tmcp_'}••••••••
                </code>
              </td>
              <td>{formatDateTime(key.created_at)}</td>
              <td>{formatDateTime(key.last_used_at, 'never')}</td>
              <td>
                <StatusBadge value={revoked ? 'revoked' : 'active'} />
                {revoked && key.revoked_at && (
                  <small className="table-subtitle">
                    {formatDateTime(key.revoked_at)}
                  </small>
                )}
              </td>
              <td>
                {!revoked && (
                  <button
                    className="button button-secondary button-small"
                    onClick={() => onRevoke(key)}
                    disabled={busyId === key.key_id}
                  >
                    {busyId === key.key_id ? 'Revoking…' : 'Revoke'}
                  </button>
                )}
              </td>
            </tr>
          )
        })}
      </tbody>
    </DataTable>
  )
}

function RevealKeyModal({
  issued,
  owner,
  onClose,
}: {
  issued: IssuedKey
  owner?: string
  onClose: () => void
}) {
  const [saved, setSaved] = useState(false)

  return (
    <Modal title="Your new API key" onClose={onClose} locked>
      <p>
        {owner ? `Key for ${owner} (label “${issued.label}”). ` : ''}
        This is the <strong>only time</strong> the key is shown. The server
        stores just a hash, so it cannot be recovered. If it is lost, revoke it
        and create a new one.
      </p>

      <div className="key-reveal">
        <code>{issued.api_key}</code>
        <CopyButton text={issued.api_key} />
      </div>

      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={saved}
          onChange={(event) => setSaved(event.target.checked)}
        />
        I have copied this key and stored it somewhere safe
      </label>

      <div className="modal-actions">
        <button
          className="button button-primary"
          onClick={onClose}
          disabled={!saved}
        >
          Done
        </button>
      </div>
    </Modal>
  )
}

function RevokeKeyModal({
  target,
  warnSelf,
  busy,
  onCancel,
  onConfirm,
}: {
  target: ApiKeyRecord
  warnSelf: boolean
  busy: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <Modal title="Revoke this key?" onClose={onCancel} small locked={busy}>
      <p>
        The key “{target.label}” ({target.key_prefix ?? 'tmcp_'}••••) will stop
        working immediately for the dashboard, the chat agent and any MCP
        client using it. This cannot be undone.
        {warnSelf &&
          ' If this is the key you are signed in with, you will be signed out.'}
      </p>

      <div className="modal-actions">
        <button
          className="button button-secondary"
          onClick={onCancel}
          disabled={busy}
        >
          Cancel
        </button>
        <button
          className="button button-danger"
          onClick={onConfirm}
          disabled={busy}
        >
          {busy ? 'Revoking…' : 'Revoke key'}
        </button>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------------ */
/* Connect an MCP client                                               */
/* ------------------------------------------------------------------ */

function ConnectCard() {
  const [tab, setTab] = useState<'claude' | 'cursor'>('claude')

  const claudeCommand =
    `claude mcp add --transport http team-gateway ${GATEWAY_MCP_URL} \\\n` +
    `  --header "x-api-key: YOUR_API_KEY"`

  const cursorConfig = JSON.stringify(
    {
      mcpServers: {
        'team-gateway': {
          url: GATEWAY_MCP_URL,
          headers: { 'x-api-key': 'YOUR_API_KEY' },
        },
      },
    },
    null,
    2,
  )

  const snippet = tab === 'claude' ? claudeCommand : cursorConfig

  return (
    <section className="resource-card">
      <div className="resource-card-heading">
        <h3>Connect an MCP client</h3>
        <Plus size={19} />
      </div>

      <p>
        Add this single gateway URL and your personal API key to your MCP
        client. You will see the tools from every enabled server without
        configuring any of them yourself.
      </p>

      <div className="key-reveal">
        <code>{GATEWAY_MCP_URL}</code>
        <CopyButton text={GATEWAY_MCP_URL} label="Copy URL" />
      </div>

      <div className="tabs" role="tablist">
        <button
          role="tab"
          aria-selected={tab === 'claude'}
          className={`tab ${tab === 'claude' ? 'tab-active' : ''}`}
          onClick={() => setTab('claude')}
        >
          Claude Code
        </button>
        <button
          role="tab"
          aria-selected={tab === 'cursor'}
          className={`tab ${tab === 'cursor' ? 'tab-active' : ''}`}
          onClick={() => setTab('cursor')}
        >
          Cursor
        </button>
      </div>

      <pre className="code-block">{snippet}</pre>

      <div className="code-actions">
        <CopyButton text={snippet} label="Copy snippet" />
        <small className="muted">
          {tab === 'claude'
            ? 'Run once in your terminal. Replace YOUR_API_KEY with a key from below.'
            : 'Save as ~/.cursor/mcp.json (or .cursor/mcp.json in a project).'}
        </small>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ */
/* My API keys (admins and members)                                    */
/* ------------------------------------------------------------------ */

function MyKeysCard({ refreshTick }: { refreshTick: number }) {
  const alive = useAlive()
  const [keys, setKeys] = useState<ApiKeyRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [label, setLabel] = useState('')
  const [creating, setCreating] = useState(false)
  const [issued, setIssued] = useState<IssuedKey | null>(null)
  const [revoking, setRevoking] = useState<ApiKeyRecord | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)

  const load = useCallback(async () => {
    try {
      const result = await api.myKeys()

      if (alive.current) {
        setKeys(result.keys)
        setError('')
      }
    } catch (e) {
      if (alive.current) setError(errMsg(e, 'Could not load your keys.'))
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [alive])

  useEffect(() => {
    void load()
  }, [load, refreshTick])

  async function create(event: FormEvent) {
    event.preventDefault()
    setCreating(true)
    setError('')

    try {
      const result = await api.createMyKey(label.trim() || 'default')

      if (alive.current) {
        setIssued(result)
        setLabel('')
      }

      await load()
    } catch (e) {
      if (alive.current) setError(errMsg(e, 'Could not create the key.'))
    } finally {
      if (alive.current) setCreating(false)
    }
  }

  async function confirmRevoke() {
    if (!revoking) return

    const target = revoking
    setBusyId(target.key_id)

    try {
      await api.revokeMyKey(target.key_id)

      if (alive.current) setRevoking(null)

      await load()
    } catch (e) {
      if (alive.current) {
        setError(errMsg(e, 'Could not revoke the key.'))
        setRevoking(null)
      }
    } finally {
      if (alive.current) setBusyId(null)
    }
  }

  return (
    <section className="resource-card">
      <div className="resource-card-heading">
        <h3>My API keys</h3>
        <KeyRound size={19} />
      </div>

      <p>
        Use a key to connect MCP clients to the gateway. Upstream server
        credentials are never exposed to you or your client.
      </p>

      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}

      <form className="inline-form" onSubmit={create}>
        <input
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="Label, e.g. laptop or cursor"
          maxLength={80}
          aria-label="Key label"
          disabled={creating}
        />
        <button
          className="button button-primary button-small"
          type="submit"
          disabled={creating}
        >
          <Plus size={15} />
          {creating ? 'Generating…' : 'Generate key'}
        </button>
      </form>

      {loading ? (
        <p className="health-loading">Loading your keys…</p>
      ) : (
        <KeyTable keys={keys} busyId={busyId} onRevoke={setRevoking} />
      )}

      {issued && (
        <RevealKeyModal issued={issued} onClose={() => setIssued(null)} />
      )}

      {revoking && (
        <RevokeKeyModal
          target={revoking}
          warnSelf
          busy={busyId !== null}
          onCancel={() => setRevoking(null)}
          onConfirm={() => void confirmRevoke()}
        />
      )}
    </section>
  )
}

/* ------------------------------------------------------------------ */
/* Admin: members                                                      */
/* ------------------------------------------------------------------ */

function InviteModal({
  onClose,
  onDone,
}: {
  onClose: () => void
  onDone: (
    username: string,
    issued: IssuedKey | null,
    warning?: string,
  ) => Promise<void>
}) {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<UserRole>('member')
  const [generate, setGenerate] = useState(true)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    setFormError('')

    const name = username.trim()
    const mail = email.trim()

    if (name.length < 2 || name.length > 80) {
      setFormError('Name must be between 2 and 80 characters.')
      return
    }

    if (mail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(mail)) {
      setFormError('Enter a valid email address, or leave it blank.')
      return
    }

    setSaving(true)

    try {
      const created = await api.createUser({
        username: name,
        email: mail || undefined,
        role,
      })

      let issued: IssuedKey | null = null
      let warning: string | undefined

      if (generate) {
        try {
          issued = await api.createKey(created.user_id, 'default')
        } catch (e) {
          warning = `User created, but the key could not be generated: ${errMsg(e, 'unknown error')}. Use “New key” on their row.`
        }
      }

      await onDone(created.username, issued, warning)
      onClose()
    } catch (e) {
      setFormError(errMsg(e, 'Could not create the user.'))
      setSaving(false)
    }
  }

  return (
    <Modal title="Invite team member" onClose={onClose} locked={saving}>
      {formError && <div className="form-error">{formError}</div>}

      <form className="form-grid" onSubmit={submit}>
        <label className="field">
          Name
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="e.g. alice"
            maxLength={80}
            disabled={saving}
            required
          />
        </label>

        <label className="field">
          Email (optional)
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="alice@company.com"
            disabled={saving}
          />
        </label>

        <label className="field">
          Role
          <select
            value={role}
            onChange={(event) => setRole(event.target.value as UserRole)}
            disabled={saving}
          >
            <option value="member">Member (uses tools)</option>
            <option value="admin">Admin (manages servers and members)</option>
          </select>
        </label>

        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={generate}
            onChange={(event) => setGenerate(event.target.checked)}
            disabled={saving}
          />
          Generate their first API key now
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
            {saving ? 'Creating…' : 'Create member'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

function MembersCard({ me, refreshTick }: { me: Me; refreshTick: number }) {
  const alive = useAlive()
  const [users, setUsers] = useState<ApiUser[]>([])
  const [keys, setKeys] = useState<ApiKeyRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showInvite, setShowInvite] = useState(false)
  const [issued, setIssued] = useState<{
    key: IssuedKey
    owner: string
  } | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [busyUser, setBusyUser] = useState<string | null>(null)
  const [busyKey, setBusyKey] = useState<number | null>(null)
  const [removing, setRemoving] = useState<ApiUser | null>(null)
  const [revokingKey, setRevokingKey] = useState<ApiKeyRecord | null>(null)

  const load = useCallback(async () => {
    try {
      const [userResult, keyResult] = await Promise.all([
        api.listUsers(),
        api.listKeys(),
      ])

      if (alive.current) {
        setUsers(userResult.users)
        setKeys(keyResult.keys)
        setError('')
      }
    } catch (e) {
      if (alive.current) setError(errMsg(e, 'Could not load team members.'))
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [alive])

  useEffect(() => {
    void load()
  }, [load, refreshTick])

  async function changeRole(user: ApiUser, role: UserRole) {
    if (role === user.role) return

    setBusyUser(user.user_id)
    setError('')

    try {
      await api.updateUserRole(user.user_id, role)
      await load()
    } catch (e) {
      if (alive.current) setError(errMsg(e, 'Could not change the role.'))
    } finally {
      if (alive.current) setBusyUser(null)
    }
  }

  async function newKey(user: ApiUser) {
    setBusyUser(user.user_id)
    setError('')

    try {
      const result = await api.createKey(user.user_id, 'admin-issued')

      if (alive.current) {
        setIssued({ key: result, owner: user.username })
        setExpanded(user.user_id)
      }

      await load()
    } catch (e) {
      if (alive.current) setError(errMsg(e, 'Could not create the key.'))
    } finally {
      if (alive.current) setBusyUser(null)
    }
  }

  async function confirmRemove() {
    if (!removing) return

    const target = removing
    setBusyUser(target.user_id)

    try {
      await api.deleteUser(target.user_id)

      if (alive.current) {
        setRemoving(null)
        setExpanded((current) =>
          current === target.user_id ? null : current,
        )
      }

      await load()
    } catch (e) {
      if (alive.current) {
        setError(errMsg(e, 'Could not remove the user.'))
        setRemoving(null)
      }
    } finally {
      if (alive.current) setBusyUser(null)
    }
  }

  async function confirmRevokeKey() {
    if (!revokingKey) return

    const target = revokingKey
    setBusyKey(target.key_id)

    try {
      await api.revokeKey(target.key_id)

      if (alive.current) setRevokingKey(null)

      await load()
    } catch (e) {
      if (alive.current) {
        setError(errMsg(e, 'Could not revoke the key.'))
        setRevokingKey(null)
      }
    } finally {
      if (alive.current) setBusyKey(null)
    }
  }

  async function handleInvited(
    username: string,
    key: IssuedKey | null,
    warning?: string,
  ) {
    if (alive.current) {
      if (key) setIssued({ key, owner: username })
      if (warning) setError(warning)
    }

    await load()
  }

  return (
    <section className="resource-card">
      <div className="resource-card-heading">
        <h3>Team members</h3>
        <Users size={19} />
      </div>

      <div className="servers-toolbar">
        <span className="muted">
          {users.length} {users.length === 1 ? 'member' : 'members'}
        </span>
        <button
          className="button button-primary button-small"
          onClick={() => setShowInvite(true)}
        >
          <UserPlus size={15} />
          Invite member
        </button>
      </div>

      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}

      {loading ? (
        <p className="health-loading">Loading team members…</p>
      ) : users.length === 0 ? (
        <EmptyState message="No members yet. Use “Invite member” to add one." />
      ) : (
        <DataTable>
          <thead>
            <tr>
              <th>Member</th>
              <th>Email</th>
              <th>Role</th>
              <th>Keys</th>
              <th>Last used</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => {
              const isMe = user.user_id === me.user_id
              const open = expanded === user.user_id
              const busy = busyUser === user.user_id
              const userKeys = keys.filter(
                (key) => key.user_id === user.user_id,
              )
              const hasRealEmail = !user.email.endsWith('@local.invalid')

              return (
                <Fragment key={user.user_id}>
                  <tr>
                    <td>
                      <div className="row-actions">
                        <button
                          className="icon-button"
                          onClick={() =>
                            setExpanded(open ? null : user.user_id)
                          }
                          aria-label={
                            open
                              ? `Hide keys for ${user.username}`
                              : `Show keys for ${user.username}`
                          }
                          aria-expanded={open}
                        >
                          {open ? (
                            <ChevronDown size={16} />
                          ) : (
                            <ChevronRight size={16} />
                          )}
                        </button>
                        <div>
                          <strong>{user.username}</strong>
                          {isMe && (
                            <small className="table-subtitle">You</small>
                          )}
                        </div>
                      </div>
                    </td>
                    <td>{hasRealEmail ? user.email : '—'}</td>
                    <td>
                      <select
                        value={user.role}
                        onChange={(event) =>
                          void changeRole(user, event.target.value as UserRole)
                        }
                        disabled={busy || isMe}
                        title={
                          isMe ? 'You cannot change your own role' : undefined
                        }
                        aria-label={`Role for ${user.username}`}
                      >
                        <option value="member">Member</option>
                        <option value="admin">Admin</option>
                      </select>
                    </td>
                    <td>
                      {user.active_keys} active
                      <small className="table-subtitle">
                        {user.total_keys} total
                      </small>
                    </td>
                    <td>{formatDateTime(user.last_used_at, 'never')}</td>
                    <td>
                      <div className="row-actions">
                        <button
                          className="button button-secondary button-small"
                          onClick={() => void newKey(user)}
                          disabled={busy}
                        >
                          <Plus size={14} />
                          New key
                        </button>
                        <button
                          className="icon-button icon-danger"
                          onClick={() => setRemoving(user)}
                          disabled={busy || isMe}
                          title={
                            isMe
                              ? 'You cannot remove your own account'
                              : 'Remove member'
                          }
                          aria-label={`Remove ${user.username}`}
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>

                  {open && (
                    <tr className="expanded-row">
                      <td colSpan={6}>
                        <KeyTable
                          keys={userKeys}
                          busyId={busyKey}
                          onRevoke={setRevokingKey}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </DataTable>
      )}

      {showInvite && (
        <InviteModal
          onClose={() => setShowInvite(false)}
          onDone={handleInvited}
        />
      )}

      {issued && (
        <RevealKeyModal
          issued={issued.key}
          owner={issued.owner}
          onClose={() => setIssued(null)}
        />
      )}

      {revokingKey && (
        <RevokeKeyModal
          target={revokingKey}
          warnSelf={revokingKey.user_id === me.user_id}
          busy={busyKey !== null}
          onCancel={() => setRevokingKey(null)}
          onConfirm={() => void confirmRevokeKey()}
        />
      )}

      {removing && (
        <Modal
          title={`Remove “${removing.username}”?`}
          onClose={() => setRemoving(null)}
          small
          locked={busyUser !== null}
        >
          <p>
            This deletes the member and all {removing.total_keys} of their API
            key(s). Their clients will be rejected on the next call. Their past
            audit log entries are kept. This cannot be undone.
          </p>

          <div className="modal-actions">
            <button
              className="button button-secondary"
              onClick={() => setRemoving(null)}
              disabled={busyUser !== null}
            >
              Cancel
            </button>
            <button
              className="button button-danger"
              onClick={() => void confirmRemove()}
              disabled={busyUser !== null}
            >
              {busyUser ? 'Removing…' : 'Remove member'}
            </button>
          </div>
        </Modal>
      )}
    </section>
  )
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

export default function TeamPage({
  me,
  refreshTick,
}: {
  me: Me
  refreshTick: number
}) {
  return (
    <div className="resource-cards">
      <ConnectCard />
      <MyKeysCard refreshTick={refreshTick} />
      {me.role === 'admin' && (
        <MembersCard me={me} refreshTick={refreshTick} />
      )}
    </div>
  )
}