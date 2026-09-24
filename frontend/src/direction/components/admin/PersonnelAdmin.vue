<script setup>
import { ref, computed, onMounted } from 'vue'
import apiClient from '@/api/client'
import { Plus, Pencil, Trash2, KeyRound, Users as UsersIcon, X, Search, ChevronDown, Check, Briefcase, HardHat, Wrench } from 'lucide-vue-next'
import { useConfirm } from '@/composables/useConfirm'

// *** AJOUT (chantier Labo) *** : compte connecté, pour n'afficher le contrôle Admin
// qu'à un compte is_super_admin -- même patron que CockpitView.vue/LigneDetailView.vue.
const user = JSON.parse(sessionStorage.getItem('user') || '{}')
const { confirm } = useConfirm()

const utilisateurs = ref([])
const departements = ref([])
const lignes = ref([])
const permissionsRegistry = ref([])
const isLoading = ref(true)
const errorMessage = ref('')

async function chargerTout() {
  isLoading.value = true
  try {
    const [usersRes, deptRes, lignesRes, permRes] = await Promise.all([
      apiClient.get('/auth/users'),
      apiClient.get('/auth/departements'),
      // *** CORRIGÉ 2026-09-18 *** : /entities/lignes ne renvoie QUE les lignes actives
      // (actif=True) -- une ligne masquée de Vue Usine restait invisible ici, impossible
      // à sélectionner même pour un cas légitime (préparer une affectation avant
      // réactivation). /admin/lignes renvoie tout, avec section_nom + actif -- exactement
      // ce qu'il faut pour grouper par section et distinguer actif/inactif dans le
      // sélecteur (cf. lignesDisponibles plus bas).
      apiClient.get('/admin/lignes'),
      apiClient.get('/auth/permissions/registry'),
    ])
    utilisateurs.value = usersRes.data
    departements.value = deptRes.data
    lignes.value = lignesRes.data
    permissionsRegistry.value = permRes.data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger le personnel.'
  } finally {
    isLoading.value = false
  }
}
onMounted(chargerTout)

// --- Recherche / filtre (même principe que LignesAdmin/VueUsineView -- volume modeste,
// 100% client) ------------------------------------------------------------------
const recherche = ref('')
const filtreType = ref('tous')  // 'tous' | 'direction' | 'operateur' | 'ouvrier'

const TYPE_LABELS = { direction: 'Direction', operateur: 'Opérateur', ouvrier: 'Ouvrier' }

// *** AJOUT 2026-09-23 *** : boutons de type de compte en tête du formulaire de
// création (cf. cadrage -- le sélecteur discret d'avant, perdu entre Nom et Mot de
// passe, cachait que Matricule/Catégorie n'apparaissent QUE pour Opérateur/Ouvrier).
const TYPES_COMPTE = [
  { value: 'direction', label: 'Direction', icone: Briefcase,
    description: 'Se connecte au cockpit (PC) avec un identifiant.' },
  { value: 'operateur', label: 'Opérateur', icone: HardHat,
    description: 'Se connecte sur la tablette avec son matricule.' },
  { value: 'ouvrier', label: 'Ouvrier', icone: Wrench,
    description: 'Se connecte sur la tablette avec son matricule.' },
]

// *** AJOUT 2026-09-23 *** : "Ancien CDI" existe déjà côté modèle (models.User,
// categorie_personnel) mais manquait dans les deux formulaires -- impossible à
// saisir depuis l'écran alors que la donnée est prévue et exploitée par le scoring.
const CATEGORIES_PERSONNEL = ['CDI', 'CDD', 'Journalier', 'Ancien CDI']

const utilisateursFiltres = computed(() => {
  const q = recherche.value.trim().toLowerCase()
  return utilisateurs.value.filter(u => {
    if (q && !`${u.nom} ${u.username || ''} ${u.matricule || ''}`.toLowerCase().includes(q)) return false
    if (filtreType.value !== 'tous' && u.user_type !== filtreType.value) return false
    return true
  })
})

function departementNom(id) {
  return departements.value.find(d => d.id === id)?.name || '—'
}

// ---------------------------------------------------------------
// Création -- POST /auth/users (schemas.UserCreate) : un SEUL de username/matricule
// selon user_type, jamais les deux -- cf. validation côté route/crud.
// ---------------------------------------------------------------
const showCreateForm = ref(false)
const createError = ref('')
const createSubmitting = ref(false)

function defaultCreateForm() {
  return {
    userType: 'direction', nom: '', password: '', username: '', matricule: '',
    categoriePersonnel: 'CDI', email: '', telephone: '', departementId: null,
    isAdmin: false,  // *** AJOUT (chantier Labo) ***
  }
}
const createForm = ref(defaultCreateForm())

async function creerUtilisateur() {
  createError.value = ''
  createSubmitting.value = true
  const payload = {
    nom: createForm.value.nom,
    password: createForm.value.password,
    user_type: createForm.value.userType,
    email: createForm.value.email || null,
    telephone: createForm.value.telephone || null,
    departement_id: createForm.value.departementId || null,
  }
  if (createForm.value.userType === 'direction') {
    payload.username = createForm.value.username
    // *** AJOUT (chantier Labo) *** : le backend re-vérifie is_super_admin de toute
    // façon (403 sinon) -- ce garde côté formulaire évite juste d'envoyer le champ
    // pour un compte qui ne pourrait de toute façon pas l'utiliser.
    if (user.is_super_admin) payload.is_admin = createForm.value.isAdmin
  } else {
    payload.matricule = createForm.value.matricule
    payload.categorie_personnel = createForm.value.categoriePersonnel
  }
  try {
    await apiClient.post('/auth/users', payload)
    showCreateForm.value = false
    createForm.value = defaultCreateForm()
    chargerTout()
  } catch (e) {
    createError.value = e.response?.data?.detail || 'Échec de la création.'
  } finally {
    createSubmitting.value = false
  }
}

// ---------------------------------------------------------------
// Édition -- PATCH /auth/users/{id} (schemas.UserUpdate, tous champs optionnels)
// ---------------------------------------------------------------
const utilisateurEnEdition = ref(null)
const editForm = ref({})
const editError = ref('')

function ouvrirEdition(u) {
  utilisateurEnEdition.value = u
  editForm.value = {
    nom: u.nom, email: u.email || '', telephone: u.telephone || '',
    departementId: u.departement_id, isActive: u.is_active, isAdmin: u.is_admin,
    userType: u.user_type, categoriePersonnel: u.categorie_personnel || '',
  }
  editError.value = ''
}

async function enregistrerEdition() {
  editError.value = ''
  try {
    await apiClient.patch(`/auth/users/${utilisateurEnEdition.value.id}`, {
      nom: editForm.value.nom,
      email: editForm.value.email || null,
      telephone: editForm.value.telephone || null,
      departement_id: editForm.value.departementId || null,
      is_active: editForm.value.isActive,
      is_admin: editForm.value.isAdmin,
      user_type: editForm.value.userType,
      categorie_personnel: editForm.value.categoriePersonnel || null,
    })
    utilisateurEnEdition.value = null
    chargerTout()
  } catch (e) {
    editError.value = e.response?.data?.detail || 'Échec de la mise à jour.'
  }
}

async function supprimerUtilisateur(u) {
  const ok = await confirm({
    title: 'Supprimer ce compte ?',
    message: `Supprimer définitivement ${u.nom} ? Cette action est irréversible.`,
    danger: true, confirmLabel: 'Supprimer',
  })
  if (!ok) return
  try {
    await apiClient.delete(`/auth/users/${u.id}`)
    chargerTout()
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Échec de la suppression.'
  }
}

// ---------------------------------------------------------------
// Permissions -- comptes "direction" uniquement (cf. auth_routes.PERMISSION_REGISTRY,
// pensé pour les menus cockpit -- un compte terrain n'a jamais accès par ce système).
// ---------------------------------------------------------------
const utilisateurPermissions = ref(null)
const permissionsCochees = ref(new Set())
const permissionsError = ref('')

async function ouvrirPermissions(u) {
  utilisateurPermissions.value = u
  permissionsError.value = ''
  try {
    const res = await apiClient.get(`/auth/users/${u.id}/permissions`)
    permissionsCochees.value = new Set(res.data.granted)
  } catch (e) {
    permissionsError.value = 'Impossible de charger les permissions.'
  }
}

function togglePermission(key) {
  if (permissionsCochees.value.has(key)) permissionsCochees.value.delete(key)
  else permissionsCochees.value.add(key)
}

async function enregistrerPermissions() {
  permissionsError.value = ''
  try {
    await apiClient.put(`/auth/users/${utilisateurPermissions.value.id}/permissions`, {
      granted: Array.from(permissionsCochees.value),
    })
    utilisateurPermissions.value = null
  } catch (e) {
    permissionsError.value = e.response?.data?.detail || 'Échec de la mise à jour.'
  }
}

// ---------------------------------------------------------------
// Affectations aux lignes -- personnel terrain uniquement (operateur/ouvrier). Une
// personne peut être affectée à plusieurs lignes en même temps (cf.
// config_admin_routes.creer_affectation_personnel, pas de clôture automatique).
// ---------------------------------------------------------------
const utilisateurAffectations = ref(null)
const affectations = ref([])
const nouvelleLigneId = ref(null)
const affectationsError = ref('')
const panneauLigneOuvert = ref(false)  // *** REVU 2026-09-18 *** remplace le <select> natif
const rechercheLigne = ref('')

async function ouvrirAffectations(u) {
  utilisateurAffectations.value = u
  affectationsError.value = ''
  nouvelleLigneId.value = null
  panneauLigneOuvert.value = false
  rechercheLigne.value = ''
  await chargerAffectations()
}

async function chargerAffectations() {
  try {
    const res = await apiClient.get('/admin/affectations-personnel', {
      params: { user_id: utilisateurAffectations.value.id },
    })
    affectations.value = res.data
  } catch (e) {
    affectationsError.value = 'Impossible de charger les affectations.'
  }
}

const affectationsActives = computed(() => affectations.value.filter(a => !a.date_fin))
const affectationsPassees = computed(() => affectations.value.filter(a => a.date_fin))

function ligneCode(ligneId) {
  return lignes.value.find(l => l.id === ligneId)?.code || `#${ligneId}`
}

const lignesDisponibles = computed(() => {
  const dejaAffectees = new Set(affectationsActives.value.map(a => a.ligne_id))
  const q = rechercheLigne.value.trim().toLowerCase()
  const restantes = lignes.value.filter(l => {
    if (dejaAffectees.has(l.id)) return false
    if (q && !`${l.code} ${l.nom}`.toLowerCase().includes(q)) return false
    return true
  })

  // Regroupées par section (cf. sections_cache, synchronisé depuis Odoo -- fiable
  // depuis le 2026-09-18) -- triées par nom de section puis par code de ligne, "Sans
  // section" toujours en dernier plutôt que mélangé alphabétiquement au milieu.
  const groupes = new Map()
  for (const l of restantes) {
    const section = l.section_nom || 'Sans section'
    if (!groupes.has(section)) groupes.set(section, [])
    groupes.get(section).push(l)
  }
  const sections = Array.from(groupes.keys()).sort((a, b) => {
    if (a === 'Sans section') return 1
    if (b === 'Sans section') return -1
    return a.localeCompare(b)
  })
  return sections.map(section => ({
    section,
    lignes: groupes.get(section).sort((a, b) => a.code.localeCompare(b.code)),
  }))
})

const ligneChoisie = computed(() => lignes.value.find(l => l.id === nouvelleLigneId.value) || null)

function choisirLigne(l) {
  nouvelleLigneId.value = l.id
  panneauLigneOuvert.value = false
}

async function ajouterAffectation() {
  if (!nouvelleLigneId.value) return
  affectationsError.value = ''
  try {
    await apiClient.post('/admin/affectations-personnel', {
      user_id: utilisateurAffectations.value.id, ligne_id: nouvelleLigneId.value,
    })
    nouvelleLigneId.value = null
    rechercheLigne.value = ''
    chargerAffectations()
  } catch (e) {
    affectationsError.value = e.response?.data?.detail || "Échec de l'affectation."
  }
}

async function terminerAffectation(a) {
  affectationsError.value = ''
  try {
    await apiClient.post(`/admin/affectations-personnel/${a.id}/terminer`)
    chargerAffectations()
  } catch (e) {
    affectationsError.value = e.response?.data?.detail || 'Échec.'
  }
}
</script>

<template>
  <div class="personnel-admin">
    <p class="hint">
      Comptes direction et personnel terrain. Les comptes terrain (Opérateur / Ouvrier)
      se connectent sur la tablette avec leur matricule -- les comptes direction avec
      leur identifiant, côté cockpit.
    </p>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>

    <div class="toolbar">
      <div class="search-wrap">
        <Search :size="16" class="search-icon" />
        <input v-model="recherche" type="search" placeholder="Rechercher par nom, identifiant…" class="search-input" />
      </div>
      <select v-model="filtreType" class="filter-select">
        <option value="tous">Tous les types</option>
        <option value="direction">Direction</option>
        <option value="operateur">Opérateur</option>
        <option value="ouvrier">Ouvrier</option>
      </select>
      <span class="result-count">{{ utilisateursFiltres.length }} / {{ utilisateurs.length }}</span>
      <button class="add-btn" @click="showCreateForm = !showCreateForm"><Plus :size="16" /> Nouveau compte</button>
    </div>

    <!-- Création -->
    <div v-if="showCreateForm" class="form-card">
      <!-- *** AJOUT 2026-09-23 *** : le type de compte en premier, sous forme de choix
           visuel -- avant, un <select> discret perdu entre Nom et Mot de passe laissait
           croire que Matricule/Catégorie manquaient, alors qu'ils n'apparaissent que
           pour Opérateur/Ouvrier (cf. TYPES_COMPTE plus haut). -->
      <div class="type-picker">
        <button
          v-for="t in TYPES_COMPTE" :key="t.value" type="button"
          :class="['type-option', { selected: createForm.userType === t.value }]"
          :title="t.description" @click="createForm.userType = t.value"
        >
          <component :is="t.icone" :size="20" />
          <span class="type-option-label">{{ t.label }}</span>
          <span class="type-option-desc">{{ t.description }}</span>
        </button>
      </div>

      <div class="form-row">
        <label class="field"><span>Nom</span><input v-model="createForm.nom" type="text" autocomplete="off" /></label>
        <label class="field">
          <span>Mot de passe</span>
          <!-- autocomplete="new-password" : empêche Chrome de préremplir avec un
               identifiant/mot de passe déjà enregistré pour ce site (cf. bug réel
               observé -- "admin" + mot de passe apparaissaient seuls à l'ouverture). -->
          <input v-model="createForm.password" type="password" placeholder="min. 6 caractères" autocomplete="new-password" />
        </label>
      </div>

      <div class="form-row">
        <label v-if="createForm.userType === 'direction'" class="field">
          <span>Identifiant (username)</span>
          <input v-model="createForm.username" type="text" placeholder="ex: mdirection" autocomplete="off" />
        </label>
        <template v-else>
          <label class="field">
            <span>Matricule</span>
            <input v-model="createForm.matricule" type="text" placeholder="ex: OP0456" autocomplete="off" />
          </label>
          <label class="field">
            <span>Catégorie</span>
            <select v-model="createForm.categoriePersonnel">
              <option v-for="c in CATEGORIES_PERSONNEL" :key="c" :value="c">{{ c }}</option>
            </select>
          </label>
        </template>
        <label class="field">
          <span>Département</span>
          <select v-model.number="createForm.departementId">
            <option :value="null">—</option>
            <option v-for="d in departements" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
        </label>
      </div>

      <div class="form-row">
        <label class="field"><span>Email (optionnel)</span><input v-model="createForm.email" type="email" autocomplete="off" /></label>
        <label class="field"><span>Téléphone (optionnel)</span><input v-model="createForm.telephone" type="text" autocomplete="off" /></label>
      </div>

      <!-- *** AJOUT (chantier Labo) *** : permet de créer directement un compte Admin
           (le Directeur, par ex.) en une seule opération, sans passer par une édition
           séparée. Visible uniquement pour un compte direction ET un créateur
           is_super_admin -- même garde qu'en édition. -->
      <label v-if="createForm.userType === 'direction' && user.is_super_admin" class="checkbox-row">
        <input type="checkbox" v-model="createForm.isAdmin" /> Administrateur
      </label>

      <p v-if="createError" class="error-banner">{{ createError }}</p>
      <div class="form-actions">
        <button class="btn secondary" @click="showCreateForm = false">Annuler</button>
        <button class="btn primary" :disabled="createSubmitting" @click="creerUtilisateur">
          {{ createSubmitting ? 'Création…' : 'Créer le compte' }}
        </button>
      </div>
    </div>

    <div v-if="isLoading" class="loading">Chargement…</div>

    <div v-else class="table-scroll">
    <table class="admin-table">
      <thead>
        <tr>
          <th>Nom</th><th>Identifiant</th><th>Type</th><th>Catégorie</th>
          <th>Département</th><th>Statut</th><th>Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="u in utilisateursFiltres" :key="u.id" :class="{ inactive: !u.is_active }">
          <td>{{ u.nom }} <span v-if="u.is_admin" class="badge badge-admin">Admin</span></td>
          <td>{{ u.username || u.matricule || '—' }}</td>
          <td>{{ TYPE_LABELS[u.user_type] || u.user_type }}</td>
          <td>{{ u.categorie_personnel || '—' }}</td>
          <td>{{ departementNom(u.departement_id) }}</td>
          <td><span :class="['badge', u.is_active ? 'badge-vert' : 'badge-gris']">{{ u.is_active ? 'Actif' : 'Désactivé' }}</span></td>
          <td>
            <div class="actions-cell">
              <button class="icon-btn" title="Modifier" @click="ouvrirEdition(u)"><Pencil :size="15" /></button>
              <button v-if="u.user_type === 'direction'" class="icon-btn" title="Permissions" @click="ouvrirPermissions(u)"><KeyRound :size="15" /></button>
              <button v-else class="icon-btn" title="Lignes affectées" @click="ouvrirAffectations(u)"><UsersIcon :size="15" /></button>
              <button class="icon-btn danger" title="Supprimer" @click="supprimerUtilisateur(u)"><Trash2 :size="15" /></button>
            </div>
          </td>
        </tr>
        <tr v-if="!utilisateursFiltres.length">
          <td colspan="7" class="empty-row">Aucun compte ne correspond à ces filtres.</td>
        </tr>
      </tbody>
    </table>
    </div>

    <!-- Modale édition -->
    <div v-if="utilisateurEnEdition" class="modal-overlay" @click.self="utilisateurEnEdition = null">
      <div class="modal-card">
        <div class="modal-header">
          <h2>Modifier {{ utilisateurEnEdition.nom }}</h2>
          <button class="icon-btn" @click="utilisateurEnEdition = null"><X :size="18" /></button>
        </div>
        <label class="field"><span>Nom</span><input v-model="editForm.nom" type="text" autocomplete="off" /></label>
        <label class="field"><span>Type de compte</span>
          <select v-model="editForm.userType">
            <option value="direction">Direction</option>
            <option value="operateur">Opérateur</option>
            <option value="ouvrier">Ouvrier</option>
          </select>
        </label>
        <label v-if="editForm.userType !== 'direction'" class="field"><span>Catégorie</span>
          <select v-model="editForm.categoriePersonnel">
            <option value="">—</option>
            <option v-for="c in CATEGORIES_PERSONNEL" :key="c" :value="c">{{ c }}</option>
          </select>
        </label>
        <label class="field"><span>Département</span>
          <select v-model.number="editForm.departementId">
            <option :value="null">—</option>
            <option v-for="d in departements" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
        </label>
        <label class="field"><span>Email</span><input v-model="editForm.email" type="email" /></label>
        <label class="field"><span>Téléphone</span><input v-model="editForm.telephone" type="text" /></label>
        <label class="checkbox-row"><input type="checkbox" v-model="editForm.isActive" /> Compte actif</label>
        <!-- *** AJOUT (chantier Labo) *** : masqué pour tout compte qui n'est pas
             is_super_admin -- même garde côté serveur (auth_routes.update_user_status),
             ce v-if évite un 403 inutile plutôt que d'être le seul rempart. -->
        <label v-if="user.is_super_admin" class="checkbox-row"><input type="checkbox" v-model="editForm.isAdmin" /> Administrateur (accès total, ignore les permissions)</label>

        <p v-if="editError" class="error-banner">{{ editError }}</p>
        <div class="modal-actions">
          <button class="btn secondary" @click="utilisateurEnEdition = null">Annuler</button>
          <button class="btn primary" @click="enregistrerEdition">Enregistrer</button>
        </div>
      </div>
    </div>

    <!-- Modale permissions -->
    <div v-if="utilisateurPermissions" class="modal-overlay" @click.self="utilisateurPermissions = null">
      <div class="modal-card">
        <div class="modal-header">
          <h2>Permissions — {{ utilisateurPermissions.nom }}</h2>
          <button class="icon-btn" @click="utilisateurPermissions = null"><X :size="18" /></button>
        </div>
        <p class="hint">Un compte Administrateur a toujours accès à tout, indépendamment de cette liste.</p>
        <label v-for="p in permissionsRegistry" :key="p.key" class="checkbox-row">
          <input type="checkbox" :checked="permissionsCochees.has(p.key)" @change="togglePermission(p.key)" />
          {{ p.label }}
        </label>
        <p v-if="permissionsError" class="error-banner">{{ permissionsError }}</p>
        <div class="modal-actions">
          <button class="btn secondary" @click="utilisateurPermissions = null">Fermer</button>
          <button class="btn primary" @click="enregistrerPermissions">Enregistrer</button>
        </div>
      </div>
    </div>

    <!-- Modale affectations lignes -->
    <div v-if="utilisateurAffectations" class="modal-overlay" @click.self="utilisateurAffectations = null">
      <div class="modal-card">
        <div class="modal-header">
          <h2>Lignes — {{ utilisateurAffectations.nom }}</h2>
          <button class="icon-btn" @click="utilisateurAffectations = null"><X :size="18" /></button>
        </div>

        <p class="section-label">Affectations actuelles</p>
        <p v-if="!affectationsActives.length" class="empty">Aucune ligne affectée actuellement.</p>
        <ul v-else class="affectation-list">
          <li v-for="a in affectationsActives" :key="a.id">
            <span>{{ ligneCode(a.ligne_id) }}</span>
            <button class="btn secondary small" @click="terminerAffectation(a)">Retirer</button>
          </li>
        </ul>

        <div class="ajout-affectation">
          <button type="button" class="ligne-picker-trigger" @click="panneauLigneOuvert = !panneauLigneOuvert">
            <span>{{ ligneChoisie ? `${ligneChoisie.code} — ${ligneChoisie.nom}` : 'Choisir une ligne…' }}</span>
            <ChevronDown :size="16" />
          </button>
          <button class="btn primary small" :disabled="!nouvelleLigneId" @click="ajouterAffectation">Affecter</button>
        </div>

        <div v-if="panneauLigneOuvert" class="ligne-picker-panel">
          <div class="ligne-picker-search">
            <Search :size="14" />
            <input v-model="rechercheLigne" type="search" placeholder="Filtrer par code ou nom…" autofocus />
          </div>
          <div class="ligne-picker-list">
            <template v-for="groupe in lignesDisponibles" :key="groupe.section">
              <div class="ligne-picker-section">{{ groupe.section }}</div>
              <button
                v-for="l in groupe.lignes" :key="l.id" type="button"
                :class="['ligne-picker-row', { selected: nouvelleLigneId === l.id }]"
                @click="choisirLigne(l)"
              >
                <Check v-if="nouvelleLigneId === l.id" :size="14" class="check-icon" />
                <span class="ligne-picker-label">{{ l.code }} — {{ l.nom }}</span>
                <span :class="['badge', l.actif ? 'badge-vert' : 'badge-gris']">{{ l.actif ? 'Active' : 'Inactive' }}</span>
              </button>
            </template>
            <p v-if="!lignesDisponibles.length" class="empty">Aucune ligne ne correspond.</p>
          </div>
        </div>

        <template v-if="affectationsPassees.length">
          <p class="section-label">Historique</p>
          <ul class="affectation-list">
            <li v-for="a in affectationsPassees" :key="a.id" class="passee">
              <span>{{ ligneCode(a.ligne_id) }}</span>
              <span class="date-range">
                {{ new Date(a.date_debut).toLocaleDateString('fr-FR') }} → {{ new Date(a.date_fin).toLocaleDateString('fr-FR') }}
              </span>
            </li>
          </ul>
        </template>

        <p v-if="affectationsError" class="error-banner">{{ affectationsError }}</p>
        <div class="modal-actions">
          <button class="btn secondary" @click="utilisateurAffectations = null">Fermer</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hint { font-size: var(--font-size-sm); color: var(--color-text-muted); max-width: 640px; margin-bottom: var(--space-4); }
.error-banner {
  background: var(--color-rouge-bg); color: var(--color-rouge);
  padding: var(--space-3); border-radius: var(--radius-md); margin-bottom: var(--space-3);
}
.loading { color: var(--color-text-muted); }
.empty { color: var(--color-text-muted); font-size: var(--font-size-sm); }

.toolbar { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-3); flex-wrap: wrap; }
.search-wrap { position: relative; flex: 1; min-width: 220px; }
.search-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--color-text-muted); pointer-events: none; }
.search-input {
  width: 100%; height: 36px; padding: 0 var(--space-3) 0 34px;
  border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: var(--font-size-sm);
}
.filter-select {
  height: 36px; padding: 0 var(--space-2); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); font-size: var(--font-size-sm); background: var(--color-surface);
}
.result-count { font-size: var(--font-size-xs); color: var(--color-text-muted); white-space: nowrap; }

.add-btn, .btn {
  display: inline-flex; align-items: center; gap: var(--space-2);
  border: none; border-radius: var(--radius-md); padding: var(--space-2) var(--space-4);
  font-weight: 700; cursor: pointer; font-size: var(--font-size-sm);
}
.add-btn, .btn.primary { background: var(--color-brand); color: var(--color-text-inverse); }
.btn.secondary { background: var(--color-border); color: var(--color-text); }
.btn.small { padding: var(--space-1) var(--space-3); font-size: var(--font-size-xs); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }

.form-card {
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-lg); padding: var(--space-4); margin-bottom: var(--space-4);
  box-shadow: var(--shadow-card);
}
.form-row { display: flex; gap: var(--space-4); margin-bottom: var(--space-3); flex-wrap: wrap; }
.field { flex: 1; min-width: 160px; display: flex; flex-direction: column; gap: 4px; font-size: var(--font-size-sm); }
.field input, .field select {
  height: 40px; padding: 0 var(--space-3); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); font-family: inherit; background: var(--color-surface);
}
.form-actions { display: flex; justify-content: flex-end; gap: var(--space-2); }

.table-scroll {
  overflow-x: auto;
  border-radius: var(--radius-lg);
}
.admin-table {
  width: 100%; min-width: 720px; border-collapse: collapse; background: var(--color-surface);
  border: 1px solid var(--color-border); border-radius: var(--radius-lg); overflow: hidden;
}
.admin-table th {
  text-align: left; background: var(--color-brand-light); color: var(--color-brand-dark);
  font-size: var(--font-size-xs); padding: var(--space-3);
}
.admin-table td { padding: var(--space-3); border-top: 1px solid var(--color-border); font-size: var(--font-size-sm); }
.admin-table tr.inactive td { color: var(--color-text-muted); }
.empty-row { text-align: center; color: var(--color-text-muted); padding: var(--space-6) !important; }

.badge { padding: 3px 10px; border-radius: 999px; font-size: var(--font-size-xs); font-weight: 700; margin-left: var(--space-2); }
.badge-admin { background: var(--color-brand-light); color: var(--color-brand-dark); }
.badge-vert { background: var(--color-vert-bg); color: var(--color-vert); }
.badge-gris { background: var(--color-border); color: var(--color-text-muted); }

.actions-cell { display: flex; gap: var(--space-2); }
.icon-btn {
  border: 1px solid var(--color-border); background: var(--color-surface); color: var(--color-text-muted);
  border-radius: var(--radius-md); width: 30px; height: 30px; display: inline-flex; align-items: center;
  justify-content: center; cursor: pointer;
}
.icon-btn:hover { background: var(--color-brand-light); color: var(--color-brand-dark); }
.icon-btn.danger:hover { background: var(--color-rouge-bg); color: var(--color-rouge); }

.modal-overlay {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.5);
  display: flex; align-items: center; justify-content: center; z-index: 50;
  padding: var(--space-4);
  box-sizing: border-box;
}
.modal-card {
  box-sizing: border-box;
  background: var(--color-surface); border-radius: var(--radius-lg); padding: var(--space-6);
  width: min(420px, 100%); max-height: 85vh; overflow-y: auto; overflow-x: hidden;
  box-shadow: 0 10px 30px rgba(0,0,0,0.2);
}
.modal-header, .ajout-affectation { min-width: 0; }
@media (max-width: 420px) {
  .modal-card { padding: var(--space-4); }
}
.modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-4); }
.modal-header h2 { margin: 0; font-size: var(--font-size-base); min-width: 0; overflow-wrap: anywhere; }
.modal-actions { display: flex; justify-content: flex-end; gap: var(--space-2); margin-top: var(--space-4); }

.checkbox-row {
  display: flex; align-items: center; gap: var(--space-2); font-size: var(--font-size-sm);
  margin-bottom: var(--space-3); cursor: pointer;
}

.section-label { font-size: var(--font-size-xs); font-weight: 700; color: var(--color-text-muted); text-transform: uppercase; margin: var(--space-3) 0 var(--space-2); }

.affectation-list { list-style: none; margin: 0 0 var(--space-3); padding: 0; display: flex; flex-direction: column; gap: var(--space-2); }
.affectation-list li {
  display: flex; align-items: center; justify-content: space-between;
  padding: var(--space-2) var(--space-3); background: var(--color-bg); border-radius: var(--radius-md); font-size: var(--font-size-sm);
}
.affectation-list li.passee { color: var(--color-text-muted); }
.date-range { font-size: var(--font-size-xs); }

.ajout-affectation { display: flex; gap: var(--space-2); margin-bottom: var(--space-2); position: relative; }
.ligne-picker-trigger {
  /* *** CORRIGÉ 2026-09-23 (débordement réel observé, écran étroit) *** : un item flex
     a par défaut min-width:auto -- sans min-width:0, ce bouton refusait de rétrécir
     sous la largeur du nom de ligne le plus long qu'il affichait, poussant toute la
     ligne .ajout-affectation, puis .modal-card, puis la PAGE entière en débordement
     horizontal. L'ellipse du <span> enfant ne peut jouer son rôle que si CE conteneur
     accepte de rétrécir en premier. */
  flex: 1; min-width: 0; height: 36px; padding: 0 var(--space-3); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); font-size: var(--font-size-sm); background: var(--color-surface);
  color: var(--color-text); display: flex; align-items: center; justify-content: space-between;
  cursor: pointer; text-align: left; gap: var(--space-2);
}
.ligne-picker-trigger span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.ligne-picker-panel {
  background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md);
  margin-bottom: var(--space-3); box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  /* Contenue DANS la modale (qui a déjà max-height:85vh + overflow-y:auto) -- jamais un
     élément natif hors de contrôle CSS comme le <select multi-optgroup> d'avant, qui
     débordait de la modale sans qu'aucune règle ici ne puisse le contraindre. */
  max-height: 260px; display: flex; flex-direction: column; overflow: hidden;
}
.ligne-picker-search {
  display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border); color: var(--color-text-muted); flex-shrink: 0;
}
.ligne-picker-search input {
  flex: 1; border: none; outline: none; font-size: var(--font-size-sm); font-family: inherit;
  background: transparent; color: var(--color-text);
}
.ligne-picker-list { overflow-y: auto; padding: var(--space-2) 0; }
.ligne-picker-section {
  font-size: var(--font-size-xs); font-weight: 700; color: var(--color-text-muted);
  text-transform: uppercase; padding: var(--space-2) var(--space-3) 4px;
}
.ligne-picker-row {
  width: 100%; display: flex; align-items: center; gap: var(--space-2);
  padding: var(--space-2) var(--space-3); border: none; background: none; cursor: pointer;
  font-family: inherit; font-size: var(--font-size-sm); text-align: left;
}
.ligne-picker-row:hover { background: var(--color-brand-light); }
.ligne-picker-row.selected { background: var(--color-brand-light); }
.ligne-picker-row .check-icon { color: var(--color-brand); flex-shrink: 0; }
.ligne-picker-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* *** AJOUT 2026-09-23 *** : boutons de type de compte en tête du formulaire de création. */
.type-picker {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.type-option {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: var(--space-3);
  border: 2px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text-muted);
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  transition: border-color 0.15s ease, background-color 0.15s ease, color 0.15s ease;
}
.type-option:hover { border-color: var(--color-brand); }
.type-option.selected {
  border-color: var(--color-brand);
  background: var(--color-brand-light);
  color: var(--color-brand-dark);
}
.type-option-label { font-weight: 700; font-size: var(--font-size-sm); color: var(--color-text); margin-top: 2px; }
.type-option.selected .type-option-label { color: var(--color-brand-dark); }
.type-option-desc { font-size: var(--font-size-xs); line-height: 1.3; }
@media (max-width: 560px) {
  .type-picker { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .type-option { transition: none; }
}
</style>