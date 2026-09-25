<script setup>
/**
 * MesPerformancesView.vue -- « Voir mes performances » (tablette). *** AJOUT 2026-09-24 ***
 *
 * Montre à la personne SES heures par ligne et le résultat de L'ÉQUIPE pendant ces heures.
 * Ce n'est volontairement PAS une note personnelle : aucun autre nom, aucune comparaison, aucun
 * rang (cadre « scoring légalement cadré »). GET /scoring/mon-activite ne prend aucun user_id :
 * le compte connecté ne peut voir que ses propres données.
 */
import { ref, computed, onMounted } from 'vue'
import apiClient from '@/api/client'
import { ArrowLeft } from 'lucide-vue-next'

const emit = defineEmits(['back'])

const iso = d => d.toISOString().slice(0, 10)
const PERIODES = [
  { cle: '7', label: '7 jours', jours: 7 },
  { cle: '30', label: '30 jours', jours: 30 },
  { cle: '90', label: '3 mois', jours: 90 },
]
const periode = ref('30')
const donnees = ref(null)
const isLoading = ref(true)
const errorMessage = ref('')

async function charger() {
  isLoading.value = true
  try {
    const jours = PERIODES.find(p => p.cle === periode.value).jours
    const fin = new Date(Date.now() - 86400000)                 // jusqu'à hier : les jours terminés
    const debut = new Date(fin.getTime() - (jours - 1) * 86400000)
    donnees.value = (await apiClient.get('/scoring/mon-activite', { params: { date_debut: iso(debut), date_fin: iso(fin) } })).data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger vos performances.'
  } finally {
    isLoading.value = false
  }
}
onMounted(charger)

const fmtPct = v => (v === null || v === undefined ? '—' : `${Number(v).toLocaleString('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`)
const fmtH = v => `${Number(v).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} h`
const aucuneAffectation = computed(() => donnees.value && !donnees.value.lignes.length)

// *** AJOUT 2026-09-25 *** : filtre section/ligne, calculé côté client sur ce qui est déjà chargé.
const sectionChoisie = ref('')
const sectionsDisponibles = computed(() => [...new Set((donnees.value?.lignes ?? []).map(l => l.section_nom).filter(Boolean))].sort())
const lignesFiltrees = computed(() => {
  const toutes = donnees.value?.lignes ?? []
  return sectionChoisie.value ? toutes.filter(l => l.section_nom === sectionChoisie.value) : toutes
})
</script>

<template>
  <div class="mes-performances">
    <div class="header-row">
      <button class="back-btn" title="Retour" @click="emit('back')"><ArrowLeft :size="20" /></button>
      <h1>Mes performances</h1>
    </div>

    <div class="periodes" role="group" aria-label="Période">
      <button v-for="p in PERIODES" :key="p.cle" :class="['periode', { actif: periode === p.cle }]" @click="periode = p.cle; charger()">{{ p.label }}</button>
    </div>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>

    <template v-else-if="donnees">
      <p v-if="aucuneAffectation" class="vide">
        Aucune présence enregistrée sur cette période. Vos heures se calculent d'après vos affectations aux lignes :
        demandez à votre chef d'équipe de vous affecter à votre ligne.
      </p>

      <template v-else>
        <div class="resume">
          <div class="tuile"><span class="tuile-label">Heures de présence</span><strong>{{ fmtH(donnees.heures_totales) }}</strong></div>
          <div class="tuile"><span class="tuile-label">Résultat de l'équipe</span><strong>{{ fmtPct(donnees.resultat_equipe_pct) }}</strong></div>
        </div>

        <div class="ligne-titre">
          <h2>Par ligne</h2>
          <select v-if="sectionsDisponibles.length > 1" v-model="sectionChoisie" class="filtre-section">
            <option value="">Toutes les sections</option>
            <option v-for="s in sectionsDisponibles" :key="s" :value="s">{{ s }}</option>
          </select>
        </div>
        <article v-for="l in lignesFiltrees" :key="l.ligne_code" class="carte-ligne">
          <header><strong>{{ l.ligne_code }}</strong><span class="nom">{{ l.ligne_nom }}</span><span v-if="l.section_nom" class="section">{{ l.section_nom }}</span></header>
          <dl>
            <dt>Jours</dt><dd>{{ l.jours_presence }}</dd>
            <dt>Heures</dt><dd>{{ fmtH(l.heures) }}</dd>
            <dt>Résultat de l'équipe</dt><dd>{{ l.equipe_masquee ? 'masqué' : fmtPct(l.resultat_equipe_pct) }}</dd>
          </dl>
        </article>
        <p v-if="!lignesFiltrees.length" class="vide">Aucune ligne pour cette section sur la période.</p>
      </template>

      <p class="avertissement">{{ donnees.avertissement }}</p>
    </template>
  </div>
</template>

<style scoped>
.mes-performances { padding: var(--space-4); height: 100%; overflow-y: auto; }
.header-row { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.header-row h1 { margin: 0; font-size: var(--font-size-xl); }
.back-btn { display: inline-flex; align-items: center; justify-content: center; width: var(--touch-target-min, 44px); height: var(--touch-target-min, 44px); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); cursor: pointer; }
.periodes { display: flex; gap: var(--space-2); margin-bottom: var(--space-4); }
.periode { flex: 1; height: var(--touch-target-min, 44px); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); font-weight: 600; cursor: pointer; font-family: inherit; }
.periode.actif { background: var(--color-brand); color: var(--color-text-inverse); border-color: var(--color-brand); }
.resume { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); margin-bottom: var(--space-4); }
.tuile { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: var(--space-3) var(--space-4); display: flex; flex-direction: column; gap: 2px; }
.tuile strong { font-size: var(--font-size-2xl); }
.tuile-label { font-size: var(--font-size-xs); text-transform: uppercase; color: var(--color-text-muted); }
h2 { font-size: var(--font-size-md); margin: 0 0 var(--space-2); }
.ligne-titre { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); margin-bottom: var(--space-2); }
.ligne-titre h2 { margin: 0; }
.filtre-section { height: 34px; padding: 0 var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-family: inherit; font-size: var(--font-size-sm); }
.carte-ligne { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: var(--space-3) var(--space-4); margin-bottom: var(--space-3); }
.carte-ligne header { display: flex; gap: var(--space-2); align-items: baseline; margin-bottom: var(--space-2); }
.nom { color: var(--color-text-muted); font-size: var(--font-size-sm); }
.section { margin-left: auto; font-size: var(--font-size-xs); color: var(--color-text-muted); text-transform: uppercase; letter-spacing: .03em; }
.carte-ligne dl { display: grid; grid-template-columns: 1fr auto; gap: 4px var(--space-3); margin: 0; font-size: var(--font-size-sm); }
.carte-ligne dt { color: var(--color-text-muted); } .carte-ligne dd { margin: 0; font-weight: 700; }
.vide, .loading { color: var(--color-text-muted); }
.avertissement { margin-top: var(--space-4); font-size: var(--font-size-xs); color: var(--color-text-muted); }
.error-banner { background: var(--color-rouge-bg); color: var(--color-rouge); padding: var(--space-3); border-radius: var(--radius-md); }
</style>