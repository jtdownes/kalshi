import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import './index.css'
import App from './App'

function Root() {
  const [authChecked, setAuthChecked] = useState(false)

  useEffect(() => {
    fetch('/api/auth/status')
      .then(r => r.json())
      .then((data: { logged_in: boolean }) => {
        if (!data.logged_in) {
          window.location.href = 'https://jtdownes.com'
        } else {
          setAuthChecked(true)
        }
      })
      .catch(() => {
        window.location.href = 'https://jtdownes.com'
      })
  }, [])

  if (!authChecked) return null

  return (
    <StrictMode>
      <HashRouter>
        <App />
      </HashRouter>
    </StrictMode>
  )
}

createRoot(document.getElementById('root')!).render(<Root />)
