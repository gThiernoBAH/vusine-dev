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
  { key: 'produit_nom', label: 'Produit' },
  { key: 'jour_horizon', label: 'Jour' },
  { key: 'qte_prevue', label: 'Prévu', align: 'right', format: v => fmtNombre(v, 0) },
  { key: 'intervalle_bas', label: 'Intervalle', align: 'right',
    title: 'Fourchette plausible (85 %) autour de la valeur prévue',
    format: (v, r) => `${fmtNombre(r.intervalle_bas, 0)} – ${fmtNombre(r.intervalle_haut, 0)}` },
]

async function charger() {
  isLoading.value = true
  try {
    lignes.value = (await apiClient.get('/labo/prevision-volume')).data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger les prévisions.'
  } finally {
    isLoading.value = false
  }
}

async function recalculer() {
  try {
    await apiClient.post('/labo/prevision-volume/recalculer')
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
      Production attendue par produit, toutes lignes confondues, sur les 14 prochains jours
      (historique réel jusqu'à J-2). Un produit n'apparaît qu'après 15 jours de production sur 6 mois.
    </p>

    <LaboToolbar
      :recalculer="recalculer"
      hint-recalcul="Relance la prévision (1 à 2 minutes). Le plan optimisé et les matières se mettent à jour à leur propre recalcul."
    >
      <template #droite><ExportButton domaine="prevision_volume" libelle="les prévisions" /></template>
    </LaboToolbar>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <DataTable
      :columns="COLONNES" :rows="lignes" :loading="isLoading"
      :default-sort="{ key: 'jour_horizon', dir: 1 }" empty-text="Aucune prévision calculée pour l'instant."
    >
      <template #cell-produit_nom="{ row }"><span :title="row.produit_code">{{ row.produit_nom ?? '—' }}</span></template>
    </DataTable>
  </div>
</template>
