<script setup>
import { useRouter } from 'vue-router'
import Sidebar from './components/Sidebar.vue'

const router = useRouter()

const user = JSON.parse(sessionStorage.getItem('user') || '{}')
// L'admin voit toujours tout (cf. auth_routes.require_permission côté backend) ; sinon,
// dépend de la permission explicite "view_parametrage" accordée par un autre admin.
const canAdmin = user.is_admin || (user.permissions || []).includes('view_parametrage')
// *** AJOUT (chantier Labo) *** : is_super_admin uniquement, jamais is_admin -- un
// compte Direction avec is_admin=True ne voit jamais le Labo (cf. router/index.js).
const canLabo = user.is_super_admin

// VueUsineView/LigneDetailView continuent d'émettre select-ligne/back exactement comme
// avant -- seule la réaction change (on pousse une route au lieu de changer une variable
// d'état locale). Aucune modification nécessaire dans ces deux composants.
function selectLigne(ligneId, jour) {
  router.push({ name: 'ligne-detail', params: { id: ligneId }, query: jour ? { jour } : {} })
}
function backToVueUsine() {
  router.push({ name: 'vue-usine' })
}
</script>

<template>
  <div class="cockpit">
    <Sidebar :user-nom="user.nom" :can-admin="canAdmin" :can-labo="canLabo" />
    <main class="main-area">
      <router-view v-slot="{ Component }">
        <component :is="Component" @select-ligne="selectLigne" @back="backToVueUsine" />
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.cockpit {
  display: flex;
  height: 100%;
}

.main-area {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
</style>
