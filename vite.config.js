import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: 'app/static/dist',
    emptyOutDir: true
  },
  server: {
    proxy: {
      '/api': process.env.YOUHOARD_API ?? 'http://127.0.0.1:8000'
    }
  }
})
