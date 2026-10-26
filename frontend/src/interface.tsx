import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Check, CircleHelp, Copy, X } from 'lucide-react'

export type RecordData = Record<string, any>

export function errMsg(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

export function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? 'No data returned'
}

export function asRecord(value: unknown): RecordData {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as RecordData
  }
  return {}
}

export function formatDateTime(
  value: string | null | undefined,
  empty = 'never',
): string {
  if (!value) return empty

  const date = new Date(value)

  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

/** Tracks whether a component is still mounted, to avoid late state updates. */
export function useAlive() {
  const ref = useRef(true)

  useEffect(() => {
    ref.current = true
    return () => {
      ref.current = false
    }
  }, [])

  return ref
}

export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // Fall back to the legacy approach below.
  }

  try {
    const element = document.createElement('textarea')
    element.value = text
    element.setAttribute('readonly', '')
    element.style.position = 'fixed'
    element.style.opacity = '0'
    document.body.appendChild(element)
    element.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(element)
    return ok
  } catch {
    return false
  }
}

export function CopyButton({
  text,
  label = 'Copy',
}: {
  text: string
  label?: string
}) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')

  async function onClick() {
    const ok = await copyText(text)
    setState(ok ? 'copied' : 'failed')
    window.setTimeout(() => setState('idle'), 1800)
  }

  return (
    <button
      type="button"
      className="button button-secondary button-small"
      onClick={() => void onClick()}
    >
      {state === 'copied' ? <Check size={14} /> : <Copy size={14} />}
      {state === 'copied'
        ? 'Copied'
        : state === 'failed'
          ? 'Copy failed'
          : label}
    </button>
  )
}

export function StatusBadge({ value }: { value: unknown }) {
  const status = String(value ?? 'unknown').toLowerCase()

  const labels: Record<string, string> = {
    connected: 'Connected',
    healthy: 'Healthy',
    success: 'Success',
    succeeded: 'Success',
    successful: 'Success',
    completed: 'Success',
    ok: 'Success',
    active: 'Active',
    enabled: 'Enabled',
    disabled: 'Disabled',
    revoked: 'Revoked',
    failed: 'Failed',
    failure: 'Failed',
    error: 'Failed',
    fail: 'Failed',
    timeout: 'Timeout',
    unreachable: 'Unreachable',
    disconnected: 'Disconnected',
    pending: 'Pending',
    unknown: 'Unknown',
    admin: 'Admin',
    member: 'Member',
  }

  const label =
    labels[status] ?? status.charAt(0).toUpperCase() + status.slice(1)

  return (
    <span
      className={`status-badge status-${status.replace(/[^a-z0-9-]/g, '-')}`}
    >
      {label}
    </span>
  )
}

export function EmptyState({ message }: { message: string }) {
  return <div className="table-empty">{message}</div>
}

export function DataTable({ children }: { children: ReactNode }) {
  return (
    <div className="table-wrap">
      <table className="data-table">{children}</table>
    </div>
  )
}

export function ErrorBanner({
  message,
  onDismiss,
}: {
  message: string
  onDismiss: () => void
}) {
  return (
    <div className="error-banner">
      <CircleHelp size={18} />
      <span>{message}</span>
      <button
        className="icon-button"
        onClick={onDismiss}
        aria-label="Dismiss error"
      >
        <X size={16} />
      </button>
    </div>
  )
}

export function Modal({
  title,
  onClose,
  children,
  small = false,
  locked = false,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  small?: boolean
  /** Locked modals can't be dismissed by clicking outside or the X. */
  locked?: boolean
}) {
  return (
    <div
      className="modal-backdrop"
      onMouseDown={locked ? undefined : onClose}
    >
      <div
        className={`modal ${small ? 'modal-small' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <h3>{title}</h3>
          {!locked && (
            <button
              className="icon-button"
              type="button"
              onClick={onClose}
              aria-label="Close"
            >
              <X size={18} />
            </button>
          )}
        </div>
        {children}
      </div>
    </div>
  )
}