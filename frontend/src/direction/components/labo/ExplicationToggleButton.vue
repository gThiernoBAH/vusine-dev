<script setup>
/**
 * ExplicationToggleButton.vue -- bouton « Analyse IA » (ex-« Analyser ») placé dans la cellule Actions d'une
 * ligne de DataTable. Ne fait AUCUN appel réseau lui-même : bascule juste la ligne dans
 * l'ensemble `expandedKeys` géré par l'écran parent (cf. DataTable.vue, slot
 * #expanded-row) -- c'est ExplicationPanel.vue, affiché dans ce slot, qui récupère et
 * affiche l'analyse.
 */
import { Sparkles } from 'lucide-vue-next'

defineProps({
  ouvert: { type: Boolean, default: false },
})
defineEmits(['toggle'])
</script>

<template>
  <button
    type="button" class="vbtn vbtn-outline" :aria-expanded="ouvert"
    :title="ouvert ? 'Masquer l\'analyse' : 'Analyse générée par IA à partir de ces chiffres, à vérifier'"
    @click="$emit('toggle')"
  >
    <Sparkles v-if="!ouvert" :size="14" aria-hidden="true" />
    {{ ouvert ? 'Masquer' : 'Analyse IA' }}
  </button>
</template>
