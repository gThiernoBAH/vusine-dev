<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import apiClient from '@/api/client'
import { User, Lock, Eye, EyeOff, Factory } from 'lucide-vue-next'
import { memoriserSessionKiosque } from '@/api/session'

const router = useRouter()

const identifiant = ref('')
const password = ref('')
const showPassword = ref(false)
const isLoading = ref(false)
const errorMessage = ref('')

const handleLogin = async () => {
  if (!identifiant.value || !password.value || isLoading.value) return
  isLoading.value = true
  errorMessage.value = ''
  try {
    const response = await apiClient.post('/auth/login', {
      identifiant: identifiant.value,
      password: password.value,
    })
    if (response.data.user) {
      sessionStorage.setItem('user', JSON.stringify(response.data.user))
    }
    // *** AJOUT 2026-09-24 *** : jeton signé, envoyé ensuite par api/client.js.
    if (response.data.access_token) {
      sessionStorage.setItem('token', response.data.access_token)
      // Compte kiosque (TV d'atelier) : session conservée après redémarrage du navigateur.
      memoriserSessionKiosque(response.data.user, response.data.access_token, response.data.expires_at)
    }
    // Même règle que router/index.js::espaceDefaut() -- "direction" -> cockpit,
    // "operateur"/"ouvrier" -> tablette. Le guard beforeEach fera le reste (redirection
    // si l'utilisateur tape /login manuellement une fois déjà connecté, etc.).
    const userType = response.data.user?.user_type
    router.push(userType === 'direction' ? '/cockpit/vue-usine' : userType === 'kiosque' ? '/andon' : '/operateur')
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || 'Le serveur Vusine est injoignable.'
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <div class="brand-icon"><Factory :size="28" /></div>
        <div>
          <div class="brand-name">SIVOP</div>
          <div class="brand-sub">Vusine — Suivi de production</div>
        </div>
      </div>

      <form @submit.prevent="handleLogin" class="login-form">
        <label class="field">
          <span class="field-label">Identifiant</span>
          <div class="input-group">
            <User :size="18" class="input-icon" />
            <input v-model="identifiant" type="text" placeholder="Nom d'utilisateur ou matricule" autofocus required />
          </div>
        </label>

        <label class="field">
          <span class="field-label">Mot de passe</span>
          <div class="input-group">
            <Lock :size="18" class="input-icon" />
            <input v-model="password" :type="showPassword ? 'text' : 'password'" placeholder="Mot de passe" required />
            <button type="button" class="toggle-pwd" @click="showPassword = !showPassword">
              <component :is="showPassword ? EyeOff : Eye" :size="18" />
            </button>
          </div>
        </label>

        <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>

        <button type="submit" class="submit-btn" :disabled="isLoading">
          {{ isLoading ? 'Connexion…' : 'Se connecter' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  height: 100%;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg);
  padding: var(--space-4);
}

.login-card {
  width: 100%;
  max-width: 400px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: var(--space-8) var(--space-6);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-8);
}

.brand-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  background: var(--color-brand);
  color: var(--color-text-inverse);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.brand-name {
  font-size: var(--font-size-lg);
  font-weight: 800;
  letter-spacing: 1px;
  color: var(--color-brand-dark);
}

.brand-sub {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.field-label {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-text-muted);
}

.input-group {
  position: relative;
  display: flex;
  align-items: center;
}

.input-icon {
  position: absolute;
  left: 14px;
  color: var(--color-text-muted);
  pointer-events: none;
}

.input-group input {
  width: 100%;
  height: var(--touch-target-min);
  padding: 0 var(--space-3) 0 44px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--font-size-base);
  color: var(--color-text);
  background: var(--color-surface);
  outline: none;
  transition: border-color 0.15s;
}

.input-group input:focus {
  border-color: var(--color-brand);
}

.toggle-pwd {
  position: absolute;
  right: 12px;
  background: none;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  display: flex;
  padding: var(--space-1);
}

.error-message {
  color: var(--color-rouge);
  font-size: var(--font-size-sm);
  margin: 0;
}

.submit-btn {
  height: var(--touch-target-min);
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-brand);
  color: var(--color-text-inverse);
  font-size: var(--font-size-base);
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s;
}

.submit-btn:hover:not(:disabled) {
  background: var(--color-brand-dark);
}

.submit-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
