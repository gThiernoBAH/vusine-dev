<script setup>
defineProps({
  statut: { type: String, required: true }, // 'vert' | 'orange' | 'rouge' | 'arret' | 'inactif' | 'demarrage'
  label: { type: String, default: null },
})

const LABELS = {
  vert: 'En production',
  orange: 'En retard',
  rouge: 'Retard critique',
  arret: 'À l\'arrêt',
  inactif: 'Inactif',
  // *** AJOUT 2026-09-17 *** : fenêtre de calcul ouverte depuis moins de
  // duree_demarrage_min (défaut 10 min) -- pourcentage pas encore significatif,
  // volontairement neutre plutôt que rouge (cf. performance_service.py).
  demarrage: 'Démarrage',
}
</script>

<template>
  <span :class="['badge', `statut-${statut}`]">
    {{ label ?? LABELS[statut] ?? statut }}
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: var(--font-size-xs);
  font-weight: 700;
  white-space: nowrap;
}

/* Les autres statuts (vert/orange/rouge/arret/inactif) sont définis globalement
   ailleurs dans l'app -- seul 'demarrage' est nouveau, défini ici en scoped pour ne
   pas dépendre d'un fichier de styles global jamais vu. Neutre (bleu clair), pas
   alarmant -- distinct du rouge/orange qui signalent un vrai problème. */
.statut-demarrage {
  background: var(--color-brand-light);
  color: var(--color-brand-dark);
}
</style>