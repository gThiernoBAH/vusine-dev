<script setup>
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import { FileDown } from 'lucide-vue-next'
import DataTable from '@/components/DataTable.vue'

const activeTab = ref('par_ligne')
const dateDebut = ref(new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10))
const dateFin = ref(new Date().toISOString().slice(0, 10))

const parLigne = ref([])
const parProduit = ref([])
const vueDirection = ref(null)
// *** AJOUT 2026-09-23 *** : onglet Historique des scans (tous les opérateurs).
const historiqueScans = ref([])
const isLoading = ref(true)
const errorMessage = ref('')

async function charger() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const params = { date_debut: dateDebut.value, date_fin: dateFin.value }
    if (activeTab.value === 'par_ligne') {
      const res = await apiClient.get('/rapports/par-ligne', { params })
      parLigne.value = res.data
    } else if (activeTab.value === 'par_produit') {
      const res = await apiClient.get('/rapports/par-produit', { params })
      parProduit.value = res.data
    } else if (activeTab.value === 'historique') {
      const res = await apiClient.get('/rapports/historique-scans', { params })
      historiqueScans.value = res.data
    } else {
      const res = await apiClient.get('/rapports/vue-direction', { params })
      vueDirection.value = res.data
    }
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger le rapport.'
  } finally {
    isLoading.value = false
  }
}
onMounted(charger)

async function exporter(format) {
  const params = { date_debut: dateDebut.value, date_fin: dateFin.value, format }
  const res = await apiClient.get('/rapports/par-ligne/export', { params, responseType: 'blob' })
  const url = window.URL.createObjectURL(new Blob([res.data]))
  const a = document.createElement('a')
  a.href = url
  a.download = `rapport_vusine_${dateDebut.value}_${dateFin.value}.${format}`
  a.click()
  window.URL.revokeObjectURL(url)
}

// *** AJOUT 2026-09-23 *** : export de l'historique des scans (xlsx/pdf/csv).
async function exporterHistorique(format) {
  const params = { date_debut: dateDebut.value, date_fin: dateFin.value, format }
  const res = await apiClient.get('/rapports/historique-scans/export', { params, responseType: 'blob' })
  const url = window.URL.createObjectURL(new Blob([res.data]))
  const a = document.createElement('a')
  a.href = url
  a.download = `historique_scans_${dateDebut.value}_${dateFin.value}.${format}`
  a.click()
  window.URL.revokeObjectURL(url)
}

const COLONNES_HISTORIQUE = [
  { key: 'created_at', label: 'Date / heure',
    format: v => new Date(v).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) },
  { key: 'operateur_nom', label: 'Opérateur' },
  { key: 'operateur_matricule', label: 'Matricule', format: v => v ?? '—' },
  { key: 'ligne_code', label: 'Ligne' },
  { key: 'produit_nom', label: 'Produit', format: v => v ?? '—' },
  { key: 'numero_lot', label: 'N° lot' },
  { key: 'nb_cartons', label: 'Cartons', align: 'right' },
  { key: 'colisage_carton', label: 'Colisage', align: 'right' },
  { key: 'quantite_totale', label: 'Quantité', align: 'right' },
  { key: 'complete', label: 'Statut',
    format: (v, row) => v ? 'Complète' : `Partielle${row.motif_partielle ? ' — ' + row.motif_partielle : ''}` },
]
</script>

<template>
  <div class="rapports">
    <header class="page-header">
      <h1>Rapports</h1>
      <p class="subtitle">Production, performance et pertes sur une période</p>
    </header>

    <div class="controls">
      <div class="tabs">
        <button :class="['tab-btn', { active: activeTab === 'par_ligne' }]" @click="activeTab = 'par_ligne'; charger()">Par ligne</button>
        <button :class="['tab-btn', { active: activeTab === 'par_produit' }]" @click="activeTab = 'par_produit'; charger()">Par produit</button>
        <button :class="['tab-btn', { active: activeTab === 'vue_direction' }]" @click="activeTab = 'vue_direction'; charger()">Vue Direction</button>
        <button :class="['tab-btn', { active: activeTab === 'historique' }]" @click="activeTab = 'historique'; charger()" title="Tous les scans effectués, tous opérateurs et toutes lignes confondus">Historique des scans</button>
      </div>
      <div class="dates">
        <input type="date" v-model="dateDebut" @change="charger" />
        <span>→</span>
        <input type="date" v-model="dateFin" @change="charger" />
        <template v-if="activeTab === 'par_ligne'">
          <button class="export-btn" title="Télécharger ce tableau au format Excel" @click="exporter('xlsx')"><FileDown :size="16" /> Excel</button>
          <button class="export-btn" title="Télécharger ce tableau au format PDF" @click="exporter('pdf')"><FileDown :size="16" /> PDF</button>
        </template>
        <template v-else-if="activeTab === 'historique'">
          <button class="export-btn" title="Télécharger l'historique au format Excel" @click="exporterHistorique('xlsx')"><FileDown :size="16" /> Excel</button>
          <button class="export-btn" title="Télécharger l'historique au format PDF" @click="exporterHistorique('pdf')"><FileDown :size="16" /> PDF</button>
          <button class="export-btn" title="Télécharger l'historique au format CSV" @click="exporterHistorique('csv')"><FileDown :size="16" /> CSV</button>
        </template>
      </div>
    </div>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>

    <!-- Par ligne -->
    <table v-else-if="activeTab === 'par_ligne'" class="rapport-table">
      <thead>
        <tr><th>Ligne</th><th>Réel</th><th>Théorique</th><th>Performance</th><th>Palettes</th><th>Temps d'arrêt</th></tr>
      </thead>
      <tbody>
        <tr v-for="r in parLigne" :key="r.ligne_id">
          <td>{{ r.code }} — {{ r.nom }}</td>
          <td>{{ r.reel_total.toLocaleString('fr-FR') }}</td>
          <td>{{ r.theorique_total.toLocaleString('fr-FR') }}</td>
          <td>{{ r.performance_moyenne !== null ? r.performance_moyenne + '%' : '—' }}</td>
          <td>{{ r.nb_palettes }}</td>
          <td>{{ r.temps_arret_min }} min</td>
        </tr>
      </tbody>
    </table>

    <!-- Par produit -->
    <table v-else-if="activeTab === 'par_produit'" class="rapport-table">
      <thead>
        <tr><th>Produit</th><th>Quantité totale</th><th>Palettes</th><th>Complètes</th><th>Partielles</th></tr>
      </thead>
      <tbody>
        <tr v-for="r in parProduit" :key="r.produit_id">
          <td>{{ r.nom }}</td>
          <td>{{ r.quantite_totale.toLocaleString('fr-FR') }}</td>
          <td>{{ r.nb_palettes }}</td>
          <td>{{ r.nb_palettes_completes }}</td>
          <td>{{ r.nb_palettes_partielles }}</td>
        </tr>
        <tr v-if="!parProduit.length">
          <td colspan="5" class="empty-row">Aucune palette rattachée à un produit sur cette période.</td>
        </tr>
      </tbody>
    </table>

    <!-- Vue Direction -->
    <div v-else-if="vueDirection" class="vue-direction">
      <div class="two-col">
        <div class="section-card">
          <h2>Top 5 lignes</h2>
          <ol>
            <li v-for="r in vueDirection.top" :key="r.ligne_id">{{ r.code }} — {{ r.performance_moyenne }}%</li>
          </ol>
        </div>
        <div class="section-card">
          <h2>Flop 5 lignes</h2>
          <ol>
            <li v-for="r in vueDirection.flop" :key="r.ligne_id">{{ r.code }} — {{ r.performance_moyenne }}%</li>
          </ol>
        </div>
      </div>

      <div class="section-card">
        <h2>Performance par atelier</h2>
        <p v-if="!vueDirection.par_atelier.length" class="empty">Aucune donnée sur la période.</p>
        <table v-else class="rapport-table nested">
          <thead>
            <tr><th>Atelier</th><th>Réel</th><th>Théorique</th><th>Performance</th><th>Lignes</th></tr>
          </thead>
          <tbody>
            <tr v-for="s in vueDirection.par_atelier" :key="s.section_nom">
              <td>{{ s.section_nom }}</td>
              <td>{{ s.reel_total.toLocaleString('fr-FR') }}</td>
              <td>{{ s.theorique_total.toLocaleString('fr-FR') }}</td>
              <td>{{ s.performance_moyenne !== null ? s.performance_moyenne + '%' : '—' }}</td>
              <td>{{ s.nb_lignes }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="section-card">
        <h2>Principales pertes par cause</h2>
        <p v-if="!vueDirection.pertes_par_cause.length" class="empty">Aucun arrêt sur la période.</p>
        <ul v-else class="pertes-list">
          <li v-for="p in vueDirection.pertes_par_cause" :key="p.cause">
            <span>{{ p.cause }}</span><strong>{{ p.duree_min }} min</strong>
          </li>
        </ul>
      </div>

      <div class="section-card">
        <h2>Évolution quotidienne (performance usine)</h2>
        <div class="evolution-row">
          <div v-for="j in vueDirection.evolution_quotidienne" :key="j.jour" class="evolution-jour">
            <div class="evolution-valeur">{{ j.performance_pct !== null ? j.performance_pct + '%' : '—' }}</div>
            <div class="evolution-date">{{ new Date(j.jour).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' }) }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Historique des scans (*** AJOUT 2026-09-23 ***) -->
    <DataTable
      v-else-if="activeTab === 'historique'"
      :columns="COLONNES_HISTORIQUE" :rows="historiqueScans" :row-key="(r, i) => i"
      :default-sort="{ key: 'created_at', dir: -1 }"
      empty-text="Aucun scan sur cette période."
    >
      <template #cell-complete="{ row }">
        <span :class="['badge', row.complete ? 'badge-vert' : 'badge-orange']">
          {{ row.complete ? 'Complète' : `Partielle${row.motif_partielle ? ' — ' + row.motif_partielle : ''}` }}
        </span>
      </template>
    </DataTable>
  </div>
</template>

<style scoped>
.rapports { padding: var(--space-6); overflow-y: auto; height: 100%; }
.page-header h1 { margin: 0; font-size: var(--font-size-2xl); }
.subtitle { color: var(--color-text-muted); margin: 4px 0 var(--space-6); }

.controls { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-4); flex-wrap: wrap; gap: var(--space-3); }
.tabs { display: flex; gap: var(--space-2); }
.tab-btn {
  border: 1px solid var(--color-border); background: var(--color-surface); color: var(--color-text-muted);
  border-radius: var(--radius-md); padding: var(--space-2) var(--space-4); font-size: var(--font-size-sm); font-weight: 600; cursor: pointer;
}
.tab-btn.active { background: var(--color-brand); color: var(--color-text-inverse); border-color: var(--color-brand); }

.dates { display: flex; align-items: center; gap: var(--space-2); }
.dates input { height: 36px; padding: 0 var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-md); }

.export-btn {
  display: inline-flex; align-items: center; gap: var(--space-2);
  height: 36px; padding: 0 var(--space-3); border: 1px solid var(--color-border);
  background: var(--color-surface); color: var(--color-text); border-radius: var(--radius-md);
  font-size: var(--font-size-sm); font-weight: 600; cursor: pointer;
}
.export-btn:hover { background: var(--color-brand-light); border-color: var(--color-brand); }

.error-banner { background: var(--color-rouge-bg); color: var(--color-rouge); padding: var(--space-3); border-radius: var(--radius-md); }
.loading, .empty { color: var(--color-text-muted); }

.rapport-table {
  width: 100%; border-collapse: collapse; background: var(--color-surface);
  border: 1px solid var(--color-border); border-radius: var(--radius-lg); overflow: hidden;
}
.rapport-table th { text-align: left; background: var(--color-brand-light); color: var(--color-brand-dark); font-size: var(--font-size-xs); padding: var(--space-3); }
.rapport-table td { padding: var(--space-3); border-top: 1px solid var(--color-border); font-size: var(--font-size-sm); }
.rapport-table.nested { box-shadow: none; border-radius: var(--radius-md); }
.empty-row { text-align: center; color: var(--color-text-muted); padding: var(--space-6) !important; }

.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-4); margin-bottom: var(--space-4); }
.section-card {
  background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg);
  padding: var(--space-4); margin-bottom: var(--space-4); box-shadow: var(--shadow-card);
}
.section-card h2 { font-size: var(--font-size-base); margin: 0 0 var(--space-3); }
.section-card ol { margin: 0; padding-left: 20px; font-size: var(--font-size-sm); }

.pertes-list { list-style: none; margin: 0; padding: 0; }
.pertes-list li { display: flex; justify-content: space-between; padding: var(--space-2) 0; border-bottom: 1px solid var(--color-border); font-size: var(--font-size-sm); }
.pertes-list li:last-child { border-bottom: none; }

.evolution-row { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.evolution-jour { text-align: center; min-width: 60px; }
.evolution-valeur { font-weight: 700; }
.evolution-date { font-size: var(--font-size-xs); color: var(--color-text-muted); }

/* *** AJOUT 2026-09-23 *** : badges de statut pour l'onglet Historique des scans. */
.badge { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: var(--font-size-xs); font-weight: 700; white-space: nowrap; }
.badge-vert { background: var(--color-vert-bg); color: var(--color-vert); }
.badge-orange { background: var(--color-orange-bg); color: #92400E; }
</style>