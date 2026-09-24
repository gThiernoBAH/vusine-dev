<template>
  <div class="app-root">
    <router-view />
    <!-- *** AJOUT 2026-09-23 *** : une seule instance pour toute l'application --
         cf. src/composables/useConfirm.js. Remplace window.confirm() partout. -->
    <ConfirmDialog />
  </div>
</template>

<script setup>
// Login/Cockpit/Tablette ne sont plus pilotés ici via shallowRef -- le router
// (cf. src/router/index.js) décide de l'écran affiché et applique la logique
// d'aiguillage direction/opérateur + les redirections de connexion/déconnexion.
import ConfirmDialog from '@/components/ConfirmDialog.vue'
</script>

<style scoped>
.app-root {
  height: 100%;
}
</style>
