<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import apiClient from '@/api/client'
import QRCode from 'qrcode'
import { ArrowLeft, Package, PauseCircle, PlayCircle, CheckCircle2, Printer } from 'lucide-vue-next'

const props = defineProps({
  ligneId: { type: Number, required: true },
})
const emit = defineEmits(['back'])

const user = JSON.parse(sessionStorage.getItem('user') || '{}')

// 'info' | 'palette_form' | 'palette_confirmation' | 'arret_form' | 'arret_en_cours'
const screen = ref('info')
const ligneDetail = ref(null)
const arretEnCours = ref(null)
const isLoading = ref(true)
const errorMessage = ref('')

// *** REVU 2026-09-17 *** : ligneDetail.of_actuel (unique) -> items_planning_jour
// (liste, 0/1/plusieurs -- une ligne peut avoir plusieurs produits planifiés le même
// jour, cf. découverte du planning hebdomadaire réel). itemSelectionne = l'item choisi
// par l'opérateur avant de valider une palette -- auto-sélectionné s'il n'y en a qu'un.
const itemSelectionne = ref(null)

async function chargerTout() {
  isLoading.value = true
  try {
    const [detailRes, arretRes] = await Promise.all([
      apiClient.get(`/entities/lignes/${props.ligneId}`),
      apiClient.get('/actions/arrets/en-cours', { params: { ligne_id: props.ligneId } }),
    ])
    ligneDetail.value = detailRes.data
    arretEnCours.value = arretRes.data
    screen.value = arretEnCours.value ? 'arret_en_cours' : 'info'
    errorMessage.value = ''

    const items = ligneDetail.value.items_planning_jour || []
    if (items.length === 1) {
      itemSelectionne.value = items[0]
    } else {
      itemSelectionne.value = null
    }
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger la ligne.'
  } finally {
    isLoading.value = false
  }
}

onMounted(chargerTout)

const items = computed(() => ligneDetail.value?.items_planning_jour || [])
const plusieursItems = computed(() => items.value.length > 1)

function selectionnerItem(item) {
  itemSelectionne.value = item
}

// ---------------------------------------------------------------
// Validation palette
// ---------------------------------------------------------------
const numeroLot = ref('')
const palettePartielle = ref(false)
const motifPartielle = ref('')
const nbCartons = ref(null)
const colisageCarton = ref(null)
// *** AJOUT 2026-09-24 (Palier 1, TRS) *** : pièces rebutées pendant le remplissage de cette
// palette (optionnel, vide = 0) -- alimente la composante Qualité du TRS.
const nbRebuts = ref(null)
const paletteSubmitting = ref(false)
const paletteError = ref('')
const derniereConfirmation = ref(null)

function ouvrirFormulairePalette() {
  if (!itemSelectionne.value) return
  numeroLot.value = ''
  palettePartielle.value = false
  motifPartielle.value = ''
  nbRebuts.value = null
  nbCartons.value = itemSelectionne.value.cartons_par_palette ?? null
  colisageCarton.value = itemSelectionne.value.colisage_par_carton ?? null
  paletteError.value = ''
  screen.value = 'palette_form'
}

const quantiteTotale = computed(() => {
  if (!nbCartons.value || !colisageCarton.value) return 0
  return nbCartons.value * colisageCarton.value
})

async function validerPalette() {
  if (!numeroLot.value || !nbCartons.value || !colisageCarton.value || paletteSubmitting.value) return
  paletteSubmitting.value = true
  paletteError.value = ''
  try {
    const res = await apiClient.post('/actions/palettes', {
      ligne_id: props.ligneId,
      planning_detail_id: itemSelectionne.value?.id ?? null,
      numero_lot: numeroLot.value,
      nb_cartons: nbCartons.value,
      colisage_carton: colisageCarton.value,
      complete: !palettePartielle.value,
      motif_partielle: palettePartielle.value ? (motifPartielle.value || null) : null,
      nb_rebuts: nbRebuts.value > 0 ? Math.floor(nbRebuts.value) : 0,
    })
    derniereConfirmation.value = res.data
    qrDataUrl.value = ''
    screen.value = 'palette_confirmation'
  } catch (e) {
    paletteError.value = e.response?.data?.detail || 'Échec de la validation.'
  } finally {
    paletteSubmitting.value = false
  }
}

// ---------------------------------------------------------------
// Étiquette palette -- QR + impression (*** AJOUT 2026-09-18 ***)
// ---------------------------------------------------------------
// PaletteOut (schemas/actions.py) ne renvoie ni produit_nom ni ligne_code/nom --
// dénormalisés nulle part côté palettes_cache. On les prend donc depuis l'état déjà en
// mémoire (itemSelectionne, ligneDetail), déjà chargés pour l'écran -- pas besoin
// d'appel API supplémentaire.
const qrDataUrl = ref('')
const etiquetteEnCours = ref(false)

async function imprimerEtiquette() {
  if (!derniereConfirmation.value || etiquetteEnCours.value) return
  etiquetteEnCours.value = true
  try {
    // Contenu du QR : le numéro de palette seul (identifiant unique) -- même principe
    // que le QR ligne qui encode juste le code de ligne (slide 11 : "Le QR ligne sert à
    // déclarer la production ; le QR palette sert à tracer la palette"). Un scan
    // ultérieur (magasin, qualité) n'a besoin que de cette clé pour retrouver la fiche
    // complète côté serveur -- pas la peine d'encoder tout le détail dans le QR lui-même.
    qrDataUrl.value = await QRCode.toDataURL(derniereConfirmation.value.numero_palette, {
      width: 220, margin: 1,
    })
    await nextTick()
    window.print()
  } catch (e) {
    paletteError.value = "Échec de la génération de l'étiquette."
  } finally {
    etiquetteEnCours.value = false
  }
}

// ---------------------------------------------------------------
// Arrêt
// ---------------------------------------------------------------
const causesArret = ref([])
const causeId = ref(null)
const equipementId = ref(null)
const commentaireArret = ref('')
const arretSubmitting = ref(false)
const arretError = ref('')

async function ouvrirFormulaireArret() {
  causeId.value = null
  equipementId.value = null
  commentaireArret.value = ''
  arretError.value = ''
  if (!causesArret.value.length) {
    try {
      const res = await apiClient.get('/entities/causes-arret')
      causesArret.value = res.data
    } catch (e) {
      arretError.value = 'Impossible de charger les causes d\'arrêt.'
    }
  }
  screen.value = 'arret_form'
}

async function demarrerArret() {
  if (!causeId.value || arretSubmitting.value) return
  arretSubmitting.value = true
  arretError.value = ''
  try {
    const res = await apiClient.post('/actions/arrets/demarrer', {
      ligne_id: props.ligneId,
      cause_id: causeId.value,
      equipement_id: equipementId.value,
      commentaire: commentaireArret.value || null,
    })
    arretEnCours.value = res.data
    screen.value = 'arret_en_cours'
  } catch (e) {
    arretError.value = e.response?.data?.detail || 'Échec du démarrage de l\'arrêt.'
  } finally {
    arretSubmitting.value = false
  }
}

async function terminerArret() {
  if (!arretEnCours.value) return
  try {
    await apiClient.post(`/actions/arrets/${arretEnCours.value.id}/terminer`)
    arretEnCours.value = null
    screen.value = 'info'
  } catch (e) {
    arretError.value = e.response?.data?.detail || 'Échec de la clôture de l\'arrêt.'
  }
}

// Chrono de l'arrêt en cours
const chronoTexte = ref('00:00:00')
let chronoHandle = null

function demarrerChrono() {
  const maj = () => {
    if (!arretEnCours.value) return
    const debut = new Date(arretEnCours.value.heure_debut).getTime()
    const ecoule = Math.max(0, Math.floor((Date.now() - debut) / 1000))
    const h = String(Math.floor(ecoule / 3600)).padStart(2, '0')
    const m = String(Math.floor((ecoule % 3600) / 60)).padStart(2, '0')
    const s = String(ecoule % 60).padStart(2, '0')
    chronoTexte.value = `${h}:${m}:${s}`
  }
  maj()
  chronoHandle = setInterval(maj, 1000)
}

onUnmounted(() => { if (chronoHandle) clearInterval(chronoHandle) })

watch(screen, (val) => {
  if (chronoHandle) { clearInterval(chronoHandle); chronoHandle = null }
  if (val === 'arret_en_cours') demarrerChrono()
}, { immediate: true })
</script>

<template>
  <div class="ligne-operateur">
    <button class="back-btn" @click="emit('back')"><ArrowLeft :size="20" /> Mes lignes</button>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>

    <template v-else-if="ligneDetail">
      <h1>{{ ligneDetail.ligne.code }} — {{ ligneDetail.ligne.nom }}</h1>

      <!-- Écran info + actions -->
      <template v-if="screen === 'info'">
        <p v-if="!items.length" class="empty">Aucune production planifiée aujourd'hui sur cette ligne.</p>

        <!-- Plusieurs produits le même jour -- l'opérateur choisit avant de valider -->
        <template v-else-if="plusieursItems">
          <p class="section-label">Plusieurs produits planifiés aujourd'hui — choisis celui sur lequel tu travailles :</p>
          <div class="item-picker">
            <button
              v-for="item in items"
              :key="item.id"
              :class="['item-option', { selected: itemSelectionne?.id === item.id }]"
              @click="selectionnerItem(item)"
            >
              <div class="item-option-nom">{{ item.produit_nom || '—' }}</div>
              <div class="item-option-qty">Cible du jour : {{ item.qty_jour?.toLocaleString('fr-FR') ?? '—' }} pcs</div>
            </button>
          </div>
        </template>

        <div v-if="itemSelectionne" class="info-card">
          <div class="info-row"><span>Produit</span><strong>{{ itemSelectionne.produit_nom || '—' }}</strong></div>
          <div class="info-row"><span>Planning</span><strong>{{ itemSelectionne.reference_planning || '—' }}</strong></div>
          <div class="info-row"><span>Cartons / palette</span><strong>{{ itemSelectionne.cartons_par_palette ?? '—' }}</strong></div>
          <div class="info-row"><span>Colisage / carton</span><strong>{{ itemSelectionne.colisage_par_carton ?? '—' }}</strong></div>
        </div>

        <div class="actions">
          <button class="action-btn primary" :disabled="!itemSelectionne" @click="ouvrirFormulairePalette">
            <Package :size="22" /> Valider une palette
          </button>
          <button class="action-btn danger" @click="ouvrirFormulaireArret">
            <PauseCircle :size="22" /> Déclarer un arrêt
          </button>
        </div>
      </template>

      <!-- Formulaire palette -->
      <template v-else-if="screen === 'palette_form'">
        <h2>{{ palettePartielle ? 'Palette partielle' : 'Valider une palette' }}</h2>
        <label class="checkbox-row">
          <input type="checkbox" v-model="palettePartielle" />
          Palette non complète
        </label>

        <label class="field">
          <span>N° de lot</span>
          <input v-model="numeroLot" type="text" placeholder="Numéro de lot" />
        </label>

        <label class="field">
          <span>Cartons sur la palette</span>
          <input v-model.number="nbCartons" type="number" min="1" :readonly="!palettePartielle" />
        </label>

        <label class="field">
          <span>Colisage / carton</span>
          <input v-model.number="colisageCarton" type="number" min="1" />
        </label>

        <label class="field">
          <span>Rebuts constatés (pièces, optionnel)</span>
          <input v-model.number="nbRebuts" type="number" min="0" inputmode="numeric" placeholder="0" />
        </label>

        <label v-if="palettePartielle" class="field">
          <span>Motif (optionnel)</span>
          <input v-model="motifPartielle" type="text" placeholder="ex: fin de poste, manque composants…" />
        </label>

        <div class="quantite-totale">Quantité totale : <strong>{{ quantiteTotale.toLocaleString('fr-FR') }} pcs</strong></div>

        <p v-if="paletteError" class="error-banner">{{ paletteError }}</p>

        <div class="form-actions">
          <button class="action-btn secondary" @click="screen = 'info'">Retour</button>
          <button class="action-btn primary" :disabled="paletteSubmitting" @click="validerPalette">
            {{ paletteSubmitting ? 'Validation…' : 'Valider la palette' }}
          </button>
        </div>
      </template>

      <!-- Confirmation palette -->
      <template v-else-if="screen === 'palette_confirmation'">
        <div class="confirmation">
          <CheckCircle2 :size="48" class="confirm-icon" />
          <h2>Palette enregistrée !</h2>
          <div class="info-card">
            <div class="info-row"><span>N° palette</span><strong>{{ derniereConfirmation.numero_palette }}</strong></div>
            <div class="info-row"><span>Quantité</span><strong>{{ derniereConfirmation.quantite_totale.toLocaleString('fr-FR') }} pcs</strong></div>
            <div class="info-row"><span>Expiration</span><strong>{{ derniereConfirmation.date_expiration || '—' }}</strong></div>
          </div>
          <div class="form-actions">
            <button class="action-btn secondary" @click="screen = 'info'">Retour</button>
            <button class="action-btn primary" @click="ouvrirFormulairePalette">Nouvelle palette</button>
          </div>
          <button class="action-btn print-btn full-width" :disabled="etiquetteEnCours" @click="imprimerEtiquette">
            <Printer :size="18" /> {{ etiquetteEnCours ? 'Préparation…' : "Imprimer l'étiquette" }}
          </button>
        </div>
      </template>

      <!-- Formulaire arrêt -->
      <template v-else-if="screen === 'arret_form'">
        <h2>Déclarer un arrêt</h2>
        <label class="field">
          <span>Cause *</span>
          <select v-model.number="causeId">
            <option :value="null" disabled>Choisir une cause</option>
            <option v-for="c in causesArret" :key="c.id" :value="c.id">{{ c.libelle }}</option>
          </select>
        </label>

        <label v-if="ligneDetail.equipements.length" class="field">
          <span>Équipement (optionnel)</span>
          <select v-model.number="equipementId">
            <option :value="null">Aucun en particulier</option>
            <option v-for="eq in ligneDetail.equipements" :key="eq.id" :value="eq.id">{{ eq.type }} — {{ eq.marque }}</option>
          </select>
        </label>

        <label class="field">
          <span>Commentaire (optionnel)</span>
          <textarea v-model="commentaireArret" rows="3" placeholder="Détails de l'arrêt"></textarea>
        </label>

        <p v-if="arretError" class="error-banner">{{ arretError }}</p>

        <div class="form-actions">
          <button class="action-btn secondary" @click="screen = 'info'">Retour</button>
          <button class="action-btn danger" :disabled="!causeId || arretSubmitting" @click="demarrerArret">
            <PlayCircle :size="18" /> {{ arretSubmitting ? 'Démarrage…' : 'Démarrer l\'arrêt' }}
          </button>
        </div>
      </template>

      <!-- Arrêt en cours -->
      <template v-else-if="screen === 'arret_en_cours'">
        <div class="arret-en-cours">
          <PauseCircle :size="48" class="arret-icon" />
          <h2>Arrêt en cours</h2>
          <div class="chrono">{{ chronoTexte }}</div>
          <div class="info-card">
            <div class="info-row"><span>Cause</span><strong>{{ arretEnCours?.cause_libelle }}</strong></div>
          </div>
          <p v-if="arretError" class="error-banner">{{ arretError }}</p>
          <button class="action-btn primary full-width" @click="terminerArret">Terminer l'arrêt</button>
        </div>
      </template>
    </template>

    <!-- *** AJOUT 2026-09-18 *** : étiquette imprimable -- invisible à l'écran (cf.
    .print-only en CSS), affichée seule au moment de window.print() (cf. imprimerEtiquette
    plus haut). N'existe que si une palette vient d'être validée. -->
    <div v-if="derniereConfirmation" class="print-only">
      <div class="etiquette">
        <div class="etiquette-header">VUSINE</div>
        <div v-if="!derniereConfirmation.complete" class="etiquette-partielle">PALETTE PARTIELLE</div>
        <div class="etiquette-numero">{{ derniereConfirmation.numero_palette }}</div>
        <img v-if="qrDataUrl" :src="qrDataUrl" alt="QR palette" class="etiquette-qr" />
        <table class="etiquette-table">
          <tbody>
            <tr><td>Ligne</td><td>{{ ligneDetail?.ligne?.code }} — {{ ligneDetail?.ligne?.nom }}</td></tr>
            <tr><td>Produit</td><td>{{ itemSelectionne?.produit_nom || '—' }}</td></tr>
            <tr><td>Planning</td><td>{{ itemSelectionne?.reference_planning || '—' }}</td></tr>
            <tr><td>N° lot</td><td>{{ derniereConfirmation.numero_lot }}</td></tr>
            <tr><td>Expiration</td><td>{{ derniereConfirmation.date_expiration || '—' }}</td></tr>
            <tr><td>Cartons</td><td>{{ derniereConfirmation.nb_cartons }} × {{ derniereConfirmation.colisage_carton }} = {{ derniereConfirmation.quantite_totale.toLocaleString('fr-FR') }} pcs</td></tr>
            <tr v-if="derniereConfirmation.nb_rebuts > 0"><td>Rebuts</td><td>{{ derniereConfirmation.nb_rebuts.toLocaleString('fr-FR') }} pcs</td></tr>
            <!-- *** AJOUT 2026-09-23 *** : matricule ajouté -- plusieurs personnes
                 peuvent porter le même nom dans l'usine. -->
            <tr><td>Opérateur</td><td>{{ user.nom }}{{ user.matricule ? ` (${user.matricule})` : '' }}</td></tr>
            <tr><td>Date / heure</td><td>{{ new Date(derniereConfirmation.created_at).toLocaleString('fr-FR') }}</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ligne-operateur {
  padding: var(--space-4);
  height: 100%;
  overflow-y: auto;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  border: none;
  background: none;
  color: var(--color-text-muted);
  font-size: var(--font-size-base);
  font-weight: 600;
  cursor: pointer;
  padding: var(--space-2) 0;
  margin-bottom: var(--space-2);
}

h1 { font-size: var(--font-size-lg); margin: 0 0 var(--space-4); }
h2 { font-size: var(--font-size-base); margin: 0 0 var(--space-3); }

.error-banner {
  background: var(--color-rouge-bg);
  color: var(--color-rouge);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-3);
}

.loading, .empty { color: var(--color-text-muted); }

.section-label {
  font-size: var(--font-size-sm);
  font-weight: 600;
  margin-bottom: var(--space-3);
}

.item-picker {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}

.item-option {
  text-align: left;
  background: var(--color-surface);
  border: 2px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  cursor: pointer;
  font-family: inherit;
}

.item-option.selected {
  border-color: var(--color-brand);
  background: var(--color-brand-light);
}

.item-option-nom { font-weight: 700; font-size: var(--font-size-sm); }
.item-option-qty { font-size: var(--font-size-xs); color: var(--color-text-muted); margin-top: 2px; }

.info-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  margin-bottom: var(--space-4);
  box-shadow: var(--shadow-card);
}

.info-row {
  display: flex;
  justify-content: space-between;
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-border);
  font-size: var(--font-size-sm);
}
.info-row:last-child { border-bottom: none; }
.info-row span { color: var(--color-text-muted); }

.actions {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: var(--touch-target-min);
  padding: 0 var(--space-4);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--font-size-base);
  font-weight: 700;
  cursor: pointer;
}

.action-btn.primary { background: var(--color-brand); color: var(--color-text-inverse); }
.action-btn.danger { background: var(--color-rouge); color: var(--color-text-inverse); }
.action-btn.secondary { background: var(--color-border); color: var(--color-text); }
.action-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.action-btn.full-width { width: 100%; }

.checkbox-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-sm);
  margin-bottom: var(--space-4);
}

.field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-bottom: var(--space-3);
  font-size: var(--font-size-sm);
}

.field input, .field select, .field textarea {
  min-height: var(--touch-target-min);
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--font-size-base);
  font-family: inherit;
}

.field textarea { padding: var(--space-3); min-height: 80px; }

.field input[readonly] { background: var(--color-bg); color: var(--color-text-muted); }

.quantite-totale {
  font-size: var(--font-size-base);
  margin-bottom: var(--space-4);
}

.form-actions {
  display: flex;
  gap: var(--space-3);
}
.form-actions .action-btn { flex: 1; }

.confirmation, .arret-en-cours {
  text-align: center;
}

.confirm-icon { color: var(--color-vert); }
.arret-icon { color: var(--color-rouge); }

.chrono {
  font-size: 2.5rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  color: var(--color-rouge);
  margin: var(--space-3) 0;
}

.print-btn {
  margin-top: var(--space-3);
  background: var(--color-surface);
  color: var(--color-text);
  border: 1px solid var(--color-border);
}

/* *** AJOUT 2026-09-18 *** : étiquette invisible à l'écran, uniquement affichée par
   window.print() (cf. imprimerEtiquette). Technique standard "n'imprimer que cet
   élément" -- tout le reste de la page est masqué au moment de l'impression. */
.print-only { display: none; }

.etiquette {
  width: 320px;
  margin: 0 auto;
  padding: 16px;
  font-family: 'Courier New', monospace;
  color: #000;
  text-align: center;
}
.etiquette-header { font-weight: 800; font-size: 1.1rem; letter-spacing: 2px; margin-bottom: 8px; }
.etiquette-partielle {
  display: inline-block; border: 2px solid #000; padding: 2px 10px; font-weight: 800;
  font-size: 0.8rem; margin-bottom: 8px;
}
.etiquette-numero { font-size: 1.3rem; font-weight: 800; margin-bottom: 10px; }
.etiquette-qr { width: 140px; height: 140px; margin: 0 auto 10px; display: block; }
.etiquette-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; text-align: left; }
.etiquette-table td { padding: 3px 4px; border-top: 1px dashed #000; }
.etiquette-table td:first-child { font-weight: 700; white-space: nowrap; padding-right: 8px; }
</style>

<!-- *** AJOUT 2026-09-18 *** : NON scopé volontairement -- une règle "cacher tout sauf
mon étiquette" doit forcément agir hors des limites du composant (body, autres vues),
ce que <style scoped> ne peut pas faire correctement (Vue ne peut pas appliquer son
attribut data-v-xxx à <body>, qui n'est pas rendu par ce composant). -->
<style>
@media print {
  body * { visibility: hidden; }
  .print-only, .print-only * { visibility: visible; }
  .print-only {
    display: block !important;
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
  }
}
</style>