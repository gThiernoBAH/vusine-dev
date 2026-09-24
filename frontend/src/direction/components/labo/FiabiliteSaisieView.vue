<script setup>
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import DataTable from '@/components/DataTable.vue'
import LaboToolbar from './LaboToolbar.vue'
import ExportButton from './ExportButton.vue'
import ExplicationToggleButton from './ExplicationToggleButton.vue'
import ExplicationPanel from './ExplicationPanel.vue'
import { fmtNombre } from './format'

const lignes = ref([])
const isLoading = ref(true)
const errorMessage = ref('')
const jours = ref(30)

// *** AJOUT 2026-09-23 *** : cf. CapaciteView.vue -- même mécanique de ligne dépliée.
const lignesDepliees = ref(new Set())
function toggleAnalyse(row) {
  const s = new Set(lignesDepliees.value)
  s.has(row.ligne_id) ? s.delete(row.ligne_id) : s.add(row.ligne_id)
  lignesDepliees.value = s
}

const COLONNES = [
  { key: 'ligne_code', label: 'Ligne' },
  { key: 'nb_of', label: 'Nb OF', align: 'right' },
  { key: 'delai_median_h', label: 'Délai médian (h)', align: 'right', format: v => fmtNombre(v) },
  { key: 'delai_p90_h', label: 'Délai P90 (h)', align: 'right', format: v => fmtNombre(v) },
  { key: 'nb_corrections', label: 'Corrections', align: 'right' },
  { key: 'actions', label: '', sortable: false, searchable: false },
]

async function charger() {
  isLoading.value = true
  try {
    lignes.value = (await apiClient.get('/labo/fiabilite-saisie', { params: { jours: jours.value } })).data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger la fiabilité de saisie.'
  } finally {
    isLoading.value = false
  }
}

onMounted(charger)
</script>

<template>
  <div>
    <p class="hint">
      Délai réel entre la production (jour de l'OF) et sa saisie dans Odoo, et corrections
      déclarées par ligne. La production du jour n'arrive en général dans Odoo que le lendemain.
    </p>

    <LaboToolbar>
      <template #gauche>
        <label class="reglage" title="Période analysée, en jours, jusqu'à aujourd'hui">
          Fenêtre (jours)
          <input v-model.number="jours" type="number" min="7" max="180" @change="charger" />
        </label>
      </template>
      <template #droite>
        <ExportButton domaine="fiabilite_saisie" :params="{ jours }" libelle="la fiabilité de saisie" />
      </template>
    </LaboToolbar>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <DataTable
      :columns="COLONNES" :rows="lignes" :loading="isLoading" row-key="ligne_id"
      :expanded-keys="lignesDepliees"
      :default-sort="{ key: 'delai_median_h', dir: -1 }" empty-text="Aucune donnée sur cette fenêtre."
    >
      <template #cell-actions="{ row }">
        <ExplicationToggleButton :ouvert="lignesDepliees.has(row.ligne_id)" @toggle="toggleAnalyse(row)" />
      </template>
      <template #expanded-row="{ row }">
        <ExplicationPanel domaine="fiabilite_saisie" :cle="{ ligne_id: row.ligne_id }" />
      </template>
    </DataTable>
  </div>
</template>
