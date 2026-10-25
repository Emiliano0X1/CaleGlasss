/**
 * Agent team panel: live view of the `agentes` SpacetimeDB database (stdb/).
 * Settings come from .env.local (see .env.example).
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { SpacetimeDBProvider } from 'spacetimedb/react'
import { DbConnection } from './module_bindings'
import './index.css'
import App from './App.tsx'

const TOKEN_KEY = 'agentes-panel-token'

function savedToken(): string | undefined {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? undefined
  } catch {
    return undefined
  }
}

// Read-only client: an anonymous identity is enough, the token is kept so a reload reuses it.
const connectionBuilder = DbConnection.builder()
  .withUri(import.meta.env.VITE_STDB_URI || 'wss://maincloud.spacetimedb.com')
  .withDatabaseName(import.meta.env.VITE_STDB_DATABASE || 'agentes')
  .withToken(savedToken())
  .onConnect((_conn, identity, token) => {
    try {
      localStorage.setItem(TOKEN_KEY, token)
    } catch {
      // private window: a new identity on each reload is fine
    }
    console.log('panel: connected as', identity.toHexString())
  })
  .onConnectError((_ctx, error) => console.error('panel: connection failed:', error))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <SpacetimeDBProvider connectionBuilder={connectionBuilder}>
      <App />
    </SpacetimeDBProvider>
  </StrictMode>,
)
