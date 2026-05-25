/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{vue,js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        neon: {
          pink: '#FE2C55',
          cyan: '#4ECDC4',
          purple: '#667eea',
          peach: '#FFE4E1',
          gold: '#FFDAB9',
        },
        dark: {
          bg: '#0a0a0a',
          panel: '#1a0a2e',
          card: '#0f1a2a',
          border: 'rgba(255,255,255,0.1)',
        },
      },
      fontFamily: {
        mono: ['Monaco', 'Consolas', 'Liberation Mono', 'monospace'],
      },
      boxShadow: {
        'neon-pink': '0 0 20px rgba(254,44,85,0.5), 0 0 40px rgba(254,44,85,0.3)',
        'neon-cyan': '0 0 20px rgba(78,205,196,0.5), 0 0 40px rgba(78,205,196,0.3)',
        'neon-purple': '0 0 20px rgba(102,126,234,0.5), 0 0 40px rgba(102,126,234,0.3)',
        'neon-peach': '0 0 20px rgba(255,228,225,0.5), 0 0 40px rgba(255,228,225,0.3)',
      },
      animation: {
        'pulse-glow': 'pulse-glow 1s infinite alternate',
        'scan': 'scan 4s linear infinite',
        'blink': 'blink 1s infinite',
      },
      keyframes: {
        'pulse-glow': {
          '0%': { boxShadow: '0 0 20px rgba(254,44,85,0.5)' },
          '100%': { boxShadow: '0 0 40px rgba(254,44,85,0.8)' },
        },
        'scan': {
          '0%': { top: '0' },
          '100%': { top: '100%' },
        },
        'blink': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.3' },
        },
      },
    },
  },
  plugins: [],
}