import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 55173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:58080',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://127.0.0.1:58080',
        changeOrigin: true,
      }
    }
  }
})
