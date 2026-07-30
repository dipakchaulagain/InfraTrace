import { type LucideIcon } from 'lucide-react'
import { cn } from '../lib/utils'

interface StatCardProps {
  label: string
  value: string | number
  icon: LucideIcon
  trend?: string
  color?: 'teal' | 'green' | 'red' | 'yellow' | 'gray'
  loading?: boolean
  onClick?: () => void
}

const colorMap = {
  teal:   'bg-primary-50 text-primary',
  green:  'bg-mint-100 text-mint-700',
  red:    'bg-red-50 text-red-500',
  yellow: 'bg-yellow-50 text-yellow-600',
  gray:   'bg-gray-100 text-gray-500',
}

export default function StatCard({
  label, value, icon: Icon, trend, color = 'teal', loading = false, onClick,
}: StatCardProps) {
  const Wrapper = onClick ? 'button' : 'div'
  return (
    <Wrapper
      className={cn(
        'card p-5 w-full text-left hover:shadow-card-hover transition-shadow duration-200',
        onClick && 'cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary-400',
      )}
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">{label}</p>
          {loading ? (
            <div className="skeleton h-7 w-20 rounded" />
          ) : (
            <p className="text-2xl font-bold text-gray-800">{value}</p>
          )}
          {trend && !loading && (
            <p className="text-xs text-gray-400 mt-1">{trend}</p>
          )}
        </div>
        <div className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-lg', colorMap[color])}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </Wrapper>
  )
}
