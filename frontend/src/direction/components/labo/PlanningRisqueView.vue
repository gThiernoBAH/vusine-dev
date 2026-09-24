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
const horizonJours = ref(14)

const STATUTS = {
  risque: { label: 'Risque', classe: 'badge-rouge', ordre: 0 },
  a_surveiller: { label: 'À surveiller', classe: 'badge-orange', ordre: 1 },
  ok: { label: 'OK', classe: 'badge-vert', ordre: 2 },
  inconnu: { label: 'Inconnu', classe: 'badge-gris', ordre: 3 },
}

const COLONNES = [
  { key: 'statut', label: 'Statut', format: v => STATUTS[v]?.label ?? v,
    sortValue: r => STATUTS[r.statut]?.ordre ?? 9 },
  { key: 'ligne_code', label: 'Ligne' },
  { key: 'produit_nom', label: 'Produit' },
  { key: 'jour', label: 'Jour' },
  { key: 'qty', label: 'Planifié', align: 'right', format: v => fmtNombre(v) },
  { key: 'mediane_jour', label: 'Médiane', align: 'right', format: v => fmtNombre(v) },
  { key: 'p90_jour', label: 'P90', align: 'right', format: v => fmtNombre(v) },
]

async function charger() {
  isLoading.value = true
  try {
    lignes.value = (await apiClient.get('/labo/planning-risque', { params: { horizon_jours: horizonJours.value } })).data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger le planning.'
  } finally {
    isLoading.value = false
  }
}

onMounted(charger)
</script>

<template>
  <div>
    <p class="hint">
      Le planning à venir demande-t-il plus que ce que la ligne a déjà démontré ?
      « Risque » : au-delà du P90 observé. « À surveiller » : au-delà de la médiane.
    </p>

    <LaboToolbar>
      <template #gauche>
        <label class="reglage" title="Nombre de jours de planning à contrôler, à partir d'aujourd'hui">
          Horizon (jours)
          <input v-model.number="horizonJours" type="number" min="1" max="60" @change="charger" />
        </label>
      </template>
      <template #droite>
        <ExportButton domaine="planning_risque" :params="{ horizon_jours: horizonJours }" libelle="le planning contrôlé" />
      </template>
    </LaboToolbar>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <DataTable
      :columns="COLONNES" :rows="lignes" :loading="isLoading" :row-key="(r, i) => i"
      :default-sort="{ key: 'statut', dir: 1 }" empty-text="Aucun planning sur cet horizon."
    >
      <template #cell-statut="{ row }">
        <span :class="['badge', STATUTS[row.statut]?.classe]">{{ STATUTS[row.statut]?.label ?? row.statut }}</span>
      </template>
    </DataTable>
  </div>
</template>
