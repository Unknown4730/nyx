/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Midnight-black canvas, deep-charcoal surfaces, electric violet + icy cyan accents.
        void: '#05060b',
        ink: '#090b12',
        surface: '#0e1119',
        raised: '#151a27',
        overlay: '#1b2131',
        hairline: '#232a3d',
        muted: '#8b93ab',
        soft: '#c3c9db',
        violet: {
          300: '#c4b5fd',
          400: '#a78bfa',
          500: '#8b5cf6',
          600: '#7c5cff',
          700: '#643fdd',
          900: '#241a4d',
        },
        cyan: {
          300: '#67e8f9',
          400: '#22d3ee',
          500: '#06b6d4',
          900: '#083241',
        },
        signal: {
          strong: '#34d399',
          good: '#22d3ee',
          partial: '#fbbf24',
          poor: '#fb7185',
          unknown: '#8b93ab',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.02em' }],
      },
      borderRadius: {
        card: '14px',
        chip: '999px',
      },
      boxShadow: {
        panel: '0 1px 0 0 rgba(255,255,255,0.04) inset, 0 24px 60px -32px rgba(0,0,0,0.9)',
        'glow-violet': '0 0 0 1px rgba(124,92,255,0.35), 0 12px 40px -18px rgba(124,92,255,0.65)',
        'glow-cyan': '0 0 0 1px rgba(34,211,238,0.3), 0 12px 40px -20px rgba(34,211,238,0.5)',
        node: '0 18px 40px -28px rgba(0,0,0,0.95)',
      },
      backgroundImage: {
        'nyx-mesh':
          'radial-gradient(900px 480px at 12% -10%, rgba(124,92,255,0.16), transparent 60%), radial-gradient(760px 420px at 92% 8%, rgba(34,211,238,0.12), transparent 62%), radial-gradient(700px 500px at 50% 108%, rgba(124,92,255,0.08), transparent 60%)',
        'nyx-grid':
          'linear-gradient(to right, rgba(147,161,199,0.09) 1px, transparent 1px), linear-gradient(to bottom, rgba(147,161,199,0.09) 1px, transparent 1px)',
        'nyx-line': 'linear-gradient(90deg, rgba(124,92,255,0.75), rgba(34,211,238,0.55), transparent)',
        'nyx-fade': 'linear-gradient(180deg, rgba(9,11,18,0.9), rgba(9,11,18,0))',
      },
      backgroundSize: {
        grid: '32px 32px',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'sweep': {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(220%)' },
        },
        'pulse-soft': {
          '0%, 100%': { opacity: '0.55' },
          '50%': { opacity: '1' },
        },
      },
      animation: {
        'fade-up': 'fade-up 240ms ease-out both',
        sweep: 'sweep 1.6s ease-in-out infinite',
        'pulse-soft': 'pulse-soft 1.8s ease-in-out infinite',
      },
      transitionTimingFunction: {
        smooth: 'cubic-bezier(0.22, 0.61, 0.36, 1)',
      },
    },
  },
  plugins: [],
}
