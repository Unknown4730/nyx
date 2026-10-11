/** @type {import('tailwindcss').Config} */
// NYX visual identity: "The Midnight Observatory".
// Solid colour tokens only. The design rule is NO GRADIENTS: none may be defined
// or used here or in any component. Glass surface tokens (rgba with alpha) live in
// src/index.css as CSS custom properties so the same values drive every glass level.
//
// Palette roles (each colour has one job):
//   primary   violet   principal interactive accent, primary actions, focus
//   blue      icy blue supporting interactions, success, positive state
//   champagne warnings and cautions
//   coral     errors and trust-boundary risk
//   silver    secondary text;  muted  tertiary text and disabled content
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        obsidian: '#080911', // page background
        carbon: '#0D1020', // secondary background
        elevated: '#15182B', // solid surface (inputs, nodes, insets)
        primary: '#B9A0FF', // violet accent: primary actions, focus, important information
        'primary-hover': '#C9B7FF',
        blue: '#73D9FF', // icy blue: supporting interactions, success
        coral: '#FF8DA1', // errors, trust boundaries
        champagne: '#FFC994', // warnings and cautions
        chalk: '#F4F2FF', // primary text
        silver: '#A5A9C5', // secondary text
        muted: '#777D9C', // tertiary text, disabled
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Consolas', 'Menlo', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.75rem', { lineHeight: '1rem', letterSpacing: '0.01em' }],
      },
      borderRadius: {
        panel: '18px',
        chip: '999px',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        spin: {
          to: { transform: 'rotate(360deg)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 240ms ease-out both',
        spin: 'spin 900ms linear infinite',
      },
    },
  },
  plugins: [],
}
