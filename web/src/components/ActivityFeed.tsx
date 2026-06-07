import { useState, useEffect } from 'react';
import { api, ActivityAlert, Camera } from '../api/client';
import {
  AlertTriangle,
  UserX,
  Clock,
  Users,
  Filter,
  RefreshCw,
} from 'lucide-react';

interface ActivityFeedProps {
  alerts: ActivityAlert[];
  cameras: Camera[];
}

const alertIcons = {
  loitering: Clock,
  unknown_person: UserX,
  quiet_hours_motion: AlertTriangle,
  person_count_change: Users,
};

const alertColors = {
  loitering: 'text-terminal-warning',
  unknown_person: 'text-terminal-danger',
  quiet_hours_motion: 'text-terminal-danger',
  person_count_change: 'text-terminal-accent',
};

const severityColors = {
  low: 'bg-terminal-accent/20 text-terminal-accent border-terminal-accent/30',
  medium: 'bg-terminal-warning/20 text-terminal-warning border-terminal-warning/30',
  high: 'bg-terminal-danger/20 text-terminal-danger border-terminal-danger/30',
};

export default function ActivityFeed({ alerts: initialAlerts, cameras }: ActivityFeedProps) {
  const [alerts, setAlerts] = useState<ActivityAlert[]>(initialAlerts);
  const [filter, setFilter] = useState({
    camera_id: '',
    alert_type: '',
    timeRange: '24',
  });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setAlerts(initialAlerts);
  }, [initialAlerts]);

  const loadAlerts = async () => {
    setLoading(true);
    try {
      const data = await api.getActivityAlerts({
        camera_id: filter.camera_id || undefined,
        alert_type: filter.alert_type || undefined,
        hours: parseInt(filter.timeRange),
      });
      setAlerts(data);
    } catch (error) {
      console.error('Failed to load alerts:', error);
    }
    setLoading(false);
  };

  const filteredAlerts = alerts.filter(alert => {
    if (filter.camera_id && alert.camera_id !== filter.camera_id) return false;
    if (filter.alert_type && alert.alert_type !== filter.alert_type) return false;
    return true;
  });

  const getCameraName = (cameraId: string) => 
    cameras.find(c => c.id === cameraId)?.name || cameraId;

  return (
    <div className="p-4 lg:p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl lg:text-2xl font-display font-bold text-terminal-accent">
          ACTIVITY FEED
        </h2>
        <button
          onClick={loadAlerts}
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
            <label className="block text-xs text-terminal-muted mb-1">Alert Type</label>
            <select
              value={filter.alert_type}
              onChange={(e) => setFilter(f => ({ ...f, alert_type: e.target.value }))}
              className="input w-full text-sm"
            >
              <option value="">All types</option>
              <option value="unknown_person">Unknown Person</option>
              <option value="loitering">Loitering</option>
              <option value="quiet_hours_motion">Quiet Hours Motion</option>
              <option value="person_count_change">Person Count Change</option>
            </select>
          </div>
          
          <div>
            <label className="block text-xs text-terminal-muted mb-1">Time Range</label>
            <select
              value={filter.timeRange}
              onChange={(e) => setFilter(f => ({ ...f, timeRange: e.target.value }))}
              className="input w-full text-sm"
            >
              <option value="1">Last hour</option>
              <option value="6">Last 6 hours</option>
              <option value="24">Last 24 hours</option>
              <option value="72">Last 3 days</option>
              <option value="168">Last week</option>
            </select>
          </div>
        </div>
      </div>

      {/* Alert List */}
      <div className="space-y-3">
        {filteredAlerts.length === 0 ? (
          <div className="card p-8 text-center">
            <AlertTriangle className="w-12 h-12 text-terminal-muted mx-auto mb-3" />
            <p className="text-terminal-muted">No alerts found</p>
          </div>
        ) : (
          filteredAlerts.map((alert, index) => {
            const Icon = alertIcons[alert.alert_type] || AlertTriangle;
            const colorClass = alertColors[alert.alert_type] || 'text-terminal-muted';
            const severityClass = severityColors[alert.severity] || severityColors.low;
            
            return (
              <div
                key={`${alert.timestamp}-${index}`}
                className="card p-4 hover:border-terminal-accent/30 transition-colors"
              >
                <div className="flex items-start gap-4">
                  <div className={`p-2 rounded-lg bg-terminal-bg ${colorClass}`}>
                    <Icon className="w-5 h-5" />
                  </div>
                  
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`badge ${severityClass}`}>
                        {alert.severity.toUpperCase()}
                      </span>
                      <span className="text-terminal-muted text-xs">
                        {getCameraName(alert.camera_id)}
                      </span>
                    </div>
                    
                    <p className="text-terminal-text font-medium">
                      {alert.description}
                    </p>
                    
                    <p className="text-terminal-muted text-xs mt-1">
                      {formatTime(alert.timestamp)}
                    </p>
                    
                    {alert.faces && alert.faces.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {alert.faces.map((face, i) => (
                          <span
                            key={i}
                            className={`text-xs px-2 py-0.5 rounded ${
                              face.known
                                ? 'bg-terminal-accent/20 text-terminal-accent'
                                : 'bg-terminal-danger/20 text-terminal-danger'
                            }`}
                          >
                            {face.name}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  
                  {alert.snapshot_path && (
                    <img
                      src={`/api/snapshot/${alert.camera_id}`}
                      alt="Alert snapshot"
                      className="w-24 h-16 object-cover rounded border border-terminal-border"
                    />
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function formatTime(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  
  return date.toLocaleString();
}

