"""
export_service.py -- exports Excel/PDF du rapport Direction (Par ligne, F5 Écritures
Odoo) et, depuis le 23/09, de l'historique des scans opérateur.

*** REFONTE 2026-09-23 *** : délègue la mise en page à export_helpers.py (pied de page
Vusine + date/heure + pagination, arrondis, en-tête Excel figé avec filtres) -- les
signatures publiques ne changent pas, reports_routes.py et labo_routes.py n'ont rien à
modifier.
"""
from datetime import date
from io import BytesIO

import pandas as pd
from openpyxl import load_workbook

from . import export_helpers as h

COLONNES = ["Ligne", "Réel", "Théorique", "Performance", "Palettes", "Arrêt (min)"]


def _df_rapport(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Ligne": f"{r['code']} — {r['nom']}",
        "Réel": r["reel_total"],
        "Théorique": r["theorique_total"],
        "Performance": (r["performance_moyenne"] / 100) if r["performance_moyenne"] is not None else None,
        "Palettes": r["nb_palettes"],
        "Arrêt (min)": r["temps_arret_min"],
    } for r in rows], columns=COLONNES)


def generer_excel_rapport(rows: list[dict], date_debut: date, date_fin: date) -> bytes:
    df = _df_rapport(rows)
    contenu = h.build_excel("Rapport par ligne", df, sous_titre=f"Du {date_debut.isoformat()} au {date_fin.isoformat()}")
    # Performance en vrai pourcentage Excel (0.95 affiché "95 %"), pas un texte "95%".
    wb = load_workbook(BytesIO(contenu))
    ws = wb.active
    col_perf = COLONNES.index("Performance") + 1
    for ligne in range(6, ws.max_row + 1):
        cell = ws.cell(row=ligne, column=col_perf)
        if cell.value is not None:
            cell.number_format = "0 %"
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def generer_pdf_rapport(rows: list[dict], date_debut: date, date_fin: date) -> bytes:
    df = _df_rapport(rows)
    df["Performance"] = df["Performance"].apply(lambda v: None if pd.isna(v) else round(v * 100))
    df = df.rename(columns={"Performance": "Performance (%)"})
    return h.build_pdf("Rapport par ligne", df, sous_titre=f"Période : {date_debut.isoformat()} au {date_fin.isoformat()}",
                        decimales={"Performance (%)": 0})


def generer_csv_rapport(rows: list[dict], date_debut: date, date_fin: date) -> bytes:
    df = _df_rapport(rows)
    df["Performance"] = df["Performance"].apply(lambda v: None if pd.isna(v) else round(v * 100, 1))
    df = df.rename(columns={"Performance": "Performance (%)"})
    return h.build_csv(df)


# =============================================================
# *** AJOUT (chantier Labo, F5 export) *** : ce que Vusine écrirait dans Odoo (palettes
# réelles) si F5 était actif, et sa comparaison avec ce qu'Odoo contient réellement
# (of_cache) -- F5 lui-même n'écrit jamais dans Odoo (décision actée), ces exports sont
# la matérialisation de "l'aperçu" en attendant que la fiabilité soit prouvée.
# =============================================================

COLONNES_ECRITURES = ["Ligne", "Jour", "Produit", "Qté réelle (palettes)", "Nb palettes", "Dont partielles"]
COLONNES_COMPARAISON = ["Ligne", "Jour", "Produit", "Qté Vusine", "Qté Odoo", "Écart", "Écart %"]


def _df_ecritures(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Ligne": r["ligne_code"], "Jour": r["jour"].isoformat(), "Produit": r["produit_nom"],
        "Qté réelle (palettes)": r["quantite_reelle"], "Nb palettes": r["nb_palettes"],
        "Dont partielles": r["nb_palettes_partielles"],
    } for r in rows], columns=COLONNES_ECRITURES)


def _df_comparaison(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Ligne": r["ligne_code"], "Jour": r["jour"].isoformat(), "Produit": r["produit_nom"],
        "Qté Vusine": r["quantite_vusine"], "Qté Odoo": r["quantite_odoo"],
        "Écart": r["ecart_qte"], "Écart %": r["ecart_pct"],
    } for r in rows], columns=COLONNES_COMPARAISON)


def generer_excel_ecritures_proposees(rows: list[dict], date_debut: date, date_fin: date) -> bytes:
    return h.build_excel("Écritures proposées vers Odoo", _df_ecritures(rows),
                          sous_titre=f"F5 non actif -- du {date_debut.isoformat()} au {date_fin.isoformat()}")


def generer_excel_comparaison_odoo(rows: list[dict], date_debut: date, date_fin: date) -> bytes:
    return h.build_excel("Comparaison Vusine (palettes) vs Odoo", _df_comparaison(rows),
                          sous_titre=f"Du {date_debut.isoformat()} au {date_fin.isoformat()}",
                          decimales={"Écart %": 1})


def generer_pdf_ecritures_proposees(rows: list[dict], date_debut: date, date_fin: date) -> bytes:
    return h.build_pdf("Écritures proposées vers Odoo (F5 non actif)", _df_ecritures(rows),
                        sous_titre=f"Période : {date_debut.isoformat()} au {date_fin.isoformat()}")


def generer_pdf_comparaison_odoo(rows: list[dict], date_debut: date, date_fin: date) -> bytes:
    return h.build_pdf("Comparaison Vusine (palettes) vs Odoo", _df_comparaison(rows),
                        sous_titre=f"Période : {date_debut.isoformat()} au {date_fin.isoformat()}",
                        decimales={"Écart %": 1})


def generer_csv_ecritures_proposees(rows: list[dict], date_debut: date, date_fin: date) -> bytes:
    return h.build_csv(_df_ecritures(rows))


def generer_csv_comparaison_odoo(rows: list[dict], date_debut: date, date_fin: date) -> bytes:
    return h.build_csv(_df_comparaison(rows))


# =============================================================
# *** AJOUT 2026-09-23 *** : historique des scans (palettes) par opérateur -- écran
# Rapports (Direction, tous opérateurs) et écran tablette "Mon historique" (opérateur,
# ses propres scans). cf. reports_service.historique_scans pour la restriction d'accès.
# =============================================================

COLONNES_HISTORIQUE = ["Date / heure", "Opérateur", "Matricule", "Ligne", "Produit",
                        "N° lot", "Cartons", "Colisage", "Quantité", "Statut"]


def _df_historique_scans(rows: list) -> pd.DataFrame:
    return pd.DataFrame([{
        "Date / heure": r.created_at.strftime("%d/%m/%Y %H:%M"),
        "Opérateur": r.operateur_nom, "Matricule": r.operateur_matricule or "—",
        "Ligne": r.ligne_code, "Produit": r.produit_nom or "—", "N° lot": r.numero_lot,
        "Cartons": r.nb_cartons, "Colisage": r.colisage_carton, "Quantité": r.quantite_totale,
        "Statut": "Complète" if r.complete else f"Partielle ({r.motif_partielle or 'motif non précisé'})",
    } for r in rows], columns=COLONNES_HISTORIQUE)


def generer_excel_historique_scans(rows: list, date_debut: date, date_fin: date) -> bytes:
    return h.build_excel("Historique des scans", _df_historique_scans(rows),
                          sous_titre=f"Du {date_debut.isoformat()} au {date_fin.isoformat()}")


def generer_pdf_historique_scans(rows: list, date_debut: date, date_fin: date) -> bytes:
    return h.build_pdf("Historique des scans", _df_historique_scans(rows),
                        sous_titre=f"Période : {date_debut.isoformat()} au {date_fin.isoformat()}")


def generer_csv_historique_scans(rows: list, date_debut: date, date_fin: date) -> bytes:
    return h.build_csv(_df_historique_scans(rows))
