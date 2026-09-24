<script setup>
import { useRouter } from 'vue-router'
import { LogOut } from 'lucide-vue-next'

const router = useRouter()
const user = JSON.parse(sessionStorage.getItem('user') || '{}')

// MesLignesView/LigneOperateurView continuent d'émettre select-ligne/back exactement
// comme avant -- seule la réaction change. Aucune modification nécessaire dans ces deux
// composants.
function selectLigne(id) {
  router.push({ name: 'ligne-operateur', params: { id } })
}
function backToMesLignes() {
  router.push({ name: 'mes-lignes' })
}
function logout() {
  sessionStorage.removeItem('user')
  router.push('/login')
}
</script>

<template>
  <div class="tablette">
    <header class="tablette-header">
      <div>
        <div class="brand-name">VUSINE</div>
        <!-- *** AJOUT 2026-09-23 *** : matricule affiché à côté du nom -- plusieurs
             personnes peuvent porter le même nom dans l'usine, le nom seul ne suffit
             pas à identifier qui est réellement connecté sur cette tablette. -->
        <div class="user-name">{{ user.nom }} <span v-if="user.matricule" class="user-matricule">({{ user.matricule }})</span></div>
      </div>
      <button class="logout-btn" @click="logout"><LogOut :size="20" /></button>
    </header>

    <main class="tablette-body">
      <router-view v-slot="{ Component }">
        <component :is="Component" @select-ligne="selectLigne" @back="backToMesLignes" />
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.tablette {
  height: 100%;
  display: flex;
  flex-direction: column;
  max-width: 480px;
  margin: 0 auto;
  background: var(--color-bg);
}

.tablette-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  background: var(--color-brand);
  color: var(--color-text-inverse);
}

.brand-name {
  font-weight: 800;
  letter-spacing: 1px;
  font-size: var(--font-size-sm);
}

.user-name {
  font-size: var(--font-size-xs);
  opacity: 0.85;
}

.user-matricule {
  opacity: 0.75;
}

.logout-btn {
  border: none;
  background: none;
  color: var(--color-text-inverse);
  cursor: pointer;
  display: flex;
  padding: var(--space-2);
}

.tablette-body {
  flex: 1;
  min-height: 0;
}
</style>
