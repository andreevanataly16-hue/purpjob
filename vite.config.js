import { defineConfig } from 'vite'

// Dev-сервер с автообновлением: любое сохранение файла в web/ мгновенно
// перерисовывает страницу в браузере, руками обновлять ничего не нужно.
export default defineConfig({
  root: 'web',
  server: {
    port: 8000,
    open: true,      // при запуске сам открывает браузер
    strictPort: false, // если 8000 занят — возьмёт следующий свободный
    proxy: {
      // Запросы к /api уходят на FastAPI. Благодаря этому фронтенд и бэкенд
      // для браузера находятся на одном адресе: не нужен CORS, а httpOnly-кука
      // сессии ходит как обычная кука того же сайта.
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true
  }
})
