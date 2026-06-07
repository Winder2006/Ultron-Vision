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
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 640, height: 360 });
  const [connected, setConnected] = useState(false);
  const imageRef = useRef<HTMLImageElement | null>(null);

  // Stream connection
  useEffect(() => {
    const streamClient = createStreamClient(cameraId);
    
    const img = new Image();
    imageRef.current = img;

    streamClient.connect((frame) => {
      setConnected(true);
      img.onload = () => {
        if (dimensions.width !== img.width || dimensions.height !== img.height) {
          setDimensions({ width: img.width, height: img.height });
        }
        drawFrame();
      };
      img.src = `data:image/jpeg;base64,${frame.data}`;
    });

    return () => {
      streamClient.disconnect();
    };
  }, [cameraId]);

  // Draw frame and overlays
  const drawFrame = () => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    const img = imageRef.current;
    
    if (!canvas || !ctx || !img) return;

    // Clear and draw frame
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    if (!showOverlays) return;

    // Calculate scale factors
    const scaleX = canvas.width / dimensions.width;
    const scaleY = canvas.height / dimensions.height;

    // Draw motion regions
    motionRegions.forEach(region => {
      const [x, y, w, h] = region.bbox;
      ctx.strokeStyle = 'rgba(255, 170, 0, 0.5)';
      ctx.fillStyle = 'rgba(255, 170, 0, 0.1)';
      ctx.lineWidth = 1;
      ctx.fillRect(x * scaleX, y * scaleY, w * scaleX, h * scaleY);
      ctx.strokeRect(x * scaleX, y * scaleY, w * scaleX, h * scaleY);
    });

    // Draw face boxes
    faces.forEach(face => {
      const [x, y, w, h] = face.bbox;
      const scaledX = x * scaleX;
      const scaledY = y * scaleY;
      const scaledW = w * scaleX;
      const scaledH = h * scaleY;

      // Box
      ctx.strokeStyle = face.known ? '#ff6600' : '#ff0000';
      ctx.lineWidth = 2;
      ctx.shadowColor = face.known ? '#ff6600' : '#ff0000';
      ctx.shadowBlur = 12;
      ctx.strokeRect(scaledX, scaledY, scaledW, scaledH);
      ctx.shadowBlur = 0;

      // Label background
      const label = face.known
        ? `${face.name} (${Math.round(face.confidence * 100)}%)`
        : 'UNKNOWN // THREAT';
      ctx.font = '12px JetBrains Mono';
      const textWidth = ctx.measureText(label).width;

      ctx.fillStyle = face.known ? '#ff6600' : '#ff0000';
      ctx.fillRect(scaledX, scaledY - 20, textWidth + 8, 18);

      // Label text
      ctx.fillStyle = '#0a0000';
      ctx.fillText(label, scaledX + 4, scaledY - 6);
    });

    // Draw tracking crosshair
    if (tracking?.active && tracking.bbox) {
      const [x, y, w, h] = tracking.bbox;
      const centerX = (x + w / 2) * scaleX;
      const centerY = (y + h / 2) * scaleY;
      const size = 30;

      ctx.strokeStyle = '#e63333';
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 5]);

      // Circle
      ctx.beginPath();
      ctx.arc(centerX, centerY, size, 0, Math.PI * 2);
      ctx.stroke();

      // Crosshair lines
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(centerX - size - 10, centerY);
      ctx.lineTo(centerX - size + 5, centerY);
      ctx.moveTo(centerX + size - 5, centerY);
      ctx.lineTo(centerX + size + 10, centerY);
      ctx.moveTo(centerX, centerY - size - 10);
      ctx.lineTo(centerX, centerY - size + 5);
      ctx.moveTo(centerX, centerY + size - 5);
      ctx.lineTo(centerX, centerY + size + 10);
      ctx.stroke();
    }
  };

  // Redraw on face/tracking changes
  useEffect(() => {
    drawFrame();
  }, [faces, tracking, motionRegions]);

  // Handle resize
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver(() => {
      const canvas = canvasRef.current;
      if (canvas && container) {
        canvas.width = container.clientWidth;
        canvas.height = container.clientHeight;
        drawFrame();
      }
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={containerRef} className="relative w-full h-full bg-black">
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full object-contain"
      />
      
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

