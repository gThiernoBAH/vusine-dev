/**
 * errors.js -- rend lisibles les erreurs de validation du serveur.
 * *** AJOUT 2026-09-24 *** : FastAPI renvoie, pour une saisie invalide, un TABLEAU d'objets
 * ([{ type, loc, msg, input, ctx }]) que les écrans affichaient tel quel, en JSON brut (constaté
 * sur le champ « identifiant Telegram »). Centralisé dans le client d'API : les 58 endroits qui
 * affichent `e.response.data.detail` en profitent sans modification.
 */
const LIBELLES_CHAMPS = {
  nom: 'Nom', username: 'Identifiant', matricule: 'Matricule', password: 'Mot de passe', email: 'Email',
  telephone: 'Téléphone', user_type: 'Type de compte', telegram_chat_id: 'Identifiant Telegram',
  section_scope: 'Atelier', libelle: 'Libellé', date_debut: 'Date de début', date_fin: 'Date de fin',
  ligne_id: 'Ligne', numero_lot: 'N° de lot', nb_cartons: 'Cartons', colisage_carton: 'Colisage', nb_rebuts: 'Rebuts',
  value: 'Valeur', key: 'Clé',
}

const TRADUCTIONS = [
  [/^Field required$/i, 'champ obligatoire'],
  [/^String should have at least (\d+) characters?/i, (m) => `doit contenir au moins ${m[1]} caractères`],
  [/^String should have at most (\d+) characters?/i, (m) => `ne peut pas dépasser ${m[1]} caractères`],
  [/value is not a valid email address/i, 'adresse email invalide'],
  [/^Input should be a valid (string|integer|number)/i, 'valeur invalide'],
  [/^Input should be greater than or equal to (\S+)/i, (m) => `doit être au moins ${m[1]}`],
  [/^Input should be less than or equal to (\S+)/i, (m) => `ne peut pas dépasser ${m[1]}`],
]

function traduire(msg) {
  for (const [motif, remplacement] of TRADUCTIONS) {
    const m = msg.match(motif)
    if (m) return typeof remplacement === 'function' ? remplacement(m) : remplacement
  }
  return msg
}

/** Transforme `detail` (chaîne, tableau FastAPI, ou autre) en une phrase lisible. */
export function formaterDetail(detail) {
  if (typeof detail === 'string') return detail
  if (!Array.isArray(detail)) return detail
  const phrases = detail.map((item) => {
    if (!item || typeof item !== 'object') return String(item)
    const brut = String(item.msg ?? '')
    // Validateur écrit à la main (type « value_error ») : le message est déjà une phrase complète.
    if (item.type === 'value_error') return brut.replace(/^Value error,\s*/i, '')
    const champ = Array.isArray(item.loc) ? item.loc.filter(x => x !== 'body' && x !== 'query').pop() : null
    const libelle = champ !== null && champ !== undefined ? (LIBELLES_CHAMPS[champ] || champ) : null
    const texte = traduire(brut)
    return libelle ? `${libelle} : ${texte}` : texte
  })
  return [...new Set(phrases)].join(' ; ')
}
