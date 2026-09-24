<script setup>
import { ref, computed, onMounted } from 'vue'
import apiClient from '@/api/client'

const lignes = ref([])
const isLoading = ref(true)
const errorMessage = ref('')

// --- Recherche / filtre / tri (100% client -- ~88 lignes, pas besoin de pagination
// serveur à cette échelle) ---------------------------------------------------------
const recherche = ref('')
const filtreSection = ref('toutes')
const filtreVisibilite = ref('toutes')  // 'toutes' | 'affichees' | 'masquees'
const triColonne = ref('code')
const triSens = ref(1)  // 1 = asc, -1 = desc

async function charger() {
  isLoading.value = true
  try {
    const res = await apiClient.get('/admin/lignes')
    lignes.value = res.data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger les lignes.'
  } finally {
    isLoading.value = false
  }
}
onMounted(charger)

async function toggleActif(ligne) {
  const nouvelActif = !ligne.actif
  try {
    const res = await apiClient.patch(`/admin/lignes/${ligne.id}/actif`, null, { params: { actif: nouvelActif } })
    // Mise à jour optimiste directe depuis la réponse (plutôt qu'un rechargement complet)
    // -- évite de perdre la position de scroll/le filtre en cours sur 88 lignes.
    Object.assign(ligne, res.data)
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Échec de la mise à jour.'
  }
}

// --- Section : synchronisée depuis Odoo depuis 2026-09-18 (sections_cache), plus
// d'édition manuelle -- lecture seule (cf. odoo_sync_service.sync_lignes).

// --- Actions en masse (sur le sous-ensemble actuellement filtré) ------------------
const actionEnMasseEnCours = ref(false)

async function toggleEnMasse(actif) {
  const cibles = lignesFiltrees.value
  if (!cibles.length) return
  actionEnMasseEnCours.value = true
  try {
    await apiClient.patch('/admin/lignes/actif-en-masse', {
      ligne_ids: cibles.map(l => l.id), actif,
    })
    cibles.forEach(l => { l.actif = actif })
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Échec de la mise à jour en masse.'
  } finally {
    actionEnMasseEnCours.value = false
  }
}
const sectionsConnues = computed(() => {
  const set = new Set(lignes.value.map(l => l.section_nom).filter(Boolean))
  return Array.from(set).sort((a, b) => a.localeCompare(b))
})

function trierPar(colonne) {
  if (triColonne.value === colonne) {
    triSens.value *= -1
  } else {
    triColonne.value = colonne
    triSens.value = 1
  }
}

const lignesFiltrees = computed(() => {
  const q = recherche.value.trim().toLowerCase()
  let resultat = lignes.value.filter(l => {
    if (q && !`${l.code} ${l.nom}`.toLowerCase().includes(q)) return false
    if (filtreSection.value === 'sans_section' && l.section_nom) return false
    if (filtreSection.value !== 'toutes' && filtreSection.value !== 'sans_section' && l.section_nom !== filtreSection.value) return false
    if (filtreVisibilite.value === 'affichees' && !l.actif) return false
    if (filtreVisibilite.value === 'masquees' && l.actif) return false
    return true
  })

  resultat = [...resultat].sort((a, b) => {
    const av = a[triColonne.value] ?? ''
    const bv = b[triColonne.value] ?? ''
    if (typeof av === 'boolean') return (av === bv ? 0 : av ? -1 : 1) * triSens.value
    return String(av).localeCompare(String(bv)) * triSens.value
  })

  return resultat
})
</script>

<template>
  <div class="lignes-admin">
    <p class="hint">
      Toutes les lignes synchronisées depuis Odoo apparaissent ici, y compris celles qui
      ne sont pas de vraies lignes de production (catégories internes, ateliers annexes...).
      Décoche celles à masquer de Vue Usine.
    </p>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <div class="toolbar">
      <input
        v-model="recherche"
        type="search"
        placeholder="Rechercher par code ou nom…"
        class="search-input"
      />
      <select v-model="filtreSection" class="filter-select">
        <option value="toutes">Toutes les sections</option>
        <option value="sans_section">Sans section renseignée</option>
        <option v-for="s in sectionsConnues" :key="s" :value="s">{{ s }}</option>
      </select>
      <select v-model="filtreVisibilite" class="filter-select">
        <option value="toutes">Affichées + masquées</option>
        <option value="affichees">Affichées seulement</option>
        <option value="masquees">Masquées seulement</option>
      </select>
      <span class="result-count">{{ lignesFiltrees.length }} / {{ lignes.length }} lignes</span>
      <button class="bulk-btn" :disabled="actionEnMasseEnCours || !lignesFiltrees.length" @click="toggleEnMasse(true)">
        Tout afficher ({{ lignesFiltrees.length }})
      </button>
      <button class="bulk-btn" :disabled="actionEnMasseEnCours || !lignesFiltrees.length" @click="toggleEnMasse(false)">
        Tout masquer ({{ lignesFiltrees.length }})
      </button>
    </div>

    <div v-if="isLoading" class="loading">Chargement…</div>

    <table v-else class="admin-table">
      <thead>
        <tr>
          <th @click="trierPar('code')" class="sortable">Code <span v-if="triColonne === 'code'">{{ triSens === 1 ? '▲' : '▼' }}</span></th>
          <th @click="trierPar('nom')" class="sortable">Nom <span v-if="triColonne === 'nom'">{{ triSens === 1 ? '▲' : '▼' }}</span></th>
          <th @click="trierPar('section_nom')" class="sortable">Section <span v-if="triColonne === 'section_nom'">{{ triSens === 1 ? '▲' : '▼' }}</span></th>
          <th @click="trierPar('actif')" class="sortable">Affichée sur Vue Usine <span v-if="triColonne === 'actif'">{{ triSens === 1 ? '▲' : '▼' }}</span></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="l in lignesFiltrees" :key="l.id" :class="{ inactive: !l.actif }">
          <td>{{ l.code }}</td>
          <td>{{ l.nom }}</td>
          <td class="section-cell">
            <span class="section-value-readonly">
              <strong v-if="l.section_code">{{ l.section_code }}</strong>
              {{ l.section_nom || '— aucune section (Odoo) —' }}
            </span>
          </td>
          <td>
            <button class="toggle-btn" :class="{ on: l.actif }" @click="toggleActif(l)">
              {{ l.actif ? 'Affichée' : 'Masquée' }}
            </button>
          </td>
        </tr>
        <tr v-if="!lignesFiltrees.length">
          <td colspan="4" class="empty-row">Aucune ligne ne correspond à ces filtres.</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.hint { font-size: var(--font-size-sm); color: var(--color-text-muted); max-width: 640px; margin-bottom: var(--space-4); }

.error-banner {
  background: var(--color-rouge-bg); color: var(--color-rouge);
  padding: var(--space-3); border-radius: var(--radius-md); margin-bottom: var(--space-3);
}
.loading { color: var(--color-text-muted); }

.toolbar {
  display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-3); flex-wrap: wrap;
}
.search-input {
  flex: 1; min-width: 220px; height: 36px; padding: 0 var(--space-3);
  border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: var(--font-size-sm);
}
.filter-select {
  height: 36px; padding: 0 var(--space-2); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); font-size: var(--font-size-sm); background: var(--color-surface);
}
.result-count { font-size: var(--font-size-xs); color: var(--color-text-muted); white-space: nowrap; }
.bulk-btn {
  height: 36px; padding: 0 var(--space-3); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); font-size: var(--font-size-xs); font-weight: 700;
  background: var(--color-surface); color: var(--color-text); cursor: pointer; white-space: nowrap;
}
.bulk-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.admin-table {
  width: 100%; border-collapse: collapse; background: var(--color-surface);
  border: 1px solid var(--color-border); border-radius: var(--radius-lg); overflow: hidden;
}
.admin-table th {
  text-align: left; background: var(--color-brand-light); color: var(--color-brand-dark);
  font-size: var(--font-size-xs); padding: var(--space-3); user-select: none;
}
.admin-table th.sortable { cursor: pointer; }
.admin-table th.sortable:hover { text-decoration: underline; }
.admin-table td { padding: var(--space-3); border-top: 1px solid var(--color-border); font-size: var(--font-size-sm); }
.admin-table tr.inactive td:not(:last-child):not(.section-cell) { color: var(--color-text-muted); }
.empty-row { text-align: center; color: var(--color-text-muted); padding: var(--space-6) !important; }

.section-cell { min-width: 160px; }
.section-value-readonly {
  color: var(--color-text); font-size: var(--font-size-sm); display: flex; gap: 6px; align-items: baseline;
}
.section-value-readonly strong { color: var(--color-brand-dark); font-size: var(--font-size-xs); }

.toggle-btn {
  border: 1px solid var(--color-border); background: var(--color-bg); color: var(--color-text-muted);
  border-radius: 999px; padding: 4px 12px; font-size: var(--font-size-xs); font-weight: 700; cursor: pointer;
}
.toggle-btn.on { background: var(--color-vert-bg); color: var(--color-vert); border-color: transparent; }
</style>