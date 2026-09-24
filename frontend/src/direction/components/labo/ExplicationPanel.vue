<script setup>
/**
 * ExplicationPanel.vue -- contenu de l'analyse F4, affiché dans le slot #expanded-row
 * de DataTable, sous la ligne concernée. Récupère l'analyse dès son affichage (donc à
 * chaque dépliage) -- sans coût : POST /labo/expliquer renvoie une analyse déjà
 * générée sans appeler OpenRouter tant que les chiffres n'ont pas changé (mémoire
 * serveur, cf. labo_explication_service.py). "Régénérer" force un nouvel appel.
 *
 * Les badges de chiffres clés viennent de `chiffres_cles`, calculés côté serveur à
 * partir de NOS données (jamais du texte du modèle) -- ce composant ne fait
 * qu'afficher ce qu'on lui donne, aucun chiffre n'est jamais lu dans le texte généré.
 */
import { ref } from 'vue'
import { AlertOctagon, AlertTriangle, Info, RefreshCw, Lightbulb } from 'lucide-vue-next'
import apiClient from '@/api/client'

const props = defineProps({
  domaine: { type: String, required: true },   // 'capacite' | 'fiabilite_saisie' | 'alertes_achat'
  cle: { type: Object, required: true },
})

const ICONES_NIVEAU = { critique: AlertOctagon, attention: AlertTriangle, info: Info }

const chargement = ref(true)
const regenerationEnCours = ref(false)
const erreur = ref('')
const resultat = ref(null)

async function charger(regenerer = false) {
  if (regenerer) regenerationEnCours.value = true
  else chargement.value = true
  erreur.value = ''
  try {
    const res = await apiClient.post('/labo/expliquer', { domaine: props.domaine, cle: props.cle, regenerer })
    resultat.value = res.data
  } catch (e) {
    erreur.value = e.response?.data?.detail || "Échec de l'analyse."
  } finally {
    chargement.value = false
    regenerationEnCours.value = false
  }
}

charger()

function formaterDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div class="explication-panel">
    <div v-if="chargement" class="explication-etat">Analyse en cours…</div>

    <p v-else-if="erreur" class="explication-erreur">{{ erreur }}</p>

    <template v-else-if="resultat">
      <div class="explication-entete">
        <div class="explication-badges">
          <span v-for="c in resultat.chiffres_cles" :key="c.label" class="explication-badge">
            <span class="explication-badge-label">{{ c.label }}</span>
            <span class="explication-badge-valeur">{{ c.valeur }}</span>
          </span>
        </div>
        <div class="explication-meta">
          <span :title="resultat.depuis_cache ? 'Analyse déjà générée, non recalculée -- aucun coût.' : 'Analyse générée à l\'instant.'">
            {{ resultat.depuis_cache ? 'Mémorisée' : 'Nouvelle' }} · {{ formaterDate(resultat.genere_le) }}
          </span>
          <button
            type="button" class="vbtn vbtn-secondary" :disabled="regenerationEnCours"
            title="Ignorer l'analyse mémorisée et en demander une nouvelle au modèle"
            @click="charger(true)"
          >
            <span v-if="regenerationEnCours" class="vbtn-spinner" aria-hidden="true" />
            <RefreshCw v-else :size="13" />
            Régénérer
          </button>
        </div>
      </div>

      <p class="explication-synthese">{{ resultat.synthese }}</p>

      <ul v-if="resultat.points_attention?.length" class="explication-points">
        <li v-for="(p, i) in resultat.points_attention" :key="i" :class="`niveau-${p.niveau}`">
          <component :is="ICONES_NIVEAU[p.niveau] || Info" :size="15" class="explication-point-icone" />
          <span>{{ p.texte }}</span>
        </li>
      </ul>

      <div v-if="resultat.action" class="explication-action">
        <Lightbulb :size="16" class="explication-action-icone" />
        <p>{{ resultat.action.texte }}</p>
        <span v-if="resultat.action.priorite === 'haute'" class="badge badge-rouge">Priorité haute</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.explication-panel {
  padding: var(--space-4) var(--space-6);
  border-left: 3px solid var(--color-brand);
}
.explication-etat { color: var(--color-text-muted); font-size: var(--font-size-sm); }
.explication-erreur { color: var(--color-rouge); font-size: var(--font-size-sm); margin: 0; }

.explication-entete {
  display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3);
  flex-wrap: wrap; margin-bottom: var(--space-3);
}
.explication-badges { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.explication-badge {
  display: inline-flex; align-items: baseline; gap: 6px;
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); padding: 4px 10px; font-size: var(--font-size-xs);
}
.explication-badge-label { color: var(--color-text-muted); }
.explication-badge-valeur { font-weight: 700; color: var(--color-brand-dark); }

.explication-meta {
  display: flex; align-items: center; gap: var(--space-2);
  font-size: var(--font-size-xs); color: var(--color-text-muted); white-space: nowrap;
}

.explication-synthese {
  margin: 0 0 var(--space-3); font-size: var(--font-size-sm); line-height: 1.55; max-width: 900px;
}

.explication-points { list-style: none; margin: 0 0 var(--space-3); padding: 0; display: flex; flex-direction: column; gap: 6px; }
.explication-points li {
  display: flex; align-items: flex-start; gap: var(--space-2);
  font-size: var(--font-size-sm); line-height: 1.4; max-width: 900px;
}
.explication-point-icone { flex-shrink: 0; margin-top: 2px; }
.niveau-critique .explication-point-icone { color: var(--color-rouge); }
.niveau-attention .explication-point-icone { color: var(--color-orange); }
.niveau-info .explication-point-icone { color: var(--color-text-muted); }

.explication-action {
  display: flex; align-items: flex-start; gap: var(--space-2);
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); padding: var(--space-3); max-width: 900px;
}
.explication-action-icone { color: var(--color-brand); flex-shrink: 0; margin-top: 1px; }
.explication-action p { margin: 0; font-size: var(--font-size-sm); flex: 1; line-height: 1.4; }
</style>
