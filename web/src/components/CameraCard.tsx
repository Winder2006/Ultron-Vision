import { Camera, CameraStatus, Face, TrackingStatus } from '../api/client';
import VideoCanvas from './VideoCanvas';
import { Maximize2, VideoOff, Target, User, UserX } from 'lucide-react';

interface CameraCardProps {
  camera: Camera;
  status?: CameraStatus;
  faces: Face[];
  tracking?: TrackingStatus;
  onClick: () => void;
}

export default function CameraCard({
  camera,
  status,
  faces,
  tracking,
  onClick,
}: CameraCardProps) {
  const isOnline = status?.online ?? false;
  const fps = status?.fps ?? 0;

  const knownFaces = faces.filter(f => f.known);
  const unknownFaces = faces.filter(f => !f.known);

  return (
    <div 
      className="card-hover group cursor-pointer overflow-hidden"
      onClick={onClick}
    >
      {/* Video Area */}
      <div className="relative aspect-video bg-black">
        {isOnline ? (
          <VideoCanvas
            cameraId={camera.id}
            faces={faces}
            tracking={tracking}
          />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-terminal-surface">
            <VideoOff className="w-12 h-12 text-terminal-danger mb-2" />
            <span className="text-terminal-danger text-sm">OFFLINE</span>
          </div>
        )}

        {/* Tracking indicator */}
        {tracking?.active && (
          <div className="absolute top-2 right-2 flex items-center gap-1.5 px-2 py-1 rounded bg-terminal-accent/90 text-terminal-bg text-xs font-medium">
            <Target className="w-3 h-3" />
            <span>Tracking: {tracking.target_name}</span>
          </div>
        )}

        {/* Expand button */}
        <button
          className="absolute top-2 left-2 p-1.5 rounded bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity"
          onClick={(e) => {
            e.stopPropagation();
            onClick();
          }}
        >
          <Maximize2 className="w-4 h-4" />
        </button>

        {/* Face count indicators */}
        <div className="absolute bottom-2 left-2 flex items-center gap-2">
          {knownFaces.length > 0 && (
            <div className="flex items-center gap-1 px-2 py-1 rounded bg-terminal-accent/90 text-terminal-bg text-xs font-medium">
              <User className="w-3 h-3" />
              <span>{knownFaces.length}</span>
            </div>
          )}
          {unknownFaces.length > 0 && (
            <div className="flex items-center gap-1 px-2 py-1 rounded bg-terminal-danger/90 text-white text-xs font-medium">
              <UserX className="w-3 h-3" />
              <span>{unknownFaces.length}</span>
            </div>
          )}
        </div>
      </div>

      {/* Info Bar */}
      <div className="p-3 border-t border-terminal-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${isOnline ? 'bg-terminal-accent animate-pulse' : 'bg-terminal-danger'}`} />
            <span className="font-medium text-terminal-text">{camera.name}</span>
          </div>
          
          <div className="flex items-center gap-3 text-xs text-terminal-muted">
            {isOnline && (
              <>
                <span>{Math.round(fps)} FPS</span>
                {camera.ptz_enabled && (
                  <span className="text-terminal-accent">PTZ</span>
                )}
              </>
            )}
          </div>
        </div>

        {/* Face names */}
        {knownFaces.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {knownFaces.map((face, i) => (
              <span
                key={i}
                className="text-xs px-2 py-0.5 rounded bg-terminal-accent/20 text-terminal-accent"
              >
                {face.name} ({Math.round(face.confidence * 100)}%)
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

