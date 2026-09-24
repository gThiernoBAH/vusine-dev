/**
 * useConfirm.js -- remplace window.confirm() par une fenêtre de confirmation dans le
 * style de Vusine (cf. ConfirmDialog.vue, monté une seule fois dans App.vue).
 *
 * État module-level (hors de toute instance de composant) : n'importe quel composant
 * peut appeler confirm(), une seule fenêtre existe à la fois dans toute l'application.
 *
 * Usage :
 *   const { confirm } = useConfirm()
 *   if (!(await confirm({ title: 'Supprimer le compte', message: `Supprimer ${nom} ?`,
 *                         danger: true, confirmLabel: 'Supprimer' }))) return
 */
import { reactive } from 'vue'

const state = reactive({
  visible: false,
  title: '',
  message: '',
  danger: false,
  confirmLabel: 'Confirmer',
  cancelLabel: 'Annuler',
  resolve: null,
})

export function useConfirm() {
  function confirm({ title = 'Confirmer', message = '', danger = false, confirmLabel = 'Confirmer', cancelLabel = 'Annuler' } = {}) {
    return new Promise((resolve) => {
      // Une confirmation déjà ouverte et jamais tranchée (cas improbable) est annulée
      // plutôt que laissée en suspens indéfiniment.
      if (state.resolve) state.resolve(false)
      Object.assign(state, { visible: true, title, message, danger, confirmLabel, cancelLabel, resolve })
    })
  }
  return { state, confirm }
}

// Utilisé uniquement par ConfirmDialog.vue -- jamais appelé directement par un écran.
export function _repondreConfirm(valeur) {
  state.visible = false
  const r = state.resolve
  state.resolve = null
  if (r) r(valeur)
}

export function _confirmState() {
  return state
}
