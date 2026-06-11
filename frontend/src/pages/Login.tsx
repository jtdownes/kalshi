import { useState, FormEvent } from 'react'
import '../styles/auth.css'

interface Props {
  onLogin: (username: string) => void
}

export default function Login({ onLogin }: Props) {
  const [usernameEmail, setUsernameEmail]       = useState('')
  const [password, setPassword]                 = useState('')
  const [usernameEmailError, setUsernameEmailError] = useState('')
  const [passwordError, setPasswordError]       = useState('')
  const [submitting, setSubmitting]             = useState(false)

  function validateUsernameEmail(value: string): boolean {
    if (value.length === 0) { setUsernameEmailError(''); return false }
    if (value.includes('@')) {
      const valid = /^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/.test(value)
      if (!valid) { setUsernameEmailError('Please enter a valid email address.'); return false }
    } else {
      const valid = /^[a-zA-Z0-9]+$/.test(value)
      if (!valid) { setUsernameEmailError('Username cannot contain special characters or spaces.'); return false }
    }
    setUsernameEmailError('')
    return true
  }

  const isValid = usernameEmail.trim().length > 0 && !usernameEmailError && password.length > 0

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!isValid || submitting) return
    setSubmitting(true)

    const trimmed = usernameEmail.trim()
    // Backend accepts username or email under the `username` key.
    const fields  = { username: trimmed, password }

    try {
      const res  = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields),
      })
      const json = await res.json()

      if (res.ok && json.ok) {
        onLogin(json.username)
      } else {
        setPasswordError(json.error || 'Login failed.')
      }
    } catch {
      setPasswordError('Network error. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-wrapper">
      <div className="auth-container">
        <div className="auth-header">
          <h1>Kalshi Bot</h1>
          <p>Sign in with your jtdownes.com account</p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <section className="form-group">
            <label htmlFor="username-email">Username or Email</label>
            <input
              id="username-email"
              type="text"
              placeholder="username or email@example.com"
              value={usernameEmail}
              onChange={e => { setUsernameEmail(e.target.value); validateUsernameEmail(e.target.value.trim()) }}
              className={usernameEmailError ? 'input-error' : ''}
              autoComplete="username"
              autoFocus
            />
            {usernameEmailError && <div className="flashed-message">{usernameEmailError}</div>}
          </section>

          <section className="form-group">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={e => { setPassword(e.target.value); if (e.target.value.length > 0) setPasswordError('') }}
              className={passwordError ? 'input-error' : ''}
              autoComplete="current-password"
            />
            {passwordError && <div className="flashed-message">{passwordError}</div>}
          </section>

          <button
            type="submit"
            className="btn-auth btn-login"
            disabled={!isValid || submitting}
          >
            {submitting ? 'Signing in…' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  )
}
