<script setup>
/**
 * DataTable.vue -- tableau partagé de Vusine : recherche multi-colonnes, tri par
 * colonne, pagination. 100 % côté client (les volumes Labo restent de l'ordre de
 * quelques milliers de lignes au plus -- 10 000 pour la comparaison Odoo).
 *
 * Même comportement que la recherche/tri de LignesAdmin.vue (clic sur l'en-tête,
 * ▲/▼), généralisé et complété par la pagination -- à réutiliser partout pour garder
 * des écrans homogènes.
 *
 * Utilisation :
 *   <DataTable :columns="colonnes" :rows="lignes" :loading="isLoading"
 *              empty-text="Aucune donnée." :default-sort="{ key: 'jour', dir: 1 }">
 *     <template #cell-statut="{ row }"><span class="badge">{{ row.statut }}</span></template>
 *   </DataTable>
 *
 * Colonne : { key, label, title?, align?: 'right', sortable?: true, searchable?: true,
 *             format?: (valeur, ligne) => string, sortValue?: (ligne) => any }
 *   - format : texte affiché ET texte recherché (ex. nombre formaté à la française).
 *   - sortValue : valeur de tri si elle diffère de row[key] (ex. priorité métier).
 *
 * Ligne dépliable (*** AJOUT 2026-09-23 ***, ex. analyse F4 sous la ligne concernée) :
 * passer `expandedKeys` (un Set des clés de ligne actuellement dépliées, géré par
 * l'écran appelant) et un slot #expanded-row="{ row }" -- rendu dans une <tr> pleine
 * largeur juste après la ligne concernée, tant que sa clé est dans le Set. DataTable ne
 * décide jamais lui-même quoi déplier : il se contente d'afficher ce que l'écran lui dit.
 */
import { ref, computed, watch } from 'vue'

const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  rowKey: { type: [String, Function], default: 'id' },
  loading: { type: Boolean, default: false },
  emptyText: { type: String, default: 'Aucune donnée.' },
  searchPlaceholder: { type: String, default: 'Rechercher dans toutes les colonnes…' },
  defaultSort: { type: Object, default: null },   // { key, dir: 1 | -1 }
  pageSize: { type: Number, default: 25 },
  pageSizes: { type: Array, default: () => [25, 50, 100] },
  rowClass: { type: Function, default: null },
  expandedKeys: { type: Set, default: null },
})

const recherche = ref('')
const triCle = ref(props.defaultSort?.key ?? null)
const triSens = ref(props.defaultSort?.dir ?? 1)
const page = ref(1)
const taillePage = ref(props.pageSize)

// Recherche insensible à la casse ET aux accents ("creme" trouve "Crème").
function normaliser(v) {
  return String(v ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
}

function texteCellule(col, row) {
  const v = row[col.key]
  if (col.format) return col.format(v, row)
  return v ?? ''
}

const colonnesRecherchables = computed(() => props.columns.filter(c => c.key && c.searchable !== false))

const lignesFiltrees = computed(() => {
  const q = normaliser(recherche.value.trim())
  if (!q) return props.rows
  const mots = q.split(/\s+/)
  // Tous les mots doivent être présents, dans n'importe quelle colonne ("ccl02 creme").
  return props.rows.filter(row => {
    const texte = colonnesRecherchables.value.map(c => normaliser(texteCellule(c, row))).join(' ')
    return mots.every(m => texte.includes(m))
  })
})

function comparer(a, b) {
  const vide = v => v === null || v === undefined || v === ''
  if (vide(a) && vide(b)) return 0
  if (vide(a)) return 1    // valeurs vides toujours en fin de liste, quel que soit le sens
  if (vide(b)) return -1
  const na = Number(a), nb = Number(b)
  if (typeof a !== 'boolean' && !Number.isNaN(na) && !Number.isNaN(nb) && String(a).trim() !== '' && String(b).trim() !== '') {
    return na - nb
  }
  return String(a).localeCompare(String(b), 'fr', { numeric: true, sensitivity: 'base' })
}

const lignesTriees = computed(() => {
  if (!triCle.value) return lignesFiltrees.value
  const col = props.columns.find(c => c.key === triCle.value)
  const valeur = col?.sortValue ?? (row => row[triCle.value])
  return [...lignesFiltrees.value].sort((a, b) => {
    const va = valeur(a), vb = valeur(b)
    const vide = v => v === null || v === undefined || v === ''
    if (vide(va) !== vide(vb)) return vide(va) ? 1 : -1   // vides en fin, dans les deux sens
    return comparer(va, vb) * triSens.value
  })
})

const nbPages = computed(() => Math.max(1, Math.ceil(lignesTriees.value.length / taillePage.value)))
const lignesPage = computed(() => {
  const debut = (page.value - 1) * taillePage.value
  return lignesTriees.value.slice(debut, debut + taillePage.value)
})
const premier = computed(() => lignesTriees.value.length ? (page.value - 1) * taillePage.value + 1 : 0)
const dernier = computed(() => Math.min(page.value * taillePage.value, lignesTriees.value.length))

// Pages affichées : 1 … 4 5 [6] 7 8 … 20
const pagesVisibles = computed(() => {
  const n = nbPages.value, p = page.value
  if (n <= 7) return Array.from({ length: n }, (_, i) => i + 1)
  const pages = new Set([1, n, p - 1, p, p + 1])
  const liste = [...pages].filter(x => x >= 1 && x <= n).sort((a, b) => a - b)
  const resultat = []
  liste.forEach((x, i) => {
    if (i && x - liste[i - 1] > 1) resultat.push('…' + x)
    resultat.push(x)
  })
  return resultat
})

watch([recherche, taillePage, () => props.rows], () => { page.value = 1 })
watch(nbPages, n => { if (page.value > n) page.value = n })

function trierPar(col) {
  if (col.sortable === false || !col.key) return
  if (triCle.value === col.key) {
    triSens.value *= -1
  } else {
    triCle.value = col.key
    triSens.value = 1
  }
  page.value = 1
}

function cle(row, index) {
  if (typeof props.rowKey === 'function') return props.rowKey(row, index)
  return row[props.rowKey] ?? index
}

function ariaSort(col) {
  if (triCle.value !== col.key) return 'none'
  return triSens.value === 1 ? 'ascending' : 'descending'
}
</script>

<template>
  <div class="data-table">
    <div class="dt-barre">
      <div class="dt-recherche">
        <svg class="dt-loupe" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2" />
          <line x1="16.5" y1="16.5" x2="21" y2="21" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
        </svg>
        <input
          v-model="recherche" type="search" :placeholder="searchPlaceholder"
          :title="`Recherche dans : ${colonnesRecherchables.map(c => c.label).join(', ')}`"
          aria-label="Rechercher dans le tableau"
        />
      </div>
      <slot name="filtres" />
      <span class="dt-compte">
        {{ lignesFiltrees.length.toLocaleString('fr-FR') }} / {{ rows.length.toLocaleString('fr-FR') }}
      </span>
    </div>

    <div v-if="loading" class="dt-etat">Chargement…</div>

    <div v-else class="dt-cadre">
      <table>
        <thead>
          <tr>
            <th
              v-for="col in columns" :key="col.key || col.label"
              :class="{ triable: col.sortable !== false && col.key, droite: col.align === 'right', actif: triCle === col.key }"
              :title="col.title || (col.sortable !== false && col.key ? `Trier par ${col.label}` : '')"
              :aria-sort="ariaSort(col)"
            >
              <button
                v-if="col.sortable !== false && col.key" type="button" class="dt-tri"
                @click="trierPar(col)"
              >
                {{ col.label }}
                <span class="dt-fleche" aria-hidden="true">{{ triCle === col.key ? (triSens === 1 ? '▲' : '▼') : '↕' }}</span>
              </button>
              <template v-else>{{ col.label }}</template>
            </th>
          </tr>
        </thead>
        <tbody>
          <template v-for="(row, i) in lignesPage" :key="cle(row, i)">
            <tr :class="rowClass ? rowClass(row) : null">
              <td v-for="col in columns" :key="col.key || col.label" :class="{ droite: col.align === 'right' }">
                <slot :name="`cell-${col.key}`" :row="row" :value="row[col.key]">
                  {{ col.format ? col.format(row[col.key], row) : (row[col.key] ?? '—') }}
                </slot>
              </td>
            </tr>
            <!-- *** AJOUT 2026-09-23 *** : ligne dépliée, pleine largeur, juste sous la
                 ligne concernée -- l'écran appelant décide QUI est déplié (expandedKeys),
                 DataTable se contente d'afficher #expanded-row tant que c'est demandé. -->
            <tr v-if="expandedKeys && expandedKeys.has(cle(row, i))" class="dt-ligne-etendue">
              <td :colspan="columns.length">
                <slot name="expanded-row" :row="row" />
              </td>
            </tr>
          </template>
          <tr v-if="!lignesPage.length">
            <td :colspan="columns.length" class="dt-vide">
              {{ rows.length ? 'Aucune ligne ne correspond à la recherche.' : emptyText }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="!loading && lignesTriees.length > pageSizes[0]" class="dt-pagination">
      <span class="dt-plage">
        {{ premier.toLocaleString('fr-FR') }}–{{ dernier.toLocaleString('fr-FR') }}
        sur {{ lignesTriees.length.toLocaleString('fr-FR') }}
      </span>
      <div class="dt-pages">
        <button type="button" class="dt-page" :disabled="page === 1" title="Page précédente" @click="page--">‹</button>
        <template v-for="p in pagesVisibles" :key="p">
          <span v-if="typeof p === 'string'" class="dt-ellipse">…</span>
          <button
            v-else type="button" :class="['dt-page', { courante: p === page }]"
            :aria-current="p === page ? 'page' : null" @click="page = p"
          >{{ p }}</button>
        </template>
        <button type="button" class="dt-page" :disabled="page === nbPages" title="Page suivante" @click="page++">›</button>
      </div>
      <label class="dt-taille">
        Lignes par page
        <select v-model.number="taillePage">
          <option v-for="t in pageSizes" :key="t" :value="t">{{ t }}</option>
        </select>
      </label>
    </div>
  </div>
</template>

<style scoped>
.dt-barre { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-3); flex-wrap: wrap; }
.dt-recherche { position: relative; flex: 1; min-width: 220px; }
.dt-loupe { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--color-text-muted); pointer-events: none; }
.dt-recherche input {
  width: 100%; height: 36px; padding: 0 var(--space-3) 0 32px;
  border: 1px solid var(--color-border); border-radius: var(--radius-md);
  font-size: var(--font-size-sm); background: var(--color-surface); font-family: inherit;
}
.dt-recherche input:focus { outline: 2px solid var(--color-brand); outline-offset: -1px; }
.dt-compte { font-size: var(--font-size-xs); color: var(--color-text-muted); white-space: nowrap; }
.dt-etat { color: var(--color-text-muted); padding: var(--space-4) 0; }

.dt-cadre {
  overflow-x: auto; background: var(--color-surface);
  border: 1px solid var(--color-border); border-radius: var(--radius-lg);
}
table { width: 100%; border-collapse: collapse; }
th {
  text-align: left; background: var(--color-brand-light); color: var(--color-brand-dark);
  font-size: var(--font-size-xs); font-weight: 700; padding: var(--space-3); white-space: nowrap; user-select: none;
}
td { padding: var(--space-3); border-top: 1px solid var(--color-border); font-size: var(--font-size-sm); }
tbody tr:hover td { background: #F8FAFC; }
/* Ligne dépliée (*** AJOUT 2026-09-23 ***) : pas de séparation ni de survol -- elle
   fait visuellement corps avec la ligne juste au-dessus. */
.dt-ligne-etendue td { padding: 0; border-top: none; background: var(--color-brand-light); }
.dt-ligne-etendue:hover td { background: var(--color-brand-light); }
.droite { text-align: right; }
th.droite .dt-tri { justify-content: flex-end; }

.dt-tri {
  display: inline-flex; align-items: center; gap: 4px; width: 100%;
  border: none; background: none; padding: 0; font: inherit; color: inherit; cursor: pointer;
}
.dt-tri:hover { text-decoration: underline; }
.dt-tri:focus-visible { outline: 2px solid var(--color-brand); outline-offset: 2px; border-radius: 2px; }
.dt-fleche { font-size: 10px; opacity: 0.35; }
th.actif .dt-fleche { opacity: 1; }
.dt-vide { text-align: center; color: var(--color-text-muted); padding: var(--space-6) !important; }

.dt-pagination {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-3);
  flex-wrap: wrap; margin-top: var(--space-3); font-size: var(--font-size-xs); color: var(--color-text-muted);
}
.dt-pages { display: flex; align-items: center; gap: 4px; }
.dt-page {
  min-width: 30px; height: 30px; padding: 0 var(--space-2); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); background: var(--color-surface); color: var(--color-text);
  font-size: var(--font-size-xs); font-weight: 600; cursor: pointer; font-family: inherit;
  transition: background-color .15s ease, border-color .15s ease;
}
.dt-page:hover:not(:disabled) { border-color: var(--color-brand); background: var(--color-brand-light); }
.dt-page.courante { background: var(--color-brand); border-color: var(--color-brand); color: var(--color-text-inverse); }
.dt-page:disabled { opacity: .4; cursor: not-allowed; }
.dt-page:focus-visible { outline: 2px solid var(--color-brand); outline-offset: 2px; }
.dt-ellipse { padding: 0 4px; }
.dt-taille select {
  margin-left: var(--space-2); height: 30px; border: 1px solid var(--color-border);
  border-radius: var(--radius-md); background: var(--color-surface); font-family: inherit;
}
@media (prefers-reduced-motion: reduce) { .dt-page { transition: none; } }
</style>
