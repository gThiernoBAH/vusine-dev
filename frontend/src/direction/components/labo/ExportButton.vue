<script setup>
/**
 * ExportButton.vue -- export Excel / PDF / CSV d'un écran Labo (GET /labo/export/{domaine}).
 * `params` : réglages de l'écran à répercuter dans l'export (horizon, fenêtre…), pour
 * que le fichier corresponde exactement à ce qui est affiché.
 */
import { ref } from 'vue'
import apiClient from '@/api/client'

const props = defineProps({
  domaine: { type: String, required: true },
  params: { type: Object, default: () => ({}) },
  libelle: { type: String, default: 'ce tableau' },
})

const FORMATS = [
  { format: 'xlsx', label: 'Excel', hint: 'Télécharger {x} au format Excel (.xlsx)' },
  { format: 'pdf', label: 'PDF', hint: 'Télécharger {x} au format PDF, prêt à imprimer' },
  { format: 'csv', label: 'CSV', hint: 'Télécharger {x} au format CSV (séparateur ;)' },
]

const enCours = ref('')
const erreur = ref('')

async function exporter(format) {
  enCours.value = format
  erreur.value = ''
  try {
    const res = await apiClient.get(`/labo/export/${props.domaine}`, {
      params: { format, ...props.params }, responseType: 'blob',
    })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = `${props.domaine}_${new Date().toISOString().slice(0, 10)}.${format}`
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
    <span v-if="erreur" class="export-erreur">{{ erreur }}</span>
    <button
      v-for="f in FORMATS" :key="f.format" type="button" class="vbtn vbtn-secondary"
      :disabled="!!enCours" :title="f.hint.replace('{x}', libelle)" @click="exporter(f.format)"
    >
      <span v-if="enCours === f.format" class="vbtn-spinner" aria-hidden="true" />
      {{ f.label }}
    </button>
  </div>
</template>

<style scoped>
.export-buttons { display: flex; align-items: center; gap: var(--space-2); }
.export-erreur { color: var(--color-rouge); font-size: var(--font-size-xs); }
</style>
