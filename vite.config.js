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
      // The API compares a request's Origin with its Host, so the dev server's Host must reach it as is.
      '/api': { target: process.env.YOUHOARD_API ?? 'http://127.0.0.1:8000', changeOrigin: false }
    }
  }
})
