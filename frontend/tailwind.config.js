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
        // Gradient presets
        gradient: {
          primary: 'from-neon-pink via-neon-pinkLight to-neon-peach',
          secondary: 'from-neon-cyan via-neon-cyanLight to-neon-green',
          tertiary: 'from-neon-purple via-neon-purpleLight to-neon-blue',
          warm: 'from-neon-peach via-neon-peachLight to-neon-yellow',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Monaco', 'Consolas', 'Liberation Mono', 'monospace'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      fontSize: {
        'display': ['2.5rem', { lineHeight: '1.2', letterSpacing: '-0.02em' }],
        'title': ['1.5rem', { lineHeight: '1.3', letterSpacing: '-0.01em' }],
        'body': ['0.9375rem', { lineHeight: '1.6' }],
        'caption': ['0.75rem', { lineHeight: '1.4' }],
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
        // Light theme shadows
        'glass': '0 1px 3px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.05)',
        'glass-lg': '0 4px 6px rgba(0,0,0,0.05), 0 10px 20px rgba(0,0,0,0.08)',
        'card': '0 2px 8px rgba(0,0,0,0.04), 0 4px 16px rgba(0,0,0,0.06)',
        'card-hover': '0 4px 12px rgba(0,0,0,0.08), 0 8px 24px rgba(0,0,0,0.1)',
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
        // Enhanced animations for cool UI
        'pulse-glow': 'pulse-glow 3s ease-in-out infinite',
        'scan': 'scan 6s ease-in-out infinite',
        'blink': 'blink 1.5s ease-in-out infinite',
        'spin-slow': 'spin 3s linear infinite',
        'bounce-subtle': 'bounce-subtle 0.6s ease-out',
        'float': 'float 4s ease-in-out infinite',
        'float-slow': 'float 6s ease-in-out infinite',
        'shimmer': 'shimmer 2.5s linear infinite',
        'gradient-flow': 'gradient-flow 6s ease infinite',
        'ripple': 'ripple 0.6s ease-out',
        'slide-up': 'slide-up 0.4s ease-out',
        'fade-in': 'fade-in 0.5s ease-out',
        'scale-in': 'scale-in 0.3s ease-out',
        'wiggle': 'wiggle 1s ease-in-out infinite',
        'bounce-in': 'bounce-in 0.5s ease-out',
        'slide-in-left': 'slide-in-left 0.3s ease-out',
        'slide-in-right': 'slide-in-right 0.3s ease-out',
        'rotate-slow': 'rotate-slow 20s linear infinite',
        'morph': 'morph 8s ease-in-out infinite',
        'color-shift': 'color-shift 5s ease infinite',
        // New cool animations
        'neon-flow': 'neon-flow 3s ease-in-out infinite',
        'cyber-pulse': 'cyber-pulse 2s ease-in-out infinite',
        'data-scroll': 'data-scroll 20s linear infinite',
        'particle-drift': 'particle-drift 15s ease-in-out infinite',
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
        'scan': {
          '0%': { top: '0%', opacity: '0' },
          '10%': { opacity: '0.7' },
          '90%': { opacity: '0.7' },
          '100%': { top: '100%', opacity: '0' },
        },
        'blink': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.3' },
        },
        'bounce-subtle': {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-5px)' },
        },
        'float': {
          '0%, 100%': { transform: 'translateY(0) rotate(0deg)' },
          '50%': { transform: 'translateY(-8px) rotate(2deg)' },
        },
        'float-slow': {
          '0%, 100%': { transform: 'translateY(0) rotate(0deg)' },
          '50%': { transform: 'translateY(-12px) rotate(1deg)' },
        },
        'shimmer': {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        'gradient-flow': {
          '0%, 100%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
        },
        'ripple': {
          '0%': { transform: 'scale(0)', opacity: '0.5' },
          '100%': { transform: 'scale(2.5)', opacity: '0' },
        },
        'slide-up': {
          '0%': { transform: 'translateY(15px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'scale-in': {
          '0%': { transform: 'scale(0.9)', opacity: '0' },
          '70%': { transform: 'scale(1.02)' },
          '100%': { transform: 'scale(1)', opacity: '1' },
        },
        'wiggle': {
          '0%, 100%': { transform: 'rotate(-3deg)' },
          '50%': { transform: 'rotate(3deg)' },
        },
        'bounce-in': {
          '0%': { transform: 'scale(0.3)', opacity: '0' },
          '50%': { transform: 'scale(1.08)' },
          '70%': { transform: 'scale(0.95)' },
          '100%': { transform: 'scale(1)', opacity: '1' },
        },
        'slide-in-left': {
          '0%': { transform: 'translateX(-25px)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        'slide-in-right': {
          '0%': { transform: 'translateX(25px)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        'rotate-slow': {
          '0%': { transform: 'rotate(0deg)' },
          '100%': { transform: 'rotate(360deg)' },
        },
        'morph': {
          '0%, 100%': { borderRadius: '60% 40% 30% 70% / 60% 30% 70% 40%' },
          '25%': { borderRadius: '40% 60% 70% 30% / 40% 70% 30% 60%' },
          '50%': { borderRadius: '30% 60% 70% 40% / 50% 60% 30% 60%' },
          '75%': { borderRadius: '50% 40% 60% 40% / 60% 40% 50% 50%' },
        },
        'color-shift': {
          '0%, 100%': { filter: 'hue-rotate(0deg)' },
          '50%': { filter: 'hue-rotate(15deg)' },
        },
        'neon-flow': {
          '0%, 100%': { opacity: '0.6', transform: 'scale(1)' },
          '50%': { opacity: '1', transform: 'scale(1.02)' },
        },
        'cyber-pulse': {
          '0%, 100%': { boxShadow: '0 0 4px rgba(244,63,94,0.2)' },
          '50%': { boxShadow: '0 0 8px rgba(244,63,94,0.4), 0 0 12px rgba(20,184,166,0.3)' },
        },
        'data-scroll': {
          '0%': { transform: 'translateY(0)' },
          '100%': { transform: 'translateY(-48px)' },
        },
        'particle-drift': {
          '0%, 100%': { transform: 'translate(0, 0) rotate(0deg)' },
          '25%': { transform: 'translate(10px, -5px) rotate(5deg)' },
          '50%': { transform: 'translate(5px, 10px) rotate(-5deg)' },
          '75%': { transform: 'translate(-5px, 5px) rotate(3deg)' },
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
      backdropBlur: {
        xs: '2px',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
  ],
}
