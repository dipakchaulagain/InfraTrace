/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Theme & Design Specification palette
        primary: {
          DEFAULT: '#5cbdb9',
          50:  '#f0fafa',
          100: '#d9f2f1',
          200: '#b3e6e4',
          300: '#80d3d0',
          400: '#5cbdb9',   // ← primary accent
          500: '#3ea4a0',
          600: '#2f8481',
          700: '#296a68',
          800: '#265655',
          900: '#234847',
        },
        mint: {
          DEFAULT: '#c2edda',
          50:  '#f2fcf7',
          100: '#dff7ec',
          200: '#c2edda',   // ← secondary accent
          300: '#93dfc0',
          400: '#5ec9a1',
          500: '#38b285',
          600: '#288f6b',
          700: '#237257',
          800: '#1f5b46',
          900: '#1c4c3b',
        },
        background: '#ebf6f5',   // soft off-white/mint background
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        DEFAULT: '0.5rem',
      },
      boxShadow: {
        card: '0 1px 4px 0 rgba(0,0,0,0.08), 0 0 0 1px rgba(0,0,0,0.04)',
        'card-hover': '0 4px 16px 0 rgba(0,0,0,0.12), 0 0 0 1px rgba(92,189,185,0.2)',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
  ],
}
