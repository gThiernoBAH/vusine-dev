<script setup>
/**
 * ValeurProduitsAdmin.vue -- valeur d'UNE pièce, produit par produit (FCFA). *** AJOUT
 * 2026-09-24 (Palier 0, coût des pertes) ***
 *
 * Sert à valoriser les arrêts (Rapports > Pareto des arrêts). Un produit laissé vide
 * retombe sur la valeur par défaut (Administration > Paramètres). Ce que « valeur »
 * représente (prix de vente, coût de revient, marge) se choisit dans les Paramètres.
 * Enregistrement à la sortie du champ (ou Entrée) ; un champ vidé retire la valeur propre.
 */
import { ref, computed, onMounted } from 'vue'
import apiClient from '@/api/client'
import DataTable from '@/components/DataTable.vue'

const produits = ref([])
const libelle = ref('Valeur unitaire')
const valeurDefaut = ref(0)
const isLoading = ref(true)
const errorMessage = ref('')
const successMessage = ref('')
const enCours = ref(new Set())
// Saisie en cours par produit (texte), distincte de la valeur enregistrée.
const saisies = ref({})

async function charger() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const [liste, lib, def] = await Promise.all([
      apiClient.get('/admin/produits-valeur'),
      apiClient.get('/auth/params/libelle_valeur_piece'),
      apiClient.get('/auth/params/valeur_piece_defaut_fcfa'),
    ])
    produits.value = liste.data
    libelle.value = lib.data.value || 'Valeur unitaire'
    valeurDefaut.value = Number(def.data.value) || 0
    saisies.value = Object.fromEntries(liste.data.map(p => [p.id, p.valeur_unitaire_fcfa ?? '']))
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger les produits.'
  } finally {
    isLoading.value = false
  }
}
onMounted(charger)

const COLONNES = computed(() => [
  { key: 'nom', label: 'Produit' },
  { key: 'default_code', label: 'Code', format: v => v ?? '—' },
  { key: 'valeur_unitaire_fcfa', label: `${libelle.value} (FCFA)`, align: 'right', sortable: true,
    sortValue: p => p.valeur_unitaire_fcfa, format: v => (v === null || v === undefined ? 'défaut' : String(v)) },
])

async function enregistrer(produit) {
  const brut = String(saisies.value[produit.id] ?? '').trim().replace(',', '.')
  const valeur = brut === '' ? null : Number(brut)
  if (valeur !== null && (Number.isNaN(valeur) || valeur < 0)) {
    errorMessage.value = `« ${produit.nom} » : la valeur doit être un nombre positif ou nul.`
    saisies.value[produit.id] = produit.valeur_unitaire_fcfa ?? ''
    return
  }
  if ((valeur ?? null) === (produit.valeur_unitaire_fcfa ?? null)) return  // rien à enregistrer
  errorMessage.value = ''
  successMessage.value = ''
  enCours.value = new Set(enCours.value).add(produit.id)
  try {
    const res = await apiClient.patch(`/admin/produits/${produit.id}/valeur`, { valeur_unitaire_fcfa: valeur })
    produit.valeur_unitaire_fcfa = res.data.valeur_unitaire_fcfa
    saisies.value[produit.id] = res.data.valeur_unitaire_fcfa ?? ''
    successMessage.value = valeur === null ? `« ${produit.nom} » : valeur retirée (valeur par défaut).` : `« ${produit.nom} » enregistré.`
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || `Échec de l'enregistrement de « ${produit.nom} ».`
    saisies.value[produit.id] = produit.valeur_unitaire_fcfa ?? ''
  } finally {
    const s = new Set(enCours.value); s.delete(produit.id); enCours.value = s
  }
}
</script>

<template>
  <div class="valeur-produits">
    <p class="hint">
      Valeur d'<strong>une pièce</strong> en FCFA, utilisée pour estimer le coût des arrêts. Ce que cette valeur représente est
      « <strong>{{ libelle }}</strong> » (modifiable dans Paramètres). Un produit laissé vide utilise la valeur par défaut,
      actuellement <strong>{{ valeurDefaut > 0 ? valeurDefaut.toLocaleString('fr-FR') + ' FCFA' : 'non configurée' }}</strong>.
    </p>
    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <p v-if="successMessage" class="success-banner">{{ successMessage }}</p>

    <DataTable
      :columns="COLONNES" :rows="produits" :loading="isLoading" row-key="id"
      :default-sort="{ key: 'nom', dir: 1 }"
      empty-text="Aucun produit fini synchronisé depuis Odoo pour l'instant."
    >
      <template #cell-valeur_unitaire_fcfa="{ row }">
        <input
          v-model="saisies[row.id]" type="text" inputmode="decimal" class="valeur-input"
          :placeholder="valeurDefaut > 0 ? String(valeurDefaut) : 'défaut'"
          :disabled="enCours.has(row.id)" :aria-label="`Valeur d'une pièce de ${row.nom}`"
          @blur="enregistrer(row)" @keydown.enter.prevent="$event.target.blur()"
        />
      </template>
    </DataTable>
  </div>
</template>

<style scoped>
.valeur-produits { display: flex; flex-direction: column; gap: var(--space-4); }
.hint { font-size: var(--font-size-sm); color: var(--color-text-muted); max-width: 720px; margin: 0; }
.error-banner { background: var(--color-rouge-bg); color: var(--color-rouge); padding: var(--space-3); border-radius: var(--radius-md); margin: 0; }
.success-banner { background: var(--color-vert-bg); color: var(--color-vert); padding: var(--space-3); border-radius: var(--radius-md); margin: 0; }
.valeur-input {
  width: 110px; height: 32px; padding: 0 var(--space-2); text-align: right;
  border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: var(--font-size-sm);
}
.valeur-input:focus { outline: 2px solid var(--color-brand); outline-offset: 1px; }
.valeur-input:disabled { opacity: .5; }
</style>
