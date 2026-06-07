import { useState, useEffect } from 'react';
import { api, Face, Camera, CrewMember } from '../api/client';
import { User, UserX, Eye, Clock, RefreshCw } from 'lucide-react';

interface CrewManifestProps {
  faces: Record<string, Face[]>;
  cameras: Camera[];
}

interface PersonHistory {
  name: string;
  last_seen: string;
  camera_id: string;
  currently_visible: boolean;
}

export default function CrewManifest({ faces, cameras }: CrewManifestProps) {
  const [_crew, setCrew] = useState<CrewMember[]>([]);
  const [history, setHistory] = useState<PersonHistory[]>([]);
  const [enrolledPeople, setEnrolledPeople] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  // Load crew data
  const loadCrewData = async () => {
    setLoading(true);
    try {
      const [crewData, enrolledData] = await Promise.all([
        api.getCrew(),
        api.getEnrolledFaces(),
      ]);
      
      setCrew(crewData);
      setEnrolledPeople(enrolledData.map(p => p.name));
      
      // Load last seen for enrolled people
      const historyPromises = enrolledData.map(async (person) => {
        try {
          return await api.getLastSeen(person.name);
        } catch {
          return null;
        }
      });
      
      const historyResults = await Promise.all(historyPromises);
      setHistory(historyResults.filter(Boolean) as PersonHistory[]);
    } catch (error) {
      console.error('Failed to load crew data:', error);
    }
    setLoading(false);
  };

  useEffect(() => {
    loadCrewData();
    const interval = setInterval(loadCrewData, 30000);
    return () => clearInterval(interval);
  }, []);

  // Build currently visible list from real-time faces
  const currentlyVisible: Map<string, { cameras: string[]; confidence: number }> = new Map();
  
  Object.entries(faces).forEach(([cameraId, faceList]) => {
    faceList.filter(f => f.known).forEach(face => {
      if (currentlyVisible.has(face.name)) {
        const existing = currentlyVisible.get(face.name)!;
        existing.cameras.push(cameraId);
        existing.confidence = Math.max(existing.confidence, face.confidence);
      } else {
        currentlyVisible.set(face.name, {
          cameras: [cameraId],
          confidence: face.confidence,
        });
      }
    });
  });

  const getCameraName = (cameraId: string) =>
    cameras.find(c => c.id === cameraId)?.name || cameraId;

  return (
    <div className="p-4 lg:p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl lg:text-2xl font-display font-bold text-terminal-accent">
          CREW MANIFEST
        </h2>
        <button
          onClick={loadCrewData}
          disabled={loading}
          className="btn-secondary text-sm flex items-center gap-2"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Currently Visible */}
      <div className="mb-8">
        <h3 className="flex items-center gap-2 text-lg font-semibold text-terminal-text mb-4">
          <Eye className="w-5 h-5 text-terminal-accent" />
          Currently Visible
        </h3>
        
        {currentlyVisible.size === 0 ? (
          <div className="card p-6 text-center">
            <User className="w-10 h-10 text-terminal-muted mx-auto mb-2" />
            <p className="text-terminal-muted">No one currently visible</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from(currentlyVisible.entries()).map(([name, data]) => (
              <div
                key={name}
                className="card p-4 border-terminal-accent/30"
              >
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-full bg-terminal-accent/20 flex items-center justify-center">
                    <User className="w-6 h-6 text-terminal-accent" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold text-terminal-text truncate">{name}</p>
                    <p className="text-xs text-terminal-muted">
                      {Math.round(data.confidence * 100)}% confidence
                    </p>
                  </div>
                  <div className="w-2 h-2 rounded-full bg-terminal-accent animate-pulse" />
                </div>
                
                <div className="mt-3 flex flex-wrap gap-1">
                  {data.cameras.map(camId => (
                    <span
                      key={camId}
                      className="text-xs px-2 py-0.5 rounded bg-terminal-bg text-terminal-muted"
                    >
                      {getCameraName(camId)}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Recent Activity / Last Seen */}
      <div>
        <h3 className="flex items-center gap-2 text-lg font-semibold text-terminal-text mb-4">
          <Clock className="w-5 h-5 text-terminal-muted" />
          Enrolled People
        </h3>
        
        {enrolledPeople.length === 0 ? (
          <div className="card p-6 text-center">
            <UserX className="w-10 h-10 text-terminal-muted mx-auto mb-2" />
            <p className="text-terminal-muted">No enrolled people</p>
            <p className="text-terminal-muted text-sm mt-1">
              Use the API to enroll faces
            </p>
          </div>
        ) : (
          <div className="card overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-terminal-border">
                  <th className="text-left p-3 text-terminal-muted text-sm font-medium">Name</th>
                  <th className="text-left p-3 text-terminal-muted text-sm font-medium">Status</th>
                  <th className="text-left p-3 text-terminal-muted text-sm font-medium">Last Seen</th>
                  <th className="text-left p-3 text-terminal-muted text-sm font-medium">Camera</th>
                </tr>
              </thead>
              <tbody>
                {enrolledPeople.map(name => {
                  const historyEntry = history.find(h => h.name === name);
                  const isVisible = currentlyVisible.has(name);
                  
                  return (
                    <tr key={name} className="border-b border-terminal-border/50 last:border-0">
                      <td className="p-3">
                        <div className="flex items-center gap-2">
                          <User className="w-4 h-4 text-terminal-muted" />
                          <span className="text-terminal-text">{name}</span>
                        </div>
                      </td>
                      <td className="p-3">
                        {isVisible ? (
                          <span className="badge-success">VISIBLE</span>
                        ) : (
                          <span className="badge bg-terminal-border text-terminal-muted border-transparent">
                            AWAY
                          </span>
                        )}
                      </td>
                      <td className="p-3 text-terminal-muted text-sm">
                        {isVisible
                          ? 'Now'
                          : historyEntry
                            ? formatTimeAgo(historyEntry.last_seen)
                            : '--'
                        }
                      </td>
                      <td className="p-3 text-terminal-muted text-sm">
                        {isVisible
                          ? currentlyVisible.get(name)?.cameras.map(getCameraName).join(', ')
                          : historyEntry
                            ? getCameraName(historyEntry.camera_id)
                            : '--'
                        }
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function formatTimeAgo(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)} min ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} hours ago`;
  if (diff < 604800000) return `${Math.floor(diff / 86400000)} days ago`;
  
  return date.toLocaleDateString();
}

