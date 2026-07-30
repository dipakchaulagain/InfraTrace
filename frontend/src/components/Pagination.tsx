import { ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '../lib/utils'

interface PaginationProps {
  page: number
  pageSize: number
  total: number
  onPage: (p: number) => void
}

export default function Pagination({ page, pageSize, total, onPage }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const from = Math.min((page - 1) * pageSize + 1, total)
  const to = Math.min(page * pageSize, total)

  return (
    <div className="flex items-center justify-between px-1 py-3 text-sm text-gray-500">
      <span>
        {total === 0 ? 'No results' : `${from}–${to} of ${total}`}
      </span>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onPage(page - 1)}
          disabled={page <= 1}
          className="btn-ghost !px-2 !py-1 disabled:opacity-40"
          aria-label="Previous page"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
          // Simple page number logic for up to 7 visible pages
          let p: number
          if (totalPages <= 7) {
            p = i + 1
          } else if (page <= 4) {
            p = i + 1
          } else if (page >= totalPages - 3) {
            p = totalPages - 6 + i
          } else {
            p = page - 3 + i
          }
          return (
            <button
              key={p}
              onClick={() => onPage(p)}
              className={cn(
                'min-w-[2rem] h-8 rounded-lg text-sm font-medium transition-colors',
                p === page
                  ? 'bg-primary text-white'
                  : 'text-gray-600 hover:bg-primary-50',
              )}
            >
              {p}
            </button>
          )
        })}
        <button
          onClick={() => onPage(page + 1)}
          disabled={page >= totalPages}
          className="btn-ghost !px-2 !py-1 disabled:opacity-40"
          aria-label="Next page"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
