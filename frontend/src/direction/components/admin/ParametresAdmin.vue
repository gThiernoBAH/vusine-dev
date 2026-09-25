<script setup>
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'

// Clés connues -- pas de route "lister tous les params" côté backend, donc on les
// interroge une par une via GET /auth/params/{key} (déjà existant, réservé admin).
const DEFINITIONS = [
  { key: 'seuil_vert_pct', label: 'Seuil vert', suffix: '%', hint: 'Performance à partir de laquelle une ligne est considérée verte.' },
  { key: 'seuil_orange_pct', label: 'Seuil orange', suffix: '%', hint: 'En dessous, la ligne passe rouge (Retard critique).' },
  { key: 'seuil_silence_scan_minutes', label: 'Silence de scan', suffix: 'min', hint: "Alerte déclenchée si aucune palette scannée depuis ce délai." },
  { key: 'duree_demarrage_min', label: 'Fenêtre de démarrage', suffix: 'min', hint: "Délai après le début de poste/OF pendant lequel une ligne n'est jamais jugée rouge/orange (pourcentage pas encore significatif)." },
  // *** AJOUT 2026-09-24 (Palier 0, coût des pertes) *** : valorisation des arrêts en FCFA.
  { key: 'valeur_piece_defaut_fcfa', label: "Valeur par défaut d'une pièce", suffix: 'FCFA', min: 0, step: 'any',
    hint: "Utilisée quand un produit n'a pas de valeur propre (Administration → Valeur des produits). 0 = non configurée : les coûts s'affichent « n/d »." },
  { key: 'libelle_valeur_piece', label: 'Ce que représente cette valeur', suffix: '', type: 'text',
    hint: "Libellé repris dans les écrans et exports (ex. « Prix de vente unitaire », « Coût de revient unitaire », « Marge unitaire »)." },
  // *** AJOUT 2026-09-24 (Palier 1) *** : prévision de fin de poste, TRS, SMED, rapport matinal.
  // Une valeur vide = la valeur par défaut indiquée dans l'aide s'applique.
  { key: 'prevision_delai_min', label: 'Délai avant prévision de fin de poste', suffix: 'min', min: 5, step: 'any',
    hint: "Temps de marche minimal avant d'afficher la prévision de fin de poste (projection linéaire de la cadence). Plus court = prévision plus instable. Défaut : 60." },
  { key: 'trs_cible_pct', label: 'Cible de TRS', suffix: '%', min: 0, step: 'any',
    hint: "Repère de Rapports → TRS : vert si atteint, orange jusqu'à 15 points en dessous, rouge sinon. Défaut : 85." },
  { key: 'smed_objectif_min', label: 'Objectif de changement de série', suffix: 'min', min: 0, step: 'any',
    hint: "Les changements dont l'écart entre scans dépasse cette durée sont signalés en rouge. 0 = pas d'objectif. Défaut : 0." },
  { key: 'cause_changement_produit', label: 'Cause « changement de série »', suffix: '', type: 'text',
    hint: "Libellé exact de la cause d'arrêt (Administration → Causes d'arrêt) qui désigne un changement de série. Défaut : « Changement produit »." },
  { key: 'rapport_matinal_heure', label: 'Heure du rapport matinal', suffix: '', type: 'text',
    hint: "Format HH:MM. L'envoi automatique doit aussi être activé côté serveur (RAPPORT_MATINAL_ENABLED). Défaut : 07:00." },
  { key: 'scoring_equipe_effectif_min', label: "Effectif minimal d'une équipe affichée", suffix: 'pers.', min: 0, step: 1,
    hint: "Sous cet effectif, le score de la ligne est masqué (une équipe de 1 ou 2 personnes désignerait quelqu'un). 0 = aucun masquage (état actuel). 3 est conseillé une fois les affectations saisies." },
  { key: 'donnees_min_palettes', label: 'Palettes minimales pour des scores représentatifs', suffix: 'palettes', min: 0, step: 1,
    hint: "Sous ce nombre de palettes sur la période, TRS et scores d'équipe sont grisés avec un avertissement (adoption des scans insuffisante). Défaut : 10." },
  { key: 'rapport_matinal_jours', label: 'Jours du rapport matinal', suffix: '', type: 'text',
    hint: "Numéros des jours d'envoi séparés par des virgules : 1 = lundi … 7 = dimanche. Défaut : 1,2,3,4,5,6." },
]

const params = ref(DEFINITIONS.map(d => ({ ...d, valeur: '', valeurOriginale: '', enregistrement: false })))
const isLoading = ref(true)
const errorMessage = ref('')
const successMessage = ref('')

async function charger() {
  isLoading.value = true
  try {
    const resultats = await Promise.all(
      params.value.map(p => apiClient.get(`/auth/params/${p.key}`))
    )
    resultats.forEach((res, i) => {
      params.value[i].valeur = res.data.value ?? ''
      params.value[i].valeurOriginale = res.data.value ?? ''
    })
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger les paramètres.'
  } finally {
    isLoading.value = false
  }
}
onMounted(charger)

async function enregistrer(p) {
  p.enregistrement = true
  successMessage.value = ''
  try {
    // CORRIGÉ 2026-09-24 : un champ type="number" donne un NOMBRE à v-model (Vue le convertit), or
    // PATCH /auth/params attend une chaîne (schemas.ParamUpdate.value: str) -> 422 à chaque
    // enregistrement d'un paramètre numérique. Défaut présent dans la version d'origine.
    await apiClient.patch('/auth/params', { key: p.key, value: String(p.valeur ?? '') })
    p.valeurOriginale = p.valeur
    successMessage.value = `${p.label} mis à jour.`
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || `Échec de la mise à jour de ${p.label}.`
  } finally {
    p.enregistrement = false
  }
}
</script>

<template>
  <div class="parametres-admin">
    <p class="hint">
      Seuils utilisés par le calcul de performance et le moteur d'alertes, et valeur d'une
      pièce pour estimer le coût des arrêts. Réservé aux comptes administrateur.
    </p>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <p v-if="successMessage" class="success-banner">{{ successMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>

    <div v-else class="params-list">
      <div v-for="p in params" :key="p.key" class="param-row">
        <div class="param-info">
          <div class="param-label">{{ p.label }}</div>
          <div class="param-hint">{{ p.hint }}</div>
        </div>
        <div class="param-input-wrap">
          <input v-model="p.valeur" :type="p.type || 'number'" :min="p.min" :step="p.step"
                 :class="['param-input', { 'param-input-texte': p.type === 'text' }]" />
          <span class="param-suffix">{{ p.suffix }}</span>
        </div>
        <button
          class="btn primary"
          :disabled="p.enregistrement || p.valeur === p.valeurOriginale"
          @click="enregistrer(p)"
        >
          {{ p.enregistrement ? 'Enregistrement…' : 'Enregistrer' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.parametres-admin { display: flex; flex-direction: column; gap: var(--space-4); }
.hint { font-size: var(--font-size-sm); color: var(--color-text-muted); max-width: 900px; margin: 0; }
.error-banner { background: var(--color-rouge-bg); color: var(--color-rouge); padding: var(--space-3); border-radius: var(--radius-md); }
.success-banner { background: var(--color-vert-bg); color: var(--color-vert); padding: var(--space-3); border-radius: var(--radius-md); }
.loading { color: var(--color-text-muted); }

.params-list {
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-lg); overflow: hidden;
}
.param-row {
  display: flex; align-items: center; gap: var(--space-4);
  padding: var(--space-4); border-bottom: 1px solid var(--color-border);
}
.param-row:last-child { border-bottom: none; }

.param-info { flex: 1; min-width: 0; }
.param-label { font-weight: 700; font-size: var(--font-size-sm); }
.param-hint { font-size: var(--font-size-xs); color: var(--color-text-muted); margin-top: 2px; }

.param-input-wrap { display: flex; align-items: center; gap: var(--space-2); }
.param-input {
  width: 80px; height: 36px; padding: 0 var(--space-2); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); font-size: var(--font-size-sm); text-align: right;
}
.param-input-texte { width: 220px; text-align: left; }
.param-suffix { font-size: var(--font-size-xs); color: var(--color-text-muted); min-width: 24px; }

.btn {
  height: 36px; border: none; border-radius: var(--radius-md); padding: 0 var(--space-4);
  font-weight: 700; cursor: pointer; background: var(--color-brand); color: var(--color-text-inverse);
  white-space: nowrap;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>