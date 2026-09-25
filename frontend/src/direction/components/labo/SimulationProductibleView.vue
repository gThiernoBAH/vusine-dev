<script setup>
import { ref, computed, onMounted } from 'vue'
import apiClient from '@/api/client'
import DataTable from '@/components/DataTable.vue'
import LaboToolbar from './LaboToolbar.vue'
import LaboSousOnglets from './LaboSousOnglets.vue'
import ExportButton from './ExportButton.vue'
import { fmtNombre } from './format'

const simulation = ref([])
const ecarts = ref([])
const isLoading = ref(true)
const errorMessage = ref('')
const vue = ref('simulation')

const VUES = [
  { value: 'simulation', label: 'Produits fabricables',
    title: 'Prédictif : combien d\'unités de chaque produit fini le stock matières actuel permet encore de fabriquer' },
  { value: 'ecarts', label: "Écarts d'inventaire",
    title: 'Constaté : écarts relevés lors des comptages physiques (synchronisés depuis Odoo, jamais mélangés à la simulation)' },
]

const COLONNES_SIMULATION = [
  { key: 'produit_fini_code', label: 'Produit fini' },
  { key: 'quantite_productible', label: 'Qté productible', align: 'right', format: v => fmtNombre(v, 0) },
  { key: 'composant_limitant_code', label: 'Composant limitant' },
  { key: 'stock_limitant', label: 'Stock limitant', align: 'right', format: v => fmtNombre(v, 3) },
  { key: 'nb_composants_sans_stock_connu', label: 'Avertissement', align: 'right',
    format: v => (v > 0 ? `${v} composant(s) sans stock connu` : '') },
]

const COLONNES_ECARTS = [
  { key: 'produit_code', label: 'Produit' },
  { key: 'emplacement_nom', label: 'Emplacement' },
  { key: 'date_validation', label: 'Date comptage' },
  { key: 'stock_systeme', label: 'Stock système', align: 'right', format: v => fmtNombre(v, 2) },
  { key: 'stock_compte', label: 'Stock compté', align: 'right', format: v => fmtNombre(v, 2) },
  { key: 'ecart_qte', label: 'Écart', align: 'right', format: v => fmtNombre(v, 2) },
]

const exportCourant = computed(() => vue.value === 'simulation'
  ? { domaine: 'simulation_productible', libelle: 'la simulation' }
  : { domaine: 'ecarts_inventaire', libelle: "les écarts d'inventaire" })

async function charger() {
  isLoading.value = true
  try {
    const [s, e] = await Promise.all([apiClient.get('/labo/simulation-productible'), apiClient.get('/labo/ecarts-inventaire')])
    simulation.value = s.data
    ecarts.value = e.data
    errorMessage.value = ''
  } catch (err) {
    errorMessage.value = err.response?.data?.detail || 'Impossible de charger la simulation.'
  } finally {
    isLoading.value = false
  }
}

async function recalculer() {
  try {
    await apiClient.post('/labo/simulation-productible/recalculer')
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
      Avec le stock matières actuel, combien d'unités de chaque produit fini peut-on encore fabriquer,
      et, à part, les écarts réellement constatés aux inventaires. Les deux ne sont jamais fusionnés.
    </p>

    <!-- Le bouton reste visible sur les deux sous-vues (2026-09-24), grisé sur les écarts : ils viennent de
         la synchronisation Odoo, il n'y a rien à recalculer ici. -->
    <LaboToolbar
      :recalculer="recalculer" :recalcul-desactive="vue !== 'simulation'"
      hint-desactive="Les écarts d'inventaire viennent de la synchronisation Odoo : il n'y a rien à recalculer ici. Le recalcul s'applique à « Produits fabricables »."
    >
      <template #gauche><LaboSousOnglets v-model="vue" :options="VUES" /></template>
      <template #droite>
        <ExportButton :key="exportCourant.domaine" :domaine="exportCourant.domaine" :libelle="exportCourant.libelle" />
      </template>
    </LaboToolbar>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <DataTable
      v-if="vue === 'simulation'" key="simulation"
      :columns="COLONNES_SIMULATION" :rows="simulation" :loading="isLoading"
      :default-sort="{ key: 'quantite_productible', dir: 1 }" empty-text="Aucune simulation calculée pour l'instant."
    >
      <template #cell-nb_composants_sans_stock_connu="{ row }">
        <span v-if="row.nb_composants_sans_stock_connu > 0" class="badge badge-orange">
          {{ row.nb_composants_sans_stock_connu }} composant(s) sans stock connu
        </span>
      </template>
    </DataTable>

    <DataTable
      v-else key="ecarts"
      :columns="COLONNES_ECARTS" :rows="ecarts" :loading="isLoading"
      :default-sort="{ key: 'date_validation', dir: -1 }" empty-text="Aucun écart d'inventaire synchronisé pour l'instant."
    >
      <template #cell-ecart_qte="{ row }">
        <span :class="{ 'text-rouge': row.ecart_qte < 0, 'text-vert': row.ecart_qte > 0 }">{{ fmtNombre(row.ecart_qte, 2) }}</span>
      </template>
    </DataTable>
  </div>
</template>
