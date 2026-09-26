<script setup>
/**
 * ScoringView.vue -- performance des ÉQUIPES + suivi individuel de formation.
 * *** REFONDU 2026-09-24 (Palier 2) *** : remplace le classement NOMINATIF CDI/CDD (rang,
 * matricule, nom, score par personne). Cadre : le score est porté par la ligne/l'équipe,
 * jamais par l'individu ; les arrêts non imputables sont neutralisés ; le suivi individuel
 * est réservé (permission dédiée), sans classement, et chaque ouverture de fiche est journalisée.
 */
import { ref, computed, onMounted } from 'vue'
import apiClient from '@/api/client'
import DataTable from '@/components/DataTable.vue'
import { RefreshCw, TrendingUp, TrendingDown, Minus } from 'lucide-vue-next'

const user = JSON.parse(sessionStorage.getItem('user') || '{}')
const aPermission = k => user.is_admin || (user.permissions || []).includes(k)
const peutSuivi = aPermission('view_suivi_individuel')

const iso = d => d.toISOString().slice(0, 10)
const hier = new Date(Date.now() - 86400000)
const dateFin = ref(iso(hier))
const dateDebut = ref(iso(new Date(hier.getTime() - 6 * 86400000)))
const onglet = ref('equipes')

const equipes = ref(null)
const isLoading = ref(true)
const errorMessage = ref('')
const snapshotEnCours = ref(false)
const snapshotMessage = ref('')

// *** AJOUT 2026-09-25 *** : Performance personnel (CDI/CDD) -- classement nominatif,
// cf. scoring_service.classement_personnel / commentaire en tête de scoring_routes.py.
const classement = ref([])
const classementErreur = ref('')
const classementChargement = ref(false)
const filtreCategorie = ref('')
const regrouperParStatut = ref(false)   // *** AJOUT 2026-09-25 *** : une table par statut (CDI/CDD/...), rang recalculé dans chaque groupe
async function chargerClassement() {
  classementChargement.value = true
  try {
    classement.value = (await apiClient.get('/scoring/classement-personnel', { params: { date_debut: dateDebut.value, date_fin: dateFin.value } })).data
    classementErreur.value = ''
  } catch (e) {
    classementErreur.value = e.response?.data?.detail || 'Impossible de charger le classement.'
  } finally {
    classementChargement.value = false
  }
}
const categoriesDisponibles = computed(() => [...new Set(classement.value.map(r => r.categorie_personnel).filter(Boolean))].sort())
const classementFiltre = computed(() => filtreCategorie.value ? classement.value.filter(r => r.categorie_personnel === filtreCategorie.value) : classement.value)
// Groupes pour l'affichage "regrouper par statut" : un rang RECALCULÉ dans chaque groupe
// (comparer un CDI à un CDD sur un même rang global n'a pas de sens -- cf. la maquette,
// qui sépare "Classement CDI" et "Classement CDD").
const groupesParStatut = computed(() => categoriesDisponibles.value.map(cat => {
  const lignes = classement.value.filter(r => r.categorie_personnel === cat)
  let rang = 0
  const avecRang = lignes.map(r => ({ ...r, rang: r.score_pct !== null && r.score_pct !== undefined ? ++rang : null }))
  return { categorie: cat, lignes: avecRang }
}))
// 4 indicateurs du haut : effectif et score moyen par statut (pondéré par personne, pas par ligne).
function resumeCategorie(cat) {
  const lignes = classement.value.filter(r => r.categorie_personnel === cat)
  const avecScore = lignes.filter(r => r.score_pct !== null && r.score_pct !== undefined)
  const moyenne = avecScore.length ? avecScore.reduce((s, r) => s + r.score_pct, 0) / avecScore.length : null
  return { actifs: lignes.length, moyenne }
}
const resumeCDI = computed(() => resumeCategorie('CDI'))
const resumeCDD = computed(() => resumeCategorie('CDD'))
const TENDANCE_ICONES = { hausse: TrendingUp, baisse: TrendingDown, stable: Minus }
const COLONNES_PERSONNEL = [
  { key: 'rang', label: 'Rang', align: 'right', format: v => v ?? '—' },
  { key: 'matricule', label: 'Matricule', format: v => v || '—' },
  { key: 'nom', label: 'Nom' },
  { key: 'user_type', label: 'Fonction', format: v => v === 'operateur' ? 'Opérateur' : v === 'ouvrier' ? 'Ouvrier' : v },
  { key: 'categorie_personnel', label: 'Statut', format: v => v || '—' },
  { key: 'nb_lignes', label: 'Lignes', align: 'right' },
  { key: 'heures', label: 'Heures', align: 'right' },
  { key: 'score_pct', label: 'Score', align: 'right' },
  { key: 'tendance', label: 'Tendance', align: 'right', sortable: false, title: 'Comparé à la même durée sur la période précédente' },
]

async function chargerEquipes() {
  isLoading.value = true
  try {
    equipes.value = (await apiClient.get('/scoring/equipes', { params: { date_debut: dateDebut.value, date_fin: dateFin.value } })).data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger les scores des équipes.'
  } finally {
    isLoading.value = false
  }
}
onMounted(chargerEquipes)

async function lancerSnapshot() {
  snapshotEnCours.value = true
  snapshotMessage.value = ''
  try {
    await apiClient.post('/scoring/snapshot/run-now')
    snapshotMessage.value = 'Snapshot du jour effectué.'
    await chargerEquipes()
  } catch (e) {
    snapshotMessage.value = e.response?.data?.detail || 'Échec du snapshot.'
  } finally {
    snapshotEnCours.value = false
  }
}

const fmtPct = v => (v === null || v === undefined ? '—' : `${Number(v).toLocaleString('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`)
const fmtMin = v => `${Number(v).toLocaleString('fr-FR')} min`
function classeScore(v) {
  // Peu de scans : aucune couleur d'alarme -- un 0 % sans données n'est pas une contre-performance.
  if (v === null || v === undefined || equipes.value?.donnees_insuffisantes) return 'gris'
  return v >= 100 ? 'vert' : v >= 80 ? 'orange' : 'rouge'
}
const COLONNES = [
  { key: 'code', label: 'Ligne', format: (v, r) => `${r.code} — ${r.nom}` },
  { key: 'section_nom', label: 'Section', format: v => v || '—' },
  { key: 'effectif', label: 'Effectif', align: 'right',
    title: "Personnes affectées à la ligne sur la période (un nombre, jamais des noms). « au moins N » : aucune affectation saisie, estimé d'après les personnes qui ont scanné (Administration → Affectations).",
    format: (v, r) => (v === null || v === undefined ? '—' : r.effectif_estime ? `au moins ${v}` : v) },
  { key: 'jours', label: 'Jours', align: 'right' },
  { key: 'score_pct', label: 'Score', align: 'right', title: 'Production (conforme + rebuts) ÷ production attendue, arrêts non imputables retirés' },
  { key: 'minutes_arret_imputables', label: 'Arrêts imputables', align: 'right', title: "Arrêts comptés contre l'équipe", format: fmtMin },
  { key: 'minutes_neutralisees', label: 'Arrêts neutralisés', align: 'right', title: "Arrêts non imputables : retirés de ce qu'on attend de l'équipe", format: fmtMin },
]

// ---- Suivi individuel (formation) ----------------------------------------------------------
const personnes = ref([])
const personneChoisie = ref('')
const suivi = ref(null)
const suiviErreur = ref('')
const journal = ref([])

async function ouvrirSuivi() {
  onglet.value = 'suivi'
  suiviErreur.value = ''
  try {
    personnes.value = (await apiClient.get('/scoring/suivi-individuel')).data
    if (user.is_admin) journal.value = (await apiClient.get('/scoring/suivi-individuel/acces')).data
  } catch (e) {
    suiviErreur.value = e.response?.data?.detail || 'Impossible de charger la liste.'
  }
}
async function chargerSuivi() {
  suivi.value = null
  if (!personneChoisie.value) return
  try {
    suivi.value = (await apiClient.get(`/scoring/suivi-individuel/${personneChoisie.value}`, { params: { date_debut: dateDebut.value, date_fin: dateFin.value } })).data
    suiviErreur.value = ''
    if (user.is_admin) journal.value = (await apiClient.get('/scoring/suivi-individuel/acces')).data
  } catch (e) {
    suiviErreur.value = e.response?.data?.detail || 'Impossible de charger le suivi.'
  }
}
const actualiser = () => (onglet.value === 'suivi' ? chargerSuivi() : onglet.value === 'personnel' ? chargerClassement() : chargerEquipes())
const heureFr = iso => new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })
</script>

<template>
  <div class="scoring">
    <header class="page-header">
      <div>
        <h1>Performance des équipes</h1>
        <p class="subtitle">
          <template v-if="onglet === 'equipes'">Score par ligne, arrêts non imputables neutralisés. Aucun classement de personnes.</template>
          <template v-else-if="onglet === 'personnel'">Classement nominatif CDI/CDD.</template>
          <template v-else>Formation : résultat des équipes pendant la présence de la personne.</template>
        </p>
      </div>
      <button class="btn primary" :disabled="snapshotEnCours" @click="lancerSnapshot">
        <RefreshCw :size="16" /> {{ snapshotEnCours ? 'Snapshot en cours…' : 'Lancer le snapshot du jour' }}
      </button>
    </header>
    <p v-if="snapshotMessage" class="snapshot-banner">{{ snapshotMessage }}</p>

    <div class="tabs">
      <button :class="['tab-btn', { active: onglet === 'equipes' }]" @click="onglet = 'equipes'">Équipes</button>
      <button :class="['tab-btn', { active: onglet === 'personnel' }]" @click="onglet = 'personnel'; chargerClassement()">Performance personnel (CDI/CDD)</button>
      <button v-if="peutSuivi" :class="['tab-btn', { active: onglet === 'suivi' }]" @click="ouvrirSuivi">Suivi individuel (formation)</button>
    </div>

    <div class="periode">
      <label>Du <input v-model="dateDebut" type="date" /></label>
      <label>au <input v-model="dateFin" type="date" /></label>
      <button class="btn secondary" @click="actualiser">Actualiser</button>
    </div>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <!-- ÉQUIPES -->
    <template v-if="onglet === 'equipes'">
      <div v-if="isLoading" class="loading">Chargement…</div>
      <template v-else-if="equipes">
        <p v-if="equipes.donnees_insuffisantes" class="warn-banner" role="alert">
          Peu de scans enregistrés sur la période ({{ equipes.nb_palettes }} palette{{ equipes.nb_palettes > 1 ? 's' : '' }}) : les scores ne sont pas
          représentatifs. Un 0 % traduit ici l'absence de scans, pas forcément une contre-performance.
        </p>
        <p v-if="equipes.nb_lignes_sans_planning > 0 && equipes.lignes.length" class="info-banner">
          {{ equipes.nb_lignes_sans_planning }} ligne(s) sans planning sur la période : non évaluées, donc absentes du tableau.
        </p>
        <p v-if="equipes.aucune_cause_imputable" class="warn-banner">
          Aucune cause d'arrêt n'est marquée « imputable à l'équipe » : aucun arrêt ne pénalise les équipes, le score ne mesure que la cadence.
          À définir dans Administration → Causes d'arrêt.
        </p>
        <p v-else class="info-banner">
          Seuls ces arrêts comptent contre une équipe : <strong>{{ equipes.causes_imputables.join(', ') }}</strong>. Tous les autres sont neutralisés.
        </p>

        <div class="kpi-total">
          <span class="kpi-label">Score global (équipes affichées)</span>
          <strong :class="['score-badge', 'statut-' + classeScore(equipes.total.score_pct)]">{{ fmtPct(equipes.total.score_pct) }}</strong>
          <small>{{ equipes.nb_jours }} jour(s) complet(s)</small>
        </div>

        <p v-if="!equipes.lignes.length" class="empty">Aucune journée complète avec planning sur cette période.</p>
        <DataTable v-else :columns="COLONNES" :rows="equipes.lignes" :row-key="r => r.ligne_id" :page-size="50" empty-text="—">
          <template #cell-score_pct="{ row }">
            <span v-if="row.masque" class="score-badge statut-gris" :title="row.masque_raison">masqué</span>
            <span v-else :class="['score-badge', 'statut-' + classeScore(row.score_pct)]">{{ fmtPct(row.score_pct) }}</span>
          </template>
        </DataTable>
        <p v-if="equipes.lignes.some(l => l.masque)" class="hint">
          « Masqué » : équipe de moins de {{ equipes.effectif_min }} personnes. Afficher un score la désignerait, donc il n'est pas montré.
        </p>
        <p class="hint">Les rebuts déclarés sont comptés dans la production : les déclarer ne pénalise pas l'équipe.</p>
      </template>
    </template>

    <!-- PERFORMANCE PERSONNEL (CDI/CDD) -->
    <template v-else-if="onglet === 'personnel'">
      <p class="warn-banner">
        Classement nominatif, réutilisant le même calcul que le score d'équipe (résultat de L'ÉQUIPE pendant la présence de chaque personne) --
        ce n'est pas une nouvelle mesure individuelle, seulement affichée et triée nominativement ici.
      </p>
      <p v-if="classementErreur" class="error-banner">{{ classementErreur }}</p>

      <!-- *** AJOUT 2026-09-25 *** : les 4 indicateurs du haut (effectif + score moyen par statut). -->
      <div class="kpis-personnel">
        <div class="kpi-perso kpi-perso-cdi"><strong>{{ resumeCDI.actifs }}</strong><span>CDI actifs</span></div>
        <div class="kpi-perso kpi-perso-cdd"><strong>{{ resumeCDD.actifs }}</strong><span>CDD actifs</span></div>
        <div :class="['kpi-perso', 'kpi-perso-score', 'statut-' + classeScore(resumeCDI.moyenne)]"><strong>{{ fmtPct(resumeCDI.moyenne) }}</strong><span>Score moyen CDI</span></div>
        <div :class="['kpi-perso', 'kpi-perso-score', 'statut-' + classeScore(resumeCDD.moyenne)]"><strong>{{ fmtPct(resumeCDD.moyenne) }}</strong><span>Score moyen CDD</span></div>
      </div>

      <div class="filtres-personnel">
        <label v-if="categoriesDisponibles.length > 1" class="choix-personne">Statut
          <select v-model="filtreCategorie" :disabled="regrouperParStatut">
            <option value="">Tous</option>
            <option v-for="c in categoriesDisponibles" :key="c" :value="c">{{ c }}</option>
          </select>
        </label>
        <label class="case-regrouper">
          <input type="checkbox" v-model="regrouperParStatut" /> Regrouper par statut (un classement par CDI/CDD, rang recalculé dans chaque groupe)
        </label>
      </div>

      <div v-if="classementChargement" class="loading">Chargement…</div>
      <template v-else-if="regrouperParStatut">
        <section v-for="g in groupesParStatut" :key="g.categorie" class="groupe-statut">
          <h3>{{ g.categorie }}</h3>
          <DataTable :columns="COLONNES_PERSONNEL" :rows="g.lignes" :row-key="r => r.user_id" :page-size="50" empty-text="Aucune donnée sur cette période.">
            <template #cell-score_pct="{ row }">
              <span :class="['score-badge', 'statut-' + classeScore(row.score_pct)]">{{ fmtPct(row.score_pct) }}</span>
            </template>
            <template #cell-tendance="{ row }">
              <component :is="TENDANCE_ICONES[row.tendance]" v-if="row.tendance" :size="16" :class="['tendance-icone', row.tendance]" />
              <span v-else>—</span>
            </template>
          </DataTable>
        </section>
      </template>
      <DataTable v-else :columns="COLONNES_PERSONNEL" :rows="classementFiltre" :row-key="r => r.user_id" :page-size="50" empty-text="Aucune donnée sur cette période.">
        <template #cell-score_pct="{ row }">
          <span :class="['score-badge', 'statut-' + classeScore(row.score_pct)]">{{ fmtPct(row.score_pct) }}</span>
        </template>
        <template #cell-tendance="{ row }">
          <component :is="TENDANCE_ICONES[row.tendance]" v-if="row.tendance" :size="16" :class="['tendance-icone', row.tendance]" />
          <span v-else>—</span>
        </template>
      </DataTable>
    </template>

    <!-- SUIVI INDIVIDUEL -->
    <template v-else-if="onglet === 'suivi'">
      <p class="warn-banner">
        Usage : identifier des besoins de <strong>formation</strong>. La fiche décrit le résultat des équipes pendant la présence de la personne,
        ce n'est ni un score individuel ni un classement. <strong>Chaque ouverture de fiche est enregistrée.</strong>
      </p>
      <p v-if="suiviErreur" class="error-banner">{{ suiviErreur }}</p>
      <label class="choix-personne">Personne
        <select v-model="personneChoisie" @change="chargerSuivi">
          <option value="">— choisir —</option>
          <option v-for="p in personnes" :key="p.user_id" :value="p.user_id">{{ p.nom }}{{ p.matricule ? ` (${p.matricule})` : '' }}</option>
        </select>
      </label>

      <div v-if="suivi" class="fiche">
        <h2>{{ suivi.nom }}</h2>
        <p>{{ suivi.heures_totales.toLocaleString('fr-FR') }} h de présence sur la période.</p>
        <table class="table-fiche">
          <thead><tr><th>Ligne</th><th>Jours</th><th>Heures</th><th>Résultat de l'équipe</th></tr></thead>
          <tbody>
            <tr v-for="l in suivi.lignes" :key="l.ligne_code">
              <td>{{ l.ligne_code }} — {{ l.ligne_nom }}</td><td>{{ l.jours_presence }}</td><td>{{ l.heures }}</td>
              <td><span v-if="l.equipe_masquee" class="score-badge statut-gris" title="Équipe de moins de 3 personnes">masqué</span><span v-else>{{ fmtPct(l.resultat_equipe_pct) }}</span></td>
            </tr>
            <tr v-if="!suivi.lignes.length"><td colspan="4" class="empty">Aucune présence enregistrée sur cette période.</td></tr>
          </tbody>
        </table>
        <p class="hint">{{ suivi.avertissement }}</p>
      </div>

      <section v-if="user.is_admin" class="journal">
        <h3>Journal des consultations</h3>
        <p v-if="!journal.length" class="empty">Aucune consultation enregistrée.</p>
        <table v-else class="table-fiche">
          <thead><tr><th>Date</th><th>Consulté par</th><th>Personne</th><th>Période</th></tr></thead>
          <tbody>
            <tr v-for="j in journal" :key="j.id"><td>{{ heureFr(j.consulte_le) }}</td><td>{{ j.consulte_par_nom }}</td><td>{{ j.personne_nom }}</td><td>{{ j.periode_debut }} → {{ j.periode_fin }}</td></tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>

<style scoped>
.scoring { padding: var(--space-6); overflow-y: auto; height: 100%; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; }
.page-header h1 { margin: 0; font-size: var(--font-size-2xl); }
.subtitle { color: var(--color-text-muted); margin: 4px 0 var(--space-4); }
.btn { display: inline-flex; align-items: center; gap: var(--space-2); border: none; border-radius: var(--radius-md); padding: 0 var(--space-4); height: 36px; font-weight: 700; cursor: pointer; background: var(--color-brand); color: var(--color-text-inverse); }
.btn.secondary { background: var(--color-surface); color: var(--color-text); border: 1px solid var(--color-border); }
.btn:disabled { opacity: .6; cursor: default; }
.snapshot-banner, .info-banner { background: var(--color-vert-bg); color: var(--color-vert); padding: var(--space-3); border-radius: var(--radius-md); margin-bottom: var(--space-3); }
.info-banner { background: var(--color-surface); color: var(--color-text); border: 1px solid var(--color-border); }
.warn-banner { background: var(--color-orange-bg); color: #92400E; padding: var(--space-3); border-radius: var(--radius-md); margin-bottom: var(--space-3); }
.error-banner { background: var(--color-rouge-bg); color: var(--color-rouge); padding: var(--space-3); border-radius: var(--radius-md); margin-bottom: var(--space-3); }
.tabs { display: flex; gap: var(--space-2); margin-bottom: var(--space-3); }
/* *** AJOUT 2026-09-25 (demande explicite, style pilule) *** */
.tab-btn {
  padding: 0 var(--space-4); height: 36px; border-radius: 999px; border: 1px solid var(--color-border);
  background: var(--color-surface); color: var(--color-text-muted); font-size: var(--font-size-sm); font-weight: 600;
  cursor: pointer; transition: background .15s ease, color .15s ease, border-color .15s ease;
}
.tab-btn:hover { border-color: var(--color-brand); color: var(--color-text); }
.tab-btn.active { background: var(--color-brand); border-color: var(--color-brand); color: var(--color-text-inverse); }
.periode { display: flex; gap: var(--space-3); align-items: center; margin-bottom: var(--space-4); }
.periode input, .choix-personne select { height: 36px; padding: 0 var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-family: inherit; }
.kpi-total { display: inline-flex; flex-direction: column; gap: 2px; padding: var(--space-3) var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); margin-bottom: var(--space-4); }
.kpi-label { font-size: var(--font-size-xs); color: var(--color-text-muted); text-transform: uppercase; }
.score-badge { display: inline-block; padding: 3px 10px; border-radius: 999px; font-weight: 700; }
.statut-vert { background: var(--color-vert-bg); color: var(--color-vert); }
.statut-orange { background: var(--color-orange-bg); color: #92400E; }
.statut-rouge { background: var(--color-rouge-bg); color: var(--color-rouge); }
.statut-gris { background: var(--color-border); color: var(--color-text-muted); }
.hint { color: var(--color-text-muted); font-size: var(--font-size-xs); margin: var(--space-2) 0; }
.choix-personne { display: flex; flex-direction: column; gap: 4px; max-width: 360px; margin-bottom: var(--space-4); font-weight: 600; }
.fiche h2 { margin: 0 0 var(--space-2); }
.table-fiche { width: 100%; border-collapse: collapse; margin: var(--space-2) 0; }
.table-fiche th, .table-fiche td { text-align: left; padding: var(--space-2); border-bottom: 1px solid var(--color-border); }
.journal { margin-top: var(--space-6); }
.empty { color: var(--color-text-muted); }
/* *** AJOUT 2026-09-25 *** : Performance personnel (CDI/CDD) -- KPIs, filtres, regroupement, tendance. */
.kpis-personnel { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-3); margin-bottom: var(--space-4); }
.kpi-perso { display: flex; flex-direction: column; gap: 2px; padding: var(--space-3) var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); }
.kpi-perso strong { font-size: var(--font-size-xl); }
.kpi-perso span { font-size: var(--font-size-xs); color: var(--color-text-muted); text-transform: uppercase; }
.kpi-perso-score.statut-vert { background: var(--color-vert-bg); } .kpi-perso-score.statut-orange { background: var(--color-orange-bg); } .kpi-perso-score.statut-rouge { background: var(--color-rouge-bg); }
.filtres-personnel { display: flex; align-items: center; gap: var(--space-4); margin-bottom: var(--space-3); flex-wrap: wrap; }
.filtres-personnel .choix-personne { margin-bottom: 0; }
.case-regrouper { display: flex; align-items: center; gap: var(--space-2); font-size: var(--font-size-sm); font-weight: 600; }
.groupe-statut { margin-bottom: var(--space-6); }
.groupe-statut h3 { font-size: var(--font-size-md); margin: 0 0 var(--space-2); }
.tendance-icone.hausse { color: var(--color-vert); } .tendance-icone.baisse { color: var(--color-rouge); } .tendance-icone.stable { color: var(--color-text-muted); }
</style>