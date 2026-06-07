/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'terminal': {
          bg: '#0a0000',
          surface: '#150000',
          border: '#2d0a0a',
          text: '#f5e0e0',
          muted: '#7d4545',
          accent: '#e63333',
          danger: '#ff4444',
          warning: '#ff8800',
        }
      },
      fontFamily: {
        'mono': ['JetBrains Mono', 'Fira Code', 'monospace'],
        'display': ['Orbitron', 'sans-serif'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'scan': 'scan 2s linear infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        scan: {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(100%)' }
        },
        glow: {
          '0%': { boxShadow: '0 0 5px #e63333, 0 0 10px #e63333' },
          '100%': { boxShadow: '0 0 10px #e63333, 0 0 20px #e63333, 0 0 30px #cc0000' }
        }
      }
    },
  },
  plugins: [],
}

