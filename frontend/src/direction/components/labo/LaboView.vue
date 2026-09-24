<script setup>
import { useRoute } from 'vue-router'

const route = useRoute()

// *** MODIFIÉ 2026-09-23 *** : codes F1…F10 retirés des libellés (l'ordre suit le fil
// du travail, pas la numérotation) ; code + description passés dans l'infobulle.
const ONGLETS = [
  { to: '/cockpit/labo/capacite', label: 'Capacité',
    hint: 'F1 · Capacité démontrée : ce que chaque ligne a réellement produit par jour, pour chaque produit (médiane, P90).' },
  { to: '/cockpit/labo/planning-risque', label: 'Planning réaliste',
    hint: 'F2 · Planning réaliste : le planning des prochains jours dépasse-t-il la capacité démontrée ?' },
  { to: '/cockpit/labo/fiabilite-saisie', label: 'Fiabilité saisie',
    hint: 'F3 · Fiabilité de la saisie : délai entre la production et sa saisie dans Odoo, corrections par ligne.' },
  { to: '/cockpit/labo/prevision-volume', label: 'Prévision',
    hint: 'F7 · Prévision de volume : production attendue par produit sur les 14 prochains jours.' },
  { to: '/cockpit/labo/plan-optimise', label: 'Plan optimisé',
    hint: 'F8 · Plan optimisé : répartition recommandée des produits sur les lignes, jour par jour.' },
  { to: '/cockpit/labo/matieres', label: 'Matières',
    hint: "F9 · Matières : ruptures projetées et alertes d'achat, avec délai fournisseur." },
  { to: '/cockpit/labo/alertes-emballage', label: 'Alertes emballage',
    hint: 'F6 · Alertes emballage : alertes d\'achat priorisées par l\'historique des arrêts « manque » de chaque ligne.' },
  { to: '/cockpit/labo/simulation-productible', label: 'Stock → produits',
    hint: "F10 · Stock → produits : quantité fabricable avec le stock matières actuel, et écarts d'inventaire constatés." },
  { to: '/cockpit/labo/ecritures-odoo', label: 'Écritures Odoo',
    hint: 'F5 · Écritures Odoo : ce que Vusine écrirait dans Odoo, comparé à la saisie réelle (aucune écriture).' },
]
</script>

<template>
  <!-- *** CORRIGÉ 2026-09-23 *** : .labo porte son propre défilement vertical -- la zone
       principale du cockpit (.main-area) est en overflow: hidden, la page restait
       coupée au bas de l'écran. -->
  <div class="labo">
    <h1>Labo</h1>
    <p class="sous-titre">Chantiers issus de SIVOX -- calculs déterministes, visible uniquement par l'administrateur.</p>

    <nav class="onglets">
      <router-link
        v-for="o in ONGLETS" :key="o.to" :to="o.to" :title="o.hint"
        :class="['onglet', { actif: route.path === o.to || route.path.startsWith(o.to + '/') }]"
      >
        {{ o.label }}
      </router-link>
    </nav>

    <div class="contenu">
      <router-view />
    </div>
  </div>
</template>

<style scoped>
.labo { height: 100%; overflow-y: auto; padding: var(--space-6); }
h1 { margin: 0 0 4px; font-size: var(--font-size-xl); }
.sous-titre { color: var(--color-text-muted); margin: 0 0 var(--space-4); }

.onglets {
  display: flex; gap: var(--space-4); border-bottom: 1px solid var(--color-border);
  margin-bottom: var(--space-4); overflow-x: auto;
}
.onglet {
  padding: var(--space-2) 0; font-size: var(--font-size-sm); font-weight: 600;
  color: var(--color-text-muted); text-decoration: none; white-space: nowrap;
  border-bottom: 2px solid transparent; transition: color .15s ease, border-color .15s ease;
}
.onglet:hover { color: var(--color-brand-dark); }
.onglet.actif { color: var(--color-brand-dark); border-bottom-color: var(--color-brand); }
.onglet:focus-visible { outline: 2px solid var(--color-brand); outline-offset: 2px; }

.contenu { min-height: 200px; padding-bottom: var(--space-8); }
</style>

<!-- Styles partagés par tous les écrans Labo (préfixés .labo : aucune fuite ailleurs). -->
<style>
/* Texte d'introduction : 2 lignes au maximum sur un écran de bureau. */
.labo .hint {
  font-size: var(--font-size-sm); color: var(--color-text-muted);
  max-width: 980px; margin: 0 0 var(--space-4); line-height: 1.45;
}
.labo .error-banner {
  background: var(--color-rouge-bg); color: var(--color-rouge);
  padding: var(--space-3); border-radius: var(--radius-md); margin-bottom: var(--space-3);
}
.labo .reglage { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--font-size-sm); }
.labo .reglage input {
  height: 30px; padding: 0 var(--space-2); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); font-family: inherit; font-size: var(--font-size-sm);
}
.labo .reglage input[type="number"] { width: 70px; }
.labo .badge { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: var(--font-size-xs); font-weight: 700; white-space: nowrap; }
.labo .badge-rouge { background: var(--color-rouge-bg); color: var(--color-rouge); }
.labo .badge-orange { background: var(--color-orange-bg); color: #92400E; }
.labo .badge-vert { background: var(--color-vert-bg); color: var(--color-vert); }
.labo .badge-gris { background: var(--color-border); color: var(--color-text-muted); }
.labo .text-rouge { color: var(--color-rouge); font-weight: 700; }
.labo .text-vert { color: var(--color-vert); font-weight: 700; }
</style>
