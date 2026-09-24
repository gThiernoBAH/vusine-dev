import axios from 'axios'

const apiClient = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

// Injecte X-User-ID depuis sessionStorage -- même mécanisme d'auth que SIVOX
// (cohérence actée), cf. backend/app/api/auth_routes.py::get_current_user.
apiClient.interceptors.request.use((config) => {
  const userData = JSON.parse(sessionStorage.getItem('user') || '{}')
  if (userData.id) {
    config.headers['X-User-ID'] = userData.id
  }
  return config
})

export default apiClient
