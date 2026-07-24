/**
 * ULTRON VISION API Client
 * Typed HTTP + WebSocket client for FastAPI endpoints
 */

// Default to the origin that served the page, so a build served BY the backend
// (Jetson at :8200, or a tunnel like https://ultron.example.com) just works —
// LAN or remote — with no rebuild. VITE_API_BASE_URL overrides it, which the
// laptop dev server uses (via web/.env.local) to point at the Jetson.
const API_BASE =
  import.meta.env.VITE_API_BASE_URL ||
  (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8200');
const WS_BASE = API_BASE.replace(/^http/, 'ws');

// Types
export interface Camera {
  id: string;
  name: string;
  ptz_enabled: boolean;
}

export interface CameraStatus {
  camera_id: string;
  online: boolean;
  fps: number;
  resolution: [number, number] | null;
  error: string | null;
}

export interface SystemStatus {
  online: boolean;
  cameras: CameraStatus[];
  uptime_seconds: number;
  gpu: {
    available: boolean;
    usage?: number;
  } | null;
}

export interface Face {
  name: string;
  confidence: number;
  bbox: [number, number, number, number]; // x, y, width, height
  known: boolean;
  camera_id?: string;
}

export interface MotionRegion {
  bbox: [number, number, number, number];
  area: number;
}

export interface MotionStatus {
  camera_id: string;
  motion_detected: boolean;
  regions: MotionRegion[];
  zones: { name: string; enabled: boolean }[];
}

export interface ActivityAlert {
  camera_id: string;
  timestamp: string;
  alert_type: 'loitering' | 'unknown_person' | 'quiet_hours_motion' | 'person_count_change';
  description: string;
  severity: 'low' | 'medium' | 'high';
  faces: Face[];
  snapshot_path?: string;
}

export interface TrackingStatus {
  camera_id: string;
  active: boolean;
  target_name: string | null;
  tracking_state: 'idle' | 'tracking' | 'searching' | 'lost';
  bbox: [number, number, number, number] | null;
}

export interface Recording {
  id: string;
  camera_id: string;
  start_time: string;
  end_time: string | null;
  file_path: string;
  type: 'continuous' | 'event';
  event_type?: string;
  thumbnail_path?: string;
}

export interface EnrolledPerson {
  name: string;
  encoding_count: number;
  image_count: number;
  image_paths: string[];
}

export interface CrewMember {
  name: string;
  known: boolean;
  cameras: string[];
  confidence: number;
}

export interface UIConfig {
  cameras: Camera[];
  default_view: string;
  theme: string;
  max_cameras_per_row: number;
}

export interface WSEvent {
  type: string;
  camera_id: string | null;
  timestamp: string;
  data: Record<string, unknown>;
}

// HTTP Client
class APIClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    return response.json();
  }

  // Status
  async getStatus(): Promise<SystemStatus> {
    return this.request('/status');
  }

  async getHealth(): Promise<{ status: string; timestamp: string }> {
    return this.request('/health');
  }

  // Snapshots
  getSnapshotUrl(cameraId?: string): string {
    return cameraId 
      ? `${this.baseUrl}/snapshot/${cameraId}`
      : `${this.baseUrl}/snapshot`;
  }

  // Faces
  async getFaces(): Promise<Face[]> {
    return this.request('/faces');
  }

  async getUnknownFaces(): Promise<Face[]> {
    return this.request('/faces/unknown');
  }

  async enrollFace(name: string, image: File): Promise<{ success: boolean; name: string; image_path: string }> {
    const formData = new FormData();
    formData.append('name', name);
    formData.append('image', image);

    const response = await fetch(`${this.baseUrl}/faces/enroll`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Enrollment failed' }));
      throw new Error(error.detail);
    }

    return response.json();
  }

  async getEnrolledFaces(): Promise<EnrolledPerson[]> {
    return this.request('/faces/enrolled');
  }

  async deleteFace(name: string): Promise<{ success: boolean }> {
    return this.request(`/faces/${encodeURIComponent(name)}`, { method: 'DELETE' });
  }

  // Motion & Activity
  async getMotion(): Promise<MotionStatus[]> {
    return this.request('/motion');
  }

  async getActivityAlerts(params?: {
    camera_id?: string;
    alert_type?: string;
    hours?: number;
  }): Promise<ActivityAlert[]> {
    const searchParams = new URLSearchParams();
    if (params?.camera_id) searchParams.set('camera_id', params.camera_id);
    if (params?.alert_type) searchParams.set('alert_type', params.alert_type);
    if (params?.hours) searchParams.set('hours', params.hours.toString());

    const query = searchParams.toString();
    return this.request(`/activity/alerts${query ? `?${query}` : ''}`);
  }

  async getActivityLog(hours: number = 24): Promise<ActivityAlert[]> {
    return this.request(`/activity/log?hours=${hours}`);
  }

  // PTZ Control
  async ptzMove(cameraId: string, direction: string, speed: number = 25): Promise<{ success: boolean }> {
    return this.request('/ptz/move', {
      method: 'POST',
      body: JSON.stringify({ camera_id: cameraId, direction, speed }),
    });
  }

  async ptzPreset(cameraId: string, presetId: number): Promise<{ success: boolean }> {
    return this.request(`/ptz/preset/${presetId}?camera_id=${cameraId}`, {
      method: 'POST',
    });
  }

  async ptzTrack(cameraId: string, target: string): Promise<{ success: boolean; tracking: string }> {
    return this.request('/ptz/track', {
      method: 'POST',
      body: JSON.stringify({ camera_id: cameraId, target }),
    });
  }

  async ptzStop(cameraId: string): Promise<{ success: boolean }> {
    return this.request(`/ptz/stop?camera_id=${cameraId}`, { method: 'POST' });
  }

  // Recordings
  async getRecordings(params?: {
    camera_id?: string;
    type?: string;
    hours?: number;
  }): Promise<Recording[]> {
    const searchParams = new URLSearchParams();
    if (params?.camera_id) searchParams.set('camera_id', params.camera_id);
    if (params?.type) searchParams.set('type', params.type);
    if (params?.hours) searchParams.set('hours', params.hours.toString());

    const query = searchParams.toString();
    return this.request(`/recordings${query ? `?${query}` : ''}`);
  }

  getRecordingUrl(recordingId: string): string {
    return `${this.baseUrl}/recordings/${recordingId}`;
  }

  async saveSnapshot(cameraId: string): Promise<{ id: string; file_path: string }> {
    return this.request(`/snapshot/save?camera_id=${cameraId}`, { method: 'POST' });
  }

  // Crew
  async getCrew(): Promise<CrewMember[]> {
    return this.request('/crew');
  }

  async getCrewHistory(hours: number = 24): Promise<ActivityAlert[]> {
    return this.request(`/crew/history?hours=${hours}`);
  }

  async getLastSeen(name: string): Promise<{
    name: string;
    camera_id: string;
    last_seen: string;
    currently_visible: boolean;
  }> {
    return this.request(`/crew/${encodeURIComponent(name)}/last_seen`);
  }

  // UI Config
  async getUIConfig(): Promise<UIConfig> {
    return this.request('/ui/config');
  }
}

// WebSocket Client
type EventCallback = (event: WSEvent) => void;

class WSClient {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private callbacks: EventCallback[] = [];
  private url: string;
  private isConnecting = false;
  private closed = false;

  constructor(endpoint: string) {
    this.url = `${WS_BASE}${endpoint}`;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN || this.isConnecting) {
      return;
    }

    this.closed = false;
    this.isConnecting = true;

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log(`WebSocket connected: ${this.url}`);
        this.reconnectAttempts = 0;
        this.isConnecting = false;
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as WSEvent;
          this.callbacks.forEach(cb => cb(data));
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };

      this.ws.onclose = () => {
        this.isConnecting = false;
        this.attemptReconnect();
      };

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        this.isConnecting = false;
      };
    } catch (e) {
      console.error('Failed to create WebSocket:', e);
      this.isConnecting = false;
      this.attemptReconnect();
    }
  }

  private attemptReconnect(): void {
    // Retry forever (capped backoff). The backend can be down for a long time
    // — e.g. the Jetson rebooting — and the UI must recover on its own without
    // a page refresh. disconnect() sets `closed` to stop this loop.
    if (this.closed) return;

    this.reconnectAttempts++;
    const delay = Math.min(
      this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
      this.maxReconnectDelay
    );

    console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);

    setTimeout(() => this.connect(), delay);
  }

  subscribe(callback: EventCallback): () => void {
    this.callbacks.push(callback);
    
    // Return unsubscribe function
    return () => {
      this.callbacks = this.callbacks.filter(cb => cb !== callback);
    };
  }

  disconnect(): void {
    this.closed = true;
    if (this.ws) {
      // Detach onclose first so closing doesn't schedule a reconnect.
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onmessage = null;
      this.ws.close();
      this.ws = null;
    }
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

// Stream Client for video frames
type FrameCallback = (frame: {
  data: string;
  timestamp: string;
  frame_id: number;
  // Original capture dimensions (the preview JPEG may be downscaled) — used
  // to scale detection overlays, which are in full-res coordinates.
  frame_w?: number;
  frame_h?: number;
}) => void;

class StreamClient {
  private ws: WebSocket | null = null;
  private callback: FrameCallback | null = null;
  private statusCallback: ((connected: boolean) => void) | null = null;
  private cameraId: string;
  private reconnectTimeout: number | null = null;

  constructor(cameraId: string) {
    this.cameraId = cameraId;
  }

  connect(
    callback: FrameCallback,
    onStatus?: (connected: boolean) => void
  ): void {
    this.callback = callback;
    this.statusCallback = onStatus ?? null;
    this.createConnection();
  }

  private createConnection(): void {
    const url = `${WS_BASE}/stream/${this.cameraId}`;

    try {
      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        this.statusCallback?.(true);
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'frame' && this.callback) {
            this.callback({
              data: data.data,
              timestamp: data.timestamp,
              frame_id: data.frame_id,
              frame_w: data.frame_w,
              frame_h: data.frame_h,
            });
          }
        } catch (e) {
          console.error('Failed to parse frame:', e);
        }
      };

      this.ws.onclose = () => {
        // Tell the UI the feed dropped so it stops showing a frozen frame.
        this.statusCallback?.(false);
        this.scheduleReconnect();
      };

      this.ws.onerror = () => {
        // Error will trigger onclose
      };
    } catch (e) {
      console.error('Failed to create stream WebSocket:', e);
      this.statusCallback?.(false);
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimeout) return;
    
    this.reconnectTimeout = window.setTimeout(() => {
      this.reconnectTimeout = null;
      if (this.callback) {
        this.createConnection();
      }
    }, 2000);
  }

  disconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    this.callback = null;
    this.statusCallback = null;

    if (this.ws) {
      // Detach handlers BEFORE closing so a close during the CONNECTING phase
      // doesn't fire onclose -> scheduleReconnect (orphaned reconnect loop).
      this.ws.onopen = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onmessage = null;
      try {
        this.ws.close();
      } catch {
        /* closing a CONNECTING socket can throw in some browsers — ignore */
      }
      this.ws = null;
    }
  }
}

// Export singleton instances
export const api = new APIClient();
export const eventsWS = new WSClient('/events');
export const createStreamClient = (cameraId: string) => new StreamClient(cameraId);

