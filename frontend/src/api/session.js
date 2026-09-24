/**
 * session.js -- persistance de la session d'un compte « kiosque » (écran Andon).
 * *** AJOUT 2026-09-24 (Palier 0) ***
 *
 * Les comptes normaux vivent dans sessionStorage : la session disparaît à la fermeture de
 * l'onglet, ce qui est voulu sur un PC partagé. Une TV d'atelier, elle, redémarre (coupure
 * de courant, mise à jour du navigateur) sans personne pour se reconnecter : la session
 * du compte kiosque est donc AUSSI gardée dans localStorage, jusqu'à son expiration
 * (30 jours côté serveur). Aucun autre type de compte n'est jamais écrit dans localStorage.
 */
const CLE = 'kiosk_session'

export function memoriserSessionKiosque(user, token, expiresAt) {
  if (user?.user_type !== 'kiosque') return
  try {
    localStorage.setItem(CLE, JSON.stringify({ user, token, expiresAt }))
  } catch { /* stockage indisponible : la session reste valable jusqu'à la fermeture de l'onglet */ }
}

export function oublierSessionKiosque() {
  try { localStorage.removeItem(CLE) } catch { /* rien à faire */ }
}

/** À appeler avant le montage de l'application : recrée la session depuis localStorage. */
export function restaurerSessionKiosque() {
  if (sessionStorage.getItem('token')) return
  try {
    const brut = localStorage.getItem(CLE)
    if (!brut) return
    const { user, token, expiresAt } = JSON.parse(brut)
    if (!user || !token || (expiresAt && expiresAt * 1000 < Date.now())) {
      localStorage.removeItem(CLE)
      return
    }
    sessionStorage.setItem('user', JSON.stringify(user))
    sessionStorage.setItem('token', token)
  } catch {
    oublierSessionKiosque()
  }
}
