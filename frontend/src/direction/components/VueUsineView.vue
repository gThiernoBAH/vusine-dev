<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import apiClient from '@/api/client'
import LigneCard from './LigneCard.vue'
import {
  CheckCircle2, AlertTriangle, TrendingDown, PauseCircle, Percent, Search,
  // *** AJOUT 2026-09-25 *** : un badge icône/couleur par section (rail de gauche), à la place du simple nom.
  Droplet, Droplets, Waves, Sparkles, Boxes, Package, Wrench, Tag, PackageOpen, CircleDot, SprayCan, Truck, Brush, Circle,
} from 'lucide-vue-next'

// Mapping volontairement approximatif ("représente plus ou moins son nom", demande explicite) : le but est
// une identification visuelle rapide par couleur+icône dans le rail, pas une taxonomie précise du métier.
// Clé en MAJUSCULES pour matcher les noms de section tels qu'Odoo les fournit ; secours générique sinon.
const STYLE_SECTIONS = {
  CLARIFIANT: { icone: Droplet, couleur: '#0ea5e9' },
  DEFRISANT: { icone: Waves, couleur: '#8b5cf6' },
  DENTIFRICE: { icone: Sparkles, couleur: '#06b6d4' },
  DIVERS: { icone: Boxes, couleur: '#64748b' },
  EMBALLAGE: { icone: Package, couleur: '#d97706' },
  ENTRETIEN: { icone: Wrench, couleur: '#475569' },
  ETIQUETTAGE: { icone: Tag, couleur: '#db2777' },
  HYDRATANT: { icone: Droplets, couleur: '#3b82f6' },
  MANCHONNAGE: { icone: PackageOpen, couleur: '#ea580c' },
  'MOULES SOUFFLAGE': { icone: CircleDot, couleur: '#0d9488' },
  PARFUM: { icone: SprayCan, couleur: '#c026d3' },
  POMMADE: { icone: Droplet, couleur: '#16a34a' },
  RAVITAILLEMENT: { icone: Truck, couleur: '#7c3aed' },
  SAVON: { icone: Droplet, couleur: '#059669' },
  SERIGRAPHIE: { icone: Brush, couleur: '#9333ea' },
  TALC: { icone: CircleDot, couleur: '#78716c' },
}
const STYLE_DEFAUT = { icone: Circle, couleur: '#94a3b8' }
const styleSection = nom => STYLE_SECTIONS[(nom || '').trim().toUpperCase()] || STYLE_DEFAUT

const emit = defineEmits(['select-ligne'])

const resume = ref(null)
const lignes = ref([])
const isLoading = ref(true)
const errorMessage = ref('')
let pollHandle = null

// --- Date consultée (*** AJOUT 2026-09-18 ***) -- défaut : aujourd'hui, au format
// YYYY-MM-DD attendu par <input type="date"> et par l'API (query param `jour`). Un
// jour passé est lu depuis le snapshot figé côté backend -- jamais de polling dessus,
// ça ne changera plus une fois la journée close. --------------------------------
function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const jourSelectionne = ref(todayIso())
const estAujourdhui = computed(() => jourSelectionne.value === todayIso())

// --- Recherche / filtre / tri (100% client -- même volume que l'admin Lignes,
// pas besoin de pousser ça côté backend) --------------------------------------
const recherche = ref('')
const filtreSection = ref('toutes')
const filtreStatut = ref('tous')  // 'tous' | 'vert' | 'orange' | 'rouge' | 'demarrage' | 'arret' | 'inactif'
const tri = ref('code')  // 'code' | 'performance_asc' | 'performance_desc' | 'retard_desc'

// --- *** AJOUT 2026-09-24 *** : affichage à plat OU par section, en densité détaillée OU compacte.
// Choix mémorisés dans le navigateur de la personne (localStorage, échec toléré). ---------------
function lirePref(cle, defaut, valides) {
  try { const v = localStorage.getItem(cle); return valides.includes(v) ? v : defaut } catch { return defaut }
}
function ecrirePref(cle, v) { try { localStorage.setItem(cle, v) } catch { /* stockage indisponible */ } }
const modeAffichage = ref(lirePref('vueusine_mode', 'plat', ['plat', 'sections']))   // 'plat' | 'sections'
const densite = ref(lirePref('vueusine_densite', 'detaillee', ['detaillee', 'compacte']))
watch(modeAffichage, v => ecrirePref('vueusine_mode', v))
watch(densite, v => ecrirePref('vueusine_densite', v))

async function fetchVueUsine() {
  try {
    const res = await apiClient.get('/dashboard/vue_usine', { params: { jour: jourSelectionne.value } })
    resume.value = res.data.resume
    lignes.value = res.data.lignes
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger la Vue Usine.'
  } finally {
    isLoading.value = false
  }
}

function gererPolling() {
  if (pollHandle) { clearInterval(pollHandle); pollHandle = null }
  // Polling léger (5-10s) -- décision d'architecture actée : pas de WebSocket/Redis en
  // V1. Uniquement pour aujourd'hui : un jour passé ne change plus, inutile de le repoller.
  if (estAujourdhui.value) {
    pollHandle = setInterval(fetchVueUsine, 7000)
  }
}

onMounted(() => {
  fetchVueUsine()
  gererPolling()
})

watch(jourSelectionne, () => {
  isLoading.value = true
  fetchVueUsine()
  gererPolling()
})

onUnmounted(() => {
  if (pollHandle) clearInterval(pollHandle)
})

const sectionsConnues = computed(() => {
  const set = new Set(lignes.value.map(l => l.section_nom).filter(Boolean))
  return Array.from(set).sort((a, b) => a.localeCompare(b))
})

const lignesFiltrees = computed(() => {
  const q = recherche.value.trim().toLowerCase()
  let resultat = lignes.value.filter(l => {
    if (q && !`${l.code} ${l.nom}`.toLowerCase().includes(q)) return false
    if (filtreSection.value !== 'toutes' && l.section_nom !== filtreSection.value) return false
    if (filtreStatut.value !== 'tous' && l.statut !== filtreStatut.value) return false
    return true
  })

  resultat = [...resultat].sort((a, b) => {
    switch (tri.value) {
      case 'performance_asc':
        return (a.performance_pct ?? -1) - (b.performance_pct ?? -1)
      case 'performance_desc':
        return (b.performance_pct ?? -1) - (a.performance_pct ?? -1)
      case 'retard_desc':
        return (b.retard_min ?? 0) - (a.retard_min ?? 0)
      default:
        return String(a.code).localeCompare(String(b.code))
    }
  })

  return resultat
})

// --- Sections : synthèse (colonne de gauche) et regroupement des tuiles ------------------------------
const GRAVITE = { arret: 0, rouge: 1, orange: 2, demarrage: 3, vert: 4, inactif: 5 }
const SANS_SECTION = 'Sans section'
const nomSection = l => l.section_nom || SANS_SECTION

// Calculée sur TOUTES les lignes (pas sur les filtres) : la colonne reste stable quand on filtre.
const statsSections = computed(() => {
  const par = new Map()
  for (const l of lignes.value) {
    const n = nomSection(l)
    if (!par.has(n)) par.set(n, { nom: n, nb: 0, reel: 0, theorique: 0, pire: 'inactif', problemes: 0 })
    const a = par.get(n)
    a.nb += 1
    if (l.theorique > 0) { a.reel += l.reel || 0; a.theorique += l.theorique }
    if ((GRAVITE[l.statut] ?? 9) < (GRAVITE[a.pire] ?? 9)) a.pire = l.statut
    if (['arret', 'rouge', 'orange'].includes(l.statut)) a.problemes += 1
  }
  return [...par.values()]
    .map(a => ({ ...a, pct: a.theorique > 0 ? Math.round((a.reel / a.theorique) * 100) : null }))
    .sort((x, y) => (x.nom === SANS_SECTION) - (y.nom === SANS_SECTION) || x.nom.localeCompare(y.nom))
})

const groupesAffiches = computed(() => {
  const par = new Map()
  for (const l of lignesFiltrees.value) {
    const n = nomSection(l)
    if (!par.has(n)) par.set(n, [])
    par.get(n).push(l)
  }
  const stats = new Map(statsSections.value.map(s => [s.nom, s]))
  return [...par.entries()]
    .sort((a, b) => (a[0] === SANS_SECTION) - (b[0] === SANS_SECTION) || a[0].localeCompare(b[0]))
    .map(([nom, items]) => ({ nom, items, stats: stats.get(nom) }))
})
function choisirSection(nom) { filtreSection.value = filtreSection.value === nom ? 'toutes' : nom }
</script>

<template>
  <div class="vue-usine">
    <header class="page-header">
      <div>
        <h1>Vue Usine</h1>
        <p class="subtitle">
          {{ estAujourdhui ? 'Production en temps réel' : 'Consultation historique — figée, pas de rafraîchissement' }}
        </p>
      </div>
      <label class="date-picker">
        <span>Jour</span>
        <input type="date" v-model="jourSelectionne" :max="todayIso()" />
      </label>
    </header>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <div v-if="resume" class="resume-cards">
      <div class="resume-card">
        <Percent :size="20" class="icon icon-brand" />
        <div>
          <div class="resume-value">{{ resume.performance_usine_pct !== null ? resume.performance_usine_pct + '%' : '—' }}</div>
          <div class="resume-label">Performance usine</div>
        </div>
      </div>
      <div class="resume-card">
        <CheckCircle2 :size="20" class="icon icon-vert" />
        <div>
          <div class="resume-value">{{ resume.lignes_vertes }}</div>
          <div class="resume-label">Vertes (≥95%)</div>
        </div>
      </div>
      <div class="resume-card">
        <TrendingDown :size="20" class="icon icon-orange" />
        <div>
          <div class="resume-value">{{ resume.lignes_orange }}</div>
          <div class="resume-label">Orange (80-94%)</div>
        </div>
      </div>
      <div class="resume-card">
        <AlertTriangle :size="20" class="icon icon-rouge" />
        <div>
          <div class="resume-value">{{ resume.lignes_rouges }}</div>
          <div class="resume-label">Rouges (&lt;80%)</div>
        </div>
      </div>
      <div class="resume-card">
        <PauseCircle :size="20" class="icon icon-arret" />
        <div>
          <div class="resume-value">{{ resume.lignes_a_larret }}</div>
          <div class="resume-label">Lignes à l'arrêt</div>
        </div>
      </div>
    </div>

    <div class="toolbar">
      <div class="search-wrap">
        <Search :size="16" class="search-icon" />
        <input v-model="recherche" type="search" placeholder="Rechercher par code ou nom…" class="search-input" />
      </div>
      <select v-model="filtreSection" class="filter-select">
        <option value="toutes">Toutes les sections</option>
        <option v-for="s in sectionsConnues" :key="s" :value="s">{{ s }}</option>
      </select>
      <select v-model="filtreStatut" class="filter-select">
        <option value="tous">Tous les statuts</option>
        <option value="vert">Vert</option>
        <option value="orange">Orange</option>
        <option value="rouge">Rouge</option>
        <option value="demarrage">Démarrage</option>
        <option value="arret">À l'arrêt</option>
        <option value="inactif">Inactif</option>
      </select>
      <select v-model="tri" class="filter-select">
        <option value="code">Trier : code</option>
        <option value="performance_desc">Trier : performance ↓</option>
        <option value="performance_asc">Trier : performance ↑</option>
        <option value="retard_desc">Trier : retard ↓</option>
      </select>
      <div class="segment" role="group" aria-label="Mode d'affichage">
        <button :class="['seg', { actif: modeAffichage === 'plat' }]" title="Toutes les lignes à plat" @click="modeAffichage = 'plat'">À plat</button>
        <button :class="['seg', { actif: modeAffichage === 'sections' }]" title="Regroupées par section (atelier)" @click="modeAffichage = 'sections'">Par section</button>
      </div>
      <div class="segment" role="group" aria-label="Densité">
        <button :class="['seg', { actif: densite === 'detaillee' }]" title="Tuiles détaillées" @click="densite = 'detaillee'">Détaillé</button>
        <button :class="['seg', { actif: densite === 'compacte' }]" title="Tuiles compactes : toutes les lignes d'un coup d'œil" @click="densite = 'compacte'">Compact</button>
      </div>
      <span class="result-count">{{ lignesFiltrees.length }} / {{ lignes.length }} lignes</span>
    </div>

    <div v-if="isLoading" class="loading">Chargement…</div>

    <div v-else :class="['zone', { 'avec-rail': modeAffichage === 'sections' }]">
      <!-- Colonne de sections (dans la page, pas dans la barre latérale) : un clic filtre sur la section -->
      <aside v-if="modeAffichage === 'sections'" class="rail" aria-label="Sections">
        <button :class="['rail-item', { actif: filtreSection === 'toutes' }]" @click="filtreSection = 'toutes'">
          <span class="rail-nom">Toutes les sections</span><span class="rail-nb">{{ lignes.length }}</span>
        </button>
        <button v-for="s in statsSections" :key="s.nom" :class="['rail-item', `pire-${s.pire}`, { actif: filtreSection === s.nom }]" @click="choisirSection(s.nom)"
                :title="`${s.nom} : ${s.nb} ligne(s)${s.problemes ? ', ' + s.problemes + ' à surveiller' : ''}`">
          <span class="rail-badge" :style="{ '--badge-couleur': styleSection(s.nom).couleur }" aria-hidden="true">
            <component :is="styleSection(s.nom).icone" :size="15" />
          </span>
          <span class="rail-point" aria-hidden="true"></span>
          <span class="rail-nom">{{ s.nom }}</span>
          <span class="rail-pct">{{ s.pct !== null ? s.pct + '%' : '—' }}</span>
          <span class="rail-nb">{{ s.nb }}</span>
        </button>
      </aside>

      <div class="contenu">
        <!-- À plat -->
        <div v-if="modeAffichage === 'plat'" :class="['lignes-grid', densite]">
          <LigneCard v-for="ligne in lignesFiltrees" :key="ligne.id" :ligne="ligne" :compact="densite === 'compacte'"
                     @select="id => emit('select-ligne', id, jourSelectionne)" />
        </div>

        <!-- Par section : un en-tête (nom, performance, lignes à surveiller) puis ses tuiles -->
        <section v-else v-for="g in groupesAffiches" :key="g.nom" class="section-bloc">
          <header class="section-tete">
            <h2>{{ g.nom }}</h2>
            <span class="section-stats">
              {{ g.stats.nb }} ligne(s) · performance {{ g.stats.pct !== null ? g.stats.pct + '%' : '—' }}
              <template v-if="g.stats.problemes"> · <strong class="a-surveiller">{{ g.stats.problemes }} à surveiller</strong></template>
            </span>
          </header>
          <div :class="['lignes-grid', densite]">
            <LigneCard v-for="ligne in g.items" :key="ligne.id" :ligne="ligne" :compact="densite === 'compacte'"
                       @select="id => emit('select-ligne', id, jourSelectionne)" />
          </div>
        </section>

        <p v-if="!lignesFiltrees.length" class="empty">Aucune ligne ne correspond à ces filtres.</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.vue-usine {
  padding: var(--space-6);
  overflow-y: auto;
  height: 100%;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.page-header h1 {
  margin: 0;
  font-size: var(--font-size-2xl);
}

.date-picker {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}
.date-picker input {
  height: 36px;
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  font-family: inherit;
  background: var(--color-surface);
}

.subtitle {
  color: var(--color-text-muted);
  margin: 4px 0 var(--space-6);
}

.error-banner {
  background: var(--color-rouge-bg);
  color: var(--color-rouge);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
}

.resume-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.resume-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  box-shadow: var(--shadow-card);
}

.icon-vert { color: var(--color-vert); }
.icon-orange { color: var(--color-orange); }
.icon-rouge { color: var(--color-rouge); }
.icon-arret { color: var(--color-arret); }
.icon-brand { color: var(--color-brand); }

.resume-value {
  font-size: var(--font-size-xl);
  font-weight: 800;
}

.resume-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.toolbar {
  display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); flex-wrap: wrap;
}
.search-wrap { position: relative; flex: 1; min-width: 220px; }
.search-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--color-text-muted); pointer-events: none; }
.search-input {
  width: 100%; height: 36px; padding: 0 var(--space-3) 0 34px;
  border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: var(--font-size-sm);
}
.filter-select {
  height: 36px; padding: 0 var(--space-2); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); font-size: var(--font-size-sm); background: var(--color-surface);
}
.result-count { font-size: var(--font-size-xs); color: var(--color-text-muted); white-space: nowrap; }

.loading {
  color: var(--color-text-muted);
  padding: var(--space-6) 0;
}

.empty { color: var(--color-text-muted); grid-column: 1 / -1; text-align: center; padding: var(--space-6) 0; }

.lignes-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--space-4); }
.lignes-grid.compacte { grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: var(--space-2); }

/* *** AJOUT 2026-09-24 *** : bascules d'affichage, colonne de sections, blocs par section */
.segment { display: inline-flex; border: 1px solid var(--color-border); border-radius: var(--radius-md); overflow: hidden; }
.seg { height: 36px; padding: 0 var(--space-3); border: none; background: var(--color-surface); font: inherit; font-size: var(--font-size-sm); font-weight: 600; color: var(--color-text-muted); cursor: pointer; }
.seg.actif { background: var(--color-brand); color: var(--color-text-inverse); }

.zone { display: block; }
.zone.avec-rail { display: grid; grid-template-columns: 250px 1fr; gap: var(--space-4); align-items: start; }
.rail { position: sticky; top: 0; display: flex; flex-direction: column; gap: var(--space-1); background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: var(--space-2); max-height: 70vh; overflow-y: auto; }
.rail-item { display: flex; align-items: center; gap: var(--space-2); width: 100%; border: none; background: none; text-align: left; padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); cursor: pointer; font: inherit; font-size: var(--font-size-sm); }
.rail-item:hover { background: var(--color-brand-light); }
.rail-item.actif { background: var(--color-brand); color: var(--color-text-inverse); }
.rail-nom { flex: 1; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rail-pct { font-weight: 700; }
.rail-nb { font-size: var(--font-size-xs); opacity: .7; min-width: 20px; text-align: right; }
/* *** AJOUT 2026-09-25 *** : badge icône/couleur par section, à la place du simple nom texte. */
.rail-badge {
  width: 26px; height: 26px; border-radius: var(--radius-md); flex-shrink: 0;
  display: grid; place-items: center; background: color-mix(in srgb, var(--badge-couleur) 16%, transparent); color: var(--badge-couleur);
}
.rail-item.actif .rail-badge { background: color-mix(in srgb, white 25%, transparent); color: var(--color-text-inverse); }
.rail-point { width: 8px; height: 8px; border-radius: 50%; background: var(--color-border); flex-shrink: 0; }
.pire-vert .rail-point { background: var(--color-vert); }
.pire-orange .rail-point { background: var(--color-orange); }
.pire-rouge .rail-point, .pire-arret .rail-point { background: var(--color-rouge); }
.pire-demarrage .rail-point { background: #3B82F6; }
.section-bloc { margin-bottom: var(--space-6); }
.section-tete { display: flex; align-items: baseline; gap: var(--space-3); flex-wrap: wrap; margin-bottom: var(--space-3); }
.section-tete h2 { margin: 0; font-size: var(--font-size-lg); }
.section-stats { color: var(--color-text-muted); font-size: var(--font-size-sm); }
.a-surveiller { color: var(--color-rouge); }
@media (max-width: 900px) { .zone.avec-rail { grid-template-columns: 1fr; } .rail { position: static; max-height: none; flex-direction: row; flex-wrap: wrap; } }
</style>