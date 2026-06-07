import { useState, useEffect } from 'react';
import { api, Recording, Camera } from '../api/client';
import {
  Film,
  Calendar,
  Filter,
  Play,
  Download,
  X,
  RefreshCw,
  Clock,
  AlertCircle,
} from 'lucide-react';

interface RecordingTimelineProps {
  cameras: Camera[];
}

export default function RecordingTimeline({ cameras }: RecordingTimelineProps) {
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedRecording, setSelectedRecording] = useState<Recording | null>(null);
  const [filter, setFilter] = useState({
    camera_id: '',
    type: '',
    hours: 24,
  });

  const loadRecordings = async () => {
    setLoading(true);
    try {
      const data = await api.getRecordings({
        camera_id: filter.camera_id || undefined,
        type: filter.type || undefined,
        hours: filter.hours,
      });
      setRecordings(data);
    } catch (error) {
      console.error('Failed to load recordings:', error);
    }
    setLoading(false);
  };

  useEffect(() => {
    loadRecordings();
  }, [filter]);

  const getCameraName = (cameraId: string) =>
    cameras.find(c => c.id === cameraId)?.name || cameraId;

  // Group recordings by date
  const groupedRecordings = recordings.reduce((groups, recording) => {
    const date = new Date(recording.start_time).toLocaleDateString();
    if (!groups[date]) {
      groups[date] = [];
    }
    groups[date].push(recording);
    return groups;
  }, {} as Record<string, Recording[]>);

  return (
    <div className="p-4 lg:p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl lg:text-2xl font-display font-bold text-terminal-accent">
          RECORDINGS
        </h2>
        <button
          onClick={loadRecordings}
          disabled={loading}
          className="btn-secondary text-sm flex items-center gap-2"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="card p-4 mb-6">
        <div className="flex items-center gap-2 mb-3">
          <Filter className="w-4 h-4 text-terminal-muted" />
          <span className="text-terminal-muted text-sm">Filters</span>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-xs text-terminal-muted mb-1">Camera</label>
            <select
              value={filter.camera_id}
              onChange={(e) => setFilter(f => ({ ...f, camera_id: e.target.value }))}
              className="input w-full text-sm"
            >
              <option value="">All cameras</option>
              {cameras.map(cam => (
                <option key={cam.id} value={cam.id}>{cam.name}</option>
              ))}
            </select>
          </div>
          
          <div>
            <label className="block text-xs text-terminal-muted mb-1">Type</label>
            <select
              value={filter.type}
              onChange={(e) => setFilter(f => ({ ...f, type: e.target.value }))}
              className="input w-full text-sm"
            >
              <option value="">All types</option>
              <option value="continuous">Continuous</option>
              <option value="event">Event</option>
            </select>
          </div>
          
          <div>
            <label className="block text-xs text-terminal-muted mb-1">Time Range</label>
            <select
              value={filter.hours}
              onChange={(e) => setFilter(f => ({ ...f, hours: parseInt(e.target.value) }))}
              className="input w-full text-sm"
            >
              <option value={6}>Last 6 hours</option>
              <option value={24}>Last 24 hours</option>
              <option value={72}>Last 3 days</option>
              <option value={168}>Last week</option>
            </select>
          </div>
        </div>
      </div>

      {/* Recordings List */}
      {loading ? (
        <div className="card p-12 text-center">
          <div className="w-8 h-8 border-2 border-terminal-accent border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-terminal-muted">Loading recordings...</p>
        </div>
      ) : recordings.length === 0 ? (
        <div className="card p-12 text-center">
          <Film className="w-12 h-12 text-terminal-muted mx-auto mb-3" />
          <p className="text-terminal-muted">No recordings found</p>
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(groupedRecordings).map(([date, dateRecordings]) => (
            <div key={date}>
              <div className="flex items-center gap-2 mb-3">
                <Calendar className="w-4 h-4 text-terminal-accent" />
                <h3 className="text-terminal-text font-medium">{date}</h3>
                <span className="text-terminal-muted text-sm">
                  ({dateRecordings.length} recording{dateRecordings.length !== 1 ? 's' : ''})
                </span>
              </div>
              
              <div className="space-y-2">
                {dateRecordings.map(recording => (
                  <div
                    key={recording.id}
                    className="card p-4 hover:border-terminal-accent/30 transition-colors cursor-pointer"
                    onClick={() => setSelectedRecording(recording)}
                  >
                    <div className="flex items-center gap-4">
                      <div className={`p-2 rounded ${
                        recording.type === 'event'
                          ? 'bg-terminal-warning/20 text-terminal-warning'
                          : 'bg-terminal-accent/20 text-terminal-accent'
                      }`}>
                        {recording.type === 'event' ? (
                          <AlertCircle className="w-5 h-5" />
                        ) : (
                          <Film className="w-5 h-5" />
                        )}
                      </div>
                      
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-terminal-text">
                            {getCameraName(recording.camera_id)}
                          </span>
                          <span className={`badge ${
                            recording.type === 'event'
                              ? 'bg-terminal-warning/20 text-terminal-warning border-terminal-warning/30'
                              : 'bg-terminal-accent/20 text-terminal-accent border-terminal-accent/30'
                          }`}>
                            {recording.type}
                          </span>
                          {recording.event_type && (
                            <span className="badge bg-terminal-danger/20 text-terminal-danger border-terminal-danger/30">
                              {recording.event_type}
                            </span>
                          )}
                        </div>
                        
                        <div className="flex items-center gap-4 mt-1 text-sm text-terminal-muted">
                          <span className="flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {formatTime(recording.start_time)}
                          </span>
                          {recording.end_time && (
                            <span>
                              Duration: {formatDuration(recording.start_time, recording.end_time)}
                            </span>
                          )}
                        </div>
                      </div>
                      
                      <div className="flex items-center gap-2">
                        <button
                          className="btn-secondary p-2"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedRecording(recording);
                          }}
                        >
                          <Play className="w-4 h-4" />
                        </button>
                        <a
                          href={api.getRecordingUrl(recording.id)}
                          download
                          className="btn-secondary p-2"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Download className="w-4 h-4" />
                        </a>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Video Player Modal */}
      {selectedRecording && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4">
          <div className="card max-w-4xl w-full max-h-[90vh] overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-terminal-border">
              <div>
                <h3 className="font-semibold text-terminal-text">
                  {getCameraName(selectedRecording.camera_id)}
                </h3>
                <p className="text-sm text-terminal-muted">
                  {formatTime(selectedRecording.start_time)}
                </p>
              </div>
              <button
                onClick={() => setSelectedRecording(null)}
                className="p-2 text-terminal-muted hover:text-terminal-text"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="p-4">
              <video
                src={api.getRecordingUrl(selectedRecording.id)}
                controls
                autoPlay
                className="w-full rounded bg-black"
              />
            </div>
            
            <div className="p-4 border-t border-terminal-border flex justify-end gap-2">
              <a
                href={api.getRecordingUrl(selectedRecording.id)}
                download
                className="btn-secondary flex items-center gap-2"
              >
                <Download className="w-4 h-4" />
                Download
              </a>
              <button
                onClick={() => setSelectedRecording(null)}
                className="btn-primary"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function formatTime(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDuration(start: string, end: string): string {
  const diff = new Date(end).getTime() - new Date(start).getTime();
  const minutes = Math.floor(diff / 60000);
  const seconds = Math.floor((diff % 60000) / 1000);
  
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

