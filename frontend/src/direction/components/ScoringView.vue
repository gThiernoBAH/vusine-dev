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
import { RefreshCw } from 'lucide-vue-next'

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
  if (v === null || v === undefined) return 'gris'
  return v >= 100 ? 'vert' : v >= 80 ? 'orange' : 'rouge'
}
const COLONNES = [
  { key: 'code', label: 'Ligne', format: (v, r) => `${r.code} — ${r.nom}` },
  { key: 'section_nom', label: 'Section', format: v => v || '—' },
  { key: 'effectif', label: 'Effectif', align: 'right', title: "Nombre de personnes affectées à la ligne sur la période (un nombre, jamais des noms)", format: v => (v === null || v === undefined ? 'non renseigné' : v) },
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
const actualiser = () => (onglet.value === 'suivi' ? chargerSuivi() : chargerEquipes())
const heureFr = iso => new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })
</script>

<template>
  <div class="scoring">
    <header class="page-header">
      <div>
        <h1>Performance des équipes</h1>
        <p class="subtitle">Score par ligne, arrêts non imputables neutralisés. Aucun classement de personnes.</p>
      </div>
      <button class="btn primary" :disabled="snapshotEnCours" @click="lancerSnapshot">
        <RefreshCw :size="16" /> {{ snapshotEnCours ? 'Snapshot en cours…' : 'Lancer le snapshot du jour' }}
      </button>
    </header>
    <p v-if="snapshotMessage" class="snapshot-banner">{{ snapshotMessage }}</p>

    <div class="tabs">
      <button :class="['tab-btn', { active: onglet === 'equipes' }]" @click="onglet = 'equipes'">Équipes</button>
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

    <!-- SUIVI INDIVIDUEL -->
    <template v-else>
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
</style>
