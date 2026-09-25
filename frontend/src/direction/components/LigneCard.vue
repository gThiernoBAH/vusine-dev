<script setup>
/**
 * LigneCard.vue -- tuile d'une ligne de la Vue Usine. *** EXTRAIT 2026-09-24 *** de VueUsineView pour
 * servir dans l'affichage à plat ET dans l'affichage par section, en deux densités :
 *   - détaillée : code, statut, nom, section, performance, retard, prévision de fin de poste ;
 *   - compacte  : code + performance sur fond teinté par le statut -- 88 lignes tiennent à l'écran,
 *                 le détail reste dans l'infobulle et au clic.
 */
import StatutBadge from './StatutBadge.vue'
import { computed } from 'vue'

const props = defineProps({
  ligne: { type: Object, required: true },
  compact: { type: Boolean, default: false },
})
defineEmits(['select'])

const LABELS = { vert: 'En production', orange: 'En retard', rouge: 'Retard critique', arret: "À l'arrêt", inactif: 'Inactif', demarrage: 'Démarrage' }
const aPrevision = computed(() => props.ligne.prevision_fin_poste !== null && props.ligne.prevision_fin_poste !== undefined)
const perf = computed(() => (props.ligne.performance_pct !== null && props.ligne.performance_pct !== undefined ? `${props.ligne.performance_pct}%` : '—'))
const infobulle = computed(() => {
  const l = props.ligne
  const p = [`${l.code} — ${l.nom}`, LABELS[l.statut] || l.statut]
  if (l.performance_pct !== null && l.performance_pct !== undefined) p.push(`performance ${l.performance_pct}%`)
  if (l.retard_min) p.push(`retard ${l.retard_min} min`)
  return p.join(' · ')
})
const fmt = n => Number(n).toLocaleString('fr-FR')
</script>

<template>
  <button :class="['ligne-card', `st-${ligne.statut}`, { compact }]" :title="infobulle" @click="$emit('select', ligne.id)">
    <template v-if="compact">
      <span class="ligne-code">{{ ligne.code }}</span>
      <span class="compact-perf">{{ perf }}</span>
    </template>
    <template v-else>
      <div class="ligne-card-top">
        <span class="ligne-code">{{ ligne.code }}</span>
        <StatutBadge :statut="ligne.statut" />
      </div>
      <div class="ligne-nom">{{ ligne.nom }}</div>
      <div class="ligne-section">{{ ligne.section_nom }}</div>
      <div class="ligne-metrics">
        <div>
          <span class="metric-value">{{ perf }}</span>
          <span class="metric-label">Performance</span>
        </div>
        <div>
          <span class="metric-value">{{ ligne.retard_min }} min</span>
          <span class="metric-label">Retard</span>
        </div>
        <!-- Projection linéaire de fin de poste, seulement quand elle est calculable. L'objectif passe
             sur la ligne du bas : « 1 371 / 10 000 » ne se replie plus sur trois lignes. -->
        <div v-if="aPrevision" title="Projection linéaire de la production en fin de poste, si la cadence actuelle se maintient">
          <span class="metric-value">{{ fmt(ligne.prevision_fin_poste) }}</span>
          <span class="metric-label">Fin de poste ≈<template v-if="ligne.objectif_jour"><br />sur {{ fmt(ligne.objectif_jour) }}</template></span>
        </div>
      </div>
    </template>
  </button>
</template>

<style scoped>
.ligne-card {
  text-align: left; background: var(--color-surface); border: 1px solid var(--color-border);
  border-left: 4px solid var(--color-border); border-radius: var(--radius-lg); padding: var(--space-4);
  cursor: pointer; font-family: inherit; box-shadow: var(--shadow-card); transition: transform .1s, box-shadow .1s;
}
.ligne-card:hover { transform: translateY(-2px); box-shadow: 0 4px 10px rgba(15, 23, 42, 0.12); }
.st-vert { border-left-color: var(--color-vert); }
.st-orange { border-left-color: var(--color-orange); }
.st-rouge { border-left-color: var(--color-rouge); }
.st-arret { border-left-color: var(--color-arret, var(--color-rouge)); }
.st-demarrage { border-left-color: #3B82F6; }
.st-inactif { border-left-color: var(--color-border); }

.ligne-card-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-2); gap: var(--space-2); }
.ligne-code { font-weight: 800; font-size: var(--font-size-lg); }
.ligne-nom { font-weight: 600; font-size: var(--font-size-sm); }
.ligne-section { color: var(--color-text-muted); font-size: var(--font-size-xs); margin-bottom: var(--space-3); }
.ligne-metrics { display: flex; flex-wrap: wrap; gap: var(--space-4) var(--space-6); padding-top: var(--space-3); border-top: 1px solid var(--color-border); }
.metric-value { display: block; font-weight: 700; font-size: var(--font-size-base); }
.metric-label { display: block; font-size: var(--font-size-xs); color: var(--color-text-muted); }

/* Compacte : teinte pleine par statut, code + % sur deux lignes. */
.ligne-card.compact { display: flex; flex-direction: column; gap: 2px; padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); box-shadow: none; min-height: 52px; }
.compact .ligne-code { font-size: var(--font-size-sm); line-height: 1.1; }
.compact-perf { font-weight: 800; font-size: var(--font-size-base); line-height: 1.1; }
.compact.st-vert { background: var(--color-vert-bg); }
.compact.st-orange { background: var(--color-orange-bg); }
.compact.st-rouge, .compact.st-arret { background: var(--color-rouge-bg); }
.compact.st-demarrage { background: #DBEAFE; }
.compact.st-inactif { background: var(--color-bg, #F1F5F9); color: var(--color-text-muted); }
</style>
