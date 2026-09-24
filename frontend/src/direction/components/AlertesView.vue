
<script setup>
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import { RefreshCw, AlertTriangle } from 'lucide-vue-next'

const alertes = ref([])
const isLoading = ref(true)
const errorMessage = ref('')
const rafraichissement = ref(false)

async function charger() {
  isLoading.value = true
  try {
    const res = await apiClient.get('/alertes')
    alertes.value = res.data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger les alertes.'
  } finally {
    isLoading.value = false
  }
}
onMounted(charger)

async function actualiser() {
  rafraichissement.value = true
  try {
    await apiClient.post('/alertes/run-now')
    await charger()
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || "Échec de l'actualisation."
  } finally {
    rafraichissement.value = false
  }
}

const LABELS_TYPE = {
  performance: 'Performance',
  silence_scan: 'Silence de scan',
  ralentissement_progressif: 'Ralentissement',
  partielle_non_justifiee: 'Traçabilité',
  of_termine_scan: 'Traçabilité',
}
</script>

<template>
  <div class="alertes-view">
    <header class="page-header">
      <div>
        <h1>Alertes</h1>
        <p class="subtitle">Performance, rythme de scan et traçabilité</p>
      </div>
      <button class="btn primary" :disabled="rafraichissement" @click="actualiser">
        <RefreshCw :size="16" /> {{ rafraichissement ? 'Actualisation…' : 'Actualiser maintenant' }}
      </button>
    </header>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>
    <p v-else-if="!alertes.length" class="empty">Aucune alerte active — tout est calme.</p>

    <ul v-else class="alertes-list">
      <li v-for="a in alertes" :key="a.id" :class="['alerte-item', `niveau-${a.niveau}`]">
        <AlertTriangle :size="18" />
        <div class="alerte-content">
          <div class="alerte-top">
            <span class="alerte-type">{{ LABELS_TYPE[a.type] || a.type }}</span>
            <span v-if="a.ligne_code" class="alerte-ligne">{{ a.ligne_code }}</span>
          </div>
          <div class="alerte-message">{{ a.message }}</div>
          <div class="alerte-date">{{ new Date(a.created_at).toLocaleString('fr-FR') }}</div>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.alertes-view { padding: var(--space-6); overflow-y: auto; height: 100%; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: var(--space-6); }
.page-header h1 { margin: 0; font-size: var(--font-size-2xl); }
.subtitle { color: var(--color-text-muted); margin: 4px 0 0; }

.btn {
  display: inline-flex; align-items: center; gap: var(--space-2); border: none; border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-4); font-weight: 700; cursor: pointer;
  background: var(--color-brand); color: var(--color-text-inverse);
}
.btn:disabled { opacity: 0.6; cursor: not-allowed; }

.error-banner { background: var(--color-rouge-bg); color: var(--color-rouge); padding: var(--space-3); border-radius: var(--radius-md); }
.loading, .empty { color: var(--color-text-muted); }

.alertes-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-3); }
.alerte-item {
  display: flex; gap: var(--space-3); background: var(--color-surface); border: 1px solid var(--color-border);
  border-left: 4px solid var(--color-orange); border-radius: var(--radius-md); padding: var(--space-3) var(--space-4);
  box-shadow: var(--shadow-card);
}
.alerte-item.niveau-rouge { border-left-color: var(--color-rouge); }
.alerte-item.niveau-rouge svg { color: var(--color-rouge); }
.alerte-item.niveau-orange svg { color: var(--color-orange); }

.alerte-top { display: flex; gap: var(--space-2); align-items: center; margin-bottom: 2px; }
.alerte-type { font-size: var(--font-size-xs); font-weight: 700; text-transform: uppercase; color: var(--color-text-muted); }
.alerte-ligne { font-size: var(--font-size-xs); font-weight: 700; background: var(--color-brand-light); color: var(--color-brand-dark); padding: 1px 8px; border-radius: 999px; }
.alerte-message { font-size: var(--font-size-sm); }
.alerte-date { font-size: var(--font-size-xs); color: var(--color-text-muted); margin-top: 2px; }
</style>
