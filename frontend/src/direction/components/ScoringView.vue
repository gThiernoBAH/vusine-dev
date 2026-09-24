<script setup>
import { ref, onMounted, computed } from 'vue'
import apiClient from '@/api/client'
import { RefreshCw } from 'lucide-vue-next'

const scores = ref([])
const isLoading = ref(true)
const errorMessage = ref('')
const activeTab = ref('CDI')

const snapshotEnCours = ref(false)
const snapshotMessage = ref('')

async function fetchScores() {
  isLoading.value = true
  try {
    const res = await apiClient.get('/scoring/personnel')
    scores.value = res.data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger le classement.'
  } finally {
    isLoading.value = false
  }
}

onMounted(fetchScores)

// *** AJOUT 2026-09-17 *** : jusqu'ici, déclencher le snapshot quotidien
// (performance_ligne_jour, base de Rapports ET du scoring historique) exigeait de
// passer par Swagger (/docs) ou curl -- aucun bouton n'existait dans l'interface,
// contrairement à "Actualiser maintenant" côté Alertes. Même pattern repris ici.
async function lancerSnapshot() {
  snapshotEnCours.value = true
  snapshotMessage.value = ''
  try {
    await apiClient.post('/scoring/snapshot/run-now')
    snapshotMessage.value = 'Snapshot du jour effectué.'
    await fetchScores()
  } catch (e) {
    snapshotMessage.value = e.response?.data?.detail || 'Échec du snapshot.'
  } finally {
    snapshotEnCours.value = false
  }
}

const scoresFiltres = computed(() => scores.value.filter((p) => p.categorie_personnel === activeTab.value))

function scoreClass(score) {
  if (score === null || score === undefined) return ''
  if (score >= 100) return 'statut-vert'
  if (score >= 80) return 'statut-orange'
  return 'statut-rouge'
}
</script>

<template>
  <div class="scoring">
    <header class="page-header">
      <div>
        <h1>Performance du personnel</h1>
        <p class="subtitle">Classement pondéré — par ligne × temps d'affectation</p>
      </div>
      <button class="btn primary" :disabled="snapshotEnCours" @click="lancerSnapshot">
        <RefreshCw :size="16" /> {{ snapshotEnCours ? 'Snapshot en cours…' : 'Lancer le snapshot du jour' }}
      </button>
    </header>

    <p v-if="snapshotMessage" class="snapshot-banner">{{ snapshotMessage }}</p>

    <div class="tabs">
      <button :class="['tab-btn', { active: activeTab === 'CDI' }]" @click="activeTab = 'CDI'">Classement CDI</button>
      <button :class="['tab-btn', { active: activeTab === 'CDD' }]" @click="activeTab = 'CDD'">Classement CDD</button>
    </div>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>
    <p v-else-if="!scoresFiltres.length" class="empty">Aucun {{ activeTab }} avec un score calculable actuellement.</p>

    <table v-else class="scoring-table">
      <thead>
        <tr>
          <th>Rang</th>
          <th>Matricule</th>
          <th>Nom</th>
          <th>Lignes</th>
          <th>Heures</th>
          <th>Score</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(p, i) in scoresFiltres" :key="p.user_id">
          <td>{{ i + 1 }}</td>
          <td>{{ p.matricule }}</td>
          <td>{{ p.nom }}</td>
          <td>{{ p.nb_lignes }}</td>
          <td>{{ p.heures_totales }}</td>
          <td>
            <span v-if="p.score_pct !== null" :class="['score-badge', scoreClass(p.score_pct)]">{{ p.score_pct }}%</span>
            <span v-else class="score-badge-empty">—</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.scoring {
  padding: var(--space-6);
  overflow-y: auto;
  height: 100%;
}

.page-header { display: flex; justify-content: space-between; align-items: flex-start; }
.page-header h1 { margin: 0; font-size: var(--font-size-2xl); }
.subtitle { color: var(--color-text-muted); margin: 4px 0 var(--space-4); }

.btn {
  display: inline-flex; align-items: center; gap: var(--space-2); border: none; border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-4); font-weight: 700; cursor: pointer;
  background: var(--color-brand); color: var(--color-text-inverse); white-space: nowrap;
}
.btn:disabled { opacity: 0.6; cursor: not-allowed; }

.snapshot-banner {
  background: var(--color-brand-light); color: var(--color-brand-dark);
  padding: var(--space-3); border-radius: var(--radius-md); margin-bottom: var(--space-4);
}

.tabs { display: flex; gap: var(--space-2); margin-bottom: var(--space-4); border-bottom: 1px solid var(--color-border); }
.tab-btn {
  border: none; background: none; padding: var(--space-3) var(--space-4); font-size: var(--font-size-sm);
  font-weight: 600; color: var(--color-text-muted); cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px;
}
.tab-btn.active { color: var(--color-brand); border-bottom-color: var(--color-brand); }

.error-banner {
  background: var(--color-rouge-bg);
  color: var(--color-rouge);
  padding: var(--space-3);
  border-radius: var(--radius-md);
}

.loading { color: var(--color-text-muted); }

.scoring-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-card);
}

.scoring-table th {
  text-align: left;
  background: var(--color-brand-light);
  color: var(--color-brand-dark);
  font-size: var(--font-size-xs);
  padding: var(--space-3);
}

.scoring-table td {
  padding: var(--space-3);
  border-top: 1px solid var(--color-border);
  font-size: var(--font-size-sm);
}

.score-badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  font-weight: 700;
  font-size: var(--font-size-xs);
}

.score-badge-empty {
  color: var(--color-text-muted);
}
</style>