<script setup>
/**
 * ExportButtonPeriode.vue -- export Excel / PDF / CSV borné par une période (F5 :
 * GET /labo/{route}/export). `libelle` précède les boutons quand un écran propose
 * plusieurs exports différents, pour qu'on sache toujours ce qu'on télécharge.
 */
import { ref } from 'vue'
import apiClient from '@/api/client'

const props = defineProps({
  route: { type: String, required: true },       // 'ecritures-proposees' | 'comparaison-odoo'
  dateDebut: { type: String, required: true },   // 'YYYY-MM-DD'
  dateFin: { type: String, required: true },
  libelle: { type: String, default: '' },
  description: { type: String, default: 'ce tableau' },
})

const FORMATS = [
  { format: 'xlsx', label: 'Excel', hint: 'Télécharger {x} sur la période choisie, au format Excel (.xlsx)' },
  { format: 'pdf', label: 'PDF', hint: 'Télécharger {x} sur la période choisie, au format PDF' },
  { format: 'csv', label: 'CSV', hint: 'Télécharger {x} sur la période choisie, au format CSV (séparateur ;)' },
]

const enCours = ref('')
const erreur = ref('')

async function exporter(format) {
  enCours.value = format
  erreur.value = ''
  try {
    const res = await apiClient.get(`/labo/${props.route}/export`, {
      params: { format, date_debut: props.dateDebut, date_fin: props.dateFin },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = `${props.route}_${props.dateDebut}_${props.dateFin}.${format}`
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    erreur.value = "Échec de l'export."
  } finally {
    enCours.value = ''
  }
}
</script>

<template>
  <div class="export-buttons">
    <span v-if="libelle" class="export-libelle">{{ libelle }}</span>
    <span v-if="erreur" class="export-erreur">{{ erreur }}</span>
    <button
      v-for="f in FORMATS" :key="f.format" type="button" class="vbtn vbtn-secondary"
      :disabled="!!enCours" :title="f.hint.replace('{x}', description)" @click="exporter(f.format)"
    >
      <span v-if="enCours === f.format" class="vbtn-spinner" aria-hidden="true" />
      {{ f.label }}
    </button>
  </div>
</template>

<style scoped>
.export-buttons { display: flex; align-items: center; gap: var(--space-2); }
.export-libelle { font-size: var(--font-size-xs); font-weight: 700; color: var(--color-text-muted); }
.export-erreur { color: var(--color-rouge); font-size: var(--font-size-xs); }
</style>
