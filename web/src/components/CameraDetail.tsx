import { useState, useEffect } from 'react';
import { Camera, Face, TrackingStatus, MotionStatus, api } from '../api/client';
import VideoCanvas from './VideoCanvas';
import PTZControls from './PTZControls';
import {
  ArrowLeft,
  Camera as CameraIcon,
  Save,
  User,
  UserX,
  Activity,
} from 'lucide-react';

interface CameraDetailProps {
  camera: Camera;
  faces: Face[];
  tracking?: TrackingStatus;
  onBack: () => void;
}

export default function CameraDetail({
  camera,
  faces,
  tracking,
  onBack,
}: CameraDetailProps) {
  const [motionStatus, setMotionStatus] = useState<MotionStatus | null>(null);
  const [recentEvents, setRecentEvents] = useState<Array<{
    type: string;
    time: Date;
    description: string;
  }>>([]);

  // Load motion status
  useEffect(() => {
    const loadMotion = async () => {
      try {
        const statuses = await api.getMotion();
        const status = statuses.find(s => s.camera_id === camera.id);
        if (status) setMotionStatus(status);
      } catch (error) {
        console.error('Failed to load motion status:', error);
      }
    };

    loadMotion();
    const interval = setInterval(loadMotion, 2000);
    return () => clearInterval(interval);
  }, [camera.id]);

  // Track face events
  useEffect(() => {
    if (faces.length > 0) {
      const knownNames = faces.filter(f => f.known).map(f => f.name);
      const unknownCount = faces.filter(f => !f.known).length;
      
      if (knownNames.length > 0 || unknownCount > 0) {
        const description = [
          knownNames.length > 0 ? knownNames.join(', ') : null,
          unknownCount > 0 ? `${unknownCount} unknown` : null,
        ].filter(Boolean).join(' + ');
        
        setRecentEvents(prev => [
          {
            type: 'face',
            time: new Date(),
            description: `Detected: ${description}`,
          },
          ...prev.slice(0, 19),
        ]);
      }
    }
  }, [faces]);

  const handleSaveSnapshot = async () => {
    try {
      await api.saveSnapshot(camera.id);
      setRecentEvents(prev => [
        {
          type: 'snapshot',
          time: new Date(),
          description: 'Snapshot saved',
        },
        ...prev.slice(0, 19),
      ]);
    } catch (error) {
      console.error('Failed to save snapshot:', error);
    }
  };

  const knownFaces = faces.filter(f => f.known);
  const unknownFaces = faces.filter(f => !f.known);

  return (
    <div className="h-full flex flex-col lg:flex-row">
      {/* Main Video Area */}
      <div className="flex-1 flex flex-col min-h-0">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-terminal-border">
          <div className="flex items-center gap-4">
            <button
              onClick={onBack}
              className="btn-secondary p-2"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-2">
              <CameraIcon className="w-5 h-5 text-terminal-accent" />
              <h2 className="text-xl font-display font-bold text-terminal-text">
                {camera.name}
              </h2>
              {camera.ptz_enabled && (
                <span className="badge-info">PTZ</span>
              )}
            </div>
          </div>
          
          <button
            onClick={handleSaveSnapshot}
            className="btn-secondary flex items-center gap-2"
          >
            <Save className="w-4 h-4" />
            <span className="hidden sm:inline">Save Snapshot</span>
          </button>
        </div>

        {/* Video */}
        <div className="flex-1 bg-black relative min-h-0">
          <VideoCanvas
            cameraId={camera.id}
            faces={faces}
            tracking={tracking}
            motionRegions={motionStatus?.regions}
          />
          
          {/* Overlay info */}
          <div className="absolute top-4 left-4 flex flex-col gap-2">
            {tracking?.active && (
              <div className="glass px-3 py-2 rounded text-sm">
                <span className="text-terminal-accent">
                  Tracking: {tracking.target_name}
                </span>
                <span className="text-terminal-muted ml-2">
                  ({tracking.tracking_state})
                </span>
              </div>
            )}
            
            {motionStatus?.motion_detected && (
              <div className="glass px-3 py-2 rounded text-sm flex items-center gap-2">
                <Activity className="w-4 h-4 text-terminal-warning" />
                <span className="text-terminal-warning">Motion Detected</span>
              </div>
            )}
          </div>

          {/* Face count overlay */}
          <div className="absolute bottom-4 left-4 flex gap-2">
            {knownFaces.length > 0 && (
              <div className="glass px-3 py-2 rounded flex items-center gap-2">
                <User className="w-4 h-4 text-terminal-accent" />
                <span className="text-terminal-accent">{knownFaces.length} known</span>
              </div>
            )}
            {unknownFaces.length > 0 && (
              <div className="glass px-3 py-2 rounded flex items-center gap-2">
                <UserX className="w-4 h-4 text-terminal-danger" />
                <span className="text-terminal-danger">{unknownFaces.length} unknown</span>
              </div>
            )}
          </div>
        </div>

        {/* Face details bar */}
        {faces.length > 0 && (
          <div className="p-4 border-t border-terminal-border bg-terminal-surface">
            <div className="flex flex-wrap gap-2">
              {faces.map((face, i) => (
                <div
                  key={i}
                  className={`px-3 py-2 rounded flex items-center gap-2 ${
                    face.known
                      ? 'bg-terminal-accent/20 border border-terminal-accent/30'
                      : 'bg-terminal-danger/20 border border-terminal-danger/30'
                  }`}
                >
                  {face.known ? (
                    <User className="w-4 h-4 text-terminal-accent" />
                  ) : (
                    <UserX className="w-4 h-4 text-terminal-danger" />
                  )}
                  <span className={face.known ? 'text-terminal-accent' : 'text-terminal-danger'}>
                    {face.name}
                  </span>
                  <span className="text-terminal-muted text-sm">
                    {Math.round(face.confidence * 100)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Sidebar */}
      <div className="w-full lg:w-80 border-t lg:border-t-0 lg:border-l border-terminal-border bg-terminal-surface flex flex-col overflow-hidden">
        {/* PTZ Controls */}
        {camera.ptz_enabled && (
          <div className="p-4 border-b border-terminal-border">
            <PTZControls
              cameraId={camera.id}
              visibleFaces={faces}
            />
          </div>
        )}

        {/* Event Feed */}
        <div className="flex-1 overflow-auto p-4">
          <h3 className="font-display font-semibold text-terminal-accent mb-3">
            LIVE EVENTS
          </h3>
          
          {recentEvents.length === 0 ? (
            <p className="text-terminal-muted text-sm">No recent events</p>
          ) : (
            <div className="space-y-2">
              {recentEvents.map((event, i) => (
                <div
                  key={i}
                  className="text-sm p-2 rounded bg-terminal-bg border border-terminal-border"
                >
                  <div className="flex items-center justify-between">
                    <span className={`badge ${
                      event.type === 'face'
                        ? 'badge-success'
                        : event.type === 'motion'
                          ? 'badge-warning'
                          : 'badge-info'
                    }`}>
                      {event.type}
                    </span>
                    <span className="text-terminal-muted text-xs">
                      {formatTime(event.time)}
                    </span>
                  </div>
                  <p className="text-terminal-text mt-1">{event.description}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

