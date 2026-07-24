import { useEffect, useRef, useState } from 'react';
import { Face, TrackingStatus } from '../api/client';
// Vendored go2rtc WebRTC client (no type declarations).
// @ts-ignore
import { VideoRTC } from '../vendor/video-rtc.js';

// Register the go2rtc custom element once.
if (typeof window !== 'undefined' && !customElements.get('video-stream')) {
  customElements.define('video-stream', VideoRTC);
}

// go2rtc runs on the same host that served the UI, port 1984. VITE_GO2RTC_BASE
// (e.g. "http://192.168.1.202:1984") overrides it for the laptop dev server.
function go2rtcWsUrl(cameraId: string): string {
  const base = import.meta.env.VITE_GO2RTC_BASE as string | undefined;
  const src = encodeURIComponent(cameraId);
  if (base) return `${base.replace(/^http/, 'ws')}/api/ws?src=${src}`;
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.hostname}:1984/api/ws?src=${src}`;
}

interface VideoCanvasProps {
  cameraId: string;
  faces: Face[];
  tracking?: TrackingStatus;
  motionRegions?: Array<{ bbox: [number, number, number, number] }>;
  showOverlays?: boolean;
}

export default function VideoCanvas({
  cameraId,
  faces,
  tracking,
  motionRegions = [],
  showOverlays = true,
}: VideoCanvasProps) {
  const videoHostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [connected, setConnected] = useState(false);

  // Latest overlay data in refs so the draw loop reads current values.
  const facesRef = useRef(faces);
  const trackingRef = useRef(tracking);
  const motionRef = useRef(motionRegions);
  const showRef = useRef(showOverlays);
  facesRef.current = faces;
  trackingRef.current = tracking;
  motionRef.current = motionRegions;
  showRef.current = showOverlays;

  useEffect(() => {
    const host = videoHostRef.current;
    if (!host) return;

    // Mount the go2rtc WebRTC <video-stream>. Appending triggers connect;
    // then setting .src starts negotiation.
    const el: any = document.createElement('video-stream');
    el.style.width = '100%';
    el.style.height = '100%';
    host.appendChild(el);
    el.mode = 'webrtc'; // force the low-latency path
    el.src = go2rtcWsUrl(cameraId);

    const video: HTMLVideoElement | undefined = el.video;
    if (video) {
      video.controls = false;
      video.muted = true;
      video.playsInline = true;
      video.style.objectFit = 'contain';
      video.addEventListener('playing', () => setConnected(true));
      video.addEventListener('waiting', () => setConnected(false));
      video.addEventListener('emptied', () => setConnected(false));
    }

    const draw = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      const rect = canvas.getBoundingClientRect();
      const cw = Math.round(rect.width);
      const ch = Math.round(rect.height);
      if (cw > 0 && ch > 0 && (canvas.width !== cw || canvas.height !== ch)) {
        canvas.width = cw;
        canvas.height = ch;
      }
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (!showRef.current) return;

      // Map full-res detection coords -> the video's on-screen rect. The
      // video is object-fit:contain, so it's letterboxed; account for that.
      const vw = (video && video.videoWidth) || 2560;
      const vh = (video && video.videoHeight) || 1440;
      const scale = Math.min(canvas.width / vw, canvas.height / vh);
      const dispW = vw * scale;
      const dispH = vh * scale;
      const offX = (canvas.width - dispW) / 2;
      const offY = (canvas.height - dispH) / 2;
      const mapX = (x: number) => offX + x * scale;
      const mapY = (y: number) => offY + y * scale;

      // Motion regions
      motionRef.current.forEach((region) => {
        const [x, y, rw, rh] = region.bbox;
        ctx.strokeStyle = 'rgba(255, 136, 0, 0.5)';
        ctx.fillStyle = 'rgba(255, 136, 0, 0.1)';
        ctx.lineWidth = 1;
        ctx.fillRect(mapX(x), mapY(y), rw * scale, rh * scale);
        ctx.strokeRect(mapX(x), mapY(y), rw * scale, rh * scale);
      });

      // Face boxes — known = orange, unknown = red
      facesRef.current.forEach((face) => {
        const [x, y, fw, fh] = face.bbox;
        const sx = mapX(x);
        const sy = mapY(y);
        const sw = fw * scale;
        const sh = fh * scale;

        const color = face.known ? '#ff6600' : '#ff0000';
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.shadowColor = color;
        ctx.shadowBlur = 12;
        ctx.strokeRect(sx, sy, sw, sh);
        ctx.shadowBlur = 0;

        const label = face.known
          ? `${face.name} (${Math.round(face.confidence * 100)}%)`
          : 'UNKNOWN // THREAT';
        ctx.font = '12px JetBrains Mono, monospace';
        const textWidth = ctx.measureText(label).width;
        ctx.fillStyle = color;
        ctx.fillRect(sx, sy - 20, textWidth + 8, 18);
        ctx.fillStyle = '#0a0000';
        ctx.fillText(label, sx + 4, sy - 6);
      });

      // Tracking crosshair
      const trk = trackingRef.current;
      if (trk?.active && trk.bbox) {
        const [x, y, tw, th] = trk.bbox;
        const cx = mapX(x + tw / 2);
        const cy = mapY(y + th / 2);
        const size = 30;
        ctx.strokeStyle = '#e63333';
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 5]);
        ctx.beginPath();
        ctx.arc(cx, cy, size, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.moveTo(cx - size - 10, cy);
        ctx.lineTo(cx - size + 5, cy);
        ctx.moveTo(cx + size - 5, cy);
        ctx.lineTo(cx + size + 10, cy);
        ctx.moveTo(cx, cy - size - 10);
        ctx.lineTo(cx, cy - size + 5);
        ctx.moveTo(cx, cy + size - 5);
        ctx.lineTo(cx, cy + size + 10);
        ctx.stroke();
      }
    };

    const overlayTimer = window.setInterval(draw, 150);

    return () => {
      window.clearInterval(overlayTimer);
      // Removing the element fires disconnectedCallback -> closes WebRTC.
      try {
        host.removeChild(el);
      } catch {
        /* already gone */
      }
      setConnected(false);
    };
  }, [cameraId]);

  return (
    <div className="relative w-full h-full bg-black">
      {/* WebRTC video mounts here (React leaves this div's children alone) */}
      <div ref={videoHostRef} className="absolute inset-0" />
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full z-10 pointer-events-none"
      />

      {!connected && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-terminal-surface/80">
          <div className="text-center">
            <div className="w-8 h-8 border-2 border-terminal-accent border-t-transparent rounded-full animate-spin mx-auto mb-2" />
            <span className="text-terminal-muted text-sm">Connecting...</span>
          </div>
        </div>
      )}
    </div>
  );
}
