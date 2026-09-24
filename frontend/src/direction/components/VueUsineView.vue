<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import apiClient from '@/api/client'
import StatutBadge from './StatutBadge.vue'
import { CheckCircle2, AlertTriangle, TrendingDown, PauseCircle, Percent, Search } from 'lucide-vue-next'

const emit = defineEmits(['select-ligne'])

const resume = ref(null)
const lignes = ref([])
const isLoading = ref(true)
const errorMessage = ref('')
let pollHandle = null

// --- Date consultée (*** AJOUT 2026-09-18 ***) -- défaut : aujourd'hui, au format
// YYYY-MM-DD attendu par <input type="date"> et par l'API (query param `jour`). Un
// jour passé est lu depuis le snapshot figé côté backend -- jamais de polling dessus,
// ça ne changera plus une fois la journée close. --------------------------------
function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const jourSelectionne = ref(todayIso())
const estAujourdhui = computed(() => jourSelectionne.value === todayIso())

// --- Recherche / filtre / tri (100% client -- même volume que l'admin Lignes,
// pas besoin de pousser ça côté backend) --------------------------------------
const recherche = ref('')
const filtreSection = ref('toutes')
const filtreStatut = ref('tous')  // 'tous' | 'vert' | 'orange' | 'rouge' | 'demarrage' | 'arret' | 'inactif'
const tri = ref('code')  // 'code' | 'performance_asc' | 'performance_desc' | 'retard_desc'

async function fetchVueUsine() {
  try {
    const res = await apiClient.get('/dashboard/vue_usine', { params: { jour: jourSelectionne.value } })
    resume.value = res.data.resume
    lignes.value = res.data.lignes
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger la Vue Usine.'
  } finally {
    isLoading.value = false
  }
}

function gererPolling() {
  if (pollHandle) { clearInterval(pollHandle); pollHandle = null }
  // Polling léger (5-10s) -- décision d'architecture actée : pas de WebSocket/Redis en
  // V1. Uniquement pour aujourd'hui : un jour passé ne change plus, inutile de le repoller.
  if (estAujourdhui.value) {
    pollHandle = setInterval(fetchVueUsine, 7000)
  }
}

onMounted(() => {
  fetchVueUsine()
  gererPolling()
})

watch(jourSelectionne, () => {
  isLoading.value = true
  fetchVueUsine()
  gererPolling()
})

onUnmounted(() => {
  if (pollHandle) clearInterval(pollHandle)
})

const sectionsConnues = computed(() => {
  const set = new Set(lignes.value.map(l => l.section_nom).filter(Boolean))
  return Array.from(set).sort((a, b) => a.localeCompare(b))
})

const lignesFiltrees = computed(() => {
  const q = recherche.value.trim().toLowerCase()
  let resultat = lignes.value.filter(l => {
    if (q && !`${l.code} ${l.nom}`.toLowerCase().includes(q)) return false
    if (filtreSection.value !== 'toutes' && l.section_nom !== filtreSection.value) return false
    if (filtreStatut.value !== 'tous' && l.statut !== filtreStatut.value) return false
    return true
  })

  resultat = [...resultat].sort((a, b) => {
    switch (tri.value) {
      case 'performance_asc':
        return (a.performance_pct ?? -1) - (b.performance_pct ?? -1)
      case 'performance_desc':
        return (b.performance_pct ?? -1) - (a.performance_pct ?? -1)
      case 'retard_desc':
        return (b.retard_min ?? 0) - (a.retard_min ?? 0)
      default:
        return String(a.code).localeCompare(String(b.code))
    }
  })

  return resultat
})
</script>

<template>
  <div class="vue-usine">
    <header class="page-header">
      <div>
        <h1>Vue Usine</h1>
        <p class="subtitle">
          {{ estAujourdhui ? 'Production en temps réel' : 'Consultation historique — figée, pas de rafraîchissement' }}
        </p>
      </div>
      <label class="date-picker">
        <span>Jour</span>
        <input type="date" v-model="jourSelectionne" :max="todayIso()" />
      </label>
    </header>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <div v-if="resume" class="resume-cards">
      <div class="resume-card">
        <Percent :size="20" class="icon icon-brand" />
        <div>
          <div class="resume-value">{{ resume.performance_usine_pct !== null ? resume.performance_usine_pct + '%' : '—' }}</div>
          <div class="resume-label">Performance usine</div>
        </div>
      </div>
      <div class="resume-card">
        <CheckCircle2 :size="20" class="icon icon-vert" />
        <div>
          <div class="resume-value">{{ resume.lignes_vertes }}</div>
          <div class="resume-label">Vertes (≥95%)</div>
        </div>
      </div>
      <div class="resume-card">
        <TrendingDown :size="20" class="icon icon-orange" />
        <div>
          <div class="resume-value">{{ resume.lignes_orange }}</div>
          <div class="resume-label">Orange (80-94%)</div>
        </div>
      </div>
      <div class="resume-card">
        <AlertTriangle :size="20" class="icon icon-rouge" />
        <div>
          <div class="resume-value">{{ resume.lignes_rouges }}</div>
          <div class="resume-label">Rouges (&lt;80%)</div>
        </div>
      </div>
      <div class="resume-card">
        <PauseCircle :size="20" class="icon icon-arret" />
        <div>
          <div class="resume-value">{{ resume.lignes_a_larret }}</div>
          <div class="resume-label">Lignes à l'arrêt</div>
        </div>
      </div>
    </div>

    <div class="toolbar">
      <div class="search-wrap">
        <Search :size="16" class="search-icon" />
        <input v-model="recherche" type="search" placeholder="Rechercher par code ou nom…" class="search-input" />
      </div>
      <select v-model="filtreSection" class="filter-select">
        <option value="toutes">Toutes les sections</option>
        <option v-for="s in sectionsConnues" :key="s" :value="s">{{ s }}</option>
      </select>
      <select v-model="filtreStatut" class="filter-select">
        <option value="tous">Tous les statuts</option>
        <option value="vert">Vert</option>
        <option value="orange">Orange</option>
        <option value="rouge">Rouge</option>
        <option value="demarrage">Démarrage</option>
        <option value="arret">À l'arrêt</option>
        <option value="inactif">Inactif</option>
      </select>
      <select v-model="tri" class="filter-select">
        <option value="code">Trier : code</option>
        <option value="performance_desc">Trier : performance ↓</option>
        <option value="performance_asc">Trier : performance ↑</option>
        <option value="retard_desc">Trier : retard ↓</option>
      </select>
      <span class="result-count">{{ lignesFiltrees.length }} / {{ lignes.length }} lignes</span>
    </div>

    <div v-if="isLoading" class="loading">Chargement…</div>

    <div v-else class="lignes-grid">
      <button
        v-for="ligne in lignesFiltrees"
        :key="ligne.id"
        class="ligne-card"
        @click="emit('select-ligne', ligne.id, jourSelectionne)"
      >
        <div class="ligne-card-top">
          <span class="ligne-code">{{ ligne.code }}</span>
          <StatutBadge :statut="ligne.statut" />
        </div>
        <div class="ligne-nom">{{ ligne.nom }}</div>
        <div class="ligne-section">{{ ligne.section_nom }}</div>
        <div class="ligne-metrics">
          <div>
            <span class="metric-value">{{ ligne.performance_pct ?? '—' }}<span v-if="ligne.performance_pct !== null">%</span></span>
            <span class="metric-label">Performance</span>
          </div>
          <div>
            <span class="metric-value">{{ ligne.retard_min }} min</span>
            <span class="metric-label">Retard</span>
          </div>
        </div>
      </button>
      <p v-if="!lignesFiltrees.length" class="empty">Aucune ligne ne correspond à ces filtres.</p>
    </div>
  </div>
</template>

<style scoped>
.vue-usine {
  padding: var(--space-6);
  overflow-y: auto;
  height: 100%;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.page-header h1 {
  margin: 0;
  font-size: var(--font-size-2xl);
}

.date-picker {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}
.date-picker input {
  height: 36px;
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  font-family: inherit;
  background: var(--color-surface);
}

.subtitle {
  color: var(--color-text-muted);
  margin: 4px 0 var(--space-6);
}

.error-banner {
  background: var(--color-rouge-bg);
  color: var(--color-rouge);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
}

.resume-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.resume-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  box-shadow: var(--shadow-card);
}

.icon-vert { color: var(--color-vert); }
.icon-orange { color: var(--color-orange); }
.icon-rouge { color: var(--color-rouge); }
.icon-arret { color: var(--color-arret); }
.icon-brand { color: var(--color-brand); }

.resume-value {
  font-size: var(--font-size-xl);
  font-weight: 800;
}

.resume-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.toolbar {
  display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); flex-wrap: wrap;
}
.search-wrap { position: relative; flex: 1; min-width: 220px; }
.search-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--color-text-muted); pointer-events: none; }
.search-input {
  width: 100%; height: 36px; padding: 0 var(--space-3) 0 34px;
  border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: var(--font-size-sm);
}
.filter-select {
  height: 36px; padding: 0 var(--space-2); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); font-size: var(--font-size-sm); background: var(--color-surface);
}
.result-count { font-size: var(--font-size-xs); color: var(--color-text-muted); white-space: nowrap; }

.loading {
  color: var(--color-text-muted);
  padding: var(--space-6) 0;
}

.empty { color: var(--color-text-muted); grid-column: 1 / -1; text-align: center; padding: var(--space-6) 0; }

.lignes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-4);
}

.ligne-card {
  text-align: left;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  cursor: pointer;
  font-family: inherit;
  box-shadow: var(--shadow-card);
  transition: transform 0.1s, box-shadow 0.1s;
}

.ligne-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 10px rgba(15, 23, 42, 0.12);
}

.ligne-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}

.ligne-code {
  font-weight: 800;
  font-size: var(--font-size-lg);
}

.ligne-nom {
  font-weight: 600;
  font-size: var(--font-size-sm);
}

.ligne-section {
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
  margin-bottom: var(--space-3);
}

.ligne-metrics {
  display: flex;
  gap: var(--space-6);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}

.metric-value {
  display: block;
  font-weight: 700;
  font-size: var(--font-size-base);
}

.metric-label {
  display: block;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}
</style>