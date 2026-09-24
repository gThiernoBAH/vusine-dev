<script setup>
/**
 * LaboToolbar.vue -- barre d'outils commune à tous les écrans Labo :
 *   à gauche : « Recalculer maintenant » (si l'écran a un calcul stocké) + réglages
 *              propres à l'écran (slot "gauche" : horizon, période, sélecteur…) ;
 *   à droite : les boutons d'export (slot "droite"), toujours à l'extrême droite.
 *
 * `recalculer` : fonction async fournie par l'écran (POST + rechargement). Absente pour
 * F2 et F3, calculés à chaque affichage -- il n'y a rien de stocké à recalculer.
 */
import { ref } from 'vue'

const props = defineProps({
  recalculer: { type: Function, default: null },
  hintRecalcul: { type: String, default: 'Relance le calcul maintenant, sans attendre le recalcul automatique de la nuit.' },
})

const enCours = ref(false)

async function lancer() {
  enCours.value = true
  try {
    await props.recalculer()
  } finally {
    enCours.value = false
  }
}
</script>

<template>
  <div class="labo-toolbar">
    <div class="gauche">
      <button
        v-if="recalculer" type="button" class="vbtn vbtn-primary"
        :disabled="enCours" :title="hintRecalcul" @click="lancer"
      >
        <span v-if="enCours" class="vbtn-spinner" aria-hidden="true" />
        {{ enCours ? 'Recalcul en cours…' : 'Recalculer maintenant' }}
      </button>
      <slot name="gauche" />
    </div>
    <div class="droite">
      <slot name="droite" />
    </div>
  </div>
</template>

<style scoped>
.labo-toolbar {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-3);
  flex-wrap: wrap; margin-bottom: var(--space-3);
}
.gauche, .droite { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
.droite { margin-left: auto; }
</style>
