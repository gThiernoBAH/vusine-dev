<script setup>
/**
 * AndonView.vue -- écran Andon : TV d'atelier, lecture seule, aucune interaction requise.
 * *** AJOUT 2026-09-24 (Palier 0), REFONDU le même jour d'après la maquette du client ***
 *
 * Principes :
 *  - Les PROBLÈMES d'abord : le tri vient du serveur (arrêt, rouge, orange, puis le reste).
 *  - Lisible de loin : gros caractères, statut écrit en toutes lettres (jamais la couleur seule),
 *    contraste élevé sur fond bleu nuit.
 *  - Tient à l'échelle : l'usine a ~90 lignes, dont beaucoup sans production prévue. Les lignes
 *    sans production sortent de la grille (simple compteur) ; les autres sont réparties en PAGES qui
 *    tournent toutes les 15 s si elles ne tiennent pas sur l'écran.
 *  - Plusieurs TV : `/andon?section=SAVON` affiche un seul atelier (ou un compte « Écran atelier »
 *    limité à une section). `?rotation=0` fige la page 1, `?rotation=30` change la durée (secondes).
 *  - Résilient : une coupure réseau ne vide JAMAIS l'écran (dernières données + bandeau).
 *  - Autonome : écran maintenu allumé (Wake Lock, HTTPS requis), rechargement complet toutes les
 *    12 h, reprise de session après redémarrage du navigateur (cf. api/session.js).
 *  - Aucun nom de personne, jamais (règle « rien de nominatif à l'atelier »).
 * Sert aussi d'aperçu aux comptes direction (menu « Écran Andon ») : un bouton Quitter apparaît alors.
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import apiClient from '@/api/client'
import { AlertTriangle, Clock, CheckCircle2, PauseCircle } from 'lucide-vue-next'

const router = useRouter()
const route = useRoute()
const user = JSON.parse(sessionStorage.getItem('user') || '{}')
const estKiosque = user.user_type === 'kiosque'

const POLL_MS = 10_000
const PERIME_APRES_MS = 45_000
const RECHARGEMENT_APRES_MS = 12 * 3600 * 1000
const demarrage = Date.now()

const sectionDemandee = (route?.query?.section || '').toString().trim()
const rotationS = (() => {
  const brut = route?.query?.rotation
  const v = Number(brut)
  return brut !== undefined && Number.isFinite(v) ? Math.max(0, v) : 15
})()

const data = ref(null)
const derniereMajOk = ref(null)
const enErreur = ref(false)
const maintenant = ref(new Date())
const controlesVisibles = ref(false)
const pleinEcran = ref(false)
const page = ref(0)
const capacite = ref(24)
const colonnes = ref(6)
const zoneH = ref(0)
const grille = ref(null)
const perfPrecedente = ref({})   // *** AJOUT 2026-09-25 *** : { [ligne_id]: performance_pct } du poll précédent, pour la flèche de tendance

let pollHandle = null
let horlogeHandle = null
let rotationHandle = null
let masquerHandle = null
let observateur = null
let enCours = false
let wakeLock = null

async function charger() {
  if (enCours) return  // jamais deux requêtes en parallèle sur un réseau lent
  enCours = true
  try {
    const params = sectionDemandee ? { section: sectionDemandee } : {}
    const res = await apiClient.get('/dashboard/andon', { params })
    // *** AJOUT 2026-09-25 *** : mémorise le performance_pct AVANT écrasement (flèche de tendance).
    if (data.value?.lignes) {
      const snap = {}
      for (const l of data.value.lignes) snap[l.id] = l.performance_pct
      perfPrecedente.value = snap
    }
    data.value = res.data
    derniereMajOk.value = new Date()
    enErreur.value = false
    if (Date.now() - demarrage > RECHARGEMENT_APRES_MS) window.location.reload()
  } catch {
    enErreur.value = true  // on GARDE data : l'écran reste affiché, bandeau d'alerte en plus
  } finally {
    enCours = false
  }
}

async function verrouillerEcran() {
  try {
    if ('wakeLock' in navigator) wakeLock = await navigator.wakeLock.request('screen')
  } catch { /* refusé (HTTP non sécurisé, batterie faible, onglet masqué) : non bloquant */ }
}
function surVisibilite() {
  if (document.visibilityState === 'visible') { verrouillerEcran(); charger() }
}
function surPleinEcran() { pleinEcran.value = !!document.fullscreenElement }

// Nombre de tuiles qui tiennent réellement dans la zone : colonnes x lignes selon la taille de l'écran.
// *** REVU 2026-09-24 (capture d'écran de l'Andon) *** : la hauteur de tuile n'est plus fixe (150 px rognait le
// statut, la durée d'arrêt et « 101 % »). Elle est calculée pour REMPLIR la zone selon le nombre de tuiles de
// la page, entre un minimum lisible et un maximum raisonnable ; le nombre de colonnes suit le nombre de lignes.
const TUILE_MIN_L = 290
const TUILE_H_MIN = 190
const TUILE_H_MAX = 300
const ECART = 14
function mesurerGrille() {
  const el = grille.value
  if (!el || !el.clientWidth || !el.clientHeight) return
  const cols = Math.max(2, Math.floor((el.clientWidth + ECART) / (TUILE_MIN_L + ECART)))
  const rows = Math.max(1, Math.floor((el.clientHeight + ECART) / (TUILE_H_MIN + ECART)))
  colonnes.value = cols
  zoneH.value = el.clientHeight
  capacite.value = cols * rows
}
// Colonnes équilibrées : 11 tuiles sur 5 colonnes max = 4 + 4 + 3, pas 5 + 5 + 1 (une tuile orpheline).
const colonnesEff = computed(() => {
  const n = lignesPage.value.length || 1
  const rangees = Math.ceil(n / Math.max(1, Math.min(colonnes.value, n)))
  return Math.max(1, Math.ceil(n / rangees))
})
const hauteurTuile = computed(() => {
  if (!zoneH.value) return TUILE_H_MIN
  const rangees = Math.max(1, Math.ceil(lignesPage.value.length / colonnesEff.value))
  return Math.min(TUILE_H_MAX, Math.max(TUILE_H_MIN, Math.floor((zoneH.value + ECART) / rangees) - ECART))
})

onMounted(() => {
  charger()
  pollHandle = setInterval(charger, POLL_MS)
  horlogeHandle = setInterval(() => { maintenant.value = new Date() }, 1000)
  if (rotationS > 0) {
    rotationHandle = setInterval(() => { if (nbPages.value > 1) page.value = (page.value + 1) % nbPages.value }, rotationS * 1000)
  }
  verrouillerEcran()
  document.addEventListener('visibilitychange', surVisibilite)
  document.addEventListener('fullscreenchange', surPleinEcran)
  if (typeof ResizeObserver !== 'undefined' && grille.value) {
    observateur = new ResizeObserver(mesurerGrille)
    observateur.observe(grille.value)
  }
  mesurerGrille()
})
onUnmounted(() => {
  clearInterval(pollHandle); clearInterval(horlogeHandle); clearInterval(rotationHandle); clearTimeout(masquerHandle)
  observateur?.disconnect()
  document.removeEventListener('visibilitychange', surVisibilite)
  document.removeEventListener('fullscreenchange', surPleinEcran)
  try { wakeLock?.release() } catch { /* déjà libéré */ }
})

// Les boutons n'apparaissent qu'au mouvement de la souris, puis disparaissent, et vivent dans le pied de
// page : ils ne recouvrent jamais une tuile.
function montrerControles() {
  controlesVisibles.value = true
  clearTimeout(masquerHandle)
  masquerHandle = setTimeout(() => { controlesVisibles.value = false }, 4000)
}
function basculerPleinEcran() {
  if (document.fullscreenElement) document.exitFullscreen?.()
  else document.documentElement.requestFullscreen?.()
}
function quitter() { router.push('/cockpit/vue-usine') }

const fmt = n => (n === null || n === undefined ? '—' : Math.round(n).toLocaleString('fr-FR'))
const heure = computed(() => maintenant.value.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }))
const dateLongue = computed(() => maintenant.value.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' }))
const heureMaj = computed(() => derniereMajOk.value
  ? derniereMajOk.value.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—')
const donneesFigees = computed(() => enErreur.value
  || (derniereMajOk.value && maintenant.value - derniereMajOk.value > PERIME_APRES_MS))

function duree(min) {
  if (min === null || min === undefined) return ''
  if (min < 60) return `${min} min`
  if (min < 1440) return `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, '0')}`
  return `${Math.floor(min / 1440)} j`
}

const STATUTS = {
  arret: { label: "À l'arrêt", classe: 's-arret', icone: PauseCircle },
  rouge: { label: 'Retard critique', classe: 's-rouge', icone: AlertTriangle },
  orange: { label: 'En retard', classe: 's-orange', icone: Clock },
  demarrage: { label: 'Démarrage', classe: 's-demarrage', icone: Clock },
  vert: { label: 'En production', classe: 's-vert', icone: CheckCircle2 },
  inactif: { label: 'Sans production', classe: 's-inactif', icone: null },
}
const statut = l => STATUTS[l.statut] || { label: l.statut, classe: 's-inactif', icone: null }

/** Ligne du bas de la tuile : le statut en toutes lettres + ce qui l'explique (cause d'arrêt, retard). */
function detailStatut(l) {
  if (l.statut === 'arret') {
    return [l.arret_cause || 'Arrêt en cours', duree(l.arret_depuis_min)].filter(Boolean).join(' · ')
  }
  if ((l.statut === 'rouge' || l.statut === 'orange') && l.retard_min > 0) return `retard ${duree(l.retard_min)}`
  return ''
}

// *** AJOUT 2026-09-25 *** : flèche de tendance -- compare au poll précédent (10 s). Calculée côté
// client (pas de champ serveur dédié) : un delta < 2 points est traité comme stable, sous peine de
// faire clignoter une flèche sur du simple bruit de mesure entre deux scans.
function tendance(l) {
  const avant = perfPrecedente.value[l.id]
  const apres = l.performance_pct
  if (avant === undefined || avant === null || apres === null || apres === undefined) return null
  const delta = apres - avant
  if (Math.abs(delta) < 2) return 'stable'
  return delta > 0 ? 'hausse' : 'baisse'
}
const FLECHES = { hausse: '↗', baisse: '↘', stable: '→' }

const toutesLignes = computed(() => data.value?.lignes ?? [])
// Sans production prévue : sortent de la grille, comptées à part.
const lignesVisibles = computed(() => toutesLignes.value.filter(l => l.statut !== 'inactif'))
const nbSansProduction = computed(() => toutesLignes.value.length - lignesVisibles.value.length)
const nbPages = computed(() => Math.max(1, Math.ceil(lignesVisibles.value.length / capacite.value)))
const lignesPage = computed(() => lignesVisibles.value.slice(page.value * capacite.value, (page.value + 1) * capacite.value))
watch(nbPages, n => { if (page.value >= n) page.value = 0 })

const resume = computed(() => data.value?.resume ?? null)
const perimetre = computed(() => data.value?.section || user.section_scope || sectionDemandee || '')
const plusieursSections = computed(() => new Set(lignesVisibles.value.map(l => l.section_nom)).size > 1)
const nbProblemes = computed(() => (resume.value?.lignes_a_larret ?? 0) + (resume.value?.lignes_rouges ?? 0) + (resume.value?.lignes_orange ?? 0))
// Aucun scan aujourd'hui alors que des retards s'affichent : ce n'est pas une contre-performance, c'est
// l'absence de saisie -- l'écran le dit au lieu d'alarmer.
const aucunScan = computed(() => !!data.value?.aucun_scan_aujourdhui && nbProblemes.value > 0)
const classePerfUsine = computed(() => {
  const p = resume.value?.performance_usine_pct
  if (aucunScan.value || p === null || p === undefined) return 's-inactif'
  return p >= 95 ? 's-vert' : p >= 80 ? 's-orange' : 's-rouge'
})
</script>

<template>
  <div class="andon" @mousemove="montrerControles" @click="montrerControles">
    <header class="barre">
      <div class="titre">
        <span class="marque">SIVOP</span><span class="sep">·</span>Andon
        <span v-if="perimetre" class="perimetre">— {{ perimetre }}</span>
      </div>
      <div class="horloge">
        <div class="heure">{{ heure }}</div>
        <div class="date">{{ dateLongue }}</div>
      </div>
    </header>

    <div v-if="donneesFigees && data" class="bandeau-alerte" role="alert">
      ⚠ Connexion perdue — données figées à {{ heureMaj }}. Nouvelle tentative en cours…
    </div>
    <div v-if="aucunScan" class="bandeau-info" role="status">
      Aucun scan enregistré aujourd'hui : les retards affichés ne sont pas représentatifs.
    </div>

    <section v-if="resume" class="kpis" aria-label="Synthèse">
      <div :class="['kpi', 'kpi-principal', classePerfUsine]">
        <div class="jauge" :style="{ '--pct': Math.min(100, resume.performance_usine_pct ?? 0) }" aria-hidden="true"></div>
        <div class="kpi-texte">
          <span class="kpi-label">Performance{{ perimetre ? '' : ' usine' }}</span>
          <span class="kpi-valeur">{{ resume.performance_usine_pct !== null ? resume.performance_usine_pct + ' %' : '—' }}</span>
          <span class="kpi-detail">{{ fmt(resume.total_reel) }} / {{ fmt(resume.total_theorique) }} pièces</span>
        </div>
      </div>
      <div class="kpi s-arret"><span class="kpi-label">À l'arrêt</span><span class="kpi-valeur">{{ resume.lignes_a_larret }}</span></div>
      <div class="kpi s-rouge"><span class="kpi-label">Retard critique</span><span class="kpi-valeur">{{ resume.lignes_rouges }}</span></div>
      <div class="kpi s-orange"><span class="kpi-label">En retard</span><span class="kpi-valeur">{{ resume.lignes_orange }}</span></div>
      <div class="kpi s-vert"><span class="kpi-label">En production</span><span class="kpi-valeur">{{ resume.lignes_vertes }}</span></div>
      <div class="kpi s-inactif"><span class="kpi-label">Sans production</span><span class="kpi-valeur">{{ nbSansProduction }}</span></div>
    </section>

    <main v-if="data && lignesVisibles.length" ref="grille" class="grille" :style="{ '--colonnes': colonnesEff, '--h-tuile': hauteurTuile + 'px' }">
      <article v-for="l in lignesPage" :key="l.id" :class="['tuile', statut(l).classe]">
        <div class="tuile-haut">
          <span class="code">{{ l.code }}</span>
          <span v-if="l.statut !== 'arret'" class="perf">
            {{ l.performance_pct !== null ? l.performance_pct + ' %' : '—' }}
            <span v-if="tendance(l)" :class="['tendance', tendance(l)]" :aria-label="tendance(l)">{{ FLECHES[tendance(l)] }}</span>
          </span>
        </div>
        <div class="produit">{{ l.produit || l.nom }}</div>
        <div v-if="l.statut !== 'arret' && l.performance_pct !== null && l.performance_pct !== undefined" class="barre-progression">
          <div class="barre-remplissage" :style="{ width: Math.min(100, l.performance_pct) + '%' }"></div>
        </div>
        <div v-if="plusieursSections && l.section_nom" class="section">{{ l.section_nom }}</div>
        <div v-if="l.statut !== 'arret' && l.prevision_fin_poste !== null && l.prevision_fin_poste !== undefined" class="prevision">
          Fin ≈ {{ fmt(l.prevision_fin_poste) }}<template v-if="l.objectif_jour"> / {{ fmt(l.objectif_jour) }}</template>
        </div>
        <div class="bas">
          <span class="statut-texte"><component :is="statut(l).icone" v-if="statut(l).icone" :size="15" class="statut-icone" /> {{ statut(l).label }}</span>
          <span v-if="detailStatut(l)" class="statut-detail">{{ detailStatut(l) }}</span>
        </div>
      </article>
    </main>
    <div v-else-if="data && toutesLignes.length" ref="grille" class="message">
      Aucune production prévue aujourd'hui{{ perimetre ? ' — ' + perimetre : '' }}.
      <div class="message-detail">{{ nbSansProduction }} ligne(s) sans production.</div>
    </div>
    <div v-else-if="data" ref="grille" class="message">Aucune ligne à afficher.</div>
    <div v-else-if="enErreur" ref="grille" class="message message-erreur">Impossible de joindre le serveur — nouvelle tentative en cours…</div>
    <div v-else ref="grille" class="message">Chargement…</div>

    <footer class="pied">
      <span :class="['pastille', { hors: donneesFigees }]"></span>
      <span>Mis à jour à {{ heureMaj }}</span>
      <span v-if="nbPages > 1" class="pages" aria-label="Pages">
        <span v-for="n in nbPages" :key="n" :class="['point', { actif: n - 1 === page }]"></span>
        Page {{ page + 1 }}/{{ nbPages }} · tri par anomalie<template v-if="rotationS > 0"> · change toutes les {{ rotationS }} s</template>
      </span>
      <span :class="['controles', { visibles: controlesVisibles }]">
        <button type="button" class="ctrl" @click.stop="basculerPleinEcran">{{ pleinEcran ? 'Quitter le plein écran' : 'Plein écran' }}</button>
        <button v-if="!estKiosque" type="button" class="ctrl" @click.stop="quitter">Quitter l'aperçu</button>
      </span>
    </footer>
  </div>
</template>

<style scoped>
/* Palette dédiée TV : indépendante des variables du cockpit (contraste maximal à distance, fond bleu
   nuit qui n'éblouit pas un atelier). Police condensée si disponible, sinon police système. */
.andon {
  position: fixed; inset: 0; display: flex; flex-direction: column; gap: 1.2vh;
  padding: 1.8vh 1.8vw; box-sizing: border-box; overflow: hidden;
  background: #0a1330; color: #f1f5f9;
  font-family: 'Barlow Condensed', 'Roboto Condensed', 'Arial Narrow', system-ui, sans-serif;
  /* *** ADOUCI 2026-09-25 (référence client) *** : couleurs moins saturées, moins "néon" qu'avant. */
  --vert: #6fae82; --orange: #c99457; --rouge: #bd6469; --bleu: #5b8fd6; --gris: #475569; --carte: #111d45; --tuile: #0d1838;
}

.barre { display: flex; justify-content: space-between; align-items: flex-end; flex: 0 0 auto; }
.titre { font-size: clamp(22px, 2.8vw, 48px); font-weight: 800; letter-spacing: .01em; line-height: 1; }
.marque { color: #7dd3fc; }
.sep { margin: 0 .5ch; color: #64748b; }
.perimetre { font-weight: 600; color: #cbd5e1; margin-left: .5ch; }
.horloge { text-align: right; line-height: 1; }
.heure { font-size: clamp(28px, 3.8vw, 68px); font-weight: 800; font-variant-numeric: tabular-nums; }
.date { font-size: clamp(12px, 1.2vw, 22px); color: #94a3b8; text-transform: capitalize; }

.bandeau-alerte, .bandeau-info {
  flex: 0 0 auto; font-weight: 700; text-align: center; padding: .7vh 1vw; border-radius: 10px; font-size: clamp(13px, 1.4vw, 26px);
}
.bandeau-alerte { background: var(--orange); color: #111827; animation: clignote-bandeau 1.6s ease-in-out infinite; }
.bandeau-info { background: #1e3a8a; color: #dbeafe; }

.kpis { display: grid; grid-template-columns: 2fr repeat(5, 1fr); gap: .9vw; flex: 0 0 auto; }
.kpi { border-radius: 14px; padding: 1vh 1vw; display: flex; flex-direction: column; justify-content: center; background: var(--carte); border: 2px solid transparent; min-width: 0; }
.kpi.s-vert { border-color: var(--vert); } .kpi.s-orange { border-color: var(--orange); }
.kpi.s-rouge, .kpi.s-arret { border-color: var(--rouge); } .kpi.s-inactif { border-color: #2a3a66; }
.kpi-label { white-space: nowrap; font-size: clamp(10px, 1.05vw, 19px); color: #94a3b8; text-transform: uppercase; letter-spacing: .05em; font-weight: 700; }
.kpi-valeur { font-size: clamp(24px, 3.4vw, 60px); font-weight: 800; line-height: 1.05; font-variant-numeric: tabular-nums; }
.kpi-principal { flex-direction: row; align-items: center; gap: .9vw; }
.kpi-principal .kpi-texte { display: flex; flex-direction: column; min-width: 0; }
.kpi-principal .kpi-valeur { font-size: clamp(30px, 4.6vw, 84px); }
.kpi-detail { font-size: clamp(11px, 1.1vw, 19px); color: #94a3b8; }

/* *** AJOUT 2026-09-25 *** : jauge circulaire (pur CSS, pas de SVG) sur le KPI principal. */
.jauge {
  width: clamp(44px, 4.6vw, 78px); height: clamp(44px, 4.6vw, 78px); border-radius: 50%; flex-shrink: 0;
  background: conic-gradient(currentColor calc(var(--pct, 0) * 1%), rgba(255, 255, 255, .12) 0);
  display: grid; place-items: center; color: #64748b;
}
.jauge::after { content: ''; width: 64%; height: 64%; border-radius: 50%; background: var(--carte); }
.kpi-principal.s-vert .jauge { color: var(--vert); }
.kpi-principal.s-orange .jauge { color: var(--orange); }
.kpi-principal.s-rouge .jauge { color: var(--rouge); }

.grille {
  flex: 1 1 auto; min-height: 0; display: grid; gap: 14px; align-content: start;
  grid-template-columns: repeat(var(--colonnes, 6), minmax(0, 1fr)); grid-auto-rows: var(--h-tuile, 190px);
}

.tuile {
  border-radius: 18px; padding: 1.2vh 1.1vw; display: flex; flex-direction: column; gap: .3vh; min-width: 0; min-height: 0; overflow: hidden;
  background: var(--tuile); border: 2px solid var(--gris);
}
.tuile.s-vert { border-color: var(--vert); }
.tuile.s-orange { border-color: var(--orange); background: #221b12; }
.tuile.s-rouge { border-color: var(--rouge); background: #21151a; }
.tuile.s-demarrage { border-color: var(--bleu); }
.tuile.s-arret { border-color: var(--rouge); background: #341a20; animation: clignote 2.2s ease-in-out infinite; }

.tuile-haut { display: flex; justify-content: space-between; align-items: baseline; gap: .6vw; }
.code { font-size: clamp(22px, 2.4vw, 44px); font-weight: 800; line-height: 1; white-space: nowrap; }
.perf { font-size: clamp(18px, 2vw, 38px); font-weight: 800; font-variant-numeric: tabular-nums; white-space: nowrap; }
.tendance { font-size: .55em; margin-left: .15em; font-weight: 800; }
.tendance.hausse { color: #8fcaa2; } .tendance.baisse { color: #e0989b; } .tendance.stable { color: #94a3b8; }
.produit { font-size: clamp(12px, 1.25vw, 22px); color: #cbd5e1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
/* *** AJOUT 2026-09-25 *** : barre de progression -- lecture instantanée sans lire le chiffre. */
.barre-progression { height: 5px; border-radius: 3px; background: rgba(255, 255, 255, .12); overflow: hidden; flex-shrink: 0; }
.barre-remplissage { height: 100%; border-radius: 3px; background: #64748b; transition: width .4s ease; }
.s-vert .barre-remplissage { background: #8fcaa2; } .s-orange .barre-remplissage { background: #e0b57e; } .s-rouge .barre-remplissage { background: #e0989b; }
.section { font-size: clamp(10px, .95vw, 17px); color: #64748b; text-transform: uppercase; letter-spacing: .04em; }
.prevision { font-size: clamp(10px, 1vw, 17px); color: #94a3b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bas { margin-top: auto; display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.statut-texte { font-size: clamp(13px, 1.4vw, 25px); font-weight: 800; white-space: nowrap; display: inline-flex; align-items: center; gap: .35em; }
.statut-icone { flex-shrink: 0; }
.statut-detail { font-size: clamp(11px, 1.05vw, 19px); font-weight: 600; opacity: .95; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.s-vert .statut-texte { color: #8fcaa2; } .s-orange .statut-texte { color: #e0b57e; }
.s-rouge .statut-texte, .s-arret .statut-texte { color: #e0989b; } .s-demarrage .statut-texte { color: #a9c6ec; }
.s-arret .statut-detail { color: #f1dcdd; }

.message { margin: auto; font-size: clamp(18px, 2.4vw, 40px); color: #94a3b8; text-align: center; }
.message-detail { font-size: clamp(14px, 1.6vw, 26px); margin-top: 1vh; }
.message-erreur { color: #fbbf24; }

.pied { flex: 0 0 auto; display: flex; align-items: center; gap: 1.2vw; color: #64748b; font-size: clamp(10px, 1vw, 17px); min-height: 34px; }
.pastille { width: .9em; height: .9em; border-radius: 50%; background: var(--vert); }
.pastille.hors { background: var(--orange); animation: clignote-bandeau 1.2s ease-in-out infinite; }
.pages { display: inline-flex; align-items: center; gap: .5ch; }
.point { width: .7em; height: .7em; border-radius: 50%; background: #2a3a66; } .point.actif { background: #7dd3fc; }
.controles { margin-left: auto; display: flex; gap: .8vw; opacity: 0; pointer-events: none; transition: opacity .25s; }
.controles.visibles { opacity: 1; pointer-events: auto; }
.ctrl { background: #1e293b; color: #f1f5f9; border: 1px solid #475569; border-radius: 8px; padding: .6vh 1vw; font: inherit; font-size: clamp(12px, 1.05vw, 18px); font-weight: 700; cursor: pointer; }
.ctrl:hover { background: #334155; }

@keyframes clignote { 0%, 100% { box-shadow: 0 0 0 0 rgba(189, 100, 105, 0); } 50% { box-shadow: 0 0 16px 3px rgba(189, 100, 105, .45); } }
@keyframes clignote-bandeau { 0%, 100% { opacity: 1; } 50% { opacity: .55; } }
@media (prefers-reduced-motion: reduce) { .tuile.s-arret, .bandeau-alerte, .pastille.hors { animation: none; } }
</style>