import { useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Server, Database, RefreshCw, Eye, EyeOff,
  CheckCircle2, XCircle, Loader2, Save, TestTube2,
  Settings2, Globe, ShieldCheck, Archive, Download,
  History, AlertTriangle, HardDriveDownload, ArchiveRestore,
} from 'lucide-react'
import {
  getSettings,
  updateVmwareSettings,
  updateNutanixSettings,
  updateSyncSettings,
  updateGeneralSettings,
  testConnection,
  updateBackupSettings,
  runBackupNow,
  downloadBackup,
  uploadBackup,
  restoreBackup,
} from '../lib/api'
import Spinner from '../components/Spinner'
import ErrorBanner from '../components/ErrorBanner'
import { formatDate } from '../lib/utils'

type Tab = 'connectors' | 'sync' | 'general' | 'backup'

const MASK = '••••••••'

// ---------------------------------------------------------------------------
// Form state types
// ---------------------------------------------------------------------------
interface VMwareForm { host: string; user: string; password: string; port: number; insecure: boolean }
interface NutanixForm { base_url: string; user: string; password: string; insecure: boolean }
interface SyncForm { page_size: number; retry_max_attempts: number; retry_wait_min: number; retry_wait_max: number; vmware_interval_minutes: number; nutanix_interval_minutes: number }
interface GeneralForm { timezone: string; session_idle_timeout_minutes: number }
interface BackupForm { enabled: boolean; interval_minutes: number; retention_count: number }
interface BackupFile { filename: string; size_bytes: number; created_at: string }
interface TestResult { status: 'ok' | 'error'; message: string; detail?: string }

const DEFAULT_VMWARE: VMwareForm   = { host: '', user: '', password: '', port: 443, insecure: false }
const DEFAULT_NUTANIX: NutanixForm = { base_url: '', user: '', password: '', insecure: false }
const DEFAULT_SYNC: SyncForm       = { page_size: 100, retry_max_attempts: 3, retry_wait_min: 1.0, retry_wait_max: 30.0, vmware_interval_minutes: 240, nutanix_interval_minutes: 240 }
const DEFAULT_GENERAL: GeneralForm = { timezone: 'UTC', session_idle_timeout_minutes: 30 }
const DEFAULT_BACKUP: BackupForm   = { enabled: false, interval_minutes: 1440, retention_count: 10 }

// Common IANA timezones for the dropdown
const TIMEZONES = [
  'UTC',
  'Asia/Kathmandu',
  'Asia/Kolkata',
  'Asia/Dhaka',
  'Asia/Bangkok',
  'Asia/Singapore',
  'Asia/Shanghai',
  'Asia/Tokyo',
  'Asia/Dubai',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Europe/Moscow',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Sao_Paulo',
  'Australia/Sydney',
  'Pacific/Auckland',
]

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function Settings() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('connectors')

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['settings'],
    queryFn: () => getSettings().then(r => r.data),
  })

  const TABS: { id: Tab; label: string; icon: typeof Settings2 }[] = [
    { id: 'connectors', label: 'Connectors',  icon: Server },
    { id: 'sync',       label: 'Sync Engine', icon: RefreshCw },
    { id: 'general',    label: 'General',     icon: Globe },
    { id: 'backup',     label: 'Database Backup', icon: Archive },
  ]

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-100 shrink-0">
          <Settings2 className="h-5 w-5 text-primary" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-800">Settings</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Connector credentials, sync configuration, and general preferences.
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 px-5 py-2.5 text-sm font-medium border-b-2 -mb-px
              whitespace-nowrap transition-colors duration-150
              ${tab === t.id
                ? 'border-primary text-primary'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}`}
          >
            <t.icon className="h-4 w-4" />
            {t.label}
            {t.id === 'connectors' && data && (
              (data.vmware?.configured && data.nutanix?.configured)
                ? <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                : (!data.vmware?.configured || !data.nutanix?.configured)
                  ? <span className="h-2 w-2 rounded-full bg-yellow-400 inline-block" />
                  : null
            )}
          </button>
        ))}
      </div>

      {isLoading && (
        <div className="flex justify-center py-16"><Spinner size="lg" /></div>
      )}
      {isError && (
        <ErrorBanner message="Failed to load settings." onRetry={refetch} />
      )}

      {!isLoading && !isError && (
        <>
          {tab === 'connectors' && (
            <ConnectorsTab data={data} qc={qc} />
          )}
          {tab === 'sync' && (
            <SyncTab initial={data?.sync ?? DEFAULT_SYNC} qc={qc} />
          )}
          {tab === 'general' && (
            <GeneralTab initial={data?.general ?? DEFAULT_GENERAL} qc={qc} />
          )}
          {tab === 'backup' && (
            <BackupTab
              initial={data?.backup ?? DEFAULT_BACKUP}
              files={data?.backup?.files ?? []}
              qc={qc}
            />
          )}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Connectors tab — VMware + Nutanix side-by-side (stack on mobile)
// ---------------------------------------------------------------------------
function ConnectorsTab({ data, qc }: { data: Record<string, unknown> | undefined; qc: ReturnType<typeof useQueryClient> }) {
  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
      <ConnectorCard
        platform="vmware"
        initial={data?.vmware as (VMwareForm & { configured?: boolean }) ?? DEFAULT_VMWARE}
        qc={qc}
      />
      <ConnectorCard
        platform="nutanix"
        initial={data?.nutanix as (NutanixForm & { configured?: boolean }) ?? DEFAULT_NUTANIX}
        qc={qc}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Single connector card (handles both platforms)
// ---------------------------------------------------------------------------
function ConnectorCard({
  platform, initial, qc,
}: {
  platform: 'vmware' | 'nutanix'
  initial: (VMwareForm | NutanixForm) & { configured?: boolean }
  qc: ReturnType<typeof useQueryClient>
}) {
  const isVmware = platform === 'vmware'

  // Separate state for each platform type
  const [vmForm, setVmForm] = useState<VMwareForm>(() => {
    if (!isVmware) return DEFAULT_VMWARE
    const i = initial as VMwareForm & { configured?: boolean }
    return { host: i.host ?? '', user: i.user ?? '', password: i.password ?? '', port: i.port ?? 443, insecure: i.insecure ?? false }
  })
  const [nxForm, setNxForm] = useState<NutanixForm>(() => {
    if (isVmware) return DEFAULT_NUTANIX
    const i = initial as NutanixForm & { configured?: boolean }
    return { base_url: i.base_url ?? '', user: i.user ?? '', password: i.password ?? '', insecure: i.insecure ?? false }
  })

  const [showPw, setShowPw] = useState(false)
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [saveOk, setSaveOk] = useState(false)

  const saveMutation = useMutation({
    mutationFn: () => isVmware
      ? updateVmwareSettings(vmForm as unknown as Record<string, unknown>)
      : updateNutanixSettings(nxForm as unknown as Record<string, unknown>),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['sources'] })
      setTestResult(null)
      setSaveOk(true)
      setTimeout(() => setSaveOk(false), 3000)
    },
  })

  const testMutation = useMutation({
    mutationFn: () => testConnection(platform),
    onSuccess: r => setTestResult(r.data as TestResult),
    onError: (e: Error) => setTestResult({ status: 'error', message: e.message }),
  })

  const configured = initial.configured ?? false
  const saveDisabled = isVmware ? (!vmForm.host || !vmForm.user) : (!nxForm.base_url || !nxForm.user)
  const hasChangedPw = isVmware
    ? (vmForm.password !== '' && vmForm.password !== MASK)
    : (nxForm.password !== '' && nxForm.password !== MASK)

  return (
    <div className="card flex flex-col">
      {/* Card header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-50 shrink-0">
            {isVmware ? <Server className="h-4 w-4 text-primary" /> : <Database className="h-4 w-4 text-primary" />}
          </div>
          <div>
            <h2 className="text-sm font-semibold text-gray-800">
              {isVmware ? 'VMware vCenter' : 'Nutanix Prism Element'}
            </h2>
            <p className="text-xs text-gray-400">
              {isVmware ? 'vSphere REST API · read-only role' : 'Prism Element REST API v2.0 · Viewer role'}
            </p>
          </div>
        </div>
        <span className={`badge shrink-0 ${configured ? 'badge-green' : 'badge-yellow'}`}>
          {configured ? 'Configured' : 'Not set up'}
        </span>
      </div>

      {/* Form body */}
      <div className="flex-1 p-5 space-y-4">
        {isVmware ? (
          <>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <Field label="Hostname / IP" required>
                  <input type="text" className="input" placeholder="vcenter.example.com"
                    value={vmForm.host}
                    onChange={e => setVmForm(f => ({ ...f, host: e.target.value }))} />
                </Field>
              </div>
              <Field label="Port">
                <input type="number" className="input" value={vmForm.port}
                  onChange={e => setVmForm(f => ({ ...f, port: parseInt(e.target.value) || 443 }))} />
              </Field>
            </div>
            <Field label="Username" required>
              <input type="text" className="input" placeholder="svc-readonly@vsphere.local"
                value={vmForm.user}
                onChange={e => setVmForm(f => ({ ...f, user: e.target.value }))} />
            </Field>
            <Field label={configured ? 'Password (leave blank to keep existing)' : 'Password'}>
              <PasswordInput value={vmForm.password} show={showPw}
                placeholder={configured ? MASK : 'Enter password'}
                onToggle={() => setShowPw(s => !s)}
                onChange={v => setVmForm(f => ({ ...f, password: v }))} />
            </Field>
            <InsecureToggle
              checked={vmForm.insecure}
              onChange={v => setVmForm(f => ({ ...f, insecure: v }))}
            />
          </>
        ) : (
          <>
            <Field label="API Base URL" required>
              <input type="text" className="input"
                placeholder="https://cluster-ip:9440/PrismGateway/services/rest/v2.0"
                value={nxForm.base_url}
                onChange={e => setNxForm(f => ({ ...f, base_url: e.target.value }))} />
              <p className="mt-1 text-xs text-gray-400">
                Full URL including port and path, e.g. <code className="bg-gray-50 px-1 rounded">https://192.168.1.10:9440/PrismGateway/services/rest/v2.0</code>
              </p>
            </Field>
            <Field label="Username" required>
              <input type="text" className="input" placeholder="svc-readonly"
                value={nxForm.user}
                onChange={e => setNxForm(f => ({ ...f, user: e.target.value }))} />
            </Field>
            <Field label={configured ? 'Password (leave blank to keep existing)' : 'Password'}>
              <PasswordInput value={nxForm.password} show={showPw}
                placeholder={configured ? MASK : 'Enter password'}
                onToggle={() => setShowPw(s => !s)}
                onChange={v => setNxForm(f => ({ ...f, password: v }))} />
            </Field>
            <InsecureToggle
              checked={nxForm.insecure}
              onChange={v => setNxForm(f => ({ ...f, insecure: v }))}
            />
          </>
        )}

        {saveMutation.isError && <ErrorBanner message={`Failed to save ${isVmware ? 'VMware' : 'Nutanix'} settings.`} />}
        {testResult && <ConnectionTestBadge result={testResult} />}
      </div>

      {/* Card footer — actions + security note */}
      <div className="px-5 pb-5 space-y-3">
        <div className="flex items-center gap-2 pt-3 border-t border-gray-100">
          <button
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || saveDisabled}
            className="btn-primary"
          >
            {saveMutation.isPending ? <Spinner size="sm" /> : <Save className="h-4 w-4" />}
            Save
          </button>
          <button
            onClick={() => testMutation.mutate()}
            disabled={testMutation.isPending || !configured}
            className="btn-secondary"
            title={!configured ? 'Save credentials first' : 'Test connection using saved credentials'}
          >
            {testMutation.isPending
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <TestTube2 className="h-4 w-4" />}
            Test connection
          </button>
          {saveOk && (
            <span className="flex items-center gap-1 text-xs text-green-600 ml-1">
              <CheckCircle2 className="h-3.5 w-3.5" /> Saved
            </span>
          )}
          {hasChangedPw && !saveOk && (
            <span className="text-xs text-yellow-600 ml-1">Unsaved changes</span>
          )}
        </div>
        {/* Security note — small, at the bottom of the card */}
        <p className="flex items-center gap-1.5 text-xs text-gray-400">
          <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-primary-400" />
          Passwords are encrypted at rest. The mask {MASK} means a password is already saved — leave blank to keep it.
        </p>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sync Engine tab
// ---------------------------------------------------------------------------

/** Format a minute count into a human-readable string, e.g. 90 → "1 h 30 min" */
function fmtInterval(minutes: number): string {
  if (!minutes || minutes <= 0) return 'Enter a value ≥ 5 minutes'
  if (minutes < 60) return `Every ${minutes} minute${minutes === 1 ? '' : 's'}`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (m === 0) return `Every ${h} hour${h === 1 ? '' : 's'}`
  return `Every ${h} h ${m} min`
}

function SyncTab({ initial, qc }: { initial: SyncForm; qc: ReturnType<typeof useQueryClient> }) {
  const [form, setForm] = useState<SyncForm>({ ...initial })
  const [saveOk, setSaveOk] = useState(false)

  const mut = useMutation({
    mutationFn: () => updateSyncSettings(form as unknown as Record<string, unknown>),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      setSaveOk(true)
      setTimeout(() => setSaveOk(false), 3000)
    },
  })

  const num = (key: keyof SyncForm) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm(f => ({ ...f, [key]: e.target.value === '' ? 0 : parseFloat(e.target.value) }))

  return (
    <div className="card p-6 space-y-6 max-w-2xl">
      <div>
        <h2 className="text-base font-semibold text-gray-800">Sync Engine</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          Controls pagination, retry behaviour, and backoff timing for both platform adapters.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        {/* Sync intervals — top section */}
        <div className="sm:col-span-2">
          <h3 className="text-sm font-medium text-gray-700 mb-3 flex items-center gap-2">
            <span className="h-px flex-1 bg-gray-100" />
            <span className="text-gray-500 font-normal">Sync Intervals</span>
            <span className="h-px flex-1 bg-gray-100" />
          </h3>
        </div>
        <Field
          label="VMware sync interval (minutes)"
          hint="How often the scheduler syncs from vCenter. Changes take effect within 30 seconds.">
          <div className="relative">
            <input type="number" min={5} max={10080} step={1} className="input pr-16"
              value={form.vmware_interval_minutes}
              onChange={e => setForm(f => ({ ...f, vmware_interval_minutes: parseInt(e.target.value) || 240 }))} />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400 pointer-events-none">min</span>
          </div>
          <p className="mt-1 text-xs text-gray-400">{fmtInterval(form.vmware_interval_minutes)}</p>
        </Field>
        <Field
          label="Nutanix sync interval (minutes)"
          hint="How often the scheduler syncs from Prism Element. Changes take effect within 30 seconds.">
          <div className="relative">
            <input type="number" min={5} max={10080} step={1} className="input pr-16"
              value={form.nutanix_interval_minutes}
              onChange={e => setForm(f => ({ ...f, nutanix_interval_minutes: parseInt(e.target.value) || 240 }))} />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400 pointer-events-none">min</span>
          </div>
          <p className="mt-1 text-xs text-gray-400">{fmtInterval(form.nutanix_interval_minutes)}</p>
        </Field>

        {/* Retry settings — bottom section */}
        <div className="sm:col-span-2 mt-2">
          <h3 className="text-sm font-medium text-gray-700 mb-3 flex items-center gap-2">
            <span className="h-px flex-1 bg-gray-100" />
            <span className="text-gray-500 font-normal">Retry &amp; Pagination</span>
            <span className="h-px flex-1 bg-gray-100" />
          </h3>
        </div>
        <Field label="Page size"
          hint="VMs fetched per API page (Nutanix only — VMware uses ContainerView).">
          <input type="number" min={10} max={500} className="input"
            value={form.page_size} onChange={num('page_size')} />
        </Field>
        <Field label="Max retry attempts"
          hint="Retries per API call before the sync run is marked failed.">
          <input type="number" min={1} max={10} className="input"
            value={form.retry_max_attempts} onChange={num('retry_max_attempts')} />
        </Field>
        <Field label="Retry min wait (s)"
          hint="Shortest pause before the first retry.">
          <input type="number" min={0.5} max={60} step={0.5} className="input"
            value={form.retry_wait_min} onChange={num('retry_wait_min')} />
        </Field>
        <Field label="Retry max wait (s)"
          hint="Upper bound for exponential backoff.">
          <input type="number" min={1} max={300} step={1} className="input"
            value={form.retry_wait_max} onChange={num('retry_wait_max')} />
        </Field>
      </div>

      {mut.isError && <ErrorBanner message="Failed to save sync settings." />}

      <div className="flex items-center gap-3 pt-2 border-t border-gray-100">
        <button onClick={() => mut.mutate()} disabled={mut.isPending} className="btn-primary">
          {mut.isPending ? <Spinner size="sm" /> : <Save className="h-4 w-4" />}
          Save sync settings
        </button>
        {saveOk && (
          <span className="flex items-center gap-1 text-xs text-green-600">
            <CheckCircle2 className="h-3.5 w-3.5" /> Saved — takes effect on the next run
          </span>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// General tab
// ---------------------------------------------------------------------------
function GeneralTab({ initial, qc }: { initial: GeneralForm; qc: ReturnType<typeof useQueryClient> }) {
  const [form, setForm] = useState<GeneralForm>({ ...initial })
  const [saveOk, setSaveOk] = useState(false)

  const mut = useMutation({
    mutationFn: () => updateGeneralSettings(form as unknown as Record<string, unknown>),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      setSaveOk(true)
      setTimeout(() => setSaveOk(false), 3000)
    },
  })

  return (
    <div className="card p-6 space-y-6 max-w-2xl">
      <div>
        <h2 className="text-base font-semibold text-gray-800">General</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          Application-wide preferences that apply across all syncs and the UI.
        </p>
      </div>

      <Field
        label="Timezone"
        hint="All timestamps in sync logs, history, and the dashboard are displayed in this timezone."
      >
        <div className="relative">
          <Globe className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
          <select
            className="select pl-9"
            value={form.timezone}
            onChange={e => setForm(f => ({ ...f, timezone: e.target.value }))}
          >
            {TIMEZONES.map(tz => (
              <option key={tz} value={tz}>{tz}</option>
            ))}
          </select>
        </div>
        <p className="mt-1.5 text-xs text-gray-400">
          Current selection: <span className="font-medium text-gray-600">{form.timezone}</span>
          {' · '}
          <span>
            Local time: {new Date().toLocaleString('en-US', { timeZone: form.timezone, hour12: false,
              year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
          </span>
        </p>
      </Field>

      <Field
        label="Session idle timeout (minutes)"
        hint="Users are automatically signed out after this many minutes of inactivity, with a warning shown 2 minutes before expiry."
      >
        <input
          type="number"
          min={5}
          max={480}
          className="input w-32"
          value={form.session_idle_timeout_minutes}
          onChange={e => setForm(f => ({ ...f, session_idle_timeout_minutes: Number(e.target.value) }))}
        />
      </Field>

      {mut.isError && <ErrorBanner message="Failed to save general settings." />}

      <div className="flex items-center gap-3 pt-2 border-t border-gray-100">
        <button onClick={() => mut.mutate()} disabled={mut.isPending} className="btn-primary">
          {mut.isPending ? <Spinner size="sm" /> : <Save className="h-4 w-4" />}
          Save
        </button>
        {saveOk && (
          <span className="flex items-center gap-1 text-xs text-green-600">
            <CheckCircle2 className="h-3.5 w-3.5" /> Saved
          </span>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Database Backup tab
// ---------------------------------------------------------------------------

// The <input min={}/max={}> attributes are hints only — nothing stops a
// user from typing (or leaving, mid-edit) an out-of-range value and
// clicking Save, which the backend correctly 422s. Clamp defensively right
// before every save so an out-of-range value can never actually be sent.
function clampBackupForm(f: BackupForm): BackupForm {
  return {
    enabled: f.enabled,
    interval_minutes: Math.min(10080, Math.max(15, f.interval_minutes || 1440)),
    retention_count: Math.min(365, Math.max(1, f.retention_count || 10)),
  }
}

function formatFileSize(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

function BackupTab({ initial, files, qc }: {
  initial: BackupForm; files: BackupFile[]; qc: ReturnType<typeof useQueryClient>
}) {
  const [form, setForm] = useState<BackupForm>({ ...initial })
  const [saveOk, setSaveOk] = useState(false)
  const [runResult, setRunResult] = useState<{ status: 'ok' | 'error'; message: string } | null>(null)
  const [uploadError, setUploadError] = useState('')
  const [restoreTarget, setRestoreTarget] = useState<string | null>(null)
  const [restoreResult, setRestoreResult] = useState<{ status: 'ok' | 'error'; message: string } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [saveError, setSaveError] = useState('')

  const saveMutation = useMutation({
    mutationFn: () => updateBackupSettings(clampBackupForm(form) as unknown as Record<string, unknown>),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      setSaveError('')
      setSaveOk(true)
      setTimeout(() => setSaveOk(false), 3000)
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string | { msg?: string }[] } } })?.response?.data?.detail
      const message = Array.isArray(detail) ? (detail[0]?.msg || 'Failed to save backup settings.') : (detail || 'Failed to save backup settings.')
      setSaveError(message)
    },
  })

  const runMutation = useMutation({
    mutationFn: () => runBackupNow(),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      setRunResult({ status: 'ok', message: `Backup created: ${r.data.filename} (${formatFileSize(r.data.size_bytes)})` })
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setRunResult({ status: 'error', message: detail || 'Backup failed.' })
    },
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadBackup(file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      setUploadError('')
      if (fileInputRef.current) fileInputRef.current.value = ''
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setUploadError(detail || 'Upload failed.')
    },
  })

  function handleDownload(filename: string) {
    downloadBackup(filename).then(r => {
      const url = URL.createObjectURL(r.data as Blob)
      const a = document.createElement('a')
      a.href = url; a.download = filename; a.click()
      URL.revokeObjectURL(url)
    })
  }

  function handleFileChosen(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) uploadMutation.mutate(file)
  }

  return (
    <div className="space-y-5 max-w-3xl">
      {/* Schedule + retention */}
      <div className="card p-6 space-y-6">
        <div>
          <h2 className="text-base font-semibold text-gray-800">Database Backup</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Full PostgreSQL backups via <code className="bg-gray-50 px-1 rounded">pg_dump</code>, written to a
            host-mounted folder (<code className="bg-gray-50 px-1 rounded">./backup</code>) so they survive
            container recreation and can be copied to another machine for recovery.
          </p>
        </div>

        <label className="flex items-center gap-2.5 text-sm text-gray-700 cursor-pointer w-fit">
          <input type="checkbox" className="rounded border-gray-300 text-primary focus:ring-primary"
            checked={form.enabled}
            onChange={e => setForm(f => ({ ...f, enabled: e.target.checked }))} />
          <span className="font-medium">Enable scheduled backups</span>
        </label>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          <Field label="Backup interval (minutes)"
            hint="How often the scheduler takes an automatic backup. Changes take effect within 30 seconds.">
            <div className="relative">
              <input type="number" min={15} max={10080} step={1} className="input pr-16"
                disabled={!form.enabled}
                value={form.interval_minutes}
                onChange={e => setForm(f => ({ ...f, interval_minutes: parseInt(e.target.value) || 1440 }))}
                onBlur={() => setForm(f => ({ ...f, interval_minutes: Math.min(10080, Math.max(15, f.interval_minutes || 1440)) }))} />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400 pointer-events-none">min</span>
            </div>
            <p className="mt-1 text-xs text-gray-400">{fmtInterval(form.interval_minutes)} · minimum 15 minutes</p>
          </Field>
          <Field label="Retention (backups to keep)"
            hint="Oldest backups beyond this count are deleted automatically after each run.">
            <input type="number" min={1} max={365} className="input"
              value={form.retention_count}
              onChange={e => setForm(f => ({ ...f, retention_count: parseInt(e.target.value) || 10 }))}
              onBlur={() => setForm(f => ({ ...f, retention_count: Math.min(365, Math.max(1, f.retention_count || 10)) }))} />
          </Field>
        </div>

        {saveError && <ErrorBanner message={saveError} />}

        <div className="flex items-center gap-3 pt-2 border-t border-gray-100">
          <button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending} className="btn-primary">
            {saveMutation.isPending ? <Spinner size="sm" /> : <Save className="h-4 w-4" />}
            Save schedule
          </button>
          <button onClick={() => { setRunResult(null); runMutation.mutate() }} disabled={runMutation.isPending} className="btn-secondary">
            {runMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <HardDriveDownload className="h-4 w-4" />}
            Backup now
          </button>
          {saveOk && (
            <span className="flex items-center gap-1 text-xs text-green-600">
              <CheckCircle2 className="h-3.5 w-3.5" /> Saved
            </span>
          )}
        </div>

        {runResult && (
          <div className={`flex items-start gap-2.5 rounded-lg px-3 py-2.5 text-sm
            ${runResult.status === 'ok' ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-700'}`}>
            {runResult.status === 'ok'
              ? <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5 text-green-600" />
              : <XCircle className="h-4 w-4 shrink-0 mt-0.5 text-red-500" />}
            <p>{runResult.message}</p>
          </div>
        )}
      </div>

      {/* Upload from another machine */}
      <div className="card p-6 space-y-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-800">Upload a backup file</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Bring a <code className="bg-gray-50 px-1 rounded">.dump</code> file from another machine — it will
            appear in the list below, ready to restore.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <input
            ref={fileInputRef}
            type="file"
            accept=".dump"
            onChange={handleFileChosen}
            disabled={uploadMutation.isPending}
            className="text-sm text-gray-600 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0
              file:bg-primary-50 file:text-primary file:text-sm file:font-medium hover:file:bg-primary-100
              file:cursor-pointer cursor-pointer"
          />
          {uploadMutation.isPending && <Spinner size="sm" />}
        </div>
        {uploadError && <ErrorBanner message={uploadError} />}
      </div>

      {/* Existing backups */}
      <div className="card">
        <div className="flex items-center gap-2 px-5 py-4 border-b border-gray-100">
          <History className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold text-gray-800">Existing Backups</h3>
          <span className="badge badge-gray">{files.length}</span>
        </div>
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Filename</th>
                <th>Created</th>
                <th>Size</th>
                <th>Download</th>
                <th>Restore</th>
              </tr>
            </thead>
            <tbody>
              {files.length === 0 && (
                <tr><td colSpan={5} className="text-center text-gray-400 py-8">No backups yet — run one above.</td></tr>
              )}
              {files.map(f => (
                <tr key={f.filename}>
                  <td className="font-mono text-xs">{f.filename}</td>
                  <td className="text-xs text-gray-500 whitespace-nowrap">{formatDate(f.created_at)}</td>
                  <td className="text-xs text-gray-500">{formatFileSize(f.size_bytes)}</td>
                  <td>
                    <button onClick={() => handleDownload(f.filename)} className="btn-ghost !px-2 !py-1" title="Download">
                      <Download className="h-4 w-4" />
                    </button>
                  </td>
                  <td>
                    <button
                      onClick={() => { setRestoreResult(null); setRestoreTarget(f.filename) }}
                      className="btn-ghost !px-2 !py-1 text-red-500 hover:bg-red-50"
                      title="Restore this backup"
                    >
                      <ArchiveRestore className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {restoreResult && (
        <div className={`flex items-start gap-2.5 rounded-lg px-4 py-3 text-sm
          ${restoreResult.status === 'ok' ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-700'}`}>
          {restoreResult.status === 'ok'
            ? <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5 text-green-600" />
            : <XCircle className="h-4 w-4 shrink-0 mt-0.5 text-red-500" />}
          <p>{restoreResult.message}</p>
        </div>
      )}

      {restoreTarget && (
        <RestoreConfirmModal
          filename={restoreTarget}
          onClose={() => setRestoreTarget(null)}
          onDone={(result) => {
            setRestoreTarget(null)
            setRestoreResult(result)
            qc.invalidateQueries({ queryKey: ['settings'] })
          }}
        />
      )}
    </div>
  )
}

// Requires typing the exact filename before Restore is enabled — this is a
// full-DB-replacing action, so it gets stronger friction than a plain
// confirm dialog (matching the severity of what it does).
function RestoreConfirmModal({ filename, onClose, onDone }: {
  filename: string
  onClose: () => void
  onDone: (result: { status: 'ok' | 'error'; message: string }) => void
}) {
  const [typed, setTyped] = useState('')
  const [error, setError] = useState('')

  const mut = useMutation({
    mutationFn: () => restoreBackup(filename),
    onSuccess: (r) => onDone({ status: 'ok', message: r.data.message || `Restored from ${filename}.` }),
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Restore failed.')
    },
  })

  const canConfirm = typed === filename

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="card max-w-lg w-full p-6 space-y-4">
        <div className="flex items-start gap-3">
          <div className="shrink-0 rounded-full bg-red-100 p-2">
            <AlertTriangle className="h-5 w-5 text-red-600" />
          </div>
          <div className="min-w-0">
            <h3 className="font-semibold text-gray-800">Restore database from backup?</h3>
            <p className="text-sm text-gray-500 mt-1">
              This <span className="font-semibold text-red-600">completely replaces all current data</span> with
              the contents of <code className="bg-gray-50 px-1 rounded break-all">{filename}</code>. Anything
              created or changed since that backup will be lost. If the restore fails partway, the current
              database is left untouched. You may need to sign in again afterward.
            </p>
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">
            Type the filename to confirm
          </label>
          <input
            type="text"
            className="input font-mono text-xs"
            value={typed}
            onChange={e => setTyped(e.target.value)}
            placeholder={filename}
            autoFocus
          />
        </div>

        {error && <ErrorBanner message={error} />}

        <div className="flex gap-2 pt-1">
          <button
            onClick={() => mut.mutate()}
            className="btn-primary !bg-red-600 hover:!bg-red-700 focus:!ring-red-400"
            disabled={!canConfirm || mut.isPending}
          >
            {mut.isPending ? <Spinner size="sm" /> : <ArchiveRestore className="h-4 w-4" />}
            Restore &amp; overwrite
          </button>
          <button type="button" onClick={onClose} className="btn-ghost" disabled={mut.isPending}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function Field({ label, children, required, hint }: {
  label: string; children: React.ReactNode; required?: boolean; hint?: string
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">
        {label}{required && <span className="ml-0.5 text-red-400">*</span>}
      </label>
      {children}
      {hint && <p className="mt-1.5 text-xs text-gray-400 leading-relaxed">{hint}</p>}
    </div>
  )
}

function PasswordInput({ value, show, onToggle, onChange, placeholder }: {
  value: string; show: boolean; onToggle: () => void
  onChange: (v: string) => void; placeholder?: string
}) {
  return (
    <div className="relative">
      <input
        type={show ? 'text' : 'password'}
        className="input pr-10"
        placeholder={placeholder}
        value={value}
        onChange={e => onChange(e.target.value)}
        autoComplete="new-password"
      />
      <button type="button" onClick={onToggle} tabIndex={-1}
        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
        aria-label={show ? 'Hide password' : 'Show password'}>
        {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  )
}

function InsecureToggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2.5 text-sm text-gray-600 cursor-pointer w-fit">
      <input type="checkbox"
        className="rounded border-gray-300 text-primary focus:ring-primary"
        checked={checked}
        onChange={e => onChange(e.target.checked)} />
      <span>
        Skip SSL verification
        <span className="ml-1 text-xs text-gray-400">(self-signed certs / lab only)</span>
      </span>
    </label>
  )
}

function ConnectionTestBadge({ result }: { result: TestResult }) {
  const ok = result.status === 'ok'
  return (
    <div className={`flex items-start gap-2.5 rounded-lg px-3 py-2.5 text-sm
      ${ok ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-700'}`}>
      {ok
        ? <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5 text-green-600" />
        : <XCircle className="h-4 w-4 shrink-0 mt-0.5 text-red-500" />}
      <div>
        <p className="font-medium">{result.message}</p>
        {result.detail && <p className="text-xs mt-0.5 opacity-80">{result.detail}</p>}
      </div>
    </div>
  )
}
