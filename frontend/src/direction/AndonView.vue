<script setup>
/**
 * AndonView.vue -- écran Andon : TV d'atelier, lecture seule, aucune interaction requise.
 * *** AJOUT 2026-09-24 (Palier 0) ***
 *
 * Principes (cf. synthèse des 4 avis, roadmap Palier 0) :
 *  - Les PROBLÈMES d'abord : le tri vient du serveur (arrêt, rouge, orange, puis le reste).
 *  - Lisible de loin : gros caractères, statut écrit en toutes lettres (jamais la couleur
 *    seule -- daltonisme), contraste élevé sur fond sombre.
 *  - Résilient : une coupure réseau ne vide JAMAIS l'écran. Les dernières données restent
 *    affichées, avec un bandeau « données figées à hh:mm », et les tentatives continuent.
 *  - Autonome : écran maintenu allumé (Wake Lock), rechargement complet toutes les 12 h
 *    (évite une page figée sur un ancien déploiement), reprise de session après
 *    redémarrage du navigateur (cf. api/session.js).
 * Sert aussi d'aperçu aux comptes direction (menu « Écran Andon ») : un bouton Quitter
 * apparaît alors, jamais pour un compte kiosque.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import apiClient from '@/api/client'

const router = useRouter()
const user = JSON.parse(sessionStorage.getItem('user') || '{}')
const estKiosque = user.user_type === 'kiosque'

const POLL_MS = 10_000
const PERIME_APRES_MS = 45_000
const RECHARGEMENT_APRES_MS = 12 * 3600 * 1000
const demarrage = Date.now()

const data = ref(null)
const derniereMajOk = ref(null)
const enErreur = ref(false)
const maintenant = ref(new Date())
const controlesVisibles = ref(false)
const pleinEcran = ref(false)

let pollHandle = null
let horlogeHandle = null
let masquerHandle = null
let enCours = false
let wakeLock = null

async function charger() {
  if (enCours) return  // jamais deux requêtes en parallèle sur un réseau lent
  enCours = true
  try {
    const res = await apiClient.get('/dashboard/andon')
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
  } catch { /* refusé (batterie faible, onglet masqué) : non bloquant */ }
}
function surVisibilite() {
  if (document.visibilityState === 'visible') { verrouillerEcran(); charger() }
}
function surPleinEcran() { pleinEcran.value = !!document.fullscreenElement }

onMounted(() => {
  charger()
  pollHandle = setInterval(charger, POLL_MS)
  horlogeHandle = setInterval(() => { maintenant.value = new Date() }, 1000)
  verrouillerEcran()
  document.addEventListener('visibilitychange', surVisibilite)
  document.addEventListener('fullscreenchange', surPleinEcran)
})
onUnmounted(() => {
  clearInterval(pollHandle); clearInterval(horlogeHandle); clearTimeout(masquerHandle)
  document.removeEventListener('visibilitychange', surVisibilite)
  document.removeEventListener('fullscreenchange', surPleinEcran)
  try { wakeLock?.release() } catch { /* déjà libéré */ }
})

// Les boutons n'apparaissent qu'au mouvement de la souris, puis disparaissent : sur une
// TV, aucun bouton ne doit rester affiché en permanence.
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
  arret: { label: 'ARRÊT', classe: 's-arret' },
  rouge: { label: 'RETARD CRITIQUE', classe: 's-rouge' },
  orange: { label: 'EN RETARD', classe: 's-orange' },
  demarrage: { label: 'DÉMARRAGE', classe: 's-demarrage' },
  vert: { label: 'OK', classe: 's-vert' },
  inactif: { label: 'PAS DE PRODUCTION', classe: 's-inactif' },
}
const statut = l => STATUTS[l.statut] || { label: l.statut.toUpperCase(), classe: 's-inactif' }
const avancement = l => (l.theorique > 0 ? Math.min(100, Math.round((l.reel / l.theorique) * 100)) : 0)

const lignes = computed(() => data.value?.lignes ?? [])
const dense = computed(() => lignes.value.length > 12)
const tresDense = computed(() => lignes.value.length > 24)
const resume = computed(() => data.value?.resume ?? null)
const classePerfUsine = computed(() => {
  const p = resume.value?.performance_usine_pct
  if (p === null || p === undefined) return 's-inactif'
  return p >= 95 ? 's-vert' : p >= 80 ? 's-orange' : 's-rouge'
})
</script>

<template>
  <div :class="['andon', { dense, 'tres-dense': tresDense }]" @mousemove="montrerControles" @click="montrerControles">
    <header class="barre">
      <div class="titre">
        <span class="marque">SIVOP</span><span class="sep">·</span>Andon
        <span v-if="user.section_scope" class="perimetre">— {{ user.section_scope }}</span>
      </div>
      <div class="horloge">
        <div class="heure">{{ heure }}</div>
        <div class="date">{{ dateLongue }}</div>
      </div>
    </header>

    <div v-if="donneesFigees && data" class="bandeau-alerte" role="alert">
      ⚠ Connexion perdue — données figées à {{ heureMaj }}. Nouvelle tentative en cours…
    </div>

    <section v-if="resume" class="kpis" aria-label="Synthèse de l'usine">
      <div :class="['kpi', 'kpi-principal', classePerfUsine]">
        <span class="kpi-label">Performance{{ user.section_scope ? '' : ' usine' }}</span>
        <span class="kpi-valeur">{{ resume.performance_usine_pct !== null ? resume.performance_usine_pct + ' %' : '—' }}</span>
        <span class="kpi-detail">{{ fmt(resume.total_reel) }} / {{ fmt(resume.total_theorique) }} pièces</span>
      </div>
      <div class="kpi s-arret"><span class="kpi-label">À l'arrêt</span><span class="kpi-valeur">{{ resume.lignes_a_larret }}</span></div>
      <div class="kpi s-rouge"><span class="kpi-label">Retard critique</span><span class="kpi-valeur">{{ resume.lignes_rouges }}</span></div>
      <div class="kpi s-orange"><span class="kpi-label">En retard</span><span class="kpi-valeur">{{ resume.lignes_orange }}</span></div>
      <div class="kpi s-vert"><span class="kpi-label">OK</span><span class="kpi-valeur">{{ resume.lignes_vertes }}</span></div>
    </section>

    <main v-if="data && lignes.length" class="grille">
      <article v-for="l in lignes" :key="l.id" :class="['tuile', statut(l).classe]">
        <div class="tuile-tete">
          <span class="code">{{ l.code }}</span>
          <span class="badge-statut">{{ statut(l).label }}</span>
        </div>
        <div class="nom">{{ l.nom }}</div>
        <div v-if="l.produit" class="produit">{{ l.produit }}</div>

        <template v-if="l.statut === 'arret'">
          <div class="arret-cause">{{ l.arret_cause || 'Arrêt en cours' }}</div>
          <div v-if="l.arret_depuis_min !== null" class="arret-duree">depuis {{ duree(l.arret_depuis_min) }}</div>
          <div v-if="l.arret_equipement" class="arret-equip">{{ l.arret_equipement }}</div>
        </template>
        <template v-else>
          <div class="perf">{{ l.performance_pct !== null ? l.performance_pct + ' %' : '—' }}</div>
          <div class="barre-avancement" aria-hidden="true"><div class="barre-remplie" :style="{ width: avancement(l) + '%' }"></div></div>
          <div class="chiffres">{{ fmt(l.reel) }} <span class="sur">/ {{ fmt(l.theorique) }}</span></div>
          <div v-if="l.retard_min > 0" class="retard">Retard {{ duree(l.retard_min) }}</div>
          <div v-if="l.prevision_fin_poste !== null && l.prevision_fin_poste !== undefined" class="prevision">
            Fin de poste ≈ {{ fmt(l.prevision_fin_poste) }}<template v-if="l.objectif_jour"> sur {{ fmt(l.objectif_jour) }}</template>
          </div>
        </template>
      </article>
    </main>
    <div v-else-if="data" class="message">Aucune ligne à afficher.</div>
    <div v-else-if="enErreur" class="message message-erreur">Impossible de joindre le serveur — nouvelle tentative en cours…</div>
    <div v-else class="message">Chargement…</div>

    <footer class="pied">
      <span :class="['pastille', { hors: donneesFigees }]"></span>
      Mis à jour à {{ heureMaj }}
    </footer>

    <div :class="['controles', { visibles: controlesVisibles }]">
      <button type="button" class="ctrl" @click.stop="basculerPleinEcran">{{ pleinEcran ? 'Quitter le plein écran' : 'Plein écran' }}</button>
      <button v-if="!estKiosque" type="button" class="ctrl" @click.stop="quitter">Quitter l'aperçu</button>
    </div>
  </div>
</template>

<style scoped>
/* Palette dédiée TV : volontairement indépendante des variables du cockpit (contraste
   maximal à distance, fond sombre pour ne pas éblouir un atelier). */
.andon {
  position: fixed; inset: 0; display: flex; flex-direction: column; gap: 1.1vh;
  padding: 1.6vh 1.6vw; box-sizing: border-box; overflow: hidden;
  background: #0b1220; color: #f1f5f9; font-family: var(--font-family, system-ui, sans-serif);
  --rouge: #dc2626; --orange: #f59e0b; --vert: #16a34a; --bleu: #2563eb; --gris: #475569;
}

.barre { display: flex; justify-content: space-between; align-items: center; flex: 0 0 auto; }
.titre { font-size: clamp(20px, 2.6vw, 44px); font-weight: 800; letter-spacing: .02em; }
.marque { color: #7dd3fc; }
.sep { margin: 0 .5ch; color: #64748b; }
.perimetre { font-weight: 600; color: #cbd5e1; margin-left: .6ch; }
.horloge { text-align: right; line-height: 1.05; }
.heure { font-size: clamp(28px, 4vw, 72px); font-weight: 800; font-variant-numeric: tabular-nums; }
.date { font-size: clamp(12px, 1.3vw, 22px); color: #94a3b8; text-transform: capitalize; }

.bandeau-alerte {
  flex: 0 0 auto; background: var(--orange); color: #111827; font-weight: 800; text-align: center;
  padding: .8vh 1vw; border-radius: 8px; font-size: clamp(13px, 1.5vw, 26px);
  animation: clignote-bandeau 1.6s ease-in-out infinite;
}

.kpis { display: grid; grid-template-columns: 2.2fr 1fr 1fr 1fr 1fr; gap: 1vw; flex: 0 0 auto; }
.kpi { border-radius: 12px; padding: 1vh 1.2vw; display: flex; flex-direction: column; justify-content: center; background: #111c30; border-left: .8vw solid var(--gris); }
.kpi.s-vert { border-left-color: var(--vert); } .kpi.s-orange { border-left-color: var(--orange); }
.kpi.s-rouge, .kpi.s-arret { border-left-color: var(--rouge); } .kpi.s-inactif { border-left-color: var(--gris); }
.kpi-label { font-size: clamp(11px, 1.2vw, 20px); color: #94a3b8; text-transform: uppercase; letter-spacing: .06em; font-weight: 700; }
.kpi-valeur { font-size: clamp(24px, 3.6vw, 64px); font-weight: 800; line-height: 1.05; font-variant-numeric: tabular-nums; }
.kpi-principal .kpi-valeur { font-size: clamp(32px, 5.2vw, 96px); }
.kpi-detail { font-size: clamp(11px, 1.2vw, 20px); color: #94a3b8; }

.grille {
  flex: 1 1 auto; min-height: 0; display: grid; gap: 1vw; align-content: start;
  grid-template-columns: repeat(auto-fill, minmax(clamp(210px, 21vw, 420px), 1fr));
  grid-auto-rows: minmax(0, 1fr);
}
.dense .grille { grid-template-columns: repeat(auto-fill, minmax(clamp(170px, 15.5vw, 320px), 1fr)); gap: .7vw; }
.tres-dense .grille { grid-template-columns: repeat(auto-fill, minmax(clamp(140px, 12.5vw, 260px), 1fr)); gap: .5vw; }

.tuile {
  border-radius: 14px; padding: 1.2vh 1vw; display: flex; flex-direction: column; gap: .3vh;
  background: var(--gris); min-width: 0; min-height: 0; overflow: hidden; box-shadow: inset 0 0 0 2px rgba(255,255,255,.08);
}
.tuile.s-vert { background: #14532d; box-shadow: inset 0 0 0 2px var(--vert); }
.tuile.s-orange { background: #78350f; box-shadow: inset 0 0 0 2px var(--orange); }
.tuile.s-rouge { background: #7f1d1d; box-shadow: inset 0 0 0 2px var(--rouge); }
.tuile.s-demarrage { background: #1e3a8a; box-shadow: inset 0 0 0 2px var(--bleu); }
.tuile.s-inactif { background: #1e293b; box-shadow: inset 0 0 0 2px #334155; color: #94a3b8; }
.tuile.s-arret { background: var(--rouge); color: #fff; animation: clignote 1.4s ease-in-out infinite; }

.tuile-tete { display: flex; justify-content: space-between; align-items: baseline; gap: .6vw; }
.code { font-size: clamp(20px, 2.5vw, 46px); font-weight: 800; }
.badge-statut { font-size: clamp(9px, .95vw, 17px); font-weight: 800; letter-spacing: .05em; background: rgba(0,0,0,.35); padding: .2vh .6vw; border-radius: 999px; white-space: nowrap; }
.nom { font-size: clamp(11px, 1.15vw, 20px); opacity: .85; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.produit { font-size: clamp(11px, 1.2vw, 21px); font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.perf { font-size: clamp(28px, 3.8vw, 72px); font-weight: 800; line-height: 1; font-variant-numeric: tabular-nums; margin-top: auto; }
.barre-avancement { height: .9vh; min-height: 5px; background: rgba(0,0,0,.35); border-radius: 999px; overflow: hidden; }
.barre-remplie { height: 100%; background: #f8fafc; border-radius: 999px; transition: width .6s ease; }
.chiffres { font-size: clamp(12px, 1.4vw, 24px); font-weight: 700; font-variant-numeric: tabular-nums; }
.sur { opacity: .7; font-weight: 500; }
.retard, .prevision { font-size: clamp(10px, 1.1vw, 19px); opacity: .9; }
.retard { font-weight: 700; }

.arret-cause { font-size: clamp(16px, 2.1vw, 38px); font-weight: 800; line-height: 1.1; margin-top: auto; }
.arret-duree { font-size: clamp(20px, 3vw, 56px); font-weight: 800; font-variant-numeric: tabular-nums; }
.arret-equip { font-size: clamp(10px, 1.1vw, 19px); opacity: .9; }

.dense .code { font-size: clamp(16px, 1.9vw, 34px); } .dense .perf { font-size: clamp(22px, 2.9vw, 52px); }
.dense .produit, .dense .prevision, .dense .retard { display: none; }
.tres-dense .nom, .tres-dense .chiffres { display: none; }

.message { margin: auto; font-size: clamp(18px, 2.4vw, 40px); color: #94a3b8; text-align: center; }
.message-erreur { color: #fbbf24; }

.pied { flex: 0 0 auto; display: flex; align-items: center; gap: .7ch; color: #64748b; font-size: clamp(10px, 1vw, 16px); }
.pastille { width: .9em; height: .9em; border-radius: 50%; background: var(--vert); }
.pastille.hors { background: var(--orange); animation: clignote-bandeau 1.2s ease-in-out infinite; }

.controles { position: fixed; right: 1.6vw; bottom: 3.5vh; display: flex; gap: .8vw; opacity: 0; pointer-events: none; transition: opacity .25s; }
.controles.visibles { opacity: 1; pointer-events: auto; }
.ctrl { background: #1e293b; color: #f1f5f9; border: 1px solid #475569; border-radius: 8px; padding: 1vh 1.2vw; font-size: clamp(12px, 1.1vw, 18px); font-weight: 700; cursor: pointer; }
.ctrl:hover { background: #334155; }

@keyframes clignote { 0%, 100% { box-shadow: inset 0 0 0 2px #fff, 0 0 0 0 rgba(220,38,38,.0); } 50% { box-shadow: inset 0 0 0 4px #fff, 0 0 22px 6px rgba(220,38,38,.75); } }
@keyframes clignote-bandeau { 0%, 100% { opacity: 1; } 50% { opacity: .55; } }
@media (prefers-reduced-motion: reduce) { .tuile.s-arret, .bandeau-alerte, .pastille.hors { animation: none; } }
</style>
