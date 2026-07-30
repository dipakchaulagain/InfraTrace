import { AlertCircle, RefreshCw } from 'lucide-react'

interface ErrorBannerProps {
  message?: string
  onRetry?: () => void
}

export default function ErrorBanner({ message = 'Something went wrong.', onRetry }: ErrorBannerProps) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4">
      <AlertCircle className="h-5 w-5 text-red-500 mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-red-700">{message}</p>
      </div>
      {onRetry && (
        <button onClick={onRetry} className="btn-ghost !px-2 !py-1 text-red-600 hover:bg-red-100">
          <RefreshCw className="h-4 w-4" />
          Retry
        </button>
      )}
    </div>
  )
}
