import { useEffect, useRef, useState } from 'react'
import { Columns3 } from 'lucide-react'

export interface ColumnOption {
  key: string
  label: string
  group: string
}

interface ColumnPickerProps {
  columns: ColumnOption[]
  visible: Set<string>
  onChange: (next: Set<string>) => void
}

// Anchored checklist dropdown — lets the caller toggle which optional table
// columns are shown. Closes on outside click; selection is fully controlled
// by the parent (which owns persistence, e.g. to localStorage).
export default function ColumnPicker({ columns, visible, onChange }: ColumnPickerProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [open])

  function toggle(key: string) {
    const next = new Set(visible)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    onChange(next)
  }

  const groups: { name: string; cols: ColumnOption[] }[] = []
  for (const col of columns) {
    let g = groups.find(g => g.name === col.group)
    if (!g) { g = { name: col.group, cols: [] }; groups.push(g) }
    g.cols.push(col)
  }

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(o => !o)} className={open ? 'btn-primary' : 'btn-secondary'}>
        <Columns3 className="h-4 w-4" />
        Columns
      </button>
      {open && (
        <div className="card absolute right-0 z-20 mt-2 w-64 p-3 max-h-96 overflow-y-auto">
          {groups.map(g => (
            <div key={g.name} className="mb-3 last:mb-0">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1.5">{g.name}</p>
              <div className="space-y-1">
                {g.cols.map(c => (
                  <label key={c.key} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer py-0.5">
                    <input
                      type="checkbox"
                      className="rounded border-gray-300 text-primary focus:ring-primary"
                      checked={visible.has(c.key)}
                      onChange={() => toggle(c.key)}
                    />
                    {c.label}
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
