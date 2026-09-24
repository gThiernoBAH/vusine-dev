<script setup>
/**
 * HistoriqueOperateurView.vue -- *** AJOUT 2026-09-23 *** : "Mon historique" côté
 * tablette. GET /rapports/historique-scans restreint automatiquement à SES PROPRES
 * scans pour un compte Opérateur/Ouvrier (cf. reports_routes.py, aucun paramètre
 * operateur_id à passer ici -- le backend l'impose, ce composant ne le demande même
 * pas). Même tableau (DataTable) que côté Direction, en plus compact pour la tablette.
 */
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import DataTable from '@/components/DataTable.vue'
import { ArrowLeft } from 'lucide-vue-next'

const emit = defineEmits(['back'])

function ilYA(jours) {
  const d = new Date()
  d.setDate(d.getDate() - jours)
  return d.toISOString().slice(0, 10)
}

const dateDebut = ref(ilYA(30))
const dateFin = ref(ilYA(0))
const scans = ref([])
const isLoading = ref(true)
const errorMessage = ref('')

const COLONNES = [
  { key: 'created_at', label: 'Date / heure',
    format: v => new Date(v).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) },
  { key: 'ligne_code', label: 'Ligne' },
  { key: 'produit_nom', label: 'Produit', format: v => v ?? '—' },
  { key: 'numero_lot', label: 'N° lot' },
  { key: 'quantite_totale', label: 'Quantité', align: 'right' },
  { key: 'complete', label: 'Statut', format: (v, row) => v ? 'Complète' : `Partielle${row.motif_partielle ? ' — ' + row.motif_partielle : ''}` },
]

async function charger() {
  isLoading.value = true
  try {
    scans.value = (await apiClient.get('/rapports/historique-scans', {
      params: { date_debut: dateDebut.value, date_fin: dateFin.value },
    })).data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger votre historique.'
  } finally {
    isLoading.value = false
  }
}

onMounted(charger)
</script>

<template>
  <div class="historique-operateur">
    <div class="header-row">
      <button class="back-btn" title="Retour" @click="emit('back')"><ArrowLeft :size="20" /></button>
      <h1>Mon historique</h1>
    </div>

    <div class="dates">
      <label>Du <input v-model="dateDebut" type="date" @change="charger" /></label>
      <label>Au <input v-model="dateFin" type="date" @change="charger" /></label>
    </div>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <DataTable
      :columns="COLONNES" :rows="scans" :loading="isLoading"
      :default-sort="{ key: 'created_at', dir: -1 }" :page-sizes="[10, 25, 50]"
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
.historique-operateur { padding: var(--space-4); height: 100%; overflow-y: auto; }

.header-row { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-3); }
.back-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: var(--touch-target-min, 44px); height: var(--touch-target-min, 44px);
  border: 1px solid var(--color-border); border-radius: var(--radius-md);
  background: var(--color-surface); color: var(--color-brand-dark); cursor: pointer;
}
h1 { font-size: var(--font-size-xl); margin: 0; }

.dates { display: flex; gap: var(--space-3); margin-bottom: var(--space-3); font-size: var(--font-size-sm); flex-wrap: wrap; }
.dates label { display: flex; align-items: center; gap: var(--space-2); }
.dates input {
  height: 36px; padding: 0 var(--space-2); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); font-family: inherit; font-size: var(--font-size-sm);
}

.error-banner { background: var(--color-rouge-bg); color: var(--color-rouge); padding: var(--space-3); border-radius: var(--radius-md); margin-bottom: var(--space-3); }

.badge { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: var(--font-size-xs); font-weight: 700; white-space: nowrap; }
.badge-vert { background: var(--color-vert-bg); color: var(--color-vert); }
.badge-orange { background: var(--color-orange-bg); color: #92400E; }
</style>
