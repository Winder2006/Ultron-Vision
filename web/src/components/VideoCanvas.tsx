import { useEffect, useRef, useState } from 'react';
import { createStreamClient, Face, TrackingStatus } from '../api/client';

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
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [connected, setConnected] = useState(false);

  // Keep latest overlay data in refs so the draw loop (set up once per camera)
  // always reads current values without re-subscribing the stream.
  const facesRef = useRef(faces);
  const trackingRef = useRef(tracking);
  const motionRef = useRef(motionRegions);
  const showRef = useRef(showOverlays);
  facesRef.current = faces;
  trackingRef.current = tracking;
  motionRef.current = motionRegions;
  showRef.current = showOverlays;

  useEffect(() => {
    const streamClient = createStreamClient(cameraId);
    const img = new Image();
    // Frame-space dimensions (the source JPEG size) for scaling overlays.
    let frameW = 640;
    let frameH = 360;

    const draw = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      // Match the drawing buffer to the displayed size.
      const rect = canvas.getBoundingClientRect();
      const w = Math.round(rect.width);
      const h = Math.round(rect.height);
      if (w > 0 && h > 0 && (canvas.width !== w || canvas.height !== h)) {
        canvas.width = w;
        canvas.height = h;
      }

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (img.complete && img.naturalWidth > 0) {
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      }

      if (!showRef.current) return;

      const scaleX = canvas.width / frameW;
      const scaleY = canvas.height / frameH;

      // Motion regions
      motionRef.current.forEach((region) => {
        const [x, y, rw, rh] = region.bbox;
        ctx.strokeStyle = 'rgba(255, 136, 0, 0.5)';
        ctx.fillStyle = 'rgba(255, 136, 0, 0.1)';
        ctx.lineWidth = 1;
        ctx.fillRect(x * scaleX, y * scaleY, rw * scaleX, rh * scaleY);
        ctx.strokeRect(x * scaleX, y * scaleY, rw * scaleX, rh * scaleY);
      });

      // Face boxes — known = orange, unknown = red (Ultron palette)
      facesRef.current.forEach((face) => {
        const [x, y, fw, fh] = face.bbox;
        const sx = x * scaleX;
        const sy = y * scaleY;
        const sw = fw * scaleX;
        const sh = fh * scaleY;

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
        const cx = (x + tw / 2) * scaleX;
        const cy = (y + th / 2) * scaleY;
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

    img.onload = () => {
      frameW = img.naturalWidth || frameW;
      frameH = img.naturalHeight || frameH;
      draw();
    };

    streamClient.connect(
      (frame) => {
        setConnected(true);
        img.src = `data:image/jpeg;base64,${frame.data}`;
      },
      // Feed dropped (Jetson reboot, network blip): flip back to the
      // "Connecting..." overlay instead of leaving a stale frozen frame.
      (isConnected) => setConnected(isConnected)
    );

    // Redraw overlays on a light interval even between frames so boxes track.
    const overlayTimer = window.setInterval(draw, 200);

    return () => {
      window.clearInterval(overlayTimer);
      streamClient.disconnect();
    };
  }, [cameraId]);

  return (
    <div className="relative w-full h-full bg-black">
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />

      {!connected && (
        <div className="absolute inset-0 flex items-center justify-center bg-terminal-surface/80">
          <div className="text-center">
            <div className="w-8 h-8 border-2 border-terminal-accent border-t-transparent rounded-full animate-spin mx-auto mb-2" />
            <span className="text-terminal-muted text-sm">Connecting...</span>
          </div>
        </div>
      )}
    </div>
  );
}
