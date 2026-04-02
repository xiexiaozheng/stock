/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // 主色调
        bg: {
          primary: '#1a1f2e',
          secondary: '#222840',
          card: '#1e2538',
          hover: '#2a3150',
        },
        accent: {
          DEFAULT: '#00d4aa',
          light: '#00f0c0',
          dark: '#00a888',
        },
        text: {
          primary: '#e8eaf0',
          secondary: '#8892b0',
          muted: '#4a5568',
        },
        border: {
          DEFAULT: '#2d3561',
          light: '#3d4a7a',
        },
        // 涨跌颜色（A股红涨绿跌）
        rise: '#ff4d4d',
        fall: '#26a95b',
        neutral: '#8892b0',
      },
      fontFamily: {
        mono: ['DM Mono', 'JetBrains Mono', 'Fira Code', 'monospace'],
        sans: ['Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
