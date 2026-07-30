/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{vue,js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // Modern refined neon palette - softer gradients
        neon: {
          // Primary accent - refined coral/rose
          pink: '#F43F5E',
          pinkLight: '#FB7185',
          pinkDark: '#BE123C',
          // Secondary accent - refined teal/emerald
          cyan: '#14B8A6',
          cyanLight: '#5EEAD4',
          cyanDark: '#0D9488',
          // Tertiary - refined indigo/violet
          purple: '#8B5CF6',
          purpleLight: '#A78BFA',
          purpleDark: '#7C3AED',
          // Warm accent - refined amber/orange
          peach: '#F59E0B',
          peachLight: '#FBBF24',
          peachDark: '#D97706',
          // Supporting colors
          blue: '#3B82F6',
          blueLight: '#60A5FA',
          green: '#10B981',
          greenLight: '#34D399',
          yellow: '#EAB308',
          yellowLight: '#FACC15',
          red: '#EF4444',
          redLight: '#F87171',
        },
        // Light mode backgrounds
        light: {
          bg: '#F8FAFC',      // Slate 50 - main background
          bgAlt: '#F1F5F9',   // Slate 100 - alternate
          panel: '#FFFFFF',   // White panels
          panelAlt: '#F8FAFC',
          card: '#FFFFFF',    // White cards
          cardHover: '#F1F5F9',
          border: 'rgba(0,0,0,0.06)',
          borderLight: 'rgba(0,0,0,0.1)',
          borderStrong: 'rgba(0,0,0,0.15)',
        },
        // Text colors for light theme
        text: {
          primary: '#1E293B',   // Slate 800
          secondary: '#475569', // Slate 600
          tertiary: '#64748B',  // Slate 500
          muted: '#94A3B8',     // Slate 400
          light: '#CBD5E1',     // Slate 300
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Monaco', 'Consolas', 'Liberation Mono', 'monospace'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      boxShadow: {
        // Subtle neon shadows - elegant and minimal for light theme
        'neon-pink': '0 0 8px rgba(244,63,94,0.15)',
        'neon-pink-sm': '0 0 4px rgba(244,63,94,0.2)',
        'neon-pink-lg': '0 0 12px rgba(244,63,94,0.2)',
        'neon-cyan': '0 0 8px rgba(20,184,166,0.15)',
        'neon-cyan-sm': '0 0 4px rgba(20,184,166,0.2)',
        'neon-cyan-lg': '0 0 12px rgba(20,184,166,0.2)',
        'neon-purple': '0 0 8px rgba(139,92,246,0.15)',
        'neon-purple-sm': '0 0 4px rgba(139,92,246,0.2)',
        'neon-purple-lg': '0 0 12px rgba(139,92,246,0.2)',
        'neon-peach': '0 0 8px rgba(245,158,11,0.15)',
      },
      // INF-07: semantic z-index layers — prefer these over z-[N] magic values.
      zIndex: {
        base: '0',
        sticky: '10',
        overlay: '20',
        modal: '50',
        toast: '60',
      },
      animation: {
        'pulse-glow': 'pulse-glow 3s ease-in-out infinite',
        'spin-slow': 'spin 3s linear infinite',
        'float-slow': 'float 6s ease-in-out infinite',
        'gradient-flow': 'gradient-flow 6s ease infinite',
      },
      keyframes: {
        'pulse-glow': {
          '0%, 100%': {
            boxShadow: '0 0 8px rgba(244,63,94,0.2), 0 0 20px rgba(244,63,94,0.1)',
            transform: 'scale(1)',
          },
          '50%': {
            boxShadow: '0 0 15px rgba(244,63,94,0.3), 0 0 35px rgba(244,63,94,0.15)',
            transform: 'scale(1.02)',
          },
        },
        'float': {
          '0%, 100%': { transform: 'translateY(0) rotate(0deg)' },
          '50%': { transform: 'translateY(-8px) rotate(2deg)' },
        },
        'gradient-flow': {
          '0%, 100%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
        },
      },
      transitionDuration: {
        '250': '250ms',
        '350': '350ms',
        '500': '500ms',
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'gradient-conic': 'conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))',
        'shimmer-gradient': 'linear-gradient(90deg, transparent 0%, rgba(0,0,0,0.03) 50%, transparent 100%)',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
  ],
}
