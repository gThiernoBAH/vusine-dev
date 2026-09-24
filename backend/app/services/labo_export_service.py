"""
labo_export_service.py -- Export générique (CSV/Excel/PDF) des écrans Labo.

*** REFONTE 2026-09-23 (v1) *** :
  - Avant : `SELECT * FROM <table>` brut -> identifiants internes (ligne_id=86,
    produit_id=8699) illisibles, noms de colonnes techniques. Chaque domaine a sa
    propre requête : codes de ligne, noms de produit, colonnes en français, dans le
    même ordre qu'à l'écran. Ce qu'on exporte = ce qu'on voit.
  - Nouveaux domaines exportables : planning_risque (F2), fiabilite_saisie (F3),
    prevision_volume (F7), plan_optimise (F8), alertes_emballage (F6) -- tous les
    écrans Labo ont désormais leurs boutons d'export.

*** REFONTE 2026-09-23 (v2) *** : délègue la mise en page à export_helpers.py (pied de
page Vusine + date/heure + pagination, arrondis par colonne, en-tête Excel figé avec
filtres) -- avant, un P90/jour s'exportait "16494.600000000002".

L'export F5 (écritures proposées / comparaison Odoo, bornés par une période) reste dans
labo_routes.py + export_service.py.
"""
from datetime import datetime
from typing import Literal

import pandas as pd
from sqlalchemy import text as sqltext

from . import labo_service
from . import export_helpers as h

# domaine -> (titre du document, requête SQL, {colonne_sql: libellé affiché})
REQUETES = {
    "capacite": ("Capacité démontrée", """
        SELECT l.code AS ligne, p.nom AS produit, c.nb_jours_observes, c.mediane_jour,
               c.p90_jour, c.dernier_jour_observe
        FROM labo_capacite_ligne_produit c
        LEFT JOIN lignes_cache l ON l.id = c.ligne_id
        LEFT JOIN produits_cache p ON p.id = c.produit_id
        WHERE c.nb_jours_observes >= 5
        ORDER BY l.code, p.nom
    """, {"ligne": "Ligne", "produit": "Produit", "nb_jours_observes": "Jours observés",
          "mediane_jour": "Médiane / jour", "p90_jour": "P90 / jour",
          "dernier_jour_observe": "Dernier jour observé"}),

    "prevision_volume": ("Prévision de volume", """
        SELECT p.nom AS produit, v.jour_horizon, v.qte_prevue, v.intervalle_bas, v.intervalle_haut
        FROM labo_prevision_volume v
        LEFT JOIN produits_cache p ON p.id = v.produit_id
        ORDER BY p.nom, v.jour_horizon
    """, {"produit": "Produit", "jour_horizon": "Jour", "qte_prevue": "Prévu",
          "intervalle_bas": "Intervalle bas", "intervalle_haut": "Intervalle haut"}),

    "plan_optimise": ("Plan optimisé", """
        SELECT l.code AS ligne, p.nom AS produit, o.jour, o.qte_recommandee, o.deficit_residuel
        FROM labo_plan_optimise o
        LEFT JOIN lignes_cache l ON l.id = o.ligne_id
        LEFT JOIN produits_cache p ON p.id = o.produit_id
        ORDER BY o.jour, l.code
    """, {"ligne": "Ligne", "produit": "Produit", "jour": "Jour",
          "qte_recommandee": "Qté recommandée", "deficit_residuel": "Déficit résiduel"}),

    "besoins_matieres": ("Besoins matières projetés", """
        SELECT matiere_code, date_rupture_projetee, stock_projete
        FROM labo_besoin_matiere_projete ORDER BY date_rupture_projetee
    """, {"matiere_code": "Matière", "date_rupture_projetee": "Rupture projetée",
          "stock_projete": "Stock projeté"}),

    "alertes_achat": ("Alertes d'achat", """
        SELECT matiere_code, date_rupture_projetee, quantite_manquante, meilleur_delai_jours,
               date_limite_commande, nb_fournisseurs_disponibles
        FROM labo_alertes_achat ORDER BY date_limite_commande
    """, {"matiere_code": "Matière", "date_rupture_projetee": "Rupture projetée",
          "quantite_manquante": "Qté manquante", "meilleur_delai_jours": "Meilleur délai (j)",
          "date_limite_commande": "Date limite commande",
          "nb_fournisseurs_disponibles": "Fournisseurs"}),

    "alertes_emballage": ("Alertes emballage", """
        SELECT a.priorite, l.code AS ligne, a.matiere_code, a.nb_arrets_manque_historique,
               a.date_limite_commande
        FROM labo_alertes_emballage_ligne a
        LEFT JOIN lignes_cache l ON l.id = a.ligne_id
        ORDER BY a.priorite ASC, a.date_limite_commande
    """, {"priorite": "Priorité", "ligne": "Ligne", "matiere_code": "Matière",
          "nb_arrets_manque_historique": "Arrêts « manque » (90 j)",
          "date_limite_commande": "Date limite commande"}),

    "simulation_productible": ("Stock -> produits finis possibles", """
        SELECT produit_fini_code, quantite_productible, composant_limitant_code,
               stock_limitant, nb_composants_sans_stock_connu
        FROM labo_simulation_productible ORDER BY quantite_productible
    """, {"produit_fini_code": "Produit fini", "quantite_productible": "Qté productible",
          "composant_limitant_code": "Composant limitant", "stock_limitant": "Stock limitant",
          "nb_composants_sans_stock_connu": "Composants sans stock connu"}),

    "ecarts_inventaire": ("Écarts d'inventaire", """
        SELECT produit_code, emplacement_nom, date_validation, stock_systeme, stock_compte, ecart_qte
        FROM labo_ecarts_inventaire ORDER BY date_validation DESC
    """, {"produit_code": "Produit", "emplacement_nom": "Emplacement",
          "date_validation": "Date comptage", "stock_systeme": "Stock système",
          "stock_compte": "Stock compté", "ecart_qte": "Écart"}),
}

# Domaines calculés à la demande (F2, F3) : mêmes fonctions que l'écran, mêmes paramètres.
LABELS_STATUT = {"risque": "Risque", "a_surveiller": "À surveiller", "ok": "OK", "inconnu": "Inconnu"}

CALCULES = {
    "planning_risque": ("Planning réaliste",
                        lambda db, p: labo_service.evaluer_planning_risque(db, int(p.get("horizon_jours", 14))),
                        {"ligne_code": "Ligne", "produit_nom": "Produit", "jour": "Jour", "qty": "Planifié",
                         "mediane_jour": "Médiane", "p90_jour": "P90", "statut": "Statut"}),
    "fiabilite_saisie": ("Fiabilité de la saisie",
                         lambda db, p: labo_service.calculer_fiabilite_saisie(db, int(p.get("jours", 30))),
                         {"ligne_code": "Ligne", "nb_of": "Nb OF", "delai_median_h": "Délai médian (h)",
                          "delai_p90_h": "Délai P90 (h)", "nb_corrections": "Corrections"}),
}

DOMAINES_EXPORTABLES = set(REQUETES) | set(CALCULES)

# Décimales par colonne, pour ne jamais exporter "16494.600000000002" -- par défaut,
# export_helpers.build_pdf/build_excel arrondissent déjà à 2 décimales ; ce dictionnaire
# n'affine que les colonnes où 2 décimales ne sont pas le bon choix (0 pour un entier
# métier, 3 pour un ratio de stock très fin...).
DECIMALES_PAR_DOMAINE: dict[str, dict[str, int]] = {
    "capacite": {"Médiane / jour": 1, "P90 / jour": 1},
    "simulation_productible": {"Stock limitant": 3},
    "planning_risque": {"Planifié": 0, "Médiane": 1, "P90": 1},
    "fiabilite_saisie": {"Délai médian (h)": 1, "Délai P90 (h)": 1},
    "plan_optimise": {"Qté recommandée": 0, "Déficit résiduel": 0},
}


def _dataframe(db, domaine: str, params: dict) -> tuple[pd.DataFrame, str]:
    if domaine in REQUETES:
        titre, sql, colonnes = REQUETES[domaine]
        df = pd.read_sql(sqltext(sql), db.bind)
    else:
        titre, fonction, colonnes = CALCULES[domaine]
        df = pd.DataFrame([dict(r) for r in fonction(db, params)], columns=list(colonnes))
        if domaine == "planning_risque" and not df.empty:
            df["statut"] = df["statut"].map(LABELS_STATUT).fillna(df["statut"])
    df = df[[c for c in colonnes if c in df.columns]].rename(columns=colonnes)
    return df, titre


def exporter(db, domaine: str, format: Literal["csv", "xlsx", "pdf"], params: dict | None = None) -> tuple[bytes, str, str]:
    if domaine not in DOMAINES_EXPORTABLES:
        raise ValueError(f"Domaine d'export inconnu : {domaine}")
    df, titre = _dataframe(db, domaine, params or {})
    decimales = DECIMALES_PAR_DOMAINE.get(domaine, {})
    horodatage = datetime.now().strftime("%Y%m%d_%H%M")
    nom_fichier = f"{domaine}_{horodatage}.{format}"

    if format == "csv":
        return h.build_csv(df), nom_fichier, "text/csv"
    if format == "xlsx":
        return (h.build_excel(titre, df, decimales=decimales), nom_fichier,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if format == "pdf":
        return h.build_pdf(titre, df, decimales=decimales), nom_fichier, "application/pdf"
    raise ValueError(f"Format non supporté : {format}")
