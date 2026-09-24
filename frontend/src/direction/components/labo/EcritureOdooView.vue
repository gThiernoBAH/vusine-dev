<script setup>
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import DataTable from '@/components/DataTable.vue'
import LaboToolbar from './LaboToolbar.vue'
import ExportButtonPeriode from './ExportButtonPeriode.vue'
import { fmtNombre } from './format'

function ilYA(jours) {
  const d = new Date()
  d.setDate(d.getDate() - jours)
  return d.toISOString().slice(0, 10)
}

const dateDebut = ref(ilYA(30))
const dateFin = ref(ilYA(0))
const comparaison = ref([])
const isLoading = ref(true)
const errorMessage = ref('')

const COLONNES = [
  { key: 'jour', label: 'Jour' },
  { key: 'ligne_code', label: 'Ligne' },
  { key: 'produit_nom', label: 'Produit' },
  { key: 'quantite_vusine', label: 'Qté Vusine', align: 'right', format: v => fmtNombre(v, 0),
    title: 'Quantité issue des palettes scannées sur la tablette' },
  { key: 'quantite_odoo', label: 'Qté Odoo', align: 'right', format: v => fmtNombre(v, 0),
    title: 'Quantité saisie dans Odoo (OF terminés)' },
  { key: 'ecart_qte', label: 'Écart', align: 'right', format: v => fmtNombre(v, 0) },
  { key: 'ecart_pct', label: 'Écart %', align: 'right', format: v => (v === null || v === undefined ? '—' : `${fmtNombre(v)} %`) },
]

async function charger() {
  isLoading.value = true
  try {
    comparaison.value = (await apiClient.get('/labo/comparaison-odoo', {
      params: { date_debut: dateDebut.value, date_fin: dateFin.value },
    })).data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger la comparaison.'
  } finally {
    isLoading.value = false
  }
}

async function recalculer() {
  try {
    await apiClient.post('/labo/ecritures-proposees/recalculer')
    await charger()
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Échec du recalcul.'
  }
}

function classeEcart(v) {
  if (v === null || v === undefined) return null
  const a = Math.abs(v)
  return a > 10 ? 'text-rouge' : a <= 5 ? 'text-vert' : null
}

onMounted(charger)
</script>

<template>
  <div>
    <p class="hint">
      Ce que Vusine écrirait dans Odoo (depuis les palettes scannées), comparé à la saisie Odoo réelle.
      Un écart proche de 0 % et stable justifiera un jour l'activation : aucune écriture pour l'instant.
    </p>

    <LaboToolbar :recalculer="recalculer">
      <template #gauche>
        <label class="reglage">Du <input v-model="dateDebut" type="date" @change="charger" /></label>
        <label class="reglage">Au <input v-model="dateFin" type="date" @change="charger" /></label>
      </template>
      <template #droite>
        <!-- Deux exports distincts, étiquetés : la comparaison affichée, et les écritures
             proposées seules (vides tant qu'aucune palette n'est scannée). -->
        <ExportButtonPeriode
          route="comparaison-odoo" libelle="Comparaison" description="la comparaison Vusine / Odoo"
          :date-debut="dateDebut" :date-fin="dateFin"
        />
        <ExportButtonPeriode
          route="ecritures-proposees" libelle="Écritures proposées"
          description="les écritures que Vusine proposerait à Odoo"
          :date-debut="dateDebut" :date-fin="dateFin"
        />
      </template>
    </LaboToolbar>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <DataTable
      :columns="COLONNES" :rows="comparaison" :loading="isLoading" :row-key="(r, i) => i"
      :default-sort="{ key: 'jour', dir: -1 }" empty-text="Aucune comparaison sur cette période."
    >
      <template #cell-ecart_pct="{ row }">
        <span :class="classeEcart(row.ecart_pct)">{{ row.ecart_pct === null || row.ecart_pct === undefined ? '—' : `${fmtNombre(row.ecart_pct)} %` }}</span>
      </template>
    </DataTable>
  </div>
</template>
