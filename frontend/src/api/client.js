import axios from 'axios'
import { oublierSessionKiosque } from './session'
import { formaterDetail } from './errors'

const apiClient = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

// *** REFAIT 2026-09-24 *** : l'API n'accepte plus l'en-tête X-User-ID (simple
// revendication d'identité, falsifiable). Elle attend le jeton signé renvoyé par
// POST /auth/login, stocké dans sessionStorage['token'] par Login.vue.
apiClient.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('token')
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`
  }
  return config
})

// Jeton expiré, révoqué (mot de passe changé, compte désactivé) ou invalide : on vide la
// session et on renvoie vers /login -- sauf pour /auth/login lui-même, où un 401 veut
// simplement dire « identifiants incorrects » et doit rester affiché par Login.vue.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    const url = error.config?.url || ''
    if (status === 401 && !url.includes('/auth/login')) {
      sessionStorage.removeItem('user')
      sessionStorage.removeItem('token')
      oublierSessionKiosque()  // session kiosque expirée/révoquée : ne pas la restaurer en boucle
      if (window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
    }
    // Erreur de validation (tableau) -> phrase lisible, pour TOUS les écrans (cf. errors.js).
    if (Array.isArray(error.response?.data?.detail)) {
      error.response.data.detail = formaterDetail(error.response.data.detail)
    }
    return Promise.reject(error)
  },
)

export default apiClient
