import { clsx, type ClassValue } from 'clsx'

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs)
}

export function formatBytes(mb: number | null | undefined): string {
  if (mb == null) return '—'
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`
  return `${mb} MB`
}

export function formatGb(gb: number | null | undefined): string {
  if (gb == null) return '—'
  return `${gb.toFixed(0)} GB`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

export function powerStateBadge(state: string): string {
  switch (state) {
    case 'on': return 'badge badge-green'
    case 'off': return 'badge badge-gray'
    case 'suspended': return 'badge badge-yellow'
    default: return 'badge badge-gray'
  }
}

export function platformBadge(platform: string): string {
  return platform === 'vmware' ? 'badge badge-blue' : 'badge badge-teal'
}
