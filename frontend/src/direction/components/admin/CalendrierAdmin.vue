<script setup>
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'

const postes = ref([])
const jours = ref([])
const isLoading = ref(true)
const errorMessage = ref('')

// --- Poste actif (formulaire simple -- un seul poste actif à la fois, cf. backend) ---
const posteForm = ref({ nom: 'Poste unique', heure_debut: '07:30', heure_fin: '17:00', pause_debut: '12:30', pause_fin: '13:30' })
const posteActifExistant = ref(null)  // objet ConfigurationPoste si un poste actif existe déjà, sinon null
const enregistrementPoste = ref(false)

// --- Jours spéciaux ---
const nouveauJour = ref({ date: '', type: 'ferie', heure_debut: '', heure_fin: '', pause_debut: '', pause_fin: '', commentaire: '' })
const ajoutJourEnCours = ref(false)

async function charger() {
  isLoading.value = true
  try {
    const [resPostes, resJours] = await Promise.all([
      apiClient.get('/admin/configuration-poste'),
      apiClient.get('/admin/jours-speciaux'),
    ])
    postes.value = resPostes.data
    jours.value = resJours.data
    const actif = postes.value.find(p => p.actif)
    if (actif) {
      posteActifExistant.value = actif
      posteForm.value = {
        nom: actif.nom, heure_debut: actif.heure_debut?.slice(0, 5) || '',
        heure_fin: actif.heure_fin?.slice(0, 5) || '',
        pause_debut: actif.pause_debut?.slice(0, 5) || '',
        pause_fin: actif.pause_fin?.slice(0, 5) || '',
      }
    }
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger le référentiel Calendrier.'
  } finally {
    isLoading.value = false
  }
}
onMounted(charger)

async function enregistrerPoste() {
  enregistrementPoste.value = true
  try {
    const payload = { ...posteForm.value, actif: true }
    if (posteActifExistant.value) {
      await apiClient.patch(`/admin/configuration-poste/${posteActifExistant.value.id}`, payload)
    } else {
      await apiClient.post('/admin/configuration-poste', payload)
    }
    await charger()
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || "Échec de l'enregistrement du poste."
  } finally {
    enregistrementPoste.value = false
  }
}

async function ajouterJour() {
  if (!nouveauJour.value.date) return
  ajoutJourEnCours.value = true
  try {
    const payload = { ...nouveauJour.value }
    if (payload.type !== 'horaire_special') {
      payload.heure_debut = null
      payload.heure_fin = null
      payload.pause_debut = null
      payload.pause_fin = null
    }
    await apiClient.post('/admin/jours-speciaux', payload)
    nouveauJour.value = { date: '', type: 'ferie', heure_debut: '', heure_fin: '', pause_debut: '', pause_fin: '', commentaire: '' }
    await charger()
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || "Échec de l'ajout du jour spécial."
  } finally {
    ajoutJourEnCours.value = false
  }
}

async function supprimerJour(jour) {
  try {
    await apiClient.delete(`/admin/jours-speciaux/${jour.id}`)
    await charger()
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Échec de la suppression.'
  }
}

const LABELS_TYPE = { ferie: 'Férié', horaire_special: 'Horaire dérogatoire', ferme: 'Fermé' }
</script>

<template>
  <div class="calendrier-admin">
    <p class="hint">
      Référentiel utilisé pour le calcul du théorique (slide 7 du cahier des charges) :
      le théorique ne s'accumule qu'entre l'heure de début et de fin de poste, et se fige
      pendant la pause -- sans ce référentiel renseigné, le calcul retombe sur un mode
      dégradé (borné à minuit uniquement).
    </p>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>

    <template v-else>
      <section class="card">
        <h2>Poste actif</h2>
        <p class="section-hint">Un seul poste actif à la fois. Ces horaires s'appliquent tous les jours, sauf jour spécial défini ci-dessous.</p>
        <div class="poste-form">
          <label>Nom
            <input v-model="posteForm.nom" type="text" placeholder="Poste unique" />
          </label>
          <label>Début
            <input v-model="posteForm.heure_debut" type="time" />
          </label>
          <label>Fin
            <input v-model="posteForm.heure_fin" type="time" />
          </label>
          <label>Pause début
            <input v-model="posteForm.pause_debut" type="time" />
          </label>
          <label>Pause fin
            <input v-model="posteForm.pause_fin" type="time" />
          </label>
          <button class="btn primary" :disabled="enregistrementPoste" @click="enregistrerPoste">
            {{ enregistrementPoste ? 'Enregistrement…' : (posteActifExistant ? 'Mettre à jour' : 'Activer ce poste') }}
          </button>
        </div>
      </section>

      <section class="card">
        <h2>Jours spéciaux</h2>
        <p class="section-hint">Fériés, horaires dérogatoires ou fermetures -- surchargent le poste actif pour une date précise.</p>

        <table v-if="jours.length" class="jours-table">
          <thead>
            <tr><th>Date</th><th>Type</th><th>Horaire</th><th>Commentaire</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="j in jours" :key="j.id">
              <td>{{ j.date }}</td>
              <td>{{ LABELS_TYPE[j.type] || j.type }}</td>
              <td>
                <span v-if="j.type === 'horaire_special'">{{ j.heure_debut?.slice(0,5) }} – {{ j.heure_fin?.slice(0,5) }}</span>
                <span v-else class="muted">—</span>
              </td>
              <td>{{ j.commentaire || '—' }}</td>
              <td><button class="link-danger" @click="supprimerJour(j)">Supprimer</button></td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty">Aucun jour spécial défini.</p>

        <div class="jour-form">
          <label>Date
            <input v-model="nouveauJour.date" type="date" />
          </label>
          <label>Type
            <select v-model="nouveauJour.type">
              <option value="ferie">Férié</option>
              <option value="horaire_special">Horaire dérogatoire</option>
              <option value="ferme">Fermé</option>
            </select>
          </label>
          <template v-if="nouveauJour.type === 'horaire_special'">
            <label>Début
              <input v-model="nouveauJour.heure_debut" type="time" />
            </label>
            <label>Fin
              <input v-model="nouveauJour.heure_fin" type="time" />
            </label>
            <label>Pause début
              <input v-model="nouveauJour.pause_debut" type="time" />
            </label>
            <label>Pause fin
              <input v-model="nouveauJour.pause_fin" type="time" />
            </label>
          </template>
          <label class="commentaire-field">Commentaire
            <input v-model="nouveauJour.commentaire" type="text" placeholder="optionnel" />
          </label>
          <button class="btn primary" :disabled="ajoutJourEnCours || !nouveauJour.date" @click="ajouterJour">
            {{ ajoutJourEnCours ? 'Ajout…' : 'Ajouter' }}
          </button>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.calendrier-admin { display: flex; flex-direction: column; gap: var(--space-4); }
.hint { font-size: var(--font-size-sm); color: var(--color-text-muted); max-width: 680px; margin: 0; }
.error-banner { background: var(--color-rouge-bg); color: var(--color-rouge); padding: var(--space-3); border-radius: var(--radius-md); }
.loading { color: var(--color-text-muted); }

.card {
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-lg); padding: var(--space-4);
}
.card h2 { margin: 0 0 4px; font-size: var(--font-size-base); }
.section-hint { font-size: var(--font-size-xs); color: var(--color-text-muted); margin: 0 0 var(--space-3); }

.poste-form, .jour-form {
  display: flex; align-items: flex-end; gap: var(--space-3); flex-wrap: wrap;
}
.poste-form label, .jour-form label {
  display: flex; flex-direction: column; gap: 4px; font-size: var(--font-size-xs); color: var(--color-text-muted); font-weight: 600;
}
.poste-form input, .jour-form input, .jour-form select {
  height: 36px; padding: 0 var(--space-2); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); font-size: var(--font-size-sm); background: var(--color-bg);
}
.commentaire-field { flex: 1; min-width: 160px; }

.btn {
  height: 36px; border: none; border-radius: var(--radius-md); padding: 0 var(--space-4);
  font-weight: 700; cursor: pointer; background: var(--color-brand); color: var(--color-text-inverse);
}
.btn:disabled { opacity: 0.6; cursor: not-allowed; }

.jours-table { width: 100%; border-collapse: collapse; margin-bottom: var(--space-4); }
.jours-table th { text-align: left; font-size: var(--font-size-xs); color: var(--color-text-muted); padding: var(--space-2) var(--space-2); border-bottom: 1px solid var(--color-border); }
.jours-table td { padding: var(--space-2); border-bottom: 1px solid var(--color-border); font-size: var(--font-size-sm); }
.muted { color: var(--color-text-muted); }
.empty { color: var(--color-text-muted); font-size: var(--font-size-sm); margin-bottom: var(--space-4); }

.link-danger { border: none; background: none; color: var(--color-rouge); cursor: pointer; font-size: var(--font-size-xs); font-weight: 600; }
</style>