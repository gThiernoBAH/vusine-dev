<script setup>
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import DataTable from '@/components/DataTable.vue'
import LaboToolbar from './LaboToolbar.vue'
import ExportButton from './ExportButton.vue'
import { fmtNombre } from './format'

const lignes = ref([])
const isLoading = ref(true)
const errorMessage = ref('')

const COLONNES = [
  { key: 'jour', label: 'Jour' },
  { key: 'ligne_code', label: 'Ligne', format: v => v ?? 'Non couvert' },
  { key: 'produit_nom', label: 'Produit' },
  { key: 'qte_recommandee', label: 'Qté recommandée', align: 'right', format: v => fmtNombre(v, 0) },
  { key: 'deficit_residuel', label: 'Déficit résiduel', align: 'right', format: v => fmtNombre(v, 0),
    title: 'Volume prévu qu\'aucune ligne éligible ne peut absorber ce jour-là' },
]

async function charger() {
  isLoading.value = true
  try {
    lignes.value = (await apiClient.get('/labo/plan-optimise')).data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger le plan.'
  } finally {
    isLoading.value = false
  }
}

async function recalculer() {
  try {
    await apiClient.post('/labo/plan-optimise/recalculer')
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
      Répartition recommandée des produits sur les lignes éligibles, jour par jour, d'après la capacité
      démontrée et la prévision. Recommandation seulement : le planning Odoo n'est jamais modifié.
    </p>

    <LaboToolbar :recalculer="recalculer">
      <template #droite><ExportButton domaine="plan_optimise" libelle="le plan optimisé" /></template>
    </LaboToolbar>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <DataTable
      :columns="COLONNES" :rows="lignes" :loading="isLoading"
      :default-sort="{ key: 'jour', dir: 1 }" empty-text="Aucun plan calculé pour l'instant."
    >
      <template #cell-ligne_code="{ row }">
        <span v-if="row.ligne_code">{{ row.ligne_code }}</span>
        <span v-else class="badge badge-rouge" title="Aucune ligne éligible n'a suffi à couvrir le volume prévu">Non couvert</span>
      </template>
      <template #cell-produit_nom="{ row }"><span :title="row.produit_code">{{ row.produit_nom ?? '—' }}</span></template>
      <template #cell-deficit_residuel="{ row }">
        <span :class="{ 'text-rouge': row.deficit_residuel > 0 }">{{ fmtNombre(row.deficit_residuel, 0) }}</span>
      </template>
    </DataTable>
  </div>
</template>
