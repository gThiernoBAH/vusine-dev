import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import fs from 'fs'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': path.resolve(import.meta.dirname, './src'),
      },
    },
    server: {
      host: '0.0.0.0',
      port: parseInt(env.VITE_PORT),
      strictPort: true,
      // Certificat mkcert (172.16.10.120, localhost, 127.0.0.1, 100.88.157.114) --
      // généré une fois dans ./certs, cf. guide_installation_certificat_vusine.md pour
      // l'installation du certificat racine sur les appareils de test.
      https: {
        key: fs.readFileSync(path.resolve(import.meta.dirname, './certs/key.pem')),
        cert: fs.readFileSync(path.resolve(import.meta.dirname, './certs/cert.pem')),
      },
      proxy: {
        '/api': {
          target: env.VITE_API_BASE_URL,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, '')
        }
      }
    }
  }
})
