/** @type {import('tailwindcss').Config} */
// Build with ./build-css.sh — output is committed to static/css/tailwind.css
module.exports = {
  content: [
    './templates/**/*.html',
    './static/js/**/*.js',
  ],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"JetBrains Mono"', 'monospace'],
        sans: ['"Atkinson Hyperlegible"', '"DM Sans"', 'sans-serif'],
      },
      colors: {
        surface:  'var(--c-surface)',
        panel:    'var(--c-panel)',
        raised:   'var(--c-raised)',
        hovered:  'var(--c-hovered)',
        lit:      'var(--c-lit)',
      },
      borderColor: {
        DEFAULT: 'var(--c-border)',
        lit:     'var(--c-border-lit)',
      }
    }
  }
}
