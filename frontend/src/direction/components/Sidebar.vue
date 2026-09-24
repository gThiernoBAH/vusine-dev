<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Factory, LayoutGrid, Users, FileText, AlertTriangle, Settings, LogOut, FlaskConical, Tv } from 'lucide-vue-next'

defineProps({
  userNom: { type: String, default: '' },
  canAdmin: { type: Boolean, default: false },
  // *** AJOUT (chantier Labo) ***
  canLabo: { type: Boolean, default: false },
})

const route = useRoute()
const router = useRouter()

const ITEMS = [
  { key: 'vue_usine', label: 'Vue Usine', icon: LayoutGrid, to: '/cockpit/vue-usine' },
  { key: 'alertes', label: 'Alertes', icon: AlertTriangle, to: '/cockpit/alertes' },
  { key: 'scoring', label: 'Équipes', icon: Users, to: '/cockpit/scoring' },
  { key: 'rapports', label: 'Rapports', icon: FileText, to: '/cockpit/rapports' },
  // *** AJOUT 2026-09-24 (Palier 0) *** : aperçu de l'écran Andon (TV d'atelier), plein écran.
  { key: 'andon', label: 'Écran Andon', icon: Tv, to: '/andon' },
]

// ligne-detail (/cockpit/lignes/:id) met en surbrillance l'onglet Vue Usine -- même
// comportement que ":active=\"activeScreen === 'ligne_detail' ? 'vue_usine' : activeScreen\""
// avant la migration (on n'accède à cet écran qu'en cliquant une carte de Vue Usine).
const activeKey = computed(() => {
  if (route.name === 'ligne-detail') return 'vue_usine'
  if (route.name === 'admin') return 'admin'
  // *** AJOUT (chantier Labo) *** : toutes les sous-routes /cockpit/labo/* surlignent
  // le même item de menu, même principe que 'admin' ci-dessus.
  if (route.path.startsWith('/cockpit/labo')) return 'labo'
  return route.path.split('/')[2] || 'vue_usine'
})

function logout() {
  sessionStorage.removeItem('user')
  sessionStorage.removeItem('token')
  router.push('/login')
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-icon"><Factory :size="22" /></div>
      <div>
        <div class="brand-name">SIVOP</div>
        <div class="brand-sub">Vusine</div>
      </div>
    </div>

    <nav class="nav">
      <router-link
        v-for="item in ITEMS"
        :key="item.key"
        :to="item.to"
        :class="['nav-item', { active: activeKey === item.key }]"
      >
        <component :is="item.icon" :size="18" />
        {{ item.label }}
      </router-link>
      <router-link
        v-if="canAdmin"
        to="/cockpit/admin"
        :class="['nav-item', { active: activeKey === 'admin' }]"
      >
        <Settings :size="18" />
        Administration
      </router-link>
      <!-- *** AJOUT (chantier Labo) *** : canLabo uniquement (is_super_admin), jamais
           canAdmin -- item invisible pour tout autre compte, y compris Direction. -->
      <router-link
        v-if="canLabo"
        to="/cockpit/labo"
        :class="['nav-item', { active: activeKey === 'labo' }]"
      >
        <FlaskConical :size="18" />
        Labo
      </router-link>
    </nav>

    <div class="sidebar-footer">
      <div class="user-name">{{ userNom }}</div>
      <button class="logout-btn" @click="logout">
        <LogOut :size="16" /> Déconnexion
      </button>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 220px;
  flex-shrink: 0;
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  height: 100%;
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.brand-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--color-brand);
  color: var(--color-text-inverse);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.brand-name {
  font-weight: 800;
  font-size: var(--font-size-sm);
  color: var(--color-brand-dark);
  letter-spacing: 0.5px;
}

.brand-sub {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.nav {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-3);
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3);
  border: none;
  background: none;
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-text-muted);
  cursor: pointer;
  text-align: left;
  text-decoration: none;
}

.nav-item:hover {
  background: var(--color-brand-light);
}

.nav-item.active {
  background: var(--color-brand-light);
  color: var(--color-brand-dark);
}

.sidebar-footer {
  padding: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.user-name {
  font-size: var(--font-size-sm);
  font-weight: 600;
  margin-bottom: var(--space-2);
}

.logout-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  border: none;
  background: none;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  cursor: pointer;
  padding: 0;
}

.logout-btn:hover {
  color: var(--color-rouge);
}
</style>
