<script setup>
/**
 * ExplicationToggleButton.vue -- bouton "Analyser" placé dans la cellule Actions d'une
 * ligne de DataTable. Ne fait AUCUN appel réseau lui-même : bascule juste la ligne dans
 * l'ensemble `expandedKeys` géré par l'écran parent (cf. DataTable.vue, slot
 * #expanded-row) -- c'est ExplicationPanel.vue, affiché dans ce slot, qui récupère et
 * affiche l'analyse.
 */
defineProps({
  ouvert: { type: Boolean, default: false },
})
defineEmits(['toggle'])
</script>

<template>
  <button
    type="button" class="vbtn vbtn-outline" :aria-expanded="ouvert"
    :title="ouvert ? 'Masquer l\'analyse' : 'Afficher un commentaire (constat, points d\'attention, action) sur cette ligne'"
    @click="$emit('toggle')"
  >
    {{ ouvert ? 'Masquer' : 'Analyser' }}
  </button>
</template>
