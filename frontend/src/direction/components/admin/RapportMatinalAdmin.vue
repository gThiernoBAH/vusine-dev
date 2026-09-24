<script setup>
/**
 * RapportMatinalAdmin.vue -- aperçu et envoi de test du rapport matinal.
 * *** AJOUT 2026-09-24 (Palier 1) ***
 * L'envoi automatique ne se règle pas ici : il est activé côté serveur
 * (RAPPORT_MATINAL_ENABLED) ; l'heure et les jours dans Paramètres ; les destinataires
 * dans Personnel (case « Rapport matinal » de chaque compte).
 */
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import { useConfirm } from '@/composables/useConfirm'

const { confirm } = useConfirm()
const apercu = ref(null)
const isLoading = ref(true)
const errorMessage = ref('')
const envoi = ref(null)          // résultat du dernier envoi
const envoiEnCours = ref(false)

async function charger() {
  isLoading.value = true
  try {
    apercu.value = (await apiClient.get('/rapports/matinal/apercu')).data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || "Impossible de charger l'aperçu."
  } finally {
    isLoading.value = false
  }
}
onMounted(charger)

async function envoyer(mode) {
  if (mode === 'tous') {
    const ok = await confirm({
      title: 'Envoyer le rapport à tous ?',
      message: `Le rapport partira maintenant vers ${apercu.value.nb_destinataires_email} adresse(s) email et ${apercu.value.nb_destinataires_telegram} chat(s) Telegram, et ne sera pas renvoyé automatiquement aujourd'hui.`,
      confirmLabel: 'Envoyer',
    })
    if (!ok) return
  }
  envoiEnCours.value = true
  envoi.value = null
  try {
    envoi.value = (await apiClient.post('/rapports/matinal/envoyer', null, { params: { mode } })).data
  } catch (e) {
    envoi.value = { envoye: false, raison: e.response?.data?.detail || "Échec de l'envoi.", email_echecs: [], telegram_echecs: [] }
  } finally {
    envoiEnCours.value = false
  }
}
</script>

<template>
  <div class="rapport-matinal-admin">
    <p class="hint">
      Synthèse envoyée chaque matin : performance du dernier jour de production, TRS, principales causes d'arrêt et arrêts en cours.
      Les destinataires se choisissent dans <strong>Personnel</strong> (modifier un compte), l'heure et les jours dans <strong>Paramètres</strong>.
    </p>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>

    <template v-else-if="apercu">
      <div class="statut-ligne">
        <span :class="['pastille', apercu.envoi_automatique_actif ? 'on' : 'off']"></span>
        <span v-if="apercu.envoi_automatique_actif">Envoi automatique <strong>actif</strong>.</span>
        <span v-else>Envoi automatique <strong>inactif</strong> : il s'active côté serveur (RAPPORT_MATINAL_ENABLED). Les boutons ci-dessous fonctionnent quand même.</span>
      </div>
      <p class="destinataires">
        Destinataires : <strong>{{ apercu.nb_destinataires_email }}</strong> par email, <strong>{{ apercu.nb_destinataires_telegram }}</strong> par Telegram.
      </p>

      <p v-if="!apercu.disponible" class="warn-banner">{{ apercu.message }}</p>

      <template v-else>
        <div class="actions">
          <button class="btn secondary" :disabled="envoiEnCours" @click="envoyer('test')">M'envoyer un test</button>
          <button class="btn primary" :disabled="envoiEnCours || (!apercu.nb_destinataires_email && !apercu.nb_destinataires_telegram)" @click="envoyer('tous')">Envoyer maintenant à tous</button>
        </div>

        <div v-if="envoi" :class="[envoi.envoye ? 'success-banner' : 'error-banner']">
          <strong>{{ envoi.envoye ? 'Envoyé.' : 'Non envoyé.' }}</strong> {{ envoi.raison }}
          <span v-if="envoi.envoye"> — {{ envoi.email_ok }} email(s), {{ envoi.telegram_ok }} Telegram.</span>
          <ul v-if="envoi.email_echecs?.length || envoi.telegram_echecs?.length" class="echecs">
            <li v-for="e in [...(envoi.email_echecs || []), ...(envoi.telegram_echecs || [])]" :key="e.destinataire">{{ e.destinataire }} : {{ e.erreur }}</li>
          </ul>
        </div>

        <h3 class="sous-titre">{{ apercu.sujet }}</h3>
        <!-- sandbox="" : le HTML du rapport est affiché sans script ni accès à la page. -->
        <iframe class="apercu-html" sandbox="" :srcdoc="apercu.html" title="Aperçu du rapport matinal"></iframe>
      </template>
    </template>
  </div>
</template>

<style scoped>
.hint { color: var(--color-text-muted); font-size: var(--font-size-sm); margin: 0 0 var(--space-4); }
.statut-ligne { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-2); }
.pastille { width: 10px; height: 10px; border-radius: 50%; background: var(--color-border); flex-shrink: 0; }
.pastille.on { background: var(--color-vert); } .pastille.off { background: var(--color-orange); }
.destinataires { margin: 0 0 var(--space-4); }
.actions { display: flex; gap: var(--space-3); margin-bottom: var(--space-4); }
.echecs { margin: var(--space-2) 0 0; padding-left: 18px; font-size: var(--font-size-sm); }
.sous-titre { font-size: var(--font-size-md); margin: var(--space-4) 0 var(--space-2); }
.apercu-html { width: 100%; height: 640px; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: #fff; }
</style>
