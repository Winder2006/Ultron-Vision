import { useState, useEffect, useCallback } from 'react';
import { api, eventsWS, UIConfig, SystemStatus, WSEvent, Face, ActivityAlert, TrackingStatus } from './api/client';
import Layout from './components/Layout';
import CameraGrid from './components/CameraGrid';
import ActivityFeed from './components/ActivityFeed';
import CrewManifest from './components/CrewManifest';
import RecordingTimeline from './components/RecordingTimeline';
import CameraDetail from './components/CameraDetail';

type View = 'cameras' | 'activity' | 'crew' | 'recordings' | 'settings';

interface AppState {
  config: UIConfig | null;
  status: SystemStatus | null;
  faces: Record<string, Face[]>;
  alerts: ActivityAlert[];
  tracking: Record<string, TrackingStatus>;
  connected: boolean;
  selectedCamera: string | null;
}

export default function App() {
  const [view, setView] = useState<View>('cameras');
  const [state, setState] = useState<AppState>({
    config: null,
    status: null,
    faces: {},
    alerts: [],
    tracking: {},
    connected: false,
    selectedCamera: null,
  });

  // Load initial config and status
  useEffect(() => {
    const loadInitialData = async () => {
      console.log('Loading initial data...');
      try {
        // Load config first
        const config = await api.getUIConfig();
        console.log('Config loaded:', config);
        
        // Load status
        const status = await api.getStatus();
        console.log('Status loaded:', status);
        
        // Update state immediately with config and status
        setState(prev => ({
          ...prev,
          config,
          status,
          connected: true,
        }));
        console.log('Initial state updated');
        
        // Load alerts separately (non-blocking)
        try {
          const alerts = await api.getActivityAlerts({ hours: 24 });
          console.log('Alerts loaded:', alerts);
          setState(prev => ({ ...prev, alerts }));
        } catch (alertError) {
          console.warn('Failed to load alerts:', alertError);
        }
        
      } catch (error) {
        console.error('Failed to load initial data:', error);
      }
    };

    loadInitialData();
  }, []);

  // Connect to events WebSocket
  useEffect(() => {
    eventsWS.connect();

    const unsubscribe = eventsWS.subscribe((event: WSEvent) => {
      switch (event.type) {
        case 'faces_detected':
          if (event.camera_id) {
            setState(prev => ({
              ...prev,
              faces: {
                ...prev.faces,
                [event.camera_id!]: (event.data.faces as Face[]) || [],
              },
            }));
          }
          break;

        case 'activity_alert':
          setState(prev => ({
            ...prev,
            alerts: [
              {
                camera_id: event.camera_id || '',
                timestamp: event.timestamp,
                ...(event.data as Omit<ActivityAlert, 'camera_id' | 'timestamp'>),
              },
              ...prev.alerts,
            ].slice(0, 100),
          }));
          break;

        case 'tracking_status':
          if (event.camera_id) {
            setState(prev => ({
              ...prev,
              tracking: {
                ...prev.tracking,
                [event.camera_id!]: event.data as unknown as TrackingStatus,
              },
            }));
          }
          break;

        case 'system_status':
          setState(prev => ({
            ...prev,
            status: event.data as unknown as SystemStatus,
            connected: true,
          }));
          break;

        case 'camera_status':
          setState(prev => {
            if (!prev.status) return prev;
            const cameraStatus = event.data as { camera_id: string; online: boolean; fps: number };
            return {
              ...prev,
              status: {
                ...prev.status,
                cameras: prev.status.cameras.map(c =>
                  c.camera_id === cameraStatus.camera_id
                    ? { ...c, ...cameraStatus }
                    : c
                ),
              },
            };
          });
          break;
      }
    });

    return () => {
      unsubscribe();
      eventsWS.disconnect();
    };
  }, []);

  // Poll for status updates
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const status = await api.getStatus();
        setState(prev => ({ ...prev, status, connected: true }));
      } catch {
        setState(prev => ({ ...prev, connected: false }));
      }
    }, 10000);

    return () => clearInterval(interval);
  }, []);

  const handleSelectCamera = useCallback((cameraId: string | null) => {
    setState(prev => ({ ...prev, selectedCamera: cameraId }));
  }, []);

  const alertCount = state.alerts.filter(
    a => new Date(a.timestamp) > new Date(Date.now() - 3600000)
  ).length;

  // Show camera detail view if a camera is selected
  if (state.selectedCamera && state.config) {
    const camera = state.config.cameras.find(c => c.id === state.selectedCamera);
    if (camera) {
      return (
        <Layout
          currentView={view}
          onNavigate={setView}
          status={state.status}
          alertCount={alertCount}
          connected={state.connected}
        >
          <CameraDetail
            camera={camera}
            faces={state.faces[camera.id] || []}
            tracking={state.tracking[camera.id]}
            onBack={() => handleSelectCamera(null)}
          />
        </Layout>
      );
    }
  }

  return (
    <Layout
      currentView={view}
      onNavigate={setView}
      status={state.status}
      alertCount={alertCount}
      connected={state.connected}
    >
      {view === 'cameras' && state.config && (
        <CameraGrid
          cameras={state.config.cameras}
          statuses={state.status?.cameras || []}
          faces={state.faces}
          tracking={state.tracking}
          maxPerRow={state.config.max_cameras_per_row}
          onSelectCamera={handleSelectCamera}
        />
      )}

      {view === 'activity' && (
        <ActivityFeed
          alerts={state.alerts}
          cameras={state.config?.cameras || []}
        />
      )}

      {view === 'crew' && (
        <CrewManifest
          faces={state.faces}
          cameras={state.config?.cameras || []}
        />
      )}

      {view === 'recordings' && (
        <RecordingTimeline cameras={state.config?.cameras || []} />
      )}

      {view === 'settings' && (
        <div className="p-6">
          <h2 className="text-2xl font-display font-bold text-terminal-accent mb-6">
            SYSTEM SETTINGS
          </h2>
          <div className="card p-6 max-w-2xl">
            <h3 className="text-lg font-semibold mb-4">Configuration</h3>
            <p className="text-terminal-muted">
              Settings are managed via config.yaml on the backend.
            </p>
            <div className="mt-6 space-y-4">
              <div>
                <label className="block text-sm text-terminal-muted mb-1">API Base URL</label>
                <input
                  type="text"
                  className="input w-full"
                  value={import.meta.env.VITE_API_BASE_URL || 'http://localhost:8200'}
                  readOnly
                />
              </div>
              <div>
                <label className="block text-sm text-terminal-muted mb-1">Cameras Configured</label>
                <div className="text-terminal-accent text-2xl font-bold">
                  {state.config?.cameras.length || 0}
                </div>
              </div>
              <div>
                <label className="block text-sm text-terminal-muted mb-1">System Uptime</label>
                <div className="text-terminal-accent text-2xl font-bold">
                  {state.status ? formatUptime(state.status.uptime_seconds) : '--'}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {!state.config && (
        <div className="flex items-center justify-center h-full">
          <div className="text-center">
            <div className="w-16 h-16 border-4 border-terminal-accent border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <p className="text-terminal-muted">Initializing ULTRON VISION...</p>
          </div>
        </div>
      )}
    </Layout>
  );
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  if (days > 0) {
    return `${days}d ${hours}h ${minutes}m`;
  }
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m`;
}

