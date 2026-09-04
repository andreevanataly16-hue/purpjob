import { defineConfig } from 'vite'

// Dev-сервер с автообновлением: любое сохранение файла в web/ мгновенно
// перерисовывает страницу в браузере, руками обновлять ничего не нужно.
export default defineConfig({
  root: 'web',
  server: {
    port: 8000,
    open: true,      // при запуске сам открывает браузер
    strictPort: false // если 8000 занят — возьмёт следующий свободный
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true
  }
})
