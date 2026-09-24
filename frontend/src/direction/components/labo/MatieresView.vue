<script setup>
import { ref, computed, onMounted } from 'vue'
import apiClient from '@/api/client'
import DataTable from '@/components/DataTable.vue'
import LaboToolbar from './LaboToolbar.vue'
import LaboSousOnglets from './LaboSousOnglets.vue'
import ExportButton from './ExportButton.vue'
import ExplicationToggleButton from './ExplicationToggleButton.vue'
import ExplicationPanel from './ExplicationPanel.vue'
import { fmtNombre } from './format'

const besoins = ref([])
const alertes = ref([])
const isLoading = ref(true)
const errorMessage = ref('')
const vue = ref('alertes')

// *** AJOUT 2026-09-23 *** : cf. CapaciteView.vue -- même mécanique de ligne dépliée
// (uniquement pertinent pour la vue "alertes", seule à avoir une colonne Actions).
const lignesDepliees = ref(new Set())
function toggleAnalyse(row) {
  const s = new Set(lignesDepliees.value)
  s.has(row.matiere_code) ? s.delete(row.matiere_code) : s.add(row.matiere_code)
  lignesDepliees.value = s
}

const VUES = [
  { value: 'alertes', label: "Alertes d'achat",
    title: "Matières qui vont manquer, avec la date limite pour commander compte tenu du meilleur délai fournisseur connu" },
  { value: 'besoins', label: 'Ruptures projetées',
    title: 'Matières dont le stock projeté passe sous zéro, et à quelle date, d\'après la prévision de production' },
]

const COLONNES_ALERTES = [
  { key: 'matiere_code', label: 'Matière' },
  { key: 'date_rupture_projetee', label: 'Rupture projetée' },
  { key: 'quantite_manquante', label: 'Qté manquante', align: 'right', format: v => fmtNombre(v, 2) },
  { key: 'meilleur_delai_jours', label: 'Meilleur délai', align: 'right', format: v => (v ?? null) === null ? '—' : `${v} j` },
  { key: 'date_limite_commande', label: 'Date limite commande', format: v => v ?? 'Aucun fournisseur connu' },
  { key: 'nb_fournisseurs_disponibles', label: 'Fournisseurs', align: 'right' },
  { key: 'actions', label: '', sortable: false, searchable: false },
]

const COLONNES_BESOINS = [
  { key: 'matiere_code', label: 'Matière' },
  { key: 'date_rupture_projetee', label: 'Rupture projetée' },
  { key: 'stock_projete', label: 'Stock projeté', align: 'right', format: v => fmtNombre(v, 2) },
]

const exportCourant = computed(() => vue.value === 'alertes'
  ? { domaine: 'alertes_achat', libelle: "les alertes d'achat" }
  : { domaine: 'besoins_matieres', libelle: 'les ruptures projetées' })

async function charger() {
  isLoading.value = true
  try {
    const [b, a] = await Promise.all([apiClient.get('/labo/besoins-matieres'), apiClient.get('/labo/alertes-achat')])
    besoins.value = b.data
    alertes.value = a.data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger les besoins matières.'
  } finally {
    isLoading.value = false
  }
}

async function recalculer() {
  try {
    await apiClient.post('/labo/matieres/recalculer')
    await charger()
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Échec du recalcul.'
  }
}

onMounted(charger)
</script>

<template>
  <div>
    <p class="hint">
      Ruptures matières projetées à partir de la prévision de production et des formules, et date
      limite de commande selon le délai fournisseur. Sans prix : le choix du fournisseur reste humain.
    </p>

    <LaboToolbar :recalculer="recalculer">
      <template #gauche><LaboSousOnglets v-model="vue" :options="VUES" /></template>
      <template #droite>
        <ExportButton :key="exportCourant.domaine" :domaine="exportCourant.domaine" :libelle="exportCourant.libelle" />
      </template>
    </LaboToolbar>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <DataTable
      v-if="vue === 'alertes'" key="alertes"
      :columns="COLONNES_ALERTES" :rows="alertes" :loading="isLoading" row-key="matiere_code"
      :expanded-keys="lignesDepliees"
      :default-sort="{ key: 'date_limite_commande', dir: 1 }" empty-text="Aucune alerte d'achat pour l'instant."
    >
      <template #cell-date_limite_commande="{ row }">
        <span :class="{ 'text-rouge': row.date_limite_commande }">{{ row.date_limite_commande ?? 'Aucun fournisseur connu' }}</span>
      </template>
      <template #cell-actions="{ row }">
        <ExplicationToggleButton :ouvert="lignesDepliees.has(row.matiere_code)" @toggle="toggleAnalyse(row)" />
      </template>
      <template #expanded-row="{ row }">
        <ExplicationPanel domaine="alertes_achat" :cle="{ matiere_code: row.matiere_code }" />
      </template>
    </DataTable>

    <DataTable
      v-else key="besoins"
      :columns="COLONNES_BESOINS" :rows="besoins" :loading="isLoading"
      :default-sort="{ key: 'date_rupture_projetee', dir: 1 }" empty-text="Aucune rupture projetée pour l'instant."
    >
      <template #cell-stock_projete="{ row }"><span class="text-rouge">{{ fmtNombre(row.stock_projete, 2) }}</span></template>
    </DataTable>
  </div>
</template>
