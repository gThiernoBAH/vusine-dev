<script setup>
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import DataTable from '@/components/DataTable.vue'
import LaboToolbar from './LaboToolbar.vue'
import ExportButton from './ExportButton.vue'

const lignes = ref([])
const isLoading = ref(true)
const errorMessage = ref('')

const COLONNES = [
  { key: 'priorite', label: 'Priorité', format: v => (v === 'haute' ? 'Haute' : 'Normale'),
    sortValue: r => (r.priorite === 'haute' ? 0 : 1) },
  { key: 'ligne_code', label: 'Ligne' },
  { key: 'matiere_code', label: 'Matière' },
  { key: 'nb_arrets_manque_historique', label: 'Arrêts « manque » (90 j)', align: 'right',
    title: 'Arrêts « Manque MP » ou « Manque emballage » déclarés sur la ligne ces 90 derniers jours' },
  { key: 'date_limite_commande', label: 'Date limite commande' },
]

async function charger() {
  isLoading.value = true
  try {
    lignes.value = (await apiClient.get('/labo/alertes-emballage')).data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger les alertes emballage.'
  } finally {
    isLoading.value = false
  }
}

async function recalculer() {
  try {
    await apiClient.post('/labo/alertes-emballage/recalculer')
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
      Alertes d'achat rapportées aux lignes qui consomment la matière. Une ligne ayant déjà subi
      un arrêt « Manque MP » ou « Manque emballage » ces 90 derniers jours passe en priorité haute.
    </p>

    <LaboToolbar :recalculer="recalculer">
      <template #droite><ExportButton domaine="alertes_emballage" libelle="les alertes emballage" /></template>
    </LaboToolbar>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <DataTable
      :columns="COLONNES" :rows="lignes" :loading="isLoading"
      :default-sort="{ key: 'priorite', dir: 1 }" empty-text="Aucune alerte emballage pour l'instant."
    >
      <template #cell-priorite="{ row }">
        <span :class="['badge', row.priorite === 'haute' ? 'badge-rouge' : 'badge-gris']">
          {{ row.priorite === 'haute' ? 'Haute' : 'Normale' }}
        </span>
      </template>
    </DataTable>
  </div>
</template>
