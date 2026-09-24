import { createRouter, createWebHistory } from 'vue-router'

import Login from '../components/Login.vue'
import CockpitView from '../direction/CockpitView.vue'
import VueUsineView from '../direction/components/VueUsineView.vue'
import LigneDetailView from '../direction/components/LigneDetailView.vue'
import AlertesView from '../direction/components/AlertesView.vue'
import ScoringView from '../direction/components/ScoringView.vue'
import RapportsView from '../direction/components/RapportsView.vue'
import AdminView from '../direction/components/AdminView.vue'
// *** AJOUT (chantier Labo) *** : chargement différé -- le Labo n'est utile qu'à un
// seul compte (is_super_admin), pas la peine d'alourdir le bundle initial de tous
// les autres profils.
const LaboView = () => import('../direction/components/labo/LaboView.vue')
const CapaciteView = () => import('../direction/components/labo/CapaciteView.vue')
const PlanningRisqueView = () => import('../direction/components/labo/PlanningRisqueView.vue')
const FiabiliteSaisieView = () => import('../direction/components/labo/FiabiliteSaisieView.vue')
const PrevisionVolumeView = () => import('../direction/components/labo/PrevisionVolumeView.vue')
const PlanOptimiseView = () => import('../direction/components/labo/PlanOptimiseView.vue')
const MatieresView = () => import('../direction/components/labo/MatieresView.vue')
const AlertesEmballageView = () => import('../direction/components/labo/AlertesEmballageView.vue')
const SimulationProductibleView = () => import('../direction/components/labo/SimulationProductibleView.vue')
const EcritureOdooView = () => import('../direction/components/labo/EcritureOdooView.vue')
import TabletteView from '../operateur/TabletteView.vue'
import MesLignesView from '../operateur/components/MesLignesView.vue'
import LigneOperateurView from '../operateur/components/LigneOperateurView.vue'
// *** AJOUT 2026-09-23 *** : "Mon historique" côté tablette.
import HistoriqueOperateurView from '../operateur/components/HistoriqueOperateurView.vue'

function getStoredUser() {
  const stored = sessionStorage.getItem('user')
  return stored ? JSON.parse(stored) : null
}

// Même règle que routerVersEspace() dans l'ancien App.vue : "direction" -> cockpit,
// "operateur"/"ouvrier" -> tablette.
function espaceDefaut(user) {
  return user?.user_type === 'direction' ? '/cockpit/vue-usine' : '/operateur'
}

const routes = [
  { path: '/login', name: 'login', component: Login, meta: { public: true } },
  {
    path: '/cockpit',
    component: CockpitView,
    meta: { requiresAuth: true, espace: 'direction' },
    children: [
      { path: '', redirect: '/cockpit/vue-usine' },
      { path: 'vue-usine', name: 'vue-usine', component: VueUsineView },
      {
        path: 'lignes/:id',
        name: 'ligne-detail',
        component: LigneDetailView,
        // Remplace les anciennes props ligne-id / jour-initial passées manuellement par
        // CockpitView -- lues directement depuis l'URL (param + query "jour").
        props: (route) => ({ ligneId: Number(route.params.id), jourInitial: route.query.jour || null }),
      },
      { path: 'alertes', name: 'alertes', component: AlertesView },
      { path: 'scoring', name: 'scoring', component: ScoringView },
      { path: 'rapports', name: 'rapports', component: RapportsView },
      // requiresAdmin vérifié dans le guard ci-dessous -- même règle que canAdmin dans
      // l'ancien CockpitView.vue (is_admin OU permission "view_parametrage").
      { path: 'admin', name: 'admin', component: AdminView, meta: { requiresAdmin: true } },
      // *** AJOUT (chantier Labo) *** : requiresLabo vérifié dans le guard ci-dessous --
      // ne teste JAMAIS is_admin (cf. auth_routes.require_labo côté backend, même
      // principe de séparation stricte).
      {
        path: 'labo',
        component: LaboView,
        meta: { requiresLabo: true },
        children: [
          { path: '', redirect: '/cockpit/labo/capacite' },
          { path: 'capacite', name: 'labo-capacite', component: CapaciteView },
          { path: 'planning-risque', name: 'labo-planning-risque', component: PlanningRisqueView },
          { path: 'fiabilite-saisie', name: 'labo-fiabilite-saisie', component: FiabiliteSaisieView },
          { path: 'prevision-volume', name: 'labo-prevision-volume', component: PrevisionVolumeView },
          { path: 'plan-optimise', name: 'labo-plan-optimise', component: PlanOptimiseView },
          { path: 'matieres', name: 'labo-matieres', component: MatieresView },
          { path: 'alertes-emballage', name: 'labo-alertes-emballage', component: AlertesEmballageView },
          { path: 'simulation-productible', name: 'labo-simulation', component: SimulationProductibleView },
          { path: 'ecritures-odoo', name: 'labo-ecritures-odoo', component: EcritureOdooView },
        ],
      },
    ],
  },
  {
    path: '/operateur',
    component: TabletteView,
    meta: { requiresAuth: true, espace: 'operateur' },
    children: [
      { path: '', name: 'mes-lignes', component: MesLignesView },
      {
        path: 'lignes/:id',
        name: 'ligne-operateur',
        component: LigneOperateurView,
        props: (route) => ({ ligneId: Number(route.params.id) }),
      },
      // *** AJOUT 2026-09-23 *** : accessible depuis le bouton "historique" de
      // MesLignesView.vue -- @back générique de TabletteView ramène à 'mes-lignes'.
      { path: 'historique', name: 'historique-operateur', component: HistoriqueOperateurView },
    ],
  },
  // Toute URL inconnue -> espace de l'utilisateur connecté, ou /login sinon.
  { path: '/:pathMatch(.*)*', redirect: () => (getStoredUser() ? espaceDefaut(getStoredUser()) : '/login') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const user = getStoredUser()

  if (to.meta.public) {
    // Déjà connecté et qui revient sur /login (ex: bouton précédent) -> direct vers son espace.
    if (user && to.name === 'login') return espaceDefaut(user)
    return true
  }

  if (!user) return '/login'

  // Un compte "direction" ne va pas sur /operateur et inversement -- même isolation que
  // routerVersEspace() avant la migration.
  if (to.meta.espace === 'direction' && user.user_type !== 'direction') return '/operateur'
  if (to.meta.espace === 'operateur' && user.user_type === 'direction') return '/cockpit/vue-usine'

  if (to.meta.requiresAdmin) {
    const canAdmin = user.is_admin || (user.permissions || []).includes('view_parametrage')
    if (!canAdmin) return espaceDefaut(user)
  }

  // *** AJOUT (chantier Labo) *** : is_super_admin uniquement -- jamais is_admin, même
  // si le compte est par ailleurs administrateur (cf. auth_routes.require_labo).
  if (to.meta.requiresLabo && !user.is_super_admin) return espaceDefaut(user)

  return true
})

export default router
