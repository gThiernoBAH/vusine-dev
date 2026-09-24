<script setup>
/**
 * LaboSousOnglets.vue -- sélecteur à deux positions (ou plus) pour les écrans qui
 * portent deux tableaux distincts (Matières, Stock -> produits). Remplace les titres
 * de section : un seul tableau visible à la fois, sa description en infobulle.
 */
defineProps({
  options: { type: Array, required: true },   // [{ value, label, title }]
  modelValue: { type: String, required: true },
})
defineEmits(['update:modelValue'])
</script>

<template>
  <div class="sous-onglets" role="tablist">
    <button
      v-for="o in options" :key="o.value" type="button" role="tab"
      :aria-selected="modelValue === o.value" :title="o.title"
      :class="['sous-onglet', { actif: modelValue === o.value }]"
      @click="$emit('update:modelValue', o.value)"
    >
      {{ o.label }}
    </button>
  </div>
</template>

<style scoped>
.sous-onglets {
  display: inline-flex; padding: 3px; gap: 2px;
  background: var(--color-border); border-radius: var(--radius-md);
}
.sous-onglet {
  border: none; background: transparent; color: var(--color-text-muted);
  padding: 5px var(--space-3); border-radius: 7px; font-family: inherit;
  font-size: var(--font-size-xs); font-weight: 700; cursor: pointer;
  transition: background-color .15s ease, color .15s ease;
}
.sous-onglet:hover:not(.actif) { color: var(--color-brand-dark); }
.sous-onglet.actif { background: var(--color-surface); color: var(--color-brand-dark); box-shadow: 0 1px 2px rgba(15, 23, 42, .08); }
.sous-onglet:focus-visible { outline: 2px solid var(--color-brand); outline-offset: 1px; }
@media (prefers-reduced-motion: reduce) { .sous-onglet { transition: none; } }
</style>
