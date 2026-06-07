import { useState } from 'react';
import { api, Face } from '../api/client';
import {
  ChevronUp,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  Target,
  Square,
  Home,
} from 'lucide-react';

interface PTZControlsProps {
  cameraId: string;
  visibleFaces: Face[];
  onTrackingStart?: (target: string) => void;
}

export default function PTZControls({
  cameraId,
  visibleFaces,
  onTrackingStart,
}: PTZControlsProps) {
  const [speed, setSpeed] = useState(25);
  const [, setIsMoving] = useState(false);
  const [trackTarget, setTrackTarget] = useState<string>('');

  const handleMove = async (direction: string) => {
    setIsMoving(true);
    try {
      await api.ptzMove(cameraId, direction, speed);
    } catch (error) {
      console.error('PTZ move failed:', error);
    }
  };

  const handleStop = async () => {
    setIsMoving(false);
    try {
      await api.ptzMove(cameraId, 'stop', 0);
    } catch (error) {
      console.error('PTZ stop failed:', error);
    }
  };

  const handlePreset = async (presetId: number) => {
    try {
      await api.ptzPreset(cameraId, presetId);
    } catch (error) {
      console.error('PTZ preset failed:', error);
    }
  };

  const handleTrack = async () => {
    if (!trackTarget) return;
    
    try {
      await api.ptzTrack(cameraId, trackTarget);
      onTrackingStart?.(trackTarget);
    } catch (error) {
      console.error('PTZ track failed:', error);
    }
  };

  const handleStopTracking = async () => {
    try {
      await api.ptzStop(cameraId);
      setTrackTarget('');
    } catch (error) {
      console.error('PTZ stop tracking failed:', error);
    }
  };

  const knownFaces = visibleFaces.filter(f => f.known);

  return (
    <div className="card p-4 space-y-4">
      <h3 className="font-display font-semibold text-terminal-accent">PTZ CONTROL</h3>

      {/* Direction Pad */}
      <div className="flex flex-col items-center gap-1">
        <button
          className="btn-secondary p-2"
          onMouseDown={() => handleMove('up')}
          onMouseUp={handleStop}
          onMouseLeave={handleStop}
        >
          <ChevronUp className="w-6 h-6" />
        </button>
        
        <div className="flex gap-1">
          <button
            className="btn-secondary p-2"
            onMouseDown={() => handleMove('left')}
            onMouseUp={handleStop}
            onMouseLeave={handleStop}
          >
            <ChevronLeft className="w-6 h-6" />
          </button>
          
          <button
            className="btn-secondary p-2"
            onClick={() => handlePreset(0)}
            title="Home position"
          >
            <Home className="w-6 h-6" />
          </button>
          
          <button
            className="btn-secondary p-2"
            onMouseDown={() => handleMove('right')}
            onMouseUp={handleStop}
            onMouseLeave={handleStop}
          >
            <ChevronRight className="w-6 h-6" />
          </button>
        </div>
        
        <button
          className="btn-secondary p-2"
          onMouseDown={() => handleMove('down')}
          onMouseUp={handleStop}
          onMouseLeave={handleStop}
        >
          <ChevronDown className="w-6 h-6" />
        </button>
      </div>

      {/* Zoom Controls */}
      <div className="flex items-center justify-center gap-2">
        <button
          className="btn-secondary p-2"
          onMouseDown={() => handleMove('zoom_out')}
          onMouseUp={handleStop}
          onMouseLeave={handleStop}
        >
          <ZoomOut className="w-5 h-5" />
        </button>
        <span className="text-terminal-muted text-sm">Zoom</span>
        <button
          className="btn-secondary p-2"
          onMouseDown={() => handleMove('zoom_in')}
          onMouseUp={handleStop}
          onMouseLeave={handleStop}
        >
          <ZoomIn className="w-5 h-5" />
        </button>
      </div>

      {/* Speed Slider */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-sm">
          <span className="text-terminal-muted">Speed</span>
          <span className="text-terminal-accent">{speed}</span>
        </div>
        <input
          type="range"
          min="1"
          max="64"
          value={speed}
          onChange={(e) => setSpeed(parseInt(e.target.value))}
          className="w-full accent-terminal-accent"
        />
      </div>

      {/* Presets */}
      <div className="space-y-2">
        <span className="text-terminal-muted text-sm">Presets</span>
        <div className="flex flex-wrap gap-1">
          {[1, 2, 3, 4].map(preset => (
            <button
              key={preset}
              onClick={() => handlePreset(preset)}
              className="btn-secondary text-sm px-3 py-1"
            >
              {preset}
            </button>
          ))}
        </div>
      </div>

      {/* Person Tracking */}
      <div className="space-y-2 pt-2 border-t border-terminal-border">
        <span className="text-terminal-muted text-sm flex items-center gap-1">
          <Target className="w-4 h-4" />
          Track Person
        </span>
        
        {knownFaces.length > 0 ? (
          <div className="flex gap-2">
            <select
              value={trackTarget}
              onChange={(e) => setTrackTarget(e.target.value)}
              className="input flex-1 text-sm"
            >
              <option value="">Select person...</option>
              {knownFaces.map((face, i) => (
                <option key={i} value={face.name}>
                  {face.name} ({Math.round(face.confidence * 100)}%)
                </option>
              ))}
            </select>
            
            {trackTarget ? (
              <button
                onClick={handleStopTracking}
                className="btn-danger text-sm px-3"
              >
                <Square className="w-4 h-4" />
              </button>
            ) : (
              <button
                onClick={handleTrack}
                disabled={!trackTarget}
                className="btn-primary text-sm px-3 disabled:opacity-50"
              >
                <Target className="w-4 h-4" />
              </button>
            )}
          </div>
        ) : (
          <p className="text-terminal-muted text-xs">
            No recognized faces visible
          </p>
        )}
      </div>
    </div>
  );
}

