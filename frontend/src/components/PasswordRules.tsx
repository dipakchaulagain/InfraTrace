import { Check, X } from 'lucide-react'

export const PASSWORD_MIN_LENGTH = 10

interface Rule { label: string; test: (pw: string) => boolean }

const RULES: Rule[] = [
  { label: `At least ${PASSWORD_MIN_LENGTH} characters`, test: pw => pw.length >= PASSWORD_MIN_LENGTH },
  { label: 'An uppercase letter', test: pw => /[A-Z]/.test(pw) },
  { label: 'A lowercase letter', test: pw => /[a-z]/.test(pw) },
  { label: 'A number', test: pw => /[0-9]/.test(pw) },
  { label: 'A special character', test: pw => /[^A-Za-z0-9]/.test(pw) },
]

export function isPasswordValid(pw: string): boolean {
  return RULES.every(r => r.test(pw))
}

export default function PasswordRules({ password }: { password: string }) {
  return (
    <ul className="mt-1.5 space-y-0.5">
      {RULES.map(r => {
        const ok = r.test(password)
        return (
          <li key={r.label} className={`flex items-center gap-1.5 text-xs ${ok ? 'text-green-600' : 'text-gray-400'}`}>
            {ok ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
            {r.label}
          </li>
        )
      })}
    </ul>
  )
}
