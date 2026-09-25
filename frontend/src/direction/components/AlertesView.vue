<script setup>
/**
 * AlertesView.vue -- alertes actives. *** REVU 2026-09-24 *** : recherche (ligne, texte, type),
 * filtres par type et gravité, et regroupement par ligne -- 3 alertes x 47 lignes noyaient
 * l'information dans 141 cartes.
 */
import { ref, computed, onMounted } from 'vue'
import apiClient from '@/api/client'
import { RefreshCw, AlertTriangle, Search, ChevronDown, ChevronRight } from 'lucide-vue-next'

const alertes = ref([])
const isLoading = ref(true)
const errorMessage = ref('')
const rafraichissement = ref(false)

const recherche = ref('')
const filtreType = ref('')
const filtreNiveau = ref('')
const groupeParLigne = ref(true)
const depliees = ref(new Set())
const jourChoisi = ref('')   // *** AJOUT 2026-09-25 *** : vide = alertes actives d'aujourd'hui (comportement d'origine)

async function charger() {
  isLoading.value = true
  try {
    const res = await apiClient.get('/alertes', { params: jourChoisi.value ? { jour: jourChoisi.value } : {} })
    alertes.value = res.data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger les alertes.'
  } finally {
    isLoading.value = false
  }
}
onMounted(charger)

async function actualiser() {
  rafraichissement.value = true
  try {
    await apiClient.post('/alertes/run-now')
    await charger()
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || "Échec de l'actualisation."
  } finally {
    rafraichissement.value = false
  }
}

const LABELS_TYPE = {
  performance: 'Performance',
  silence_scan: 'Silence de scan',
  ralentissement_progressif: 'Ralentissement',
  partielle_non_justifiee: 'Traçabilité',
  of_termine_scan: 'Traçabilité',
}
const libelleType = t => LABELS_TYPE[t] || t
const norm = t => String(t ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()

const typesDisponibles = computed(() => [...new Set(alertes.value.map(a => libelleType(a.type)))].sort())

// Recherche : « ccl04 » ou « ccl04 ccl05 » (plusieurs termes = plusieurs lignes possibles), texte du
// message ou type. Accents et casse ignorés.
const alertesFiltrees = computed(() => {
  const termes = norm(recherche.value).split(/[\s,;]+/).filter(Boolean)
  return alertes.value.filter(a => {
    if (filtreType.value && libelleType(a.type) !== filtreType.value) return false
    if (filtreNiveau.value && a.niveau !== filtreNiveau.value) return false
    if (!termes.length) return true
    const meule = norm(`${a.ligne_code || ''} ${a.message} ${libelleType(a.type)}`)
    return termes.some(t => meule.includes(t))
  })
})

const RANG_NIVEAU = { rouge: 0, orange: 1 }
const groupes = computed(() => {
  const par = new Map()
  for (const a of alertesFiltrees.value) {
    const cle = a.ligne_code || 'Sans ligne'
    if (!par.has(cle)) par.set(cle, [])
    par.get(cle).push(a)
  }
  return [...par.entries()]
    .map(([ligne, items]) => ({
      ligne, items,
      niveau: items.some(i => i.niveau === 'rouge') ? 'rouge' : 'orange',
    }))
    .sort((x, y) => (RANG_NIVEAU[x.niveau] ?? 9) - (RANG_NIVEAU[y.niveau] ?? 9) || x.ligne.localeCompare(y.ligne))
})
const estDeplie = g => depliees.value.has(g.ligne)
function basculer(g) {
  const s = new Set(depliees.value)
  s.has(g.ligne) ? s.delete(g.ligne) : s.add(g.ligne)
  depliees.value = s
}
const toutDeplier = () => { depliees.value = new Set(groupes.value.map(g => g.ligne)) }
const toutReplier = () => { depliees.value = new Set() }
const dateFr = iso => new Date(iso).toLocaleString('fr-FR')
</script>

<template>
  <div class="alertes-view">
    <header class="page-header">
      <div>
        <h1>Alertes</h1>
        <p class="subtitle">Performance, rythme de scan et traçabilité</p>
      </div>
      <div class="header-actions">
        <!-- *** AJOUT 2026-09-25 *** : consulter les alertes d'un jour passé (créées ce jour-là,
             résolues ou non -- pas de reconstitution fiable de "ce qui était ouvert à telle heure",
             cf. avertissement backend). "Actualiser maintenant" n'a de sens que pour aujourd'hui. -->
        <div class="date-choisie">
          <label for="alertes-jour">Jour :</label>
          <input id="alertes-jour" type="date" v-model="jourChoisi" :max="new Date().toISOString().slice(0, 10)" @change="charger" />
          <button v-if="jourChoisi" class="btn secondary" @click="jourChoisi = ''; charger()">Aujourd'hui</button>
        </div>
        <button v-if="!jourChoisi" class="btn primary" :disabled="rafraichissement" @click="actualiser">
          <RefreshCw :size="16" /> {{ rafraichissement ? 'Actualisation…' : 'Actualiser maintenant' }}
        </button>
      </div>
    </header>

    <p v-if="jourChoisi" class="hint">
      Alertes <strong>créées</strong> le {{ jourChoisi }} (résolues incluses). Faute de date de résolution en base, ceci ne reconstitue pas
      ce qui était encore ouvert à une heure précise de ce jour-là.
    </p>
    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>
    <p v-else-if="!alertes.length" class="empty">{{ jourChoisi ? "Aucune alerte créée ce jour-là." : "Aucune alerte active — tout est calme." }}</p>


    <template v-else>
      <div class="filtres">
        <label class="recherche">
          <Search :size="16" />
          <input v-model="recherche" type="search" placeholder="Rechercher une ligne (ex. CCL04, CDF01), un type ou un mot du message…" />
        </label>
        <select v-model="filtreType" title="Filtrer par type d'alerte">
          <option value="">Tous les types</option>
          <option v-for="t in typesDisponibles" :key="t" :value="t">{{ t }}</option>
        </select>
        <select v-model="filtreNiveau" title="Filtrer par gravité">
          <option value="">Toutes les gravités</option>
          <option value="rouge">Critiques</option>
          <option value="orange">À surveiller</option>
        </select>
        <div class="modes" role="group" aria-label="Affichage">
          <button :class="['mode', { actif: groupeParLigne }]" @click="groupeParLigne = true">Par ligne</button>
          <button :class="['mode', { actif: !groupeParLigne }]" @click="groupeParLigne = false">Liste</button>
        </div>
      </div>

      <p class="compteur">
        {{ alertesFiltrees.length }} alerte(s) sur {{ groupes.length }} ligne(s)
        <template v-if="alertesFiltrees.length !== alertes.length"> — filtré sur {{ alertes.length }}</template>
        <template v-if="groupeParLigne && groupes.length > 1">
          · <button class="lien" @click="toutDeplier">tout déplier</button> · <button class="lien" @click="toutReplier">tout replier</button>
        </template>
      </p>

      <p v-if="!alertesFiltrees.length" class="empty">Aucune alerte ne correspond à ces filtres.</p>

      <!-- Par ligne : une ligne, un bloc dépliable -->
      <ul v-else-if="groupeParLigne" class="groupes">
        <li v-for="g in groupes" :key="g.ligne" :class="['groupe', `niveau-${g.niveau}`]">
          <button class="groupe-tete" :aria-expanded="estDeplie(g)" @click="basculer(g)">
            <component :is="estDeplie(g) ? ChevronDown : ChevronRight" :size="16" />
            <span class="alerte-ligne">{{ g.ligne }}</span>
            <span class="groupe-resume">{{ g.items.length }} alerte(s) — {{ [...new Set(g.items.map(i => libelleType(i.type)))].join(', ') }}</span>
          </button>
          <ul v-if="estDeplie(g)" class="alertes-list interne">
            <li v-for="a in g.items" :key="a.id" :class="['alerte-item', `niveau-${a.niveau}`]">
              <AlertTriangle :size="18" />
              <div class="alerte-content">
                <span class="alerte-type">{{ libelleType(a.type) }}</span>
                <div class="alerte-message">{{ a.message }}</div>
                <div class="alerte-date">{{ dateFr(a.created_at) }}</div>
              </div>
            </li>
          </ul>
        </li>
      </ul>

      <!-- Liste plate -->
      <ul v-else class="alertes-list">
        <li v-for="a in alertesFiltrees" :key="a.id" :class="['alerte-item', `niveau-${a.niveau}`]">
          <AlertTriangle :size="18" />
          <div class="alerte-content">
            <div class="alerte-top">
              <span class="alerte-type">{{ libelleType(a.type) }}</span>
              <span v-if="a.ligne_code" class="alerte-ligne">{{ a.ligne_code }}</span>
            </div>
            <div class="alerte-message">{{ a.message }}</div>
            <div class="alerte-date">{{ dateFr(a.created_at) }}</div>
          </div>
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.alertes-view { padding: var(--space-6); overflow-y: auto; height: 100%; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: var(--space-6); }
.page-header h1 { margin: 0; font-size: var(--font-size-2xl); }
.header-actions { display: flex; align-items: center; gap: var(--space-3); }
.date-choisie { display: flex; align-items: center; gap: var(--space-2); font-size: var(--font-size-sm); }
.hint { color: var(--color-text-muted); font-size: var(--font-size-sm); margin: 0 0 var(--space-3); }
.subtitle { color: var(--color-text-muted); margin: 4px 0 0; }

.btn {
  display: inline-flex; align-items: center; gap: var(--space-2); border: none; border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-4); font-weight: 700; cursor: pointer;
  background: var(--color-brand); color: var(--color-text-inverse);
}
.btn:disabled { opacity: 0.6; cursor: not-allowed; }

.error-banner { background: var(--color-rouge-bg); color: var(--color-rouge); padding: var(--space-3); border-radius: var(--radius-md); }
.loading, .empty { color: var(--color-text-muted); }

.alertes-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-3); }
.alerte-item {
  display: flex; gap: var(--space-3); background: var(--color-surface); border: 1px solid var(--color-border);
  border-left: 4px solid var(--color-orange); border-radius: var(--radius-md); padding: var(--space-3) var(--space-4);
  box-shadow: var(--shadow-card);
}
.alerte-item.niveau-rouge { border-left-color: var(--color-rouge); }
.alerte-item.niveau-rouge svg { color: var(--color-rouge); }
.alerte-item.niveau-orange svg { color: var(--color-orange); }

.alerte-top { display: flex; gap: var(--space-2); align-items: center; margin-bottom: 2px; }
.alerte-type { font-size: var(--font-size-xs); font-weight: 700; text-transform: uppercase; color: var(--color-text-muted); }
.alerte-ligne { font-size: var(--font-size-xs); font-weight: 700; background: var(--color-brand-light); color: var(--color-brand-dark); padding: 1px 8px; border-radius: 999px; }
.alerte-message { font-size: var(--font-size-sm); }
.alerte-date { font-size: var(--font-size-xs); color: var(--color-text-muted); margin-top: 2px; }

.filtres { display: flex; gap: var(--space-3); flex-wrap: wrap; align-items: center; margin-bottom: var(--space-3); }
.recherche { flex: 1 1 320px; display: flex; align-items: center; gap: var(--space-2); height: 40px; padding: 0 var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); color: var(--color-text-muted); }
.recherche input { flex: 1; border: none; outline: none; background: transparent; font-family: inherit; font-size: var(--font-size-sm); color: var(--color-text); }
.filtres select { height: 40px; padding: 0 var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); font-family: inherit; }
.modes { display: inline-flex; border: 1px solid var(--color-border); border-radius: var(--radius-md); overflow: hidden; }
.mode { border: none; background: var(--color-surface); padding: 0 var(--space-3); height: 40px; font-weight: 600; cursor: pointer; color: var(--color-text-muted); }
.mode.actif { background: var(--color-brand); color: var(--color-text-inverse); }
.compteur { color: var(--color-text-muted); font-size: var(--font-size-sm); margin: 0 0 var(--space-3); }
.lien { border: none; background: none; color: var(--color-brand); cursor: pointer; padding: 0; font: inherit; text-decoration: underline; }

.groupes { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-2); }
.groupe { background: var(--color-surface); border: 1px solid var(--color-border); border-left: 4px solid var(--color-orange); border-radius: var(--radius-md); }
.groupe.niveau-rouge { border-left-color: var(--color-rouge); }
.groupe-tete { display: flex; align-items: center; gap: var(--space-3); width: 100%; border: none; background: none; padding: var(--space-3) var(--space-4); cursor: pointer; text-align: left; font-family: inherit; }
.groupe-resume { color: var(--color-text-muted); font-size: var(--font-size-sm); }
.alertes-list.interne { padding: 0 var(--space-3) var(--space-3); }
</style>