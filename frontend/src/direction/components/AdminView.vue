<script setup>
import { ref } from 'vue'
import PersonnelAdmin from './admin/PersonnelAdmin.vue'
import EquipementsAdmin from './admin/EquipementsAdmin.vue'
import CausesArretAdmin from './admin/CausesArretAdmin.vue'
import LignesAdmin from './admin/LignesAdmin.vue'
import CalendrierAdmin from './admin/CalendrierAdmin.vue'
import ParametresAdmin from './admin/ParametresAdmin.vue'

const TABS = [
  { key: 'lignes', label: 'Lignes' },
  { key: 'personnel', label: 'Personnel' },
  { key: 'equipements', label: 'Équipements' },
  { key: 'causes', label: "Causes d'arrêt" },
  { key: 'calendrier', label: 'Calendrier' },
  { key: 'parametres', label: 'Paramètres' },
]
const activeTab = ref('lignes')
</script>

<template>
  <div class="admin-view">
    <header class="page-header">
      <h1>Administration</h1>
      <p class="subtitle">Lignes, personnel, équipements et paramétrage</p>
    </header>

    <div class="tabs">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        :class="['tab-btn', { active: activeTab === tab.key }]"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <LignesAdmin v-if="activeTab === 'lignes'" />
    <PersonnelAdmin v-else-if="activeTab === 'personnel'" />
    <EquipementsAdmin v-else-if="activeTab === 'equipements'" />
    <CausesArretAdmin v-else-if="activeTab === 'causes'" />
    <CalendrierAdmin v-else-if="activeTab === 'calendrier'" />
    <ParametresAdmin v-else-if="activeTab === 'parametres'" />
  </div>
</template>

<style scoped>
.admin-view {
  padding: var(--space-6);
  overflow-y: auto;
  height: 100%;
}

.page-header h1 { margin: 0; font-size: var(--font-size-2xl); }
.subtitle { color: var(--color-text-muted); margin: 4px 0 var(--space-6); }

.tabs {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.tab-btn {
  border: none;
  background: none;
  padding: var(--space-3) var(--space-4);
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-text-muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}

.tab-btn.active {
  color: var(--color-brand);
  border-bottom-color: var(--color-brand);
}
</style>