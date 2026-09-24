#!/usr/bin/env bash
# reset_vusinedb_dev.sh -- Reset complet de vusinedb_dev
#
# Supprime la base vusinedb_dev et la reconstruit de zéro dans l'ordre correct :
#   1. schema.sql  -- tout le DDL (auth + métier + Labo), état actuel consolidé
#   2. params.sql  -- données de référence (départements, seuils, sections, causes
#                     d'arrêt, poste par défaut, compte admin)
#
# *** SIMPLIFIÉ (chantier Labo) *** : remplace les 4 fichiers précédents
# (01_auth_schema.sql, 02_auth_seed_data.sql, 03_business_schema.sql,
# 04_labo_migration.sql) par ces 2 seuls fichiers -- même principe que schema.sql +
# params.sql côté SIVOX. Les 4 anciens fichiers restent lisibles pour l'historique
# mais ne sont plus joués par ce script.
#
# Usage :
#   chmod +x reset_vusinedb_dev.sh
#   ./reset_vusinedb_dev.sh
#
# Adapte DB_USER/DB_NAME si besoin (valeurs déduites de la session -- vérifie ton .env).

set -euo pipefail

DB_USER="${DB_USER:-postgres}"
DB_NAME="${DB_NAME:-vusinedb_dev}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- CONFIGURATION DU MOT DE PASSE EN DUR ---
export PGPASSWORD="sivop2026"

echo "⚠️  Ceci va SUPPRIMER définitivement la base '${DB_NAME}' et tout son contenu"
echo "   (données de test, données synchronisées Odoo, config manuelle -- poste actif"
echo "   dans Administration > Calendrier compris)."
read -p "Continuer ? (taper 'oui' pour confirmer) " confirm
if [ "$confirm" != "oui" ]; then
    echo "Annulé."
    exit 1
fi

echo ""
echo "1/4 -- Coupe les connexions actives à ${DB_NAME}..."
psql -h localhost -U "$DB_USER" -d postgres -c "
    SELECT pg_terminate_backend(pid) FROM pg_stat_activity
    WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();
"

echo "2/4 -- Drop + recrée ${DB_NAME}..."
dropdb -h localhost -U "$DB_USER" --if-exists "$DB_NAME"
createdb -h localhost -U "$DB_USER" "$DB_NAME"

echo "3/4 -- Joue schema.sql (tout le DDL)..."
psql -h localhost -U "$DB_USER" -d "$DB_NAME" -f "${SCRIPT_DIR}/schema.sql"

echo "4/4 -- Joue params.sql (données de référence)..."
psql -h localhost -U "$DB_USER" -d "$DB_NAME" -f "${SCRIPT_DIR}/params.sql"

echo ""
echo "✅ ${DB_NAME} reconstruite de zéro."
echo ""
echo "Étapes suivantes :"
echo "  1. Relancer l'ETL complet : python3 -u -m scripts.run_vusine_sync --mode full"
echo "     (rapide + historique en une fois -- recrée tous les caches Odoo, y compris"
echo "     les référentiels du Labo : formules, stock matières, écarts, fournisseurs)"
echo "  2. python3 -u -m scripts.run_labo_ingestors   (calcule F1, F7, F8, F9, F10, F5, F6)"
echo "  3. Administration > Calendrier : le poste par défaut est déjà seedé (07:30-17:00,"
echo "     pause 12:30-13:30) via params.sql -- à ajuster si besoin"
echo "  4. python3 -u -m scripts.seed_test_data   (si tu veux aussi les lignes de test)"
echo "  5. Vérifier .env : SNAPSHOT_SCHEDULER_ENABLED / ODOO_SYNC_SCHEDULER_ENABLED"
echo "  6. Se connecter en admin : admin / (mot de passe existant, hash conservé)"
echo "  7. Si ce compte doit voir le Labo : UPDATE users SET is_super_admin = true WHERE username = 'admin';"
