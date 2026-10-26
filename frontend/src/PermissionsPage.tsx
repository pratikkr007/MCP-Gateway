import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Trash2 } from 'lucide-react'

import { api } from './api'
import type {
  ApiUser,
  MemberTool,
  PermissionEffect,
  ToolPermission,
} from './api'
import { DataTable, EmptyState, ErrorBanner, StatusBadge } from './interface'

function errMsg(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

export default function PermissionsPage({
  refreshTick,
}: {
  refreshTick: number
}) {
  const [rules, setRules] = useState<ToolPermission[]>([])
  const [users, setUsers] = useState<ApiUser[]>([])
  const [tools, setTools] = useState<MemberTool[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [subjectType, setSubjectType] = useState<'role' | 'user'>('role')
  const [subject, setSubject] = useState('member')
  const [server, setServer] = useState('*')
  const [tool, setTool] = useState('*')
  const [effect, setEffect] = useState<PermissionEffect>('deny')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [perms, userList, toolList] = await Promise.all([
        api.permissions(),
        api.listUsers(),
        api.myTools(),
      ])
      setRules(perms.permissions ?? [])
      setUsers(userList.users ?? [])
      setTools(toolList.tools ?? [])
    } catch (e) {
      setError(errMsg(e, 'Could not load permissions'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshTick])

  const servers = useMemo(
    () => [...new Set(tools.map((item) => item.upstream_server))].sort(),
    [tools],
  )

  const serverTools = useMemo(
    () =>
      tools
        .filter((item) => item.upstream_server === server)
        .map((item) => item.upstream_tool)
        .sort(),
    [tools, server],
  )

  // Only members can be restricted; admins always have full access.
  const memberUsers = users.filter((item) => item.role === 'member')

  function changeSubjectType(next: 'role' | 'user') {
    setSubjectType(next)
    setSubject(next === 'role' ? 'member' : (memberUsers[0]?.user_id ?? ''))
  }

  function changeServer(next: string) {
    setServer(next)
    setTool('*')
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!subject) {
      setError('Choose who this rule applies to.')
      return
    }
    setError('')
    setNotice('')
    try {
      await api.setPermission({
        subject_type: subjectType,
        subject,
        server_name: server,
        tool_name: server === '*' ? '*' : tool,
        effect,
      })
      setNotice('Rule saved.')
      await load()
    } catch (e) {
      setError(errMsg(e, 'Could not save rule'))
    }
  }

  async function remove(rule: ToolPermission) {
    if (!window.confirm('Remove this rule?')) return
    setError('')
    setNotice('')
    try {
      await api.deletePermission(rule.id)
      setNotice('Rule removed.')
      await load()
    } catch (e) {
      setError(errMsg(e, 'Could not remove rule'))
    }
  }

  return (
    <section className="panel data-panel">
      <div className="panel-heading">
        <div>
          <h3>Tool permissions</h3>
          <p>
            Admins always have full access. Rules restrict members. A user rule
            overrides a role rule; a specific tool overrides a whole-server
            rule; deny wins ties. With no matching rule, the tool is allowed.
          </p>
        </div>
        <span className="live-tag">LIVE DATA</span>
      </div>

      {error && <ErrorBanner message={error} onDismiss={() => setError('')} />}
      {notice && (
        <p className="success-message" role="status">
          {notice}
        </p>
      )}

      <form
        onSubmit={(event) => void submit(event)}
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 12,
          alignItems: 'flex-end',
          margin: '16px 0',
        }}
      >
        <label>
          Applies to
          <select
            value={subjectType}
            onChange={(e) =>
              changeSubjectType(e.target.value as 'role' | 'user')
            }
          >
            <option value="role">Role</option>
            <option value="user">Specific user</option>
          </select>
        </label>

        <label>
          {subjectType === 'role' ? 'Role' : 'User'}
          <select value={subject} onChange={(e) => setSubject(e.target.value)}>
            {subjectType === 'role' ? (
              <option value="member">member</option>
            ) : (
              memberUsers.map((item) => (
                <option key={item.user_id} value={item.user_id}>
                  {item.username}
                </option>
              ))
            )}
          </select>
        </label>

        <label>
          Server
          <select value={server} onChange={(e) => changeServer(e.target.value)}>
            <option value="*">All servers</option>
            {servers.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>

        <label>
          Tool
          <select
            value={tool}
            onChange={(e) => setTool(e.target.value)}
            disabled={server === '*'}
          >
            <option value="*">All tools</option>
            {serverTools.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>

        <label>
          Effect
          <select
            value={effect}
            onChange={(e) => setEffect(e.target.value as PermissionEffect)}
          >
            <option value="deny">Deny</option>
            <option value="allow">Allow</option>
          </select>
        </label>

        <button className="button button-primary" type="submit">
          Save rule
        </button>
      </form>

      {loading ? (
        <p className="health-loading">Loading rules...</p>
      ) : rules.length === 0 ? (
        <EmptyState message="No rules. Every member can use every enabled tool." />
      ) : (
        <DataTable>
          <thead>
            <tr>
              <th>Applies to</th>
              <th>Server</th>
              <th>Tool</th>
              <th>Effect</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => (
              <tr key={rule.id}>
                <td>
                  {rule.subject_type === 'role'
                    ? `Role: ${rule.subject}`
                    : `User: ${rule.subject_label}`}
                </td>
                <td>{rule.server_name === '*' ? 'All servers' : rule.server_name}</td>
                <td>{rule.tool_name === '*' ? 'All tools' : rule.tool_name}</td>
                <td>
                  <StatusBadge value={rule.effect} />
                </td>
                <td>
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => void remove(rule)}
                  >
                    <Trash2 size={15} /> Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </section>
  )
}