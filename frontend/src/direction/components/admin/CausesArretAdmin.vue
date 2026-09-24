<script setup>
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import { Plus } from 'lucide-vue-next'

const causes = ref([])
const isLoading = ref(true)
const errorMessage = ref('')
const nouveauLibelle = ref('')

async function charger() {
  isLoading.value = true
  try {
    const res = await apiClient.get('/admin/causes-arret')
    causes.value = res.data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger les causes d\'arrêt.'
  } finally {
    isLoading.value = false
  }
}
onMounted(charger)

async function toggleActif(cause) {
  await apiClient.patch(`/admin/causes-arret/${cause.id}`, { actif: !cause.actif })
  charger()
}

async function ajouterCause() {
  if (!nouveauLibelle.value) return
  await apiClient.post('/admin/causes-arret', { libelle: nouveauLibelle.value, ordre_affichage: causes.value.length + 1 })
  nouveauLibelle.value = ''
  charger()
}
</script>

<template>
  <div class="causes-admin">
    <div class="add-row">
      <input v-model="nouveauLibelle" type="text" placeholder="Nouvelle cause d'arrêt…" @keyup.enter="ajouterCause" />
      <button class="btn primary" @click="ajouterCause"><Plus :size="16" /> Ajouter</button>
    </div>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>

    <ul v-else class="causes-list">
      <li v-for="c in causes" :key="c.id" :class="{ inactive: !c.actif }">
        <span>{{ c.libelle }}</span>
        <button class="toggle-btn" :class="{ on: c.actif }" @click="toggleActif(c)">
          {{ c.actif ? 'Active' : 'Désactivée' }}
        </button>
      </li>
    </ul>
    <p class="hint">Une cause désactivée disparaît du menu déroulant "Déclarer un arrêt" côté tablette, sans supprimer l'historique des arrêts déjà enregistrés avec cette cause.</p>
  </div>
</template>

<style scoped>
.add-row { display: flex; gap: var(--space-2); margin-bottom: var(--space-4); max-width: 480px; }
.add-row input {
  flex: 1; height: 40px; padding: 0 var(--space-3); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); font-family: inherit;
}
.btn {
  display: inline-flex; align-items: center; gap: var(--space-2);
  border: none; border-radius: var(--radius-md); padding: 0 var(--space-4);
  font-weight: 700; cursor: pointer; background: var(--color-brand); color: var(--color-text-inverse);
}

.error-banner {
  background: var(--color-rouge-bg); color: var(--color-rouge);
  padding: var(--space-3); border-radius: var(--radius-md); margin-bottom: var(--space-3);
}
.loading { color: var(--color-text-muted); }

.causes-list {
  list-style: none; margin: 0; padding: 0; max-width: 480px;
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-lg); overflow: hidden;
}
.causes-list li {
  display: flex; align-items: center; justify-content: space-between;
  padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--color-border);
  font-size: var(--font-size-sm);
}
.causes-list li:last-child { border-bottom: none; }
.causes-list li.inactive span { color: var(--color-text-muted); text-decoration: line-through; }

.toggle-btn {
  border: 1px solid var(--color-border); background: var(--color-bg); color: var(--color-text-muted);
  border-radius: 999px; padding: 4px 12px; font-size: var(--font-size-xs); font-weight: 700; cursor: pointer;
}
.toggle-btn.on { background: var(--color-vert-bg); color: var(--color-vert); border-color: transparent; }

.hint { font-size: var(--font-size-xs); color: var(--color-text-muted); max-width: 480px; margin-top: var(--space-3); }
</style>
