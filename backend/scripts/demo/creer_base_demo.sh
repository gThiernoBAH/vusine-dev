#!/bin/bash
# creer_base_demo.sh -- copie la base de PRODUCTION vers une base de DÉMO séparée (lecture seule sur la source).
#
#   ./creer_base_demo.sh vusine vusine_demo            # crée la copie
#   ./creer_base_demo.sh vusine vusine_demo --ecraser  # la recrée à neuf (efface l'ancienne démo)
#
# Variables PostgreSQL habituelles : PGHOST, PGPORT, PGUSER, PGPASSWORD.
# La source n'est jamais modifiée (simple pg_dump). Le nom de la cible DOIT contenir « demo ».
set -euo pipefail
SRC="${1:?Usage: $0 <base_source> <base_demo> [--ecraser]}"
DEMO="${2:?Usage: $0 <base_source> <base_demo> [--ecraser]}"
case "$DEMO" in *demo*) ;; *) echo "REFUS : le nom de la base cible doit contenir « demo »." >&2; exit 1;; esac
[ "$SRC" != "$DEMO" ] || { echo "REFUS : source et cible identiques." >&2; exit 1; }

if psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$DEMO'" postgres | grep -q 1; then
  [ "${3:-}" = "--ecraser" ] || { echo "La base $DEMO existe déjà. Ajoutez --ecraser pour la recréer." >&2; exit 1; }
  dropdb "$DEMO"
fi
createdb "$DEMO"
echo "Copie de $SRC vers $DEMO ..."
pg_dump --no-owner --no-privileges "$SRC" | psql -q -v ON_ERROR_STOP=1 "$DEMO" > /dev/null
echo "OK. Lignes copiées : $(psql -tAc 'SELECT COUNT(*) FROM lignes_cache' "$DEMO"), items de planning : $(psql -tAc 'SELECT COUNT(*) FROM planning_detail_cache' "$DEMO")."
echo
echo "Étape suivante -- démarrer une SECONDE instance de l'application sur cette base (la production reste intacte) :"
echo "  cd backend && DATABASE_URL=postgresql://USER:MDP@localhost/$DEMO uvicorn app.main:app --port 8001"
echo "  cd frontend && VITE_PORT=5174 VITE_API_BASE_URL=http://localhost:8001 npm run dev"
