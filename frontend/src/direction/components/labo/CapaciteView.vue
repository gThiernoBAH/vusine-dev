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

// *** AJOUT 2026-09-23 *** : lignes actuellement dépliées (analyse F4 affichée sous la
// ligne, cf. DataTable.vue -- expandedKeys/#expanded-row). Clé = "ligneId:produitId".
const lignesDepliees = ref(new Set())
function cleAnalyse(row) { return `${row.ligne_id}:${row.produit_id}` }
function toggleAnalyse(row) {
  const cle = cleAnalyse(row)
  const s = new Set(lignesDepliees.value)
  s.has(cle) ? s.delete(cle) : s.add(cle)
  lignesDepliees.value = s
}

const COLONNES = [
  { key: 'ligne_code', label: 'Ligne' },
  { key: 'produit_nom', label: 'Produit' },
  { key: 'nb_jours_observes', label: 'Jours observés', align: 'right' },
  { key: 'mediane_jour', label: 'Médiane / jour', align: 'right', format: v => fmtNombre(v) },
  { key: 'p90_jour', label: 'P90 / jour', align: 'right', format: v => fmtNombre(v),
    title: 'Niveau atteint ou dépassé seulement 1 jour sur 10' },
  { key: 'dernier_jour_observe', label: 'Dernier jour observé' },
  { key: 'actions', label: '', sortable: false, searchable: false },
]

async function charger() {
  isLoading.value = true
  try {
    lignes.value = (await apiClient.get('/labo/capacite')).data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger la capacité.'
  } finally {
    isLoading.value = false
  }
}

async function recalculer() {
  try {
    await apiClient.post('/labo/capacite/recalculer')
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
      Production réellement démontrée par jour, pour chaque ligne et chaque produit, d'après
      les OF terminés. Seuls les couples observés au moins 5 jours sont affichés.
    </p>

    <LaboToolbar :recalculer="recalculer">
      <template #droite><ExportButton domaine="capacite" libelle="la capacité démontrée" /></template>
    </LaboToolbar>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <DataTable
      :columns="COLONNES" :rows="lignes" :loading="isLoading"
      :default-sort="{ key: 'ligne_code', dir: 1 }"
      :row-key="cleAnalyse" :expanded-keys="lignesDepliees"
      empty-text="Aucune capacité démontrée pour l'instant."
    >
      <template #cell-produit_nom="{ row }"><span :title="row.produit_code">{{ row.produit_nom ?? '—' }}</span></template>
      <template #cell-actions="{ row }">
        <ExplicationToggleButton :ouvert="lignesDepliees.has(cleAnalyse(row))" @toggle="toggleAnalyse(row)" />
      </template>
      <template #expanded-row="{ row }">
        <ExplicationPanel domaine="capacite" :cle="{ ligne_id: row.ligne_id, produit_id: row.produit_id }" />
      </template>
    </DataTable>
  </div>
</template>
