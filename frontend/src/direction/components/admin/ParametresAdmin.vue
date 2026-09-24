<script setup>
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'

// Clés connues -- pas de route "lister tous les params" côté backend, donc on les
// interroge une par une via GET /auth/params/{key} (déjà existant, réservé admin).
const DEFINITIONS = [
  { key: 'seuil_vert_pct', label: 'Seuil vert', suffix: '%', hint: 'Performance à partir de laquelle une ligne est considérée verte.' },
  { key: 'seuil_orange_pct', label: 'Seuil orange', suffix: '%', hint: 'En dessous, la ligne passe rouge (Retard critique).' },
  { key: 'seuil_silence_scan_minutes', label: 'Silence de scan', suffix: 'min', hint: "Alerte déclenchée si aucune palette scannée depuis ce délai." },
  { key: 'duree_demarrage_min', label: 'Fenêtre de démarrage', suffix: 'min', hint: "Délai après le début de poste/OF pendant lequel une ligne n'est jamais jugée rouge/orange (pourcentage pas encore significatif)." },
]

const params = ref(DEFINITIONS.map(d => ({ ...d, valeur: '', valeurOriginale: '', enregistrement: false })))
const isLoading = ref(true)
const errorMessage = ref('')
const successMessage = ref('')

async function charger() {
  isLoading.value = true
  try {
    const resultats = await Promise.all(
      params.value.map(p => apiClient.get(`/auth/params/${p.key}`))
    )
    resultats.forEach((res, i) => {
      params.value[i].valeur = res.data.value ?? ''
      params.value[i].valeurOriginale = res.data.value ?? ''
    })
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger les paramètres.'
  } finally {
    isLoading.value = false
  }
}
onMounted(charger)

async function enregistrer(p) {
  p.enregistrement = true
  successMessage.value = ''
  try {
    await apiClient.patch('/auth/params', { key: p.key, value: p.valeur })
    p.valeurOriginale = p.valeur
    successMessage.value = `${p.label} mis à jour.`
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || `Échec de la mise à jour de ${p.label}.`
  } finally {
    p.enregistrement = false
  }
}
</script>

<template>
  <div class="parametres-admin">
    <p class="hint">
      Seuils utilisés par le calcul de performance et le moteur d'alertes. Réservé aux
      comptes administrateur.
    </p>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <p v-if="successMessage" class="success-banner">{{ successMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>

    <div v-else class="params-list">
      <div v-for="p in params" :key="p.key" class="param-row">
        <div class="param-info">
          <div class="param-label">{{ p.label }}</div>
          <div class="param-hint">{{ p.hint }}</div>
        </div>
        <div class="param-input-wrap">
          <input v-model="p.valeur" type="number" class="param-input" />
          <span class="param-suffix">{{ p.suffix }}</span>
        </div>
        <button
          class="btn primary"
          :disabled="p.enregistrement || p.valeur === p.valeurOriginale"
          @click="enregistrer(p)"
        >
          {{ p.enregistrement ? 'Enregistrement…' : 'Enregistrer' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.parametres-admin { display: flex; flex-direction: column; gap: var(--space-4); }
.hint { font-size: var(--font-size-sm); color: var(--color-text-muted); max-width: 640px; margin: 0; }
.error-banner { background: var(--color-rouge-bg); color: var(--color-rouge); padding: var(--space-3); border-radius: var(--radius-md); }
.success-banner { background: var(--color-vert-bg); color: var(--color-vert); padding: var(--space-3); border-radius: var(--radius-md); }
.loading { color: var(--color-text-muted); }

.params-list {
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-lg); overflow: hidden;
}
.param-row {
  display: flex; align-items: center; gap: var(--space-4);
  padding: var(--space-4); border-bottom: 1px solid var(--color-border);
}
.param-row:last-child { border-bottom: none; }

.param-info { flex: 1; min-width: 0; }
.param-label { font-weight: 700; font-size: var(--font-size-sm); }
.param-hint { font-size: var(--font-size-xs); color: var(--color-text-muted); margin-top: 2px; }

.param-input-wrap { display: flex; align-items: center; gap: var(--space-2); }
.param-input {
  width: 80px; height: 36px; padding: 0 var(--space-2); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); font-size: var(--font-size-sm); text-align: right;
}
.param-suffix { font-size: var(--font-size-xs); color: var(--color-text-muted); width: 24px; }

.btn {
  height: 36px; border: none; border-radius: var(--radius-md); padding: 0 var(--space-4);
  font-weight: 700; cursor: pointer; background: var(--color-brand); color: var(--color-text-inverse);
  white-space: nowrap;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>