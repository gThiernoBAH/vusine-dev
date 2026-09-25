<script setup>
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import { FileDown } from 'lucide-vue-next'
import DataTable from '@/components/DataTable.vue'
import ParetoChart from './ParetoChart.vue'

const activeTab = ref('par_ligne')
const dateDebut = ref(new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10))
const dateFin = ref(new Date().toISOString().slice(0, 10))

const parLigne = ref([])
const parProduit = ref([])
const vueDirection = ref(null)
// *** AJOUT 2026-09-23 *** : onglet Historique des scans (tous les opérateurs).
const historiqueScans = ref([])
// *** AJOUT 2026-09-24 (Palier 0) *** : onglet Pareto des arrêts (causes, coût estimé).
const pareto = ref(null)
// *** AJOUT 2026-09-24 (Palier 1) *** : onglet TRS (disponibilité x performance x qualité).
const trs = ref(null)
// *** AJOUT 2026-09-24 (Palier 1) *** : onglet Changements de série (SMED).
const smed = ref(null)
const ligneId = ref('')
const lignesFiltre = ref([])
const causesDepliees = ref(new Set())
const isLoading = ref(true)
const errorMessage = ref('')

async function charger() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const params = { date_debut: dateDebut.value, date_fin: dateFin.value }
    if (ligneId.value) params.ligne_id = ligneId.value   // 2026-09-24 : filtre ligne commun à TOUS les onglets
    if (activeTab.value === 'par_ligne') {
      const res = await apiClient.get('/rapports/par-ligne', { params })
      parLigne.value = res.data
    } else if (activeTab.value === 'par_produit') {
      const res = await apiClient.get('/rapports/par-produit', { params })
      parProduit.value = res.data
    } else if (activeTab.value === 'historique') {
      const res = await apiClient.get('/rapports/historique-scans', { params })
      historiqueScans.value = res.data
    } else if (activeTab.value === 'smed') {
      const res = await apiClient.get('/rapports/changements-serie', { params })
      smed.value = res.data
    } else if (activeTab.value === 'trs') {
      const res = await apiClient.get('/rapports/trs', { params })
      trs.value = res.data
    } else if (activeTab.value === 'pareto') {
      const res = await apiClient.get('/rapports/pareto-arrets', { params })
      pareto.value = res.data
      causesDepliees.value = new Set()
    } else {
      const res = await apiClient.get('/rapports/vue-direction', { params })
      vueDirection.value = res.data
    }
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger le rapport.'
  } finally {
    isLoading.value = false
  }
}
onMounted(async () => {
  charger()
  // Liste des lignes pour le filtre du Pareto -- non bloquant : sans elle, le filtre reste
  // simplement vide et le Pareto « toutes lignes » fonctionne quand même.
  try { lignesFiltre.value = (await apiClient.get('/entities/lignes')).data } catch { /* filtre indisponible */ }
})

// *** REFONDU 2026-09-24 *** : un seul export pour tous les onglets (Excel / PDF / CSV), même
// période, même filtre ligne -- remplace les sept fonctions quasi identiques.
const EXPORTS = {
  par_ligne: ['/rapports/par-ligne/export', 'rapport_vusine'],
  par_produit: ['/rapports/par-produit/export', 'rapport_produits'],
  vue_direction: ['/rapports/vue-direction/export', 'vue_direction'],
  historique: ['/rapports/historique-scans/export', 'historique_scans'],
  pareto: ['/rapports/pareto-arrets/export', 'pareto_arrets'],
  smed: ['/rapports/changements-serie/export', 'changements_serie'],
  trs: ['/rapports/trs/export', 'trs'],
}
async function exporter(format) {
  const [chemin, base] = EXPORTS[activeTab.value]
  const params = { date_debut: dateDebut.value, date_fin: dateFin.value, format }
  if (ligneId.value) params.ligne_id = ligneId.value
  const res = await apiClient.get(chemin, { params, responseType: 'blob' })
  const url = window.URL.createObjectURL(new Blob([res.data]))
  const a = document.createElement('a')
  a.href = url
  a.download = `${base}_${dateDebut.value}_${dateFin.value}.${format}`
  a.click()
  window.URL.revokeObjectURL(url)
}

const fmtNombre = v => Math.round(v).toLocaleString('fr-FR')
// Une décimale FIXE : l'API renvoie 97.0, que JavaScript réduit à « 97 » -- d'où « 97 % » à côté de
// « 92,2 % ». toLocaleString force « 97,0 % » (corrigé le 2026-09-24, trouvé par les tests d'interface).
const fmtPct = v => `${Number(v).toLocaleString('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`
// null = coût non calculable (pas de planning ce jour-là, ou valeur de pièce manquante) : « n/d »,
// jamais 0 -- un zéro laisserait croire qu'un arrêt n'a rien coûté.
const fmtPct1 = v => (v === null || v === undefined ? '—' : fmtPct(v))
// Couleur d'un TRS par rapport à la cible paramétrée (trs_cible_pct) : atteint = vert,
// à moins de 15 points = orange, au-delà = rouge.
function classeTrs(valeur) {
  // Données insuffisantes : aucune couleur d'alarme (un 0 % sans scans n'est pas une alerte).
  if (valeur === null || valeur === undefined || !trs.value || trs.value.donnees_insuffisantes) return 'gris'
  const cible = trs.value.cible_pct
  return valeur >= cible ? 'vert' : valeur >= cible - 15 ? 'orange' : 'rouge'
}
const fmtFcfa = v => (v === null || v === undefined ? 'n/d' : `${fmtNombre(v)} FCFA`)

function toggleCause(row) {
  const s = new Set(causesDepliees.value)
  s.has(row.cause_id) ? s.delete(row.cause_id) : s.add(row.cause_id)
  causesDepliees.value = s
}

const fmtPctEntier = v => (v === null || v === undefined ? '—' : `${v} %`)
const COLONNES_PAR_LIGNE = [
  { key: 'code', label: 'Ligne', format: (v, r) => `${r.code} — ${r.nom}` },
  { key: 'reel_total', label: 'Réel', align: 'right', format: fmtNombre },
  { key: 'theorique_total', label: 'Théorique', align: 'right', format: fmtNombre },
  { key: 'performance_moyenne', label: 'Performance', align: 'right', format: fmtPctEntier },
  { key: 'nb_palettes', label: 'Palettes', align: 'right' },
  { key: 'temps_arret_min', label: "Temps d'arrêt", align: 'right', format: v => `${fmtNombre(v)} min` },
]
const COLONNES_PAR_PRODUIT = [
  { key: 'nom', label: 'Produit' },
  { key: 'quantite_totale', label: 'Quantité totale', align: 'right', format: fmtNombre },
  { key: 'nb_palettes', label: 'Palettes', align: 'right' },
  { key: 'nb_palettes_completes', label: 'Complètes', align: 'right' },
  { key: 'nb_palettes_partielles', label: 'Partielles', align: 'right' },
]
const COLONNES_ATELIER = [
  { key: 'section_nom', label: 'Atelier' },
  { key: 'reel_total', label: 'Réel', align: 'right', format: fmtNombre },
  { key: 'theorique_total', label: 'Théorique', align: 'right', format: fmtNombre },
  { key: 'performance_moyenne', label: 'Performance', align: 'right', format: fmtPctEntier },
  { key: 'nb_lignes', label: 'Lignes', align: 'right' },
]

const COLONNES_TRS = [
  { key: 'code', label: 'Ligne', format: (v, r) => `${r.code} — ${r.nom}` },
  { key: 'jours', label: 'Jours', align: 'right', title: 'Jours complets pris en compte (planning > 0, poste terminé)' },
  { key: 'qte_planifiee', label: 'Planifié', align: 'right', format: fmtNombre },
  { key: 'production_conforme', label: 'Conforme', align: 'right', format: fmtNombre },
  { key: 'rebuts', label: 'Rebuts', align: 'right', format: fmtNombre },
  { key: 'minutes_arret', label: 'Arrêt', align: 'right', title: "Minutes d'arrêt pendant les heures de poste", format: v => `${fmtNombre(v)} min` },
  { key: 'disponibilite_pct', label: 'Dispo.', align: 'right', title: 'Disponibilité : part du temps de poste où la ligne pouvait produire', format: fmtPct1 },
  { key: 'performance_pct', label: 'Perf.', align: 'right', title: 'Performance : production brute / production attendue pendant le temps de marche', format: fmtPct1 },
  { key: 'qualite_pct', label: 'Qualité', align: 'right', title: 'Qualité : production conforme / production brute', format: fmtPct1 },
  { key: 'trs_pct', label: 'TRS', align: 'right', title: 'Disponibilité x Performance x Qualité = production conforme / quantité planifiée', format: fmtPct1 },
  { key: 'pertes_arrets_pieces', label: 'Perte arrêts', align: 'right', title: 'Pièces non produites à cause des arrêts', format: fmtNombre },
  { key: 'pertes_cadence_pieces', label: 'Perte cadence', align: 'right', title: 'Pièces perdues par une cadence inférieure à la référence (négatif = cadence dépassée)', format: fmtNombre },
  { key: 'pertes_rebuts_pieces', label: 'Perte rebuts', align: 'right', title: 'Pièces rebutées', format: fmtNombre },
]

const fmtMin = v => (v === null || v === undefined ? '—' : `${fmtNombre(v)} min`)
const fmtHeure = iso => new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
const COLONNES_SMED_LIGNES = [
  { key: 'ligne_code', label: 'Ligne' },
  { key: 'nb_changements', label: 'Changements', align: 'right' },
  { key: 'moyenne_min', label: 'Moyenne', align: 'right', format: fmtMin },
  { key: 'mediane_min', label: 'Médiane', align: 'right', format: fmtMin },
  { key: 'meilleur_min', label: 'Meilleur', align: 'right', format: fmtMin },
  { key: 'pire_min', label: 'Pire', align: 'right', format: fmtMin },
  { key: 'moyenne_declaree_min', label: 'Déclaré (moy.)', align: 'right', title: 'Temps moyen déclaré sur la tablette (arrêts « Changement produit »), quand il existe', format: fmtMin },
]
const COLONNES_SMED = [
  { key: 'jour', label: 'Jour', format: v => new Date(v).toLocaleDateString('fr-FR') },
  { key: 'ligne_code', label: 'Ligne' },
  { key: 'produit_avant', label: 'Produit avant' },
  { key: 'produit_apres', label: 'Produit après' },
  { key: 'dernier_scan_avant', label: 'Dernier scan A', format: fmtHeure },
  { key: 'premier_scan_apres', label: 'Premier scan B', format: fmtHeure },
  { key: 'ecart_scans_min', label: 'Écart', align: 'right', title: "Écart entre le dernier scan du produit A et le premier scan du produit B, hors pause. Inclut le remplissage de la 1re palette de B.", format: fmtMin },
  { key: 'arret_declare_min', label: 'Déclaré', align: 'right', title: 'Temps déclaré sur la tablette (arrêt « Changement produit ») dans cet intervalle', format: fmtMin },
]

const COLONNES_PARETO = [
  { key: 'rang', label: '#', align: 'right' },
  { key: 'cause', label: 'Cause' },
  { key: 'duree_min', label: 'Durée', title: "Durée totale d'arrêt, plafonnée à la période", align: 'right', format: v => `${fmtNombre(v)} min` },
  { key: 'nb_arrets', label: 'Arrêts', align: 'right' },
  { key: 'pct', label: '% du total', align: 'right', format: fmtPct },
  { key: 'pct_cumule', label: '% cumulé', title: 'Cumul dans l\'ordre décroissant : la courbe de Pareto', align: 'right', format: fmtPct },
  { key: 'cout_fcfa', label: 'Coût estimé', align: 'right',
    title: 'Production planifiée perdue pendant les heures de poste, valorisée. « n/d » si le planning ou la valeur manque.',
    format: fmtFcfa },
  { key: 'actions', label: '', sortable: false, searchable: false },
]

const COLONNES_HISTORIQUE = [
  { key: 'created_at', label: 'Date / heure',
    format: v => new Date(v).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) },
  { key: 'operateur_nom', label: 'Opérateur' },
  { key: 'operateur_matricule', label: 'Matricule', format: v => v ?? '—' },
  { key: 'ligne_code', label: 'Ligne' },
  { key: 'produit_nom', label: 'Produit', format: v => v ?? '—' },
  { key: 'numero_lot', label: 'N° lot' },
  { key: 'nb_cartons', label: 'Cartons', align: 'right' },
  { key: 'colisage_carton', label: 'Colisage', align: 'right' },
  { key: 'quantite_totale', label: 'Quantité', align: 'right' },
  { key: 'nb_rebuts', label: 'Rebuts', title: 'Pièces rebutées déclarées pendant le remplissage de la palette', align: 'right' },
  { key: 'complete', label: 'Statut',
    format: (v, row) => v ? 'Complète' : `Partielle${row.motif_partielle ? ' — ' + row.motif_partielle : ''}` },
]
</script>

<template>
  <div class="rapports">
    <header class="page-header">
      <h1>Rapports</h1>
      <p class="subtitle">Production, performance et pertes sur une période</p>
    </header>

    <div class="controls">
      <div class="tabs">
        <button :class="['tab-btn', { active: activeTab === 'par_ligne' }]" @click="activeTab = 'par_ligne'; charger()">Par ligne</button>
        <button :class="['tab-btn', { active: activeTab === 'par_produit' }]" @click="activeTab = 'par_produit'; charger()">Par produit</button>
        <button :class="['tab-btn', { active: activeTab === 'vue_direction' }]" @click="activeTab = 'vue_direction'; charger()">Vue Direction</button>
        <button :class="['tab-btn', { active: activeTab === 'historique' }]" @click="activeTab = 'historique'; charger()" title="Tous les scans effectués, tous opérateurs et toutes lignes confondus">Historique des scans</button>
        <button :class="['tab-btn', { active: activeTab === 'pareto' }]" @click="activeTab = 'pareto'; charger()" title="Quelles causes d'arrêt pèsent le plus, et ce qu'elles coûtent">Pareto des arrêts</button>
        <button :class="['tab-btn', { active: activeTab === 'smed' }]" @click="activeTab = 'smed'; charger()" title="Durée des changements de série, déduite des scans de palettes">Changements de série</button>
        <button :class="['tab-btn', { active: activeTab === 'trs' }]" @click="activeTab = 'trs'; charger()" title="Taux de Rendement Synthétique : disponibilité x performance x qualité">TRS</button>
      </div>
    </div>

    <!-- *** UNIFORMISÉ 2026-09-24 *** : la même barre sous les onglets pour TOUS les écrans
         Rapports : période, ligne, puis les trois exports ; la recherche du tableau vient juste
         dessous (DataTable). -->
    <div class="toolbar">
      <div class="dates">
        <input type="date" v-model="dateDebut" @change="charger" />
        <span>→</span>
        <input type="date" v-model="dateFin" @change="charger" />
      </div>
      <select v-model="ligneId" class="ligne-select" title="Limiter le rapport à une ligne" @change="charger">
        <option value="">Toutes les lignes</option>
        <option v-for="l in lignesFiltre" :key="l.id" :value="l.id">{{ l.code }} — {{ l.nom }}</option>
      </select>
      <button class="export-btn" title="Télécharger ce rapport au format Excel" @click="exporter('xlsx')"><FileDown :size="16" /> Excel</button>
      <button class="export-btn" title="Télécharger ce rapport au format PDF" @click="exporter('pdf')"><FileDown :size="16" /> PDF</button>
      <button class="export-btn" title="Télécharger ce rapport au format CSV" @click="exporter('csv')"><FileDown :size="16" /> CSV</button>
    </div>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>

    <!-- Par ligne -->
    <DataTable
      v-else-if="activeTab === 'par_ligne'"
      :columns="COLONNES_PAR_LIGNE" :rows="parLigne" :row-key="r => r.ligne_id" :page-size="100"
      :default-sort="{ key: 'code', dir: 1 }" empty-text="Aucune ligne sur cette période."
    />

    <!-- Par produit -->
    <DataTable
      v-else-if="activeTab === 'par_produit'"
      :columns="COLONNES_PAR_PRODUIT" :rows="parProduit" :row-key="r => r.produit_id" :page-size="100"
      :default-sort="{ key: 'quantite_totale', dir: -1 }" empty-text="Aucune palette rattachée à un produit sur cette période."
    />

    <!-- Changements de série (*** AJOUT 2026-09-24, Palier 1 ***) -->
    <div v-else-if="activeTab === 'smed' && smed" class="smed-view">
      <div class="kpis">
        <div class="kpi"><span class="kpi-label">Changements</span><strong>{{ smed.nb_changements }}</strong><small>sur la période</small></div>
        <div class="kpi"><span class="kpi-label">Moyenne</span><strong>{{ fmtMin(smed.moyenne_min) }}</strong><small>écart entre scans</small></div>
        <div class="kpi"><span class="kpi-label">Meilleur</span><strong>{{ fmtMin(smed.meilleur_min) }}</strong><small>médiane {{ fmtMin(smed.mediane_min) }}</small></div>
        <div v-if="smed.objectif_min" :class="['kpi', 'kpi-objectif', { 'kpi-alerte': smed.nb_au_dessus_objectif > 0 }]">
          <span class="kpi-label">Objectif</span><strong>{{ smed.objectif_min }} min</strong>
          <small>{{ smed.nb_au_dessus_objectif }} changement(s) au-dessus</small>
        </div>
      </div>
      <p class="info-banner">
        L'écart mesuré va du dernier scan du produit précédent au premier scan du produit suivant, hors pause et hors heures de poste.
        Il <strong>inclut le remplissage de la première palette</strong> : c'est une borne haute, à suivre comme une tendance.
      </p>
      <p v-if="!smed.nb_changements" class="empty">Aucun changement de série détecté sur cette période.</p>
      <template v-else>
        <h3 class="sous-titre">Par ligne</h3>
        <DataTable :columns="COLONNES_SMED_LIGNES" :rows="smed.lignes" :row-key="r => r.ligne_id" :page-size="50" empty-text="—" />
        <h3 class="sous-titre">Détail des changements</h3>
        <DataTable
          :columns="COLONNES_SMED" :rows="smed.changements" :row-key="r => r.ligne_id + r.premier_scan_apres" :page-size="25"
          empty-text="Aucun changement."
        >
          <template #cell-ecart_scans_min="{ row }">
            <span :class="['badge', row.au_dessus_objectif ? 'badge-rouge' : 'badge-gris']"
                  :title="row.au_dessus_objectif ? 'Au-dessus de l\'objectif de ' + smed.objectif_min + ' min' : ''">{{ fmtMin(row.ecart_scans_min) }}</span>
          </template>
        </DataTable>
      </template>
    </div>

    <!-- TRS (*** AJOUT 2026-09-24, Palier 1 ***) -->
    <div v-else-if="activeTab === 'trs' && trs" class="trs-view">
      <div class="kpis">
        <div :class="['kpi', 'kpi-trs', 'trs-' + (trs.donnees_insuffisantes ? 'gris' : classeTrs(trs.usine.trs_pct))]">
          <span class="kpi-label">TRS</span>
          <strong>{{ fmtPct1(trs.usine.trs_pct) }}</strong>
          <small>cible {{ String(trs.cible_pct).replace('.', ',') }} %</small>
        </div>
        <div class="kpi" title="Part du temps de poste où les lignes pouvaient produire">
          <span class="kpi-label">Disponibilité</span><strong>{{ fmtPct1(trs.usine.disponibilite_pct) }}</strong>
          <small>{{ fmtNombre(trs.usine.minutes_arret) }} min d'arrêt</small>
        </div>
        <div class="kpi" title="Production brute / production attendue pendant le temps de marche">
          <span class="kpi-label">Performance</span><strong>{{ fmtPct1(trs.usine.performance_pct) }}</strong>
          <small>cadence réelle vs planifiée</small>
        </div>
        <div class="kpi" title="Production conforme / production brute">
          <span class="kpi-label">Qualité</span>
          <strong>{{ trs.qualite_renseignee ? fmtPct1(trs.usine.qualite_pct) : 'non mesurée' }}</strong>
          <small>{{ fmtNombre(trs.usine.rebuts) }} rebut(s) déclaré(s)</small>
        </div>
      </div>

      <p v-if="trs.donnees_insuffisantes" class="warn-banner" role="alert">
        Peu de scans enregistrés sur la période ({{ trs.nb_palettes }} palette{{ trs.nb_palettes > 1 ? 's' : '' }}) : les pourcentages ne sont pas
        représentatifs. Un 0 % traduit ici l'absence de scans, pas forcément une contre-performance.
      </p>
      <p v-if="trs.nb_lignes_sans_planning > 0 && trs.nb_jours > 0" class="info-banner">
        {{ trs.nb_lignes_sans_planning }} ligne(s) sans planning sur la période : non évaluées, donc absentes du tableau.
      </p>
      <p v-if="!trs.qualite_renseignee && trs.nb_jours > 0" class="info-banner">
        Aucun rebut n'a été déclaré sur la période : la Qualité est comptée à 100 % par défaut, elle n'est pas mesurée.
        Les opérateurs déclarent les rebuts au scan de chaque palette (« Rebuts constatés »).
      </p>
      <p v-if="trs.pieces_hors_planning > 0" class="warn-banner">
        {{ fmtNombre(trs.pieces_hors_planning) }} pièces ont été produites sans planning ce jour-là (ou un jour fermé) : elles ne sont pas comptées dans le TRS.
      </p>
      <p v-if="trs.jour_en_cours_exclu" class="info-banner">Aujourd'hui n'est pas compté : le TRS ne porte que sur des journées complètes.</p>

      <p v-if="!trs.nb_jours" class="empty">Aucune journée complète avec planning sur cette période.</p>
      <template v-else>
        <p class="formule-trs">
          TRS = Disponibilité × Performance × Qualité = production conforme ÷ quantité planifiée
          ({{ trs.nb_jours }} jour(s) complet(s)).
        </p>
        <DataTable
          :columns="COLONNES_TRS" :rows="trs.lignes" :row-key="r => r.ligne_id" :page-size="50"
          :default-sort="{ key: 'trs_pct', dir: 1 }" empty-text="Aucune ligne avec planning sur la période."
        >
          <template #cell-trs_pct="{ row }">
            <span :class="['badge', 'trs-badge', 'trs-' + classeTrs(row.trs_pct)]">{{ fmtPct1(row.trs_pct) }}</span>
          </template>
        </DataTable>

        <div v-if="trs.evolution.length > 1" class="section-card evolution-trs">
          <h2>Évolution quotidienne du TRS (usine)</h2>
          <div class="evolution-row">
            <div v-for="j in trs.evolution" :key="j.jour" class="evolution-jour">
              <div :class="['evolution-valeur', 'txt-' + classeTrs(j.trs_pct)]">{{ fmtPct1(j.trs_pct) }}</div>
              <div class="evolution-date">{{ new Date(j.jour).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' }) }}</div>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- Pareto des arrêts (*** AJOUT 2026-09-24, Palier 0 ***) -->
    <div v-else-if="activeTab === 'pareto' && pareto" class="pareto-view">
      <div class="kpis">
        <div class="kpi">
          <span class="kpi-label">Temps d'arrêt</span>
          <strong>{{ fmtNombre(pareto.total_duree_min) }} min</strong>
          <small>≈ {{ (pareto.total_duree_min / 60).toLocaleString('fr-FR', { maximumFractionDigits: 1 }) }} h</small>
        </div>
        <div class="kpi">
          <span class="kpi-label">Arrêts</span>
          <strong>{{ pareto.total_nb_arrets }}</strong>
          <small>sur la période</small>
        </div>
        <div class="kpi">
          <span class="kpi-label">Coût estimé</span>
          <strong>{{ fmtFcfa(pareto.total_cout_fcfa) }}</strong>
          <small>valorisé au « {{ pareto.libelle_valeur }} »</small>
        </div>
      </div>

      <p v-if="!pareto.valorisation_configuree" class="info-banner">
        Aucune valeur de pièce n'est configurée : les coûts ne sont pas calculés. Renseignez la valeur par défaut
        (Administration → Paramètres) ou la valeur de chaque produit (Administration → Valeur des produits).
      </p>
      <p v-else-if="pareto.minutes_non_valorisees > 0" class="warn-banner">
        {{ fmtNombre(pareto.minutes_non_valorisees) }} min d'arrêt n'ont pas pu être valorisées (pas de planning ce
        jour-là, ou un produit planifié sans valeur) : le coût affiché est un minimum.
      </p>
      <p v-if="pareto.nb_arrets_non_clotures > 0" class="warn-banner">
        {{ pareto.nb_arrets_non_clotures }} arrêt(s) jamais clôturé(s) : comptés jusqu'à la fin de la période. À vérifier
        sur la tablette — une saisie oubliée gonfle la durée.
      </p>

      <div class="section-card">
        <h2>Pareto des causes d'arrêt</h2>
        <p v-if="!pareto.causes.length" class="empty">Aucun arrêt sur la période.</p>
        <template v-else>
          <ParetoChart :causes="pareto.causes" />
          <p class="chart-legende">Barres pleines : les causes qui expliquent les premiers 80 % du temps d'arrêt.</p>
        </template>
      </div>

      <DataTable
        v-if="pareto.causes.length"
        :columns="COLONNES_PARETO" :rows="pareto.causes" :row-key="r => r.cause_id"
        :expanded-keys="causesDepliees" :default-sort="{ key: 'rang', dir: 1 }" :page-size="50"
        empty-text="Aucun arrêt sur la période."
      >
        <template #cell-actions="{ row }">
          <button type="button" class="vbtn vbtn-outline" :aria-expanded="causesDepliees.has(row.cause_id)"
                  title="Voir la répartition de cette cause par ligne et par équipement" @click="toggleCause(row)">
            {{ causesDepliees.has(row.cause_id) ? 'Masquer' : 'Détail' }}
          </button>
        </template>
        <template #expanded-row="{ row }">
          <div class="detail-grid">
            <div>
              <h3>Par ligne</h3>
              <table class="rapport-table nested">
                <thead><tr><th>Ligne</th><th>Durée</th><th>Arrêts</th><th>Coût estimé</th></tr></thead>
                <tbody>
                  <tr v-for="l in row.par_ligne" :key="l.ligne_id">
                    <td>{{ l.ligne_code }}</td><td>{{ fmtNombre(l.duree_min) }} min</td>
                    <td>{{ l.nb_arrets }}</td><td>{{ fmtFcfa(l.cout_fcfa) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div>
              <h3>Par équipement</h3>
              <table class="rapport-table nested">
                <thead><tr><th>Équipement</th><th>Durée</th><th>Arrêts</th></tr></thead>
                <tbody>
                  <tr v-for="e in row.par_equipement" :key="e.equipement">
                    <td>{{ e.equipement }}</td><td>{{ fmtNombre(e.duree_min) }} min</td><td>{{ e.nb_arrets }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
      </DataTable>
    </div>

    <!-- Vue Direction -->
    <!-- *** CORRIGÉ 2026-09-24 *** : la condition ne testait que `vueDirection` -- une fois
         cet onglet visité, son contenu s'affichait aussi sur « Historique des scans » (la
         chaîne v-else-if tombait dessus avant d'atteindre le bon onglet). -->
    <div v-else-if="activeTab === 'vue_direction' && vueDirection" class="vue-direction">
      <div class="two-col">
        <div class="section-card">
          <h2>Top 5 lignes</h2>
          <ol>
            <li v-for="r in vueDirection.top" :key="r.ligne_id">{{ r.code }} — {{ r.performance_moyenne }}%</li>
          </ol>
        </div>
        <div class="section-card">
          <h2>Flop 5 lignes</h2>
          <ol>
            <li v-for="r in vueDirection.flop" :key="r.ligne_id">{{ r.code }} — {{ r.performance_moyenne }}%</li>
          </ol>
        </div>
      </div>

      <div class="section-card">
        <h2>Performance par atelier</h2>
        <p v-if="!vueDirection.par_atelier.length" class="empty">Aucune donnée sur la période.</p>
        <DataTable v-else :columns="COLONNES_ATELIER" :rows="vueDirection.par_atelier" :row-key="r => r.section_nom" :page-size="50" empty-text="Aucune donnée sur la période." />
      </div>

      <div class="section-card">
        <h2>Principales pertes par cause</h2>
        <p v-if="!vueDirection.pertes_par_cause.length" class="empty">Aucun arrêt sur la période.</p>
        <ul v-else class="pertes-list">
          <li v-for="p in vueDirection.pertes_par_cause" :key="p.cause">
            <span>{{ p.cause }}</span><strong>{{ p.duree_min }} min</strong>
          </li>
        </ul>
      </div>

      <div class="section-card">
        <h2>Évolution quotidienne (performance usine)</h2>
        <div class="evolution-row">
          <div v-for="j in vueDirection.evolution_quotidienne" :key="j.jour" class="evolution-jour">
            <div class="evolution-valeur">{{ j.performance_pct !== null ? j.performance_pct + '%' : '—' }}</div>
            <div class="evolution-date">{{ new Date(j.jour).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' }) }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Historique des scans (*** AJOUT 2026-09-23 ***) -->
    <DataTable
      v-else-if="activeTab === 'historique'"
      :columns="COLONNES_HISTORIQUE" :rows="historiqueScans" :row-key="(r, i) => i"
      :default-sort="{ key: 'created_at', dir: -1 }"
      empty-text="Aucun scan sur cette période."
    >
      <template #cell-complete="{ row }">
        <span :class="['badge', row.complete ? 'badge-vert' : 'badge-orange']">
          {{ row.complete ? 'Complète' : `Partielle${row.motif_partielle ? ' — ' + row.motif_partielle : ''}` }}
        </span>
      </template>
    </DataTable>
  </div>
</template>

<style scoped>
.rapports { padding: var(--space-6); overflow-y: auto; height: 100%; }
.page-header h1 { margin: 0; font-size: var(--font-size-2xl); }
.subtitle { color: var(--color-text-muted); margin: 4px 0 var(--space-6); }

.controls { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-4); flex-wrap: wrap; gap: var(--space-3); }
.tabs { display: flex; gap: var(--space-2); }
.tab-btn {
  border: 1px solid var(--color-border); background: var(--color-surface); color: var(--color-text-muted);
  border-radius: var(--radius-md); padding: var(--space-2) var(--space-4); font-size: var(--font-size-sm); font-weight: 600; cursor: pointer;
}
.tab-btn.active { background: var(--color-brand); color: var(--color-text-inverse); border-color: var(--color-brand); }

.toolbar { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; margin-bottom: var(--space-4); }
.dates { display: flex; align-items: center; gap: var(--space-2); }
.kpi-trs.trs-gris { border-left-color: var(--color-border); }
.dates input { height: 36px; padding: 0 var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-md); }

.export-btn {
  display: inline-flex; align-items: center; gap: var(--space-2);
  height: 36px; padding: 0 var(--space-3); border: 1px solid var(--color-border);
  background: var(--color-surface); color: var(--color-text); border-radius: var(--radius-md);
  font-size: var(--font-size-sm); font-weight: 600; cursor: pointer;
}
.export-btn:hover { background: var(--color-brand-light); border-color: var(--color-brand); }

.error-banner { background: var(--color-rouge-bg); color: var(--color-rouge); padding: var(--space-3); border-radius: var(--radius-md); }
.loading, .empty { color: var(--color-text-muted); }

.rapport-table {
  width: 100%; border-collapse: collapse; background: var(--color-surface);
  border: 1px solid var(--color-border); border-radius: var(--radius-lg); overflow: hidden;
}
.rapport-table th { text-align: left; background: var(--color-brand-light); color: var(--color-brand-dark); font-size: var(--font-size-xs); padding: var(--space-3); }
.rapport-table td { padding: var(--space-3); border-top: 1px solid var(--color-border); font-size: var(--font-size-sm); }
.rapport-table.nested { box-shadow: none; border-radius: var(--radius-md); }
.empty-row { text-align: center; color: var(--color-text-muted); padding: var(--space-6) !important; }

.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-4); margin-bottom: var(--space-4); }
.section-card {
  background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg);
  padding: var(--space-4); margin-bottom: var(--space-4); box-shadow: var(--shadow-card);
}
.section-card h2 { font-size: var(--font-size-base); margin: 0 0 var(--space-3); }
.section-card ol { margin: 0; padding-left: 20px; font-size: var(--font-size-sm); }

.pertes-list { list-style: none; margin: 0; padding: 0; }
.pertes-list li { display: flex; justify-content: space-between; padding: var(--space-2) 0; border-bottom: 1px solid var(--color-border); font-size: var(--font-size-sm); }
.pertes-list li:last-child { border-bottom: none; }

.evolution-row { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.evolution-jour { text-align: center; min-width: 60px; }
.evolution-valeur { font-weight: 700; }
.evolution-date { font-size: var(--font-size-xs); color: var(--color-text-muted); }

/* *** AJOUT 2026-09-23 *** : badges de statut pour l'onglet Historique des scans. */
.badge { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: var(--font-size-xs); font-weight: 700; white-space: nowrap; }
.badge-vert { background: var(--color-vert-bg); color: var(--color-vert); }
.badge-orange { background: var(--color-orange-bg); color: #92400E; }

/* *** AJOUT 2026-09-24 (Palier 0) *** : onglet Pareto des arrêts. */
.ligne-select { height: 36px; padding: 0 var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); max-width: 220px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: var(--space-4); margin-bottom: var(--space-4); }
.kpi {
  background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg);
  padding: var(--space-4); box-shadow: var(--shadow-card); display: flex; flex-direction: column; gap: 2px;
}
.kpi-label { font-size: var(--font-size-xs); color: var(--color-text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: .03em; }
.kpi strong { font-size: var(--font-size-xl); }
.kpi small { color: var(--color-text-muted); font-size: var(--font-size-xs); }
.info-banner { background: var(--color-brand-light); color: var(--color-brand-dark); padding: var(--space-3); border-radius: var(--radius-md); font-size: var(--font-size-sm); }
.warn-banner { background: var(--color-orange-bg); color: #92400E; padding: var(--space-3); border-radius: var(--radius-md); font-size: var(--font-size-sm); }
.chart-legende { margin: var(--space-2) 0 0; font-size: var(--font-size-xs); color: var(--color-text-muted); }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-4); padding: var(--space-3); }
.detail-grid h3 { margin: 0 0 var(--space-2); font-size: var(--font-size-sm); }
@media (max-width: 900px) { .detail-grid { grid-template-columns: 1fr; } }

/* *** AJOUT 2026-09-24 (Palier 1) *** : onglet TRS. Couleurs relatives à la cible paramétrée. */
.badge-rouge { background: var(--color-rouge-bg); color: var(--color-rouge); }
.badge-gris { background: var(--color-border); color: var(--color-text); }
.sous-titre { margin: var(--space-4) 0 var(--space-2); font-size: var(--font-size-md); }
.kpi-alerte { border-left: 6px solid var(--color-rouge); }
.kpi-trs { border-left: 6px solid var(--color-border); }
.kpi-trs.trs-vert { border-left-color: var(--color-vert); }
.kpi-trs.trs-orange { border-left-color: var(--color-orange); }
.kpi-trs.trs-rouge { border-left-color: var(--color-rouge); }
.trs-badge.trs-vert { background: var(--color-vert-bg); color: var(--color-vert); }
.trs-badge.trs-orange { background: var(--color-orange-bg); color: #92400E; }
.trs-badge.trs-rouge { background: var(--color-rouge-bg); color: var(--color-rouge); }
.trs-badge.trs-gris { background: var(--color-border); color: var(--color-text-muted); }
.txt-vert { color: var(--color-vert); } .txt-orange { color: #92400E; } .txt-rouge { color: var(--color-rouge); }
.formule-trs { font-size: var(--font-size-xs); color: var(--color-text-muted); margin: 0 0 var(--space-3); }
.evolution-trs { margin-top: var(--space-4); }
</style>
