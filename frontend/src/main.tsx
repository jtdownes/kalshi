import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import './index.css'
import App from './App'
import Login from './pages/Login'

function Root() {
  const [authChecked, setAuthChecked] = useState(false)
  const [loggedIn,    setLoggedIn]    = useState(false)

  useEffect(() => {
    fetch('/api/auth/status')
      .then(r => r.json())
      .then((d: { logged_in: boolean }) => {
        setLoggedIn(d.logged_in)
        setAuthChecked(true)
      })
      .catch(() => setAuthChecked(true))
  }, [])

  if (!authChecked) return null

  if (!loggedIn) {
    return <Login onLogin={() => setLoggedIn(true)} />
  }

  return (
    <StrictMode>
      <HashRouter>
        <App />
      </HashRouter>
    </StrictMode>
  )
}

createRoot(document.getElementById('root')!).render(<Root />)
