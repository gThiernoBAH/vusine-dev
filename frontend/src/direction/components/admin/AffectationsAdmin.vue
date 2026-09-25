<script setup>
/**
 * AffectationsAdmin.vue -- qui travaille sur quelle ligne, PAR LIGNE.
 * *** AJOUT 2026-09-24 *** : jusqu'ici l'affectation se faisait compte par compte (Personnel →
 * icône « Lignes affectées »), ce qui ne permet pas de composer une équipe. Ici on choisit une
 * ligne, puis on coche plusieurs personnes d'un coup. Ces affectations alimentent l'effectif
 * des lignes, le score d'équipe et « Voir mes performances ».
 */
import { ref, computed, onMounted } from 'vue'
import apiClient from '@/api/client'
import { Search, UserMinus } from 'lucide-vue-next'

const lignes = ref([])
const personnes = ref([])
const effectifs = ref({})
const ligneChoisie = ref(null)
const affectes = ref([])
const rechercheLigne = ref('')
const recherchePersonne = ref('')
const cochees = ref(new Set())
const isLoading = ref(true)
const enCours = ref(false)
const errorMessage = ref('')
const message = ref('')

async function charger() {
  isLoading.value = true
  try {
    const [l, u, e] = await Promise.all([
      apiClient.get('/admin/lignes'), apiClient.get('/auth/users'), apiClient.get('/admin/affectations-effectifs'),
    ])
    lignes.value = l.data.filter(x => x.actif !== false)
    personnes.value = u.data.filter(x => ['operateur', 'ouvrier'].includes(x.user_type) && x.is_active)
    effectifs.value = e.data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger les données.'
  } finally {
    isLoading.value = false
  }
}
onMounted(charger)

const norm = t => String(t ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()

// Lignes groupées par section, filtrées par la recherche.
const groupes = computed(() => {
  const q = norm(rechercheLigne.value)
  const par = new Map()
  for (const l of lignes.value) {
    if (q && !norm(`${l.code} ${l.nom} ${l.section_nom || ''}`).includes(q)) continue
    const s = l.section_nom || 'Sans section'
    if (!par.has(s)) par.set(s, [])
    par.get(s).push(l)
  }
  return [...par.entries()].sort((a, b) => a[0].localeCompare(b[0]))
})

async function choisirLigne(l) {
  ligneChoisie.value = l
  cochees.value = new Set()
  message.value = ''
  await chargerAffectes()
}
async function chargerAffectes() {
  try {
    affectes.value = (await apiClient.get(`/admin/affectations-ligne/${ligneChoisie.value.id}`)).data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || "Impossible de charger l'équipe de cette ligne."
  }
}

const deja = computed(() => new Set(affectes.value.map(a => a.user_id)))
const candidats = computed(() => {
  const q = norm(recherchePersonne.value)
  return personnes.value
    .filter(p => !deja.value.has(p.id))
    .filter(p => !q || norm(`${p.nom} ${p.matricule || ''}`).includes(q))
    .sort((a, b) => a.nom.localeCompare(b.nom))
})

function basculer(p) {
  const s = new Set(cochees.value)
  s.has(p.id) ? s.delete(p.id) : s.add(p.id)
  cochees.value = s
}
const toutCocher = () => { cochees.value = new Set(candidats.value.map(p => p.id)) }
const toutDecocher = () => { cochees.value = new Set() }

async function affecter() {
  if (!cochees.value.size || enCours.value) return
  enCours.value = true
  message.value = ''
  try {
    const r = (await apiClient.post(`/admin/affectations-ligne/${ligneChoisie.value.id}`, { user_ids: [...cochees.value] })).data
    message.value = `${r.ajoutes} personne(s) affectée(s)${r.deja_affectes ? `, ${r.deja_affectes} déjà présente(s)` : ''}${r.ignores ? `, ${r.ignores} ignorée(s)` : ''}.`
    cochees.value = new Set()
    await Promise.all([chargerAffectes(), rafraichirEffectifs()])
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || "Échec de l'affectation."
  } finally {
    enCours.value = false
  }
}
async function retirer(a) {
  try {
    await apiClient.post(`/admin/affectations-personnel/${a.affectation_id}/terminer`)
    message.value = `${a.nom} retiré(e) de la ligne.`
    await Promise.all([chargerAffectes(), rafraichirEffectifs()])
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Échec du retrait.'
  }
}
async function rafraichirEffectifs() {
  try { effectifs.value = (await apiClient.get('/admin/affectations-effectifs')).data } catch { /* non bloquant */ }
}
const effectifDe = l => effectifs.value[String(l.id)] || 0
</script>

<template>
  <div class="affectations">
    <p class="hint">
      Composez l'équipe de chaque ligne. Ces affectations alimentent l'<strong>effectif</strong> des lignes, le <strong>score d'équipe</strong>
      et la page « Mes performances » de chaque opérateur. <strong>Ce sont aussi ces affectations qui déterminent les lignes que chaque opérateur voit sur sa tablette</strong> (« Mes lignes »). Une personne peut être affectée à plusieurs lignes.
    </p>
    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>

    <div v-else class="deux-colonnes">
      <!-- Colonne gauche : les lignes, groupées par section -->
      <section class="colonne lignes">
        <label class="recherche"><Search :size="16" />
          <input v-model="rechercheLigne" type="search" placeholder="Filtrer les lignes (code, nom, section)…" />
        </label>
        <div class="liste">
          <template v-for="[section, ls] in groupes" :key="section">
            <div class="section-titre">{{ section }}</div>
            <button v-for="l in ls" :key="l.id" type="button" :class="['ligne-item', { actif: ligneChoisie?.id === l.id }]" @click="choisirLigne(l)">
              <span class="ligne-code">{{ l.code }}</span>
              <span class="ligne-nom">{{ l.nom }}</span>
              <span :class="['effectif', { vide: !effectifDe(l) }]" :title="effectifDe(l) ? `${effectifDe(l)} personne(s) affectée(s)` : 'Personne affecté'">{{ effectifDe(l) }}</span>
            </button>
          </template>
          <p v-if="!groupes.length" class="empty">Aucune ligne ne correspond.</p>
        </div>
      </section>

      <!-- Colonne droite : l'équipe de la ligne choisie -->
      <section class="colonne equipe">
        <p v-if="!ligneChoisie" class="empty">Choisissez une ligne à gauche pour composer son équipe.</p>
        <template v-else>
          <h2>{{ ligneChoisie.code }} — {{ ligneChoisie.nom }}</h2>
          <p v-if="message" class="success-banner">{{ message }}</p>

          <h3>Équipe actuelle ({{ affectes.length }})</h3>
          <p v-if="!affectes.length" class="empty">Personne n'est affecté à cette ligne.</p>
          <ul v-else class="affectes">
            <li v-for="a in affectes" :key="a.affectation_id">
              <span>{{ a.nom }}<small v-if="a.matricule"> ({{ a.matricule }})</small></span>
              <button type="button" class="retirer" @click="retirer(a)"><UserMinus :size="14" /> Retirer</button>
            </li>
          </ul>

          <h3>Ajouter des personnes</h3>
          <label class="recherche"><Search :size="16" />
            <input v-model="recherchePersonne" type="search" placeholder="Rechercher un nom ou un matricule…" />
          </label>
          <div class="outils-liste">
            <button type="button" class="lien" @click="toutCocher">tout cocher ({{ candidats.length }})</button>
            <button type="button" class="lien" @click="toutDecocher">tout décocher</button>
          </div>
          <ul class="candidats">
            <li v-for="p in candidats" :key="p.id">
              <label><input type="checkbox" :checked="cochees.has(p.id)" @change="basculer(p)" />
                {{ p.nom }}<small v-if="p.matricule"> ({{ p.matricule }})</small>
              </label>
            </li>
            <li v-if="!candidats.length" class="empty">Aucune personne à ajouter.</li>
          </ul>
          <button type="button" class="btn primary" :disabled="!cochees.size || enCours" @click="affecter">
            {{ enCours ? 'Affectation…' : `Affecter ${cochees.size || ''} personne(s)` }}
          </button>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.hint { color: var(--color-text-muted); font-size: var(--font-size-sm); margin: 0 0 var(--space-4); max-width: 1120px}
.deux-colonnes { display: grid; grid-template-columns: minmax(280px, 380px) 1fr; gap: var(--space-4); align-items: start; }
.colonne { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: var(--space-4); }
.recherche { display: flex; align-items: center; gap: var(--space-2); height: 38px; padding: 0 var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); color: var(--color-text-muted); margin-bottom: var(--space-2); }
.recherche input { flex: 1; border: none; outline: none; background: transparent; font-family: inherit; color: var(--color-text); }
.liste { max-height: 62vh; overflow-y: auto; }
.section-titre { font-size: var(--font-size-xs); font-weight: 700; text-transform: uppercase; color: var(--color-text-muted); margin: var(--space-3) 0 var(--space-1); }
.ligne-item { display: flex; align-items: center; gap: var(--space-2); width: 100%; text-align: left; border: none; background: none; padding: var(--space-2); border-radius: var(--radius-md); cursor: pointer; font-family: inherit; }
.ligne-item:hover { background: var(--color-brand-light); }
.ligne-item.actif { background: var(--color-brand); color: var(--color-text-inverse); }
.ligne-code { font-weight: 700; min-width: 64px; }
.ligne-nom { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--font-size-sm); }
.effectif { min-width: 26px; text-align: center; font-size: var(--font-size-xs); font-weight: 700; padding: 2px 6px; border-radius: 999px; background: var(--color-vert-bg); color: var(--color-vert); }
.effectif.vide { background: var(--color-orange-bg); color: #92400E; }
.equipe h2 { margin: 0 0 var(--space-3); }
.equipe h3 { margin: var(--space-4) 0 var(--space-2); font-size: var(--font-size-md); }
.affectes, .candidats { list-style: none; margin: 0; padding: 0; }
.affectes li { display: flex; justify-content: space-between; align-items: center; padding: var(--space-2) 0; border-bottom: 1px solid var(--color-border); }
.retirer { display: inline-flex; align-items: center; gap: 4px; border: 1px solid var(--color-border); background: var(--color-surface); border-radius: var(--radius-md); padding: 4px 10px; cursor: pointer; font-family: inherit; }
.candidats { max-height: 32vh; overflow-y: auto; border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: var(--space-2); margin-bottom: var(--space-3); }
.candidats li { padding: 4px 0; }
.candidats label { display: flex; align-items: center; gap: var(--space-2); cursor: pointer; }
.outils-liste { display: flex; gap: var(--space-3); margin-bottom: var(--space-2); }
.lien { border: none; background: none; color: var(--color-brand); cursor: pointer; padding: 0; font: inherit; text-decoration: underline; }
.btn { display: inline-flex; align-items: center; gap: var(--space-2); border: none; border-radius: var(--radius-md); padding: 0 var(--space-4); height: 38px; font-weight: 700; cursor: pointer; background: var(--color-brand); color: var(--color-text-inverse); }
.btn:disabled { opacity: .55; cursor: not-allowed; }
.success-banner { background: var(--color-vert-bg); color: var(--color-vert); padding: var(--space-3); border-radius: var(--radius-md); }
.error-banner { background: var(--color-rouge-bg); color: var(--color-rouge); padding: var(--space-3); border-radius: var(--radius-md); }
.empty, .loading { color: var(--color-text-muted); }
</style>
