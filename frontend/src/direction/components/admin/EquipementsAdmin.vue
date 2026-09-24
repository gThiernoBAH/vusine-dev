<script setup>
import { ref, onMounted } from 'vue'
import apiClient from '@/api/client'
import { Plus } from 'lucide-vue-next'

const equipements = ref([])
const lignes = ref([])
const isLoading = ref(true)
const errorMessage = ref('')

const showForm = ref(false)
const formError = ref('')
const form = ref(defaultForm())

function defaultForm() {
  return { type: '', marque: '', modele: '', numeroInterne: '', capacite: '' }
}

async function chargerTout() {
  isLoading.value = true
  try {
    const [eqRes, lignesRes] = await Promise.all([
      apiClient.get('/admin/equipements'),
      apiClient.get('/entities/lignes'),
    ])
    equipements.value = eqRes.data
    lignes.value = lignesRes.data
    errorMessage.value = ''
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || 'Impossible de charger les équipements.'
  } finally {
    isLoading.value = false
  }
}
onMounted(chargerTout)

async function creerEquipement() {
  formError.value = ''
  try {
    await apiClient.post('/admin/equipements', {
      type: form.value.type,
      marque: form.value.marque || null,
      modele: form.value.modele || null,
      numero_interne: form.value.numeroInterne || null,
      capacite: form.value.capacite || null,
    })
    showForm.value = false
    form.value = defaultForm()
    chargerTout()
  } catch (e) {
    formError.value = e.response?.data?.detail || 'Échec de la création.'
  }
}

const affectationChoix = ref({})

async function affecter(eq) {
  const ligneId = affectationChoix.value[eq.id]
  if (!ligneId) return
  await apiClient.post('/admin/affectations-equipement', { equipement_id: eq.id, ligne_id: ligneId })
  chargerTout()
}

function statutLabel(statut) {
  return { disponible: 'Disponible', en_panne: 'En panne', en_maintenance: 'En maintenance', retire: 'Retiré' }[statut] || statut
}
function statutClass(statut) {
  if (statut === 'disponible') return 'statut-vert'
  if (statut === 'en_panne') return 'statut-rouge'
  return 'statut-orange'
}
</script>

<template>
  <div class="equipements-admin">
    <div class="toolbar">
      <button class="add-btn" @click="showForm = !showForm"><Plus :size="16" /> Nouvel équipement</button>
    </div>

    <div v-if="showForm" class="form-card">
      <div class="form-row">
        <label class="field"><span>Type</span><input v-model="form.type" type="text" placeholder="remplisseuse, étiqueteuse…" /></label>
        <label class="field"><span>Marque</span><input v-model="form.marque" type="text" /></label>
        <label class="field"><span>Modèle</span><input v-model="form.modele" type="text" /></label>
      </div>
      <div class="form-row">
        <label class="field"><span>N° interne</span><input v-model="form.numeroInterne" type="text" /></label>
        <label class="field"><span>Capacité</span><input v-model="form.capacite" type="text" placeholder="ex: 12 000 pcs/h" /></label>
      </div>
      <p v-if="formError" class="error-banner">{{ formError }}</p>
      <div class="form-actions">
        <button class="btn secondary" @click="showForm = false">Annuler</button>
        <button class="btn primary" @click="creerEquipement">Créer</button>
      </div>
    </div>

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    <div v-if="isLoading" class="loading">Chargement…</div>

    <table v-else class="admin-table">
      <thead>
        <tr><th>Type</th><th>Marque / Modèle</th><th>N° interne</th><th>Statut</th><th>Ligne actuelle</th><th>Affecter</th></tr>
      </thead>
      <tbody>
        <tr v-for="eq in equipements" :key="eq.id">
          <td>{{ eq.type }}</td>
          <td>{{ eq.marque }} {{ eq.modele }}</td>
          <td>{{ eq.numero_interne || '—' }}</td>
          <td><span :class="['badge', statutClass(eq.statut)]">{{ statutLabel(eq.statut) }}</span></td>
          <td>{{ eq.ligne_actuelle_code || '—' }}</td>
          <td>
            <div class="affect-cell">
              <select v-model.number="affectationChoix[eq.id]">
                <option :value="null" disabled>Ligne…</option>
                <option v-for="l in lignes" :key="l.id" :value="l.id">{{ l.code }}</option>
              </select>
              <button class="btn primary small" @click="affecter(eq)">OK</button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.toolbar { margin-bottom: var(--space-4); }

.add-btn, .btn {
  display: inline-flex; align-items: center; gap: var(--space-2);
  border: none; border-radius: var(--radius-md); padding: var(--space-2) var(--space-4);
  font-weight: 700; cursor: pointer;
}
.add-btn, .btn.primary { background: var(--color-brand); color: var(--color-text-inverse); }
.btn.secondary { background: var(--color-border); color: var(--color-text); }
.btn.small { padding: var(--space-1) var(--space-3); font-size: var(--font-size-sm); }

.form-card {
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-lg); padding: var(--space-4); margin-bottom: var(--space-4);
  box-shadow: var(--shadow-card);
}
.form-row { display: flex; gap: var(--space-4); margin-bottom: var(--space-3); }
.field { flex: 1; display: flex; flex-direction: column; gap: 4px; font-size: var(--font-size-sm); }
.field input {
  height: 40px; padding: 0 var(--space-3); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); font-family: inherit;
}
.form-actions { display: flex; justify-content: flex-end; gap: var(--space-2); }

.error-banner {
  background: var(--color-rouge-bg); color: var(--color-rouge);
  padding: var(--space-3); border-radius: var(--radius-md); margin-bottom: var(--space-3);
}
.loading { color: var(--color-text-muted); }

.admin-table {
  width: 100%; border-collapse: collapse; background: var(--color-surface);
  border: 1px solid var(--color-border); border-radius: var(--radius-lg); overflow: hidden;
}
.admin-table th {
  text-align: left; background: var(--color-brand-light); color: var(--color-brand-dark);
  font-size: var(--font-size-xs); padding: var(--space-3);
}
.admin-table td { padding: var(--space-3); border-top: 1px solid var(--color-border); font-size: var(--font-size-sm); }

.badge { padding: 3px 10px; border-radius: 999px; font-size: var(--font-size-xs); font-weight: 700; }

.affect-cell { display: flex; gap: var(--space-2); }
.affect-cell select {
  height: 32px; padding: 0 var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-md);
}
</style>
