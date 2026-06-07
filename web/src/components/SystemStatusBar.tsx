import { Cpu, HardDrive, Camera } from 'lucide-react';
import { SystemStatus } from '../api/client';

interface SystemStatusBarProps {
  status: SystemStatus | null;
}

export default function SystemStatusBar({ status }: SystemStatusBarProps) {
  if (!status) {
    return (
      <div className="flex items-center gap-4 text-terminal-muted text-sm">
        <span>Loading...</span>
      </div>
    );
  }

  const onlineCameras = status.cameras.filter(c => c.online).length;
  const totalCameras = status.cameras.length;
  const avgFps = status.cameras.length > 0
    ? Math.round(status.cameras.reduce((sum, c) => sum + c.fps, 0) / status.cameras.length)
    : 0;

  return (
    <div className="flex items-center gap-6 text-sm">
      <div className="flex items-center gap-2">
        <Camera className="w-4 h-4 text-terminal-muted" />
        <span className={onlineCameras === totalCameras ? 'text-terminal-accent' : 'text-terminal-warning'}>
          {onlineCameras}/{totalCameras}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <HardDrive className="w-4 h-4 text-terminal-muted" />
        <span className="text-terminal-text">{avgFps} FPS</span>
      </div>

      {status.gpu?.available && (
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-terminal-muted" />
          <span className="text-terminal-accent">GPU</span>
        </div>
      )}

      <div className="flex items-center gap-2 text-terminal-muted">
        <span className="text-xs">UP</span>
        <span className="text-terminal-text">{formatUptime(status.uptime_seconds)}</span>
      </div>
    </div>
  );
}

function formatUptime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

