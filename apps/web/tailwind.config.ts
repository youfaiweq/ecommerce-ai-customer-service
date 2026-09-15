import type { Config } from 'tailwindcss'

/**
 * Apple-informed 极简高级 3C 配色 / 字体 / 间距系统
 * 完整 token 见 README.md "设计语言"章节
 */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts}'],
  theme: {
    extend: {
      colors: {
        // Surface & border
        bg: { DEFAULT: '#FFFFFF', tint: '#F5F5F7', quiet: '#FAFAFA' },
        ink: { primary: '#0A0A0A', body: '#1D1D1F', quiet: '#6E6E73', hint: '#9CA0A8' },
        line: { DEFAULT: '#E5E5E7', strong: '#D2D2D7', thin: '#EFEFF1' },
        // Accent (single blue — Apple-informed)
        accent: { DEFAULT: '#0071E3', hover: '#006ED1', soft: '#E6F1FB' },
        // Semantic
        sale: '#FF3B30',
        stock: '#34C759',
        preorder: '#FF9500',
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          'SF Pro Display',
          'Inter',
          'Segoe UI',
          'system-ui',
          'sans-serif',
        ],
        mono: ['JetBrains Mono', 'SF Mono', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['11px', { lineHeight: '1.5', letterSpacing: '0.04em' }],
        xs: ['12px', { lineHeight: '1.5' }],
        base: ['13px', { lineHeight: '1.6' }],
        sm: ['14px', { lineHeight: '1.5' }],
        lg: ['18px', { lineHeight: '1.4' }],
        xl: ['24px', { lineHeight: '1.2', letterSpacing: '-0.4px' }],
        '2xl': ['40px', { lineHeight: '1.05', letterSpacing: '-1px' }],
        '3xl': ['64px', { lineHeight: '1.04', letterSpacing: '-2.4px' }],
      },
      spacing: {
        18: '4.5rem',
        22: '5.5rem',
        30: '7.5rem',
      },
      borderRadius: {
        pill: '999px',
      },
      maxWidth: {
        container: '1240px',
      },
      transitionTimingFunction: {
        out: 'cubic-bezier(0.32, 0.72, 0, 1)',
      },
    },
  },
} satisfies Config
