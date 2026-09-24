// Formats d'affichage partagés par les écrans Labo.

// Nombre à la française (espace des milliers, virgule décimale) ; '—' si absent.
export function fmtNombre(v, decimales = 1) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n.toLocaleString('fr-FR', { maximumFractionDigits: decimales })
}

export function fmtTexte(v) {
  return v === null || v === undefined || v === '' ? '—' : v
}
