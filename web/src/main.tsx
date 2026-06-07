import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/globals.css'

// NOTE: StrictMode intentionally double-mounts components in dev, which tears
// down and re-opens the per-camera stream WebSocket mid-handshake ("closed
// before connection established") and prevents the video from ever settling.
// Disabled so the live stream connects cleanly.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <App />,
)

