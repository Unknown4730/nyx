/** @type {import('tailwindcss').Config} */
// NYX visual identity: "Obsidian Glass × Electric Acid".
// Solid colour tokens only. The design rule is NO GRADIENTS: no gradient
// background images are defined here, and none may be added.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        obsidian: '#08090D', // page background
        carbon: '#101218', // surface
        elevated: '#171A23', // raised surface
        acid: '#D7FF3F', // primary action and key state
        violet: '#A78BFA', // supporting accent
        cyan: '#70E7FF', // supporting accent
        chalk: '#F4F4F0', // primary text
        silver: '#9296A3', // muted text
        signal: '#FF5B6E', // errors and caution
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Consolas', 'Menlo', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.75rem', { lineHeight: '1rem', letterSpacing: '0.01em' }],
      },
      borderRadius: {
        panel: '16px',
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
