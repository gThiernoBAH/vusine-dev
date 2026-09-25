<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import apiClient from '@/api/client'
import StatutBadge from './StatutBadge.vue'
import DataTable from '@/components/DataTable.vue'
import { ArrowLeft, Wrench, Users, PauseCircle, Package, Pencil, ClipboardList } from 'lucide-vue-next'

const router = useRouter()

// *** AJOUT 2026-09-25 *** : colonnes triables (DataTable) pour "Équipe sur la ligne".
const COLONNES_PERSONNEL = [
  { key: 'matricule', label: 'Matricule', format: v => v || '—' },
  { key: 'nom', label: 'Nom' },
  { key: 'user_type', label: 'Fonction' },
  { key: 'categorie_personnel', label: 'Statut' },
  { key: 'heure_debut', label: 'Heure début', sortable: false },
]

const props = defineProps({
  ligneId: { type: Number, required: true },
  jourInitial: { type: String, default: null },  // *** AJOUT 2026-09-18 *** transmis par VueUsineView
})
const emit = defineEmits(['back'])

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const jourSelectionne = ref(props.jourInitial || todayIso())
const estAujourdhui = computed(() => jourSelectionne.value === todayIso())

const detail = ref(null)       // GET /entities/lignes/{id} -- items_planning_jour, équipements, personnel (référentiel, pas daté)
const performance = ref(null)  // GET /dashboard/lignes/{id} -- perf + arrêts du jour choisi
const palettes = ref([])
const isLoading = ref(true)
const errorMessage = ref('')
let pollHandle = null

const user = JSON.parse(sessionStorage.getItem('user') || '{}')
const peutCorriger = user.is_admin || (user.permissions || []).includes('correction_palette')

// *** AJOUT 2026-09-25 *** : compteurs par fonction pour l'en-tête "Équipe sur la ligne".
const compteursPersonnel = computed(() => {
  const liste = detail.value?.personnel || []
  return {
    operateurs: liste.filter(p => p.user_type === 'operateur').length,
    ouvriers: liste.filter(p => p.user_type === 'ouvrier').length,
  }
})

// Édition d'une palette (permission correction_palette, cf. action_routes.corriger_palette)
const paletteEnEdition = ref(null)
const editForm = ref({ nbCartons: 0, colisageCarton: 0, motif: '' })
const editError = ref('')

function ouvrirEdition(p) {
  paletteEnEdition.value = p
  editForm.value = { nbCartons: p.nb_cartons, colisageCarton: p.colisage_carton, motif: '' }
  editError.value = ''
}

async function enregistrerCorrection() {
  try {
    await apiClient.patch(`/actions/palettes/${paletteEnEdition.value.id}`, {
      nb_cartons: editForm.value.nbCartons,
      colisage_carton: editForm.value.colisageCarton,
      motif: editForm.value.motif || null,
    })
    paletteEnEdition.value = null
    fetchAll()
  } catch (e) {
    editError.value = e.response?.data?.detail || 'Échec de la correction.'
  }
}

async function fetchAll() {
  try {
    const [detailRes, perfRes, palettesRes] = await Promise.all([
      apiClient.get(`/entities/lignes/${props.ligneId}`),
      apiClient.get(`/dashboard/lignes/${props.ligneId}`, { params: { jour: jourSelectionne.value } }),
      apiClient.get('/actions/palettes/recentes', { params: { ligne_id: props.ligneId, limit: 10, jour: jourSelectionne.value } }),
    ])
    detail.value = detailRes.data
    performance.value = perfRes.data
    palettes.value = palettesRes.data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger le détail de la ligne.'
  } finally {
    isLoading.value = false
  }
}

function gererPolling() {
  if (pollHandle) { clearInterval(pollHandle); pollHandle = null }
  if (estAujourdhui.value) {
    pollHandle = setInterval(fetchAll, 7000)
  }
}

function startPolling() {
  fetchAll()
  gererPolling()
}

onMounted(startPolling)
onUnmounted(() => { if (pollHandle) clearInterval(pollHandle) })

// Si l'utilisateur clique sur une autre ligne depuis Vue Usine sans redémarrer le
// composant (le parent réutilise LigneDetailView), on recharge proprement.
watch(() => props.ligneId, () => {
  isLoading.value = true
  fetchAll()
})

watch(() => props.jourInitial, (val) => {
  if (val) jourSelectionne.value = val
})

watch(jourSelectionne, () => {
  isLoading.value = true
  fetchAll()
  gererPolling()
})
</script>

<template>
  <div class="ligne-detail">
    <button class="back-btn" @click="emit('back')">
      <ArrowLeft :size="18" /> Retour à Vue Usine
    </button>

    <label class="date-picker">
      <span>Jour consulté</span>
      <input type="date" v-model="jourSelectionne" :max="todayIso()" />
      <span v-if="!estAujourdhui" class="historique-badge">Vue historique — figée</span>
    </label>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>

    <template v-else-if="detail && performance">
      <header class="ligne-header">
        <div>
          <h1>{{ detail.ligne.code }} — {{ detail.ligne.nom }}</h1>
          <p class="subtitle">{{ detail.ligne.section_nom }}</p>
        </div>
        <StatutBadge :statut="performance.ligne.statut" />
      </header>

      <div class="metrics-row">
        <div class="metric-card">
          <div class="metric-value">{{ performance.ligne.reel.toLocaleString('fr-FR') }}</div>
          <div class="metric-label">Réel (pcs)</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">{{ performance.ligne.theorique?.toLocaleString('fr-FR') ?? '—' }}</div>
          <div class="metric-label">Théorique (pcs)</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">{{ performance.ligne.performance_pct ?? '—' }}<span v-if="performance.ligne.performance_pct !== null">%</span></div>
          <div class="metric-label">Performance</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">{{ performance.ligne.retard_min }} min</div>
          <div class="metric-label">Retard</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">{{ performance.nb_palettes_du_jour }}</div>
          <div class="metric-label">Palettes du jour</div>
        </div>
        <!-- *** AJOUT 2026-09-24 (Palier 1) *** : prévision de fin de poste (projection linéaire). -->
        <div v-if="performance.ligne.prevision_fin_poste !== null && performance.ligne.prevision_fin_poste !== undefined" class="metric-card"
             title="Projection linéaire : cadence moyenne observée pendant le temps de marche, maintenue jusqu'à la fin du poste">
          <div class="metric-value">{{ performance.ligne.prevision_fin_poste.toLocaleString('fr-FR') }}</div>
          <div class="metric-label">Fin de poste ≈<template v-if="performance.ligne.objectif_jour"> / {{ performance.ligne.objectif_jour.toLocaleString('fr-FR') }}</template></div>
        </div>
      </div>

      <!-- *** REVU 2026-09-17 *** : remplace l'ancien bloc "Ordre de fabrication en
      cours" (unique, of_cache) par la liste des items du planning hebdomadaire réel --
      une ligne peut avoir 0, 1 ou plusieurs produits planifiés le même jour. -->
      <div class="section-card">
        <h2><ClipboardList :size="16" /> Planning du jour</h2>
        <p v-if="!detail.items_planning_jour.length" class="empty">
          Aucun item de planning pour cette ligne aujourd'hui.
        </p>
        <div v-else class="planning-list">
          <div v-for="item in detail.items_planning_jour" :key="item.id" class="planning-item">
            <div class="planning-item-main">
              <span class="planning-produit">{{ item.produit_nom || '—' }}</span>
              <span class="planning-ref">{{ item.reference_planning || '—' }}</span>
            </div>
            <div class="planning-qty">
              Cible du jour : <strong>{{ item.qty_jour?.toLocaleString('fr-FR') ?? '—' }} pcs</strong>
            </div>
          </div>
        </div>
      </div>

      <div class="two-col">
        <div class="section-card">
          <h2><Wrench :size="16" /> Équipements</h2>
          <p v-if="!detail.equipements.length" class="empty">Aucun équipement affecté actuellement.</p>
          <ul v-else class="item-list">
            <li v-for="eq in detail.equipements" :key="eq.id">
              <div class="item-title">{{ eq.type }} — {{ eq.marque }} {{ eq.modele }}</div>
              <div class="item-sub">{{ eq.numero_interne }} · {{ eq.capacite || '—' }}</div>
              <StatutBadge :statut="eq.statut === 'disponible' ? 'vert' : (eq.statut === 'en_panne' ? 'rouge' : 'orange')" :label="eq.statut" />
            </li>
          </ul>
        </div>

        <div class="section-card">
          <h2><Users :size="16" /> Équipe sur la ligne</h2>
          <!-- *** AJOUT 2026-09-25 *** : compteurs par fonction + tableau détaillé (matricule, fonction,
               statut, poste), demandé côté Direction. Purement du roster (qui est affecté), aucune donnée
               de performance individuelle ici -- pas la même question que le classement nominatif. -->
          <div v-if="detail.personnel.length" class="equipe-compteurs">
            <div class="compteur"><strong>{{ compteursPersonnel.operateurs }}</strong><span>Opérateur(s)</span></div>
            <div class="compteur"><strong>{{ compteursPersonnel.ouvriers }}</strong><span>Ouvrier(s)</span></div>
            <div class="compteur compteur-total"><strong>{{ detail.personnel.length }}</strong><span>Total personnel</span></div>
          </div>
          <p v-if="!detail.personnel.length" class="empty">Aucun personnel affecté actuellement.</p>
          <DataTable v-else :columns="COLONNES_PERSONNEL" :rows="detail.personnel" :row-key="p => p.user_id"
                     :default-sort="{ key: 'nom', dir: 1 }" :page-size="50" empty-text="—">
            <template #cell-user_type="{ row }">{{ row.user_type === 'operateur' ? 'Opérateur' : row.user_type === 'ouvrier' ? 'Ouvrier' : row.user_type }}</template>
            <template #cell-categorie_personnel="{ row }">{{ row.categorie_personnel || '—' }}</template>
            <template #cell-heure_debut="{ }">{{ detail.poste_heure_debut || '—' }}</template>
          </DataTable>
          <p v-if="detail.personnel.length" class="hint" title="Horaire du poste du jour, identique pour toute la ligne -- pas un pointage individuel.">
            « Heure début » = début du poste du jour, pas un pointage par personne.
          </p>
          <button class="btn secondary btn-gerer-equipe" @click="router.push({ path: '/cockpit/admin', query: { onglet: 'affectations' } })">Gérer l'équipe (Affectations)</button>
        </div>
      </div>

      <div class="section-card">
        <h2><Package :size="16" /> Palettes récentes</h2>
        <p v-if="!palettes.length" class="empty">Aucune palette récente.</p>
        <table v-else class="arrets-table">
          <thead>
            <tr><th>N°</th><th>Lot</th><th>Quantité</th><th>Heure</th><th v-if="peutCorriger"></th></tr>
          </thead>
          <tbody>
            <tr v-for="p in palettes" :key="p.id">
              <td>{{ p.numero_palette }}</td>
              <td>{{ p.numero_lot }}</td>
              <td>{{ p.quantite_totale.toLocaleString('fr-FR') }}</td>
              <td>{{ new Date(p.created_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) }}</td>
              <td v-if="peutCorriger">
                <button class="link-btn" @click="ouvrirEdition(p)"><Pencil :size="14" /> Corriger</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Correction palette -->
      <div v-if="paletteEnEdition" class="modal-overlay" @click.self="paletteEnEdition = null">
        <div class="modal-card">
          <h2>Corriger {{ paletteEnEdition.numero_palette }}</h2>
          <label class="field"><span>Cartons</span><input v-model.number="editForm.nbCartons" type="number" min="1" /></label>
          <label class="field"><span>Colisage / carton</span><input v-model.number="editForm.colisageCarton" type="number" min="1" /></label>
          <label class="field"><span>Motif de la correction (optionnel)</span><input v-model="editForm.motif" type="text" placeholder="ex: erreur de saisie" /></label>
          <p v-if="editError" class="error-banner">{{ editError }}</p>
          <div class="modal-actions">
            <button class="btn secondary" @click="paletteEnEdition = null">Annuler</button>
            <button class="btn primary" @click="enregistrerCorrection">Enregistrer</button>
          </div>
        </div>
      </div>

      <div class="section-card">
        <h2><PauseCircle :size="16" /> Arrêts du jour</h2>
        <p v-if="!performance.arrets_du_jour.length" class="empty">Aucun arrêt aujourd'hui.</p>
        <table v-else class="arrets-table">
          <thead>
            <tr><th>Cause</th><th>Équipement</th><th>Début</th><th>Durée</th></tr>
          </thead>
          <tbody>
            <tr v-for="a in performance.arrets_du_jour" :key="a.id">
              <td>{{ a.cause_libelle }}</td>
              <td>{{ a.equipement_label || '—' }}</td>
              <td>{{ new Date(a.heure_debut).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) }}</td>
              <td>{{ a.heure_fin ? `${a.duree_min} min` : 'En cours' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<style scoped>
.ligne-detail {
  padding: var(--space-6);
  overflow-y: auto;
  height: 100%;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  border: none;
  background: none;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  font-weight: 600;
  cursor: pointer;
  padding: 0;
  margin-bottom: var(--space-4);
}

.back-btn:hover { color: var(--color-brand); }

.date-picker {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-bottom: var(--space-4);
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
.historique-badge {
  background: var(--color-orange-bg, #FEF3E2);
  color: var(--color-orange, #B45309);
  padding: 2px 10px;
  border-radius: 999px;
  font-weight: 700;
}

.error-banner {
  background: var(--color-rouge-bg);
  color: var(--color-rouge);
  padding: var(--space-3);
  border-radius: var(--radius-md);
}

.link-btn {
  display: inline-flex; align-items: center; gap: 4px;
  border: none; background: none; color: var(--color-brand); cursor: pointer;
  font-size: var(--font-size-xs); font-weight: 600;
}

.modal-overlay {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.5);
  display: flex; align-items: center; justify-content: center; z-index: 50;
}
.modal-card {
  background: var(--color-surface); border-radius: var(--radius-lg); padding: var(--space-6);
  width: 100%; max-width: 360px; box-shadow: 0 10px 30px rgba(0,0,0,0.2);
}
.modal-card h2 { margin: 0 0 var(--space-4); font-size: var(--font-size-base); }
.modal-actions { display: flex; justify-content: flex-end; gap: var(--space-2); margin-top: var(--space-4); }

.field { display: flex; flex-direction: column; gap: 4px; font-size: var(--font-size-sm); margin-bottom: var(--space-3); }
.field input { height: 40px; padding: 0 var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-family: inherit; }

.btn {
  border: none; border-radius: var(--radius-md); padding: var(--space-2) var(--space-4);
  font-weight: 700; cursor: pointer; font-size: var(--font-size-sm);
}
.btn.primary { background: var(--color-brand); color: var(--color-text-inverse); }
.btn.secondary { background: var(--color-border); color: var(--color-text); }

.loading { color: var(--color-text-muted); }

.ligne-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.ligne-header h1 { margin: 0; font-size: var(--font-size-xl); }
.subtitle { color: var(--color-text-muted); margin: 4px 0 0; }

.metrics-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-6);
}

.metric-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  text-align: center;
  box-shadow: var(--shadow-card);
}

.metric-value { font-size: var(--font-size-xl); font-weight: 800; }
.metric-label { font-size: var(--font-size-xs); color: var(--color-text-muted); }

.section-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  margin-bottom: var(--space-4);
  box-shadow: var(--shadow-card);
}

.section-card h2 {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-base);
  margin: 0 0 var(--space-3);
}

.planning-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.planning-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--color-bg);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
}

.planning-item-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.planning-produit { font-weight: 700; }
.planning-ref { font-size: var(--font-size-xs); color: var(--color-text-muted); }
.planning-qty { font-size: var(--font-size-sm); }

.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}

.empty { color: var(--color-text-muted); font-size: var(--font-size-sm); }

.item-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.item-list li {
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.item-list li:last-child { border-bottom: none; padding-bottom: 0; }

/* *** AJOUT 2026-09-25 *** : compteurs par fonction + bouton de gestion, écran "Équipe sur la ligne". */
.equipe-compteurs { display: flex; gap: var(--space-3); margin-bottom: var(--space-3); }
.compteur { flex: 1; background: var(--color-bg); border-radius: var(--radius-md); padding: var(--space-2) var(--space-3); text-align: center; }
.compteur strong { display: block; font-size: var(--font-size-lg); }
.compteur span { font-size: var(--font-size-xs); color: var(--color-text-muted); }
.compteur-total { background: var(--color-brand-light); }
.btn-gerer-equipe { margin-top: var(--space-3); width: 100%; }
.hint { color: var(--color-text-muted); font-size: var(--font-size-xs); margin-top: var(--space-2); }

.item-title { font-weight: 600; font-size: var(--font-size-sm); }
.item-sub { font-size: var(--font-size-xs); color: var(--color-text-muted); }

.arrets-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}

.arrets-table th {
  text-align: left;
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
  padding: var(--space-2);
  border-bottom: 1px solid var(--color-border);
}

.arrets-table td {
  padding: var(--space-2);
  border-bottom: 1px solid var(--color-border);
}
</style>