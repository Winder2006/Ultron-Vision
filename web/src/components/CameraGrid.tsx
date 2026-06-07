import { Camera, CameraStatus, Face, TrackingStatus } from '../api/client';
import CameraCard from './CameraCard';

interface CameraGridProps {
  cameras: Camera[];
  statuses: CameraStatus[];
  faces: Record<string, Face[]>;
  tracking: Record<string, TrackingStatus>;
  maxPerRow: number;
  onSelectCamera: (cameraId: string) => void;
}

export default function CameraGrid({
  cameras,
  statuses,
  faces,
  tracking,
  maxPerRow,
  onSelectCamera,
}: CameraGridProps) {
  const getStatus = (cameraId: string) => 
    statuses.find(s => s.camera_id === cameraId);

  return (
    <div className="p-4 lg:p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl lg:text-2xl font-display font-bold text-terminal-accent">
          LIVE CAMERAS
        </h2>
        <div className="text-terminal-muted text-sm">
          {cameras.length} camera{cameras.length !== 1 ? 's' : ''} configured
        </div>
      </div>

      <div 
        className="grid gap-4 lg:gap-6"
        style={{
          gridTemplateColumns: `repeat(${Math.min(maxPerRow, cameras.length)}, minmax(0, 1fr))`,
        }}
      >
        {cameras.map(camera => (
          <CameraCard
            key={camera.id}
            camera={camera}
            status={getStatus(camera.id)}
            faces={faces[camera.id] || []}
            tracking={tracking[camera.id]}
            onClick={() => onSelectCamera(camera.id)}
          />
        ))}
      </div>

      {cameras.length === 0 && (
        <div className="card p-12 text-center">
          <p className="text-terminal-muted text-lg">No cameras configured</p>
          <p className="text-terminal-muted text-sm mt-2">
            Add cameras to config.yaml and restart the backend
          </p>
        </div>
      )}
    </div>
  );
}

