<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import apiClient from '@/api/client'
import QrScanner from 'qr-scanner'
import QrScannerWorkerPath from 'qr-scanner/qr-scanner-worker.min.js?url'
import { ChevronRight, QrCode, X, Keyboard, History } from 'lucide-vue-next'
import { useRouter } from 'vue-router'

QrScanner.WORKER_PATH = QrScannerWorkerPath

const emit = defineEmits(['select-ligne'])
const router = useRouter()

// *** AJOUT 2026-09-23 *** : accès à son propre historique de scans -- navigation
// directe (pas de passage par l'emit select-ligne/back de TabletteView, qui suppose
// une LIGNE) puisque ce n'est pas une ligne mais un écran séparé.
function ouvrirHistorique() {
  router.push({ name: 'historique-operateur' })
}

const lignes = ref([])
const isLoading = ref(true)
const errorMessage = ref('')

onMounted(async () => {
  try {
    const res = await apiClient.get('/entities/lignes/mes-lignes')
    lignes.value = res.data
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger vos lignes.'
  } finally {
    isLoading.value = false
  }
})

// ---------------------------------------------------------------
// Scan QR caméra (*** AJOUT 2026-09-18 ***) -- le QR de la ligne encode son `code`
// (ex: "L12", cf. étiquettes imprimées côté usine -- même convention que le QR ligne
// des maquettes). Le scan ne fait QUE retrouver la ligne correspondante PARMI celles
// déjà affectées à l'opérateur (lignes.value, chargé ci-dessus) -- aucun nouvel appel
// réseau nécessaire, aucun moyen de "scanner" une ligne qui n'est pas la sienne.
// ---------------------------------------------------------------
const modeScan = ref(false)
const videoEl = ref(null)
const scanError = ref('')
let scanner = null

async function ouvrirScan() {
  scanError.value = ''
  modeScan.value = true
  // nextTick implicite : le <video> n'existe qu'une fois modeScan=true rendu -- on
  // attend le prochain tick via setTimeout(0) pour rester simple sans import supplémentaire.
  await new Promise(r => setTimeout(r, 0))
  if (!videoEl.value) return

  try {
    scanner = new QrScanner(videoEl.value, (result) => traiterScan(result.data), {
      highlightScanRegion: true,
      highlightCodeOutline: true,
      preferredCamera: 'environment',  // caméra arrière -- pas la selfie
    })
    await scanner.start()
  } catch (e) {
    // Cas fréquents : pas de HTTPS (getUserMedia l'exige, sauf localhost), permission
    // refusée, pas de caméra disponible (tablette de bureau/émulateur).
    scanError.value = "Impossible d'accéder à la caméra -- vérifie les autorisations, ou utilise la sélection manuelle ci-dessous."
  }
}

function fermerScan() {
  if (scanner) {
    scanner.stop()
    scanner.destroy()
    scanner = null
  }
  modeScan.value = false
  scanError.value = ''
}

function traiterScan(code) {
  const valeur = (code || '').trim()
  const ligne = lignes.value.find(l => l.code.toLowerCase() === valeur.toLowerCase())
  if (!ligne) {
    // Pas d'affectation trouvée -- message clair plutôt qu'un échec silencieux, scan
    // continue (l'opérateur a pu viser le mauvais QR, pas la peine de tout refermer).
    scanError.value = `Ligne "${valeur}" non reconnue ou pas affectée à ton compte.`
    return
  }
  fermerScan()
  emit('select-ligne', ligne.id)
}

onUnmounted(() => {
  if (scanner) { scanner.stop(); scanner.destroy(); scanner = null }
})
</script>

<template>
  <div class="mes-lignes">
    <div class="header-row">
      <h1>Mes lignes ({{ lignes.length }})</h1>
      <div class="header-actions">
        <button class="historique-btn" title="Voir mes scans passés, toutes lignes confondues" @click="ouvrirHistorique">
          <History :size="18" />
        </button>
        <button class="scan-btn" @click="ouvrirScan"><QrCode :size="18" /> Scanner</button>
      </div>
    </div>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>
    <p v-else-if="!lignes.length" class="empty">Aucune ligne ne vous est actuellement affectée.</p>

    <div v-else class="lignes-list">
      <button v-for="ligne in lignes" :key="ligne.id" class="ligne-btn" @click="emit('select-ligne', ligne.id)">
        <div>
          <div class="ligne-code">{{ ligne.code }}</div>
          <div class="ligne-nom">{{ ligne.nom }}</div>
        </div>
        <ChevronRight :size="24" />
      </button>
    </div>

    <!-- Overlay scan caméra -->
    <div v-if="modeScan" class="scan-overlay">
      <div class="scan-header">
        <span>Scanner le QR Code de la ligne</span>
        <button class="close-btn" @click="fermerScan"><X :size="22" /></button>
      </div>
      <video ref="videoEl" class="scan-video"></video>
      <p class="scan-hint">Placez le QR Code de la ligne dans le cadre</p>
      <p v-if="scanError" class="error-banner scan-error">{{ scanError }}</p>
      <button class="manual-fallback-btn" @click="fermerScan"><Keyboard :size="16" /> Sélection manuelle</button>
    </div>
  </div>
</template>

<style scoped>
.mes-lignes {
  padding: var(--space-4);
  height: 100%;
  overflow-y: auto;
  position: relative;
}

.header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
  gap: var(--space-3);
}

h1 {
  font-size: var(--font-size-xl);
  margin: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.scan-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: var(--touch-target-min, 44px);
  padding: 0 var(--space-4);
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-brand);
  color: var(--color-text-inverse);
  font-weight: 700;
  font-size: var(--font-size-sm);
  cursor: pointer;
  white-space: nowrap;
}

/* *** AJOUT 2026-09-23 *** : bouton "Mon historique", même hauteur tactile que Scanner
   (cf. --touch-target-min -- contrainte tablette, doigts pas toujours secs/précis). */
.historique-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--touch-target-min, 44px);
  height: var(--touch-target-min, 44px);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-brand-dark);
  cursor: pointer;
}

.error-banner {
  background: var(--color-rouge-bg);
  color: var(--color-rouge);
  padding: var(--space-3);
  border-radius: var(--radius-md);
}

.loading, .empty { color: var(--color-text-muted); }

.lignes-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ligne-btn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 72px;
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
  cursor: pointer;
  font-family: inherit;
  color: var(--color-text-muted);
}

.ligne-code {
  font-size: var(--font-size-lg);
  font-weight: 800;
  color: var(--color-text);
}

.ligne-nom {
  font-size: var(--font-size-sm);
}

.scan-overlay {
  position: fixed;
  inset: 0;
  background: #000;
  z-index: 100;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.scan-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4);
  color: #fff;
  font-weight: 700;
}

.close-btn {
  border: none;
  background: rgba(255, 255, 255, 0.15);
  color: #fff;
  border-radius: 999px;
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.scan-video {
  width: 100%;
  max-width: 480px;
  flex: 1;
  object-fit: cover;
}

.scan-hint {
  color: #fff;
  font-size: var(--font-size-sm);
  padding: var(--space-3);
  text-align: center;
}

.scan-error {
  margin: 0 var(--space-4) var(--space-3);
}

.manual-fallback-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-6);
  padding: var(--space-2) var(--space-4);
  border: 1px solid rgba(255, 255, 255, 0.4);
  background: transparent;
  color: #fff;
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  cursor: pointer;
}
</style>