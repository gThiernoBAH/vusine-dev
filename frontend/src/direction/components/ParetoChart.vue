<script setup>
/**
 * ParetoChart.vue -- diagramme de Pareto des causes d'arrêt (barres = durée, courbe =
 * % cumulé, repère à 80 %). SVG pur, aucune dépendance : le volume est de l'ordre de 10
 * causes. *** AJOUT 2026-09-24 (Palier 0) ***
 *
 * Les barres jusqu'à la cause qui fait franchir 80 % de cumul sont mises en avant
 * (« les quelques causes qui expliquent l'essentiel »), les suivantes sont atténuées.
 * Props : causes = [{ cause, duree_min, pct, pct_cumule }] déjà triées par durée décroissante.
 */
import { computed } from 'vue'

const props = defineProps({
  causes: { type: Array, default: () => [] },
})

const L = 720, H = 300
const marge = { g: 54, d: 46, h: 16, b: 78 }
const largeurUtile = L - marge.g - marge.d
const hauteurUtile = H - marge.h - marge.b

const maxDuree = computed(() => Math.max(1, ...props.causes.map(c => c.duree_min)))
// Graduation « ronde » de l'axe des durées (4 intervalles).
const maxAxe = computed(() => {
  const brut = maxDuree.value
  const pas = Math.pow(10, Math.floor(Math.log10(brut)))
  const norm = brut / pas
  const arrondi = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10
  return arrondi * pas
})

const yDuree = v => marge.h + hauteurUtile - (v / maxAxe.value) * hauteurUtile
const yPct = v => marge.h + hauteurUtile - (v / 100) * hauteurUtile

const pas = computed(() => largeurUtile / Math.max(1, props.causes.length))
const largeurBarre = computed(() => Math.min(56, pas.value * 0.62))
const xCentre = i => marge.g + pas.value * i + pas.value / 2

// Index de la première cause qui atteint ou dépasse 80 % : les barres 0..index = « essentiel ».
const indexEssentiel = computed(() => {
  const i = props.causes.findIndex(c => c.pct_cumule >= 80)
  return i === -1 ? props.causes.length - 1 : i
})

const barres = computed(() => props.causes.map((c, i) => ({
  x: xCentre(i) - largeurBarre.value / 2,
  y: yDuree(c.duree_min),
  h: marge.h + hauteurUtile - yDuree(c.duree_min),
  essentiel: i <= indexEssentiel.value,
  libelle: c.cause,
  titre: `${c.cause} : ${c.duree_min} min (${String(c.pct).replace('.', ',')} %), cumul ${String(c.pct_cumule).replace('.', ',')} %`,
  cx: xCentre(i),
})))

const pointsCourbe = computed(() => props.causes.map((c, i) => `${xCentre(i)},${yPct(c.pct_cumule)}`).join(' '))
const graduationsDuree = computed(() => [0, 1, 2, 3, 4].map(k => ({ v: (maxAxe.value / 4) * k, y: yDuree((maxAxe.value / 4) * k) })))
const graduationsPct = [0, 25, 50, 75, 100]

function court(t, n = 14) { return t.length > n ? t.slice(0, n - 1) + '…' : t }
const fmt = v => Math.round(v).toLocaleString('fr-FR')
</script>

<template>
  <svg :viewBox="`0 0 ${L} ${H}`" class="pareto" role="img"
       aria-label="Diagramme de Pareto : durée d'arrêt par cause et pourcentage cumulé">
    <!-- grille + axe des durées (gauche) -->
    <g v-for="g in graduationsDuree" :key="'gd' + g.v">
      <line :x1="marge.g" :x2="L - marge.d" :y1="g.y" :y2="g.y" class="grille" />
      <text :x="marge.g - 8" :y="g.y + 4" class="axe" text-anchor="end">{{ fmt(g.v) }}</text>
    </g>
    <text :x="14" :y="marge.h + hauteurUtile / 2" class="axe-titre" text-anchor="middle"
          :transform="`rotate(-90 14 ${marge.h + hauteurUtile / 2})`">minutes d'arrêt</text>

    <!-- axe des % cumulés (droite) -->
    <g v-for="p in graduationsPct" :key="'gp' + p">
      <text :x="L - marge.d + 8" :y="yPct(p) + 4" class="axe courbe-axe" text-anchor="start">{{ p }} %</text>
    </g>
    <!-- repère 80 % -->
    <line :x1="marge.g" :x2="L - marge.d" :y1="yPct(80)" :y2="yPct(80)" class="repere-80" />

    <!-- barres -->
    <g v-for="(b, i) in barres" :key="'b' + i">
      <rect :x="b.x" :y="b.y" :width="largeurBarre" :height="b.h" rx="3"
            :class="['barre', { attenuee: !b.essentiel }]"><title>{{ b.titre }}</title></rect>
      <text :x="b.cx" :y="b.y - 5" class="valeur" text-anchor="middle">{{ fmt(causes[i].duree_min) }}</text>
      <text :x="b.cx" :y="marge.h + hauteurUtile + 14" class="etiquette" text-anchor="end"
            :transform="`rotate(-30 ${b.cx} ${marge.h + hauteurUtile + 14})`"><title>{{ b.libelle }}</title>{{ court(b.libelle) }}</text>
    </g>

    <!-- courbe cumulée -->
    <polyline v-if="causes.length > 1" :points="pointsCourbe" class="courbe" />
    <g v-for="(c, i) in causes" :key="'pt' + i">
      <circle :cx="xCentre(i)" :cy="yPct(c.pct_cumule)" r="3.5" class="point"><title>{{ barres[i].titre }}</title></circle>
    </g>
  </svg>
</template>

<style scoped>
.pareto { width: 100%; height: auto; display: block; }
.grille { stroke: var(--color-border); stroke-width: 1; }
.axe { font-size: 11px; fill: var(--color-text-muted); }
.axe-titre { font-size: 11px; fill: var(--color-text-muted); }
.courbe-axe { fill: var(--color-orange); }
.barre { fill: var(--color-brand); }
.barre.attenuee { fill: var(--color-brand); opacity: .35; }
.valeur { font-size: 11px; font-weight: 700; fill: var(--color-text); }
.etiquette { font-size: 11px; fill: var(--color-text); }
.courbe { fill: none; stroke: var(--color-orange); stroke-width: 2.5; stroke-linejoin: round; }
.point { fill: var(--color-surface); stroke: var(--color-orange); stroke-width: 2.5; }
.repere-80 { stroke: var(--color-orange); stroke-width: 1; stroke-dasharray: 5 4; opacity: .7; }
</style>
