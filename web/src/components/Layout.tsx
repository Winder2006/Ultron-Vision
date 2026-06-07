import { ReactNode } from 'react';
import {
  Camera,
  Activity,
  Users,
  Film,
  Settings,
  AlertTriangle,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { SystemStatus } from '../api/client';
import SystemStatusBar from './SystemStatusBar';

type View = 'cameras' | 'activity' | 'crew' | 'recordings' | 'settings';

interface LayoutProps {
  children: ReactNode;
  currentView: View;
  onNavigate: (view: View) => void;
  status: SystemStatus | null;
  alertCount: number;
  connected: boolean;
}

const navItems: { id: View; label: string; icon: typeof Camera }[] = [
  { id: 'cameras', label: 'Cameras', icon: Camera },
  { id: 'activity', label: 'Activity', icon: Activity },
  { id: 'crew', label: 'Crew', icon: Users },
  { id: 'recordings', label: 'Recordings', icon: Film },
  { id: 'settings', label: 'Settings', icon: Settings },
];

export default function Layout({
  children,
  currentView,
  onNavigate,
  status,
  alertCount,
  connected,
}: LayoutProps) {
  return (
    <div className="h-screen flex flex-col bg-terminal-bg overflow-hidden">
      {/* Header */}
      <header className="h-14 bg-terminal-surface border-b border-terminal-border flex items-center justify-between px-4 flex-shrink-0">
        <div className="flex items-center gap-4">
          <h1 className="font-display font-bold text-xl tracking-wider">
            <span className="text-terminal-accent glow-text">ULTRON</span>
            <span className="text-terminal-text ml-2">VISION</span>
          </h1>
          
          <div className="h-6 w-px bg-terminal-border" />
          
          <div className="flex items-center gap-2">
            {connected ? (
              <Wifi className="w-4 h-4 text-terminal-accent" />
            ) : (
              <WifiOff className="w-4 h-4 text-terminal-danger animate-pulse" />
            )}
            <span className={`text-xs ${connected ? 'text-terminal-accent' : 'text-terminal-danger'}`}>
              {connected ? 'ONLINE' : 'OFFLINE'}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          {alertCount > 0 && (
            <button
              onClick={() => onNavigate('activity')}
              className="flex items-center gap-2 px-3 py-1.5 rounded bg-terminal-danger/20 border border-terminal-danger/50 text-terminal-danger hover:bg-terminal-danger/30 transition-colors"
            >
              <AlertTriangle className="w-4 h-4" />
              <span className="text-sm font-medium">{alertCount} Alert{alertCount !== 1 ? 's' : ''}</span>
            </button>
          )}

          <SystemStatusBar status={status} />
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <nav className="w-16 lg:w-48 bg-terminal-surface border-r border-terminal-border flex-shrink-0">
          <ul className="p-2 space-y-1">
            {navItems.map(item => {
              const Icon = item.icon;
              const isActive = currentView === item.id;
              
              return (
                <li key={item.id}>
                  <button
                    onClick={() => onNavigate(item.id)}
                    className={`
                      w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all
                      ${isActive
                        ? 'bg-terminal-accent/20 text-terminal-accent border border-terminal-accent/30'
                        : 'text-terminal-muted hover:bg-terminal-border/50 hover:text-terminal-text border border-transparent'
                      }
                    `}
                  >
                    <Icon className="w-5 h-5 flex-shrink-0" />
                    <span className="hidden lg:block text-sm font-medium">
                      {item.label}
                    </span>
                    {item.id === 'activity' && alertCount > 0 && (
                      <span className="hidden lg:flex ml-auto bg-terminal-danger text-white text-xs font-bold px-1.5 py-0.5 rounded-full">
                        {alertCount}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Main Content */}
        <main className="flex-1 overflow-auto">
          {children}
        </main>
      </div>
    </div>
  );
}

