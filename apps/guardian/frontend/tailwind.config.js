/** @type {import('tailwindcss').Config} */
const ink = {
  50: '#FBF8F3', 100: '#F0E8DD', 200: '#DECEC1', 300: '#BDA997',
  400: '#7C6A5F', 500: '#75665B', 600: '#64564C', 700: '#53463D',
  800: '#40352D', 900: '#2D2520', 950: '#211B17',
};
const brick = {
  50: '#FBF0EB', 100: '#F5DED5', 200: '#E9BDB0', 300: '#D99482',
  400: '#C67560', 500: '#B35542', 600: '#A64232', 700: '#8C3529',
  800: '#722920', 900: '#581F19', 950: '#3B1611',
};
const olive = {
  50: '#F4F5EB', 100: '#E9ECD9', 200: '#D5DAB9', 300: '#B6BF93',
  400: '#929E6D', 500: '#788554', 600: '#637044', 700: '#526039',
  800: '#414D2E', 900: '#303A23', 950: '#21291A',
};
const ochre = {
  50: '#FAF4E7', 100: '#F5EACF', 200: '#E9D6A3', 300: '#D4B571',
  400: '#BC9349', 500: '#AC7C35', 600: '#9B6A2F', 700: '#815524',
  800: '#69441F', 900: '#51341B', 950: '#352215',
};

module.exports = {
  darkMode: ['class'],
  content: ['./src/**/*.{js,jsx,ts,tsx}', './public/index.html'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-body)'],
        display: ['var(--font-display)'],
      },
      fontSize: {
        xs: ['0.8125rem', { lineHeight: '1.5' }],
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      colors: {
        ink, brick, olive, ochre,
        danger: brick,
        // Shared primitives and auth fallback screens retain their neutral utility names.
        slate: ink,
        gray: ink,
        amber: ochre,
        red: brick,
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        card: { DEFAULT: 'hsl(var(--card))', foreground: 'hsl(var(--card-foreground))' },
        popover: { DEFAULT: 'hsl(var(--popover))', foreground: 'hsl(var(--popover-foreground))' },
        primary: { DEFAULT: 'hsl(var(--primary))', foreground: 'hsl(var(--primary-foreground))' },
        secondary: { DEFAULT: 'hsl(var(--secondary))', foreground: 'hsl(var(--secondary-foreground))' },
        muted: { DEFAULT: 'hsl(var(--muted))', foreground: 'hsl(var(--muted-foreground))' },
        accent: { DEFAULT: 'hsl(var(--accent))', foreground: 'hsl(var(--accent-foreground))' },
        destructive: { DEFAULT: 'hsl(var(--destructive))', foreground: 'hsl(var(--destructive-foreground))' },
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        chart: Object.fromEntries([1, 2, 3, 4, 5].map(index => [index, `hsl(var(--chart-${index}))`])),
      },
      keyframes: {
        'accordion-down': { from: { height: '0' }, to: { height: 'var(--radix-accordion-content-height)' } },
        'accordion-up': { from: { height: 'var(--radix-accordion-content-height)' }, to: { height: '0' } },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
};
