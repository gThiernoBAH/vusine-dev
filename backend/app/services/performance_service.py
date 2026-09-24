from datetime import datetime, date, time
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..core import crud
from ..models.production import Palette, Arret, LigneCache, PlanningDetailCache, ConfigurationPoste, JourSpecial

DUREE_DEMARRAGE_DEFAUT_MIN = 10  # cf. param 'duree_demarrage_min', éditable
# *** AJOUT 2026-09-24 (Palier 1) *** : temps de marche minimal avant de projeter la fin
# de poste -- cf. param 'prevision_delai_min', éditable. Une palette se remplit en une
# heure ou plus : projeter plus tôt donnerait des chiffres très instables (0 tant qu'aucune
# palette n'est scannée, puis un bond).
PREVISION_DELAI_DEFAUT_MIN = 60


def _bornes_poste_du_jour(db: Session, jour: date) -> Optional[dict]:
    """Détermine les horaires de poste applicables pour ce jour -- jour spécial
    (férié/horaire dérogatoire/fermeture) s'il y en a un, sinon le poste actif par
    défaut (un seul actif à la fois, cf. schema.sql). Retourne None si RIEN n'est
    configuré (fallback legacy, cf. calculer_performance_ligne)."""
    special = db.query(JourSpecial).filter(JourSpecial.date == jour).first()
    if special:
        if special.type == "ferme":
            return {"ferme": True}
        if special.heure_debut and special.heure_fin:
            return {
                "ferme": False, "heure_debut": special.heure_debut, "heure_fin": special.heure_fin,
                "pause_debut": special.pause_debut, "pause_fin": special.pause_fin,
            }
        return {"ferme": True}

    poste = db.query(ConfigurationPoste).filter(ConfigurationPoste.actif.is_(True)).first()
    if not poste:
        return None

    return {
        "ferme": False, "heure_debut": poste.heure_debut, "heure_fin": poste.heure_fin,
        "pause_debut": poste.pause_debut, "pause_fin": poste.pause_fin,
    }


def _duree_pause_ecoulee_s(pause_debut: Optional[time], pause_fin: Optional[time], jour: date, borne_debut: datetime, instant: datetime) -> float:
    """Durée de la pause programmée déjà écoulée dans la fenêtre [borne_debut, instant]
    -- traitée comme un arrêt "gratuit" qui fige l'objectif théorique (slide 7 : "pause
    qui fige l'objectif"), en plus des arrêts réellement déclarés sur la tablette."""
    if not pause_debut or not pause_fin:
        return 0.0
    pause_debut_dt = datetime.combine(jour, pause_debut)
    pause_fin_dt = datetime.combine(jour, pause_fin)
    debut_effectif = max(pause_debut_dt, borne_debut)
    fin_effective = min(pause_fin_dt, instant)
    return max(0.0, (fin_effective - debut_effectif).total_seconds())


def calculer_performance_ligne(
    db: Session, ligne: LigneCache, items_planning_jour: list[PlanningDetailCache],
    maintenant: Optional[datetime] = None,
) -> dict:
    """
    Calcule réel/théorique/performance %/retard/statut couleur pour une ligne, à
    l'instant présent.

    *** REVU EN PROFONDEUR 2026-09-17 *** : le théorique ne vient plus d'un "OF en
    cours" (of_cache/mrp.production n'est jamais "en cours" chez SIVOP -- 100% des OF
    observés étaient 'done') mais du planning hebdomadaire réel
    (planning_detail_cache/mrp.detail.planning.line, cf. ligne_helpers.get_planning_du_jour).
    `items_planning_jour` peut contenir 0, 1 ou PLUSIEURS items (plusieurs produits
    planifiés le même jour sur la même ligne, décision actée le 2026-09-17 : pas de
    restriction artificielle) -- le théorique du jour = la SOMME des `qty` de tous les
    items, répartie linéairement sur les heures nettes de poste écoulées.

    Formule : théorique(instant) = qty_totale_jour × (heures nettes écoulées depuis le
    début du poste ÷ heures nettes totales du poste), où "nettes" = moins la pause
    programmée et moins les arrêts déclarés -- même principe "une pause fige l'objectif"
    qu'avant (slide 7), juste appliqué à un total journalier plutôt qu'à un taux horaire.

    *** IMPORTANT *** : ce calcul EXIGE un poste actif configuré (configuration_poste) --
    sans lui, impossible de savoir sur combien d'heures répartir la quantité du jour, la
    ligne est donc "inactif" plutôt que d'afficher un chiffre inventé. Contrairement à
    l'ancien calcul (taux horaire simple), il n'y a pas de repli utilisable ici.

    Statuts (cf. légende maquettes Vue Usine) :
      "arret"     -- un arrêt est actuellement en cours sur la ligne
      "demarrage" -- moins de duree_demarrage_min depuis le début du poste ET
                     performance < 100% -- pourcentage pas encore significatif
      "vert"      -- performance >= 100%
      "orange"    -- 80% <= performance < 100%
      "rouge"     -- performance < 80%
      "inactif"   -- aucun item planifié aujourd'hui / poste non configuré / usine
                     fermée ce jour / avant le début du poste
    """
    # Un arrêt en cours prime sur tout le reste, qu'on puisse calculer un théorique ou
    # non -- indépendant de toute fenêtre de calcul.
    arret_ouvert = (
        db.query(Arret).filter(Arret.ligne_id == ligne.id, Arret.heure_fin.is_(None)).first()
    )
    arret_en_cours = arret_ouvert is not None

    if not items_planning_jour:
        return {
            "reel": 0, "theorique": None, "performance_pct": None, "retard_min": 0,
            "statut": "arret" if arret_en_cours else "inactif", "arret_en_cours": arret_en_cours,
        }

    qty_totale_jour = sum(float(item.qty) for item in items_planning_jour if item.qty)

    # `maintenant` injectable (tests, rejeu) -- par défaut l'heure serveur, comme avant.
    maintenant = maintenant or datetime.now()
    aujourd_hui = maintenant.date()
    bornes = _bornes_poste_du_jour(db, aujourd_hui)

    if bornes and bornes.get("ferme"):
        return {
            "reel": 0, "theorique": 0, "performance_pct": None, "retard_min": 0,
            "statut": "arret" if arret_en_cours else "inactif", "arret_en_cours": arret_en_cours,
        }

    if not bornes or qty_totale_jour <= 0:
        # Poste non configuré (impossible de répartir la quantité sur des heures) ou
        # rien de réellement planifié -- inactif plutôt qu'un chiffre inventé.
        return {
            "reel": 0, "theorique": None, "performance_pct": None, "retard_min": 0,
            "statut": "arret" if arret_en_cours else "inactif", "arret_en_cours": arret_en_cours,
        }

    poste_debut_dt = datetime.combine(aujourd_hui, bornes["heure_debut"])
    poste_fin_dt = datetime.combine(aujourd_hui, bornes["heure_fin"])
    pause_debut = bornes.get("pause_debut")
    pause_fin = bornes.get("pause_fin")

    duree_pause_totale_s = 0.0
    if pause_debut and pause_fin:
        duree_pause_totale_s = max(0.0, (datetime.combine(aujourd_hui, pause_fin) - datetime.combine(aujourd_hui, pause_debut)).total_seconds())
    duree_totale_disponible_s = max(0.0, (poste_fin_dt - poste_debut_dt).total_seconds() - duree_pause_totale_s)

    borne_debut = poste_debut_dt
    instant_reference = min(maintenant, poste_fin_dt)
    duree_ecoulee_brute_s = max(0.0, (instant_reference - borne_debut).total_seconds())

    # Arrêts déclarés dans la fenêtre, plafonnés à instant_reference (comme avant).
    arrets = db.query(Arret).filter(Arret.ligne_id == ligne.id, Arret.heure_debut >= borne_debut).all()
    duree_arrets_s = 0.0
    for a in arrets:
        fin = min(a.heure_fin or maintenant, instant_reference)
        duree_arrets_s += max(0.0, (fin - a.heure_debut).total_seconds())

    duree_pause_ecoulee_s = _duree_pause_ecoulee_s(pause_debut, pause_fin, aujourd_hui, borne_debut, instant_reference)

    duree_disponible_ecoulee_s = max(0.0, duree_ecoulee_brute_s - duree_arrets_s - duree_pause_ecoulee_s)

    fraction = (duree_disponible_ecoulee_s / duree_totale_disponible_s) if duree_totale_disponible_s > 0 else 0.0
    theorique = round(qty_totale_jour * fraction)

    cadence_equivalente_horaire = (
        qty_totale_jour / (duree_totale_disponible_s / 3600) if duree_totale_disponible_s > 0 else None
    )

    # Réel : toutes les palettes de la ligne depuis le début du poste (pas
    # instant_reference -- une palette scannée après la fin théorique de poste, en
    # heures sup, doit quand même compter), tous produits confondus (le théorique
    # agrège déjà plusieurs produits, cf. docstring).
    reel = (
        db.query(func.coalesce(func.sum(Palette.quantite_totale), 0))
        .filter(Palette.ligne_id == ligne.id, Palette.created_at >= borne_debut)
        .scalar()
    )
    reel = int(reel or 0)

    if theorique and theorique > 0:
        performance_pct = round(reel / theorique * 100)
        retard_min = (
            max(0, round((theorique - reel) / cadence_equivalente_horaire * 60))
            if cadence_equivalente_horaire else 0
        )
    else:
        performance_pct = None
        retard_min = 0

    # --- *** AJOUT 2026-09-24 (Palier 1) *** Prévision de fin de poste, par projection
    # LINÉAIRE : cadence moyenne observée pendant le temps de marche écoulé (hors arrêts et
    # pause), maintenue pendant le temps de marche restant (hors pause). Suppose qu'aucun
    # nouvel arrêt ne survient -- c'est une projection « si tout continue comme
    # maintenant », pas une promesse. Absente (None) tant que le temps de marche est
    # inférieur à prevision_delai_min ou qu'aucune palette n'est scannée.
    prevision_fin_poste = None
    delai_str = crud.get_param(db, "prevision_delai_min")
    grace_str = crud.get_param(db, "duree_demarrage_min")
    try:
        delai_min = float(delai_str) if delai_str else PREVISION_DELAI_DEFAUT_MIN
        grace_min = float(grace_str) if grace_str else DUREE_DEMARRAGE_DEFAUT_MIN
    except ValueError:
        delai_min, grace_min = PREVISION_DELAI_DEFAUT_MIN, DUREE_DEMARRAGE_DEFAUT_MIN
    if reel > 0 and duree_disponible_ecoulee_s >= max(delai_min, grace_min) * 60:
        restant_brut_s = max(0.0, (poste_fin_dt - instant_reference).total_seconds())
        pause_restante_s = max(0.0, duree_pause_totale_s - duree_pause_ecoulee_s)
        restant_net_s = max(0.0, restant_brut_s - pause_restante_s)
        cadence_par_s = reel / duree_disponible_ecoulee_s
        prevision_fin_poste = round(reel + cadence_par_s * restant_net_s)

    if arret_en_cours:
        statut = "arret"
    elif performance_pct is None:
        statut = "inactif"
    else:
        duree_grace_str = crud.get_param(db, "duree_demarrage_min")
        duree_grace_min = float(duree_grace_str) if duree_grace_str else DUREE_DEMARRAGE_DEFAUT_MIN
        en_demarrage = (duree_ecoulee_brute_s / 60) < duree_grace_min
        if en_demarrage and performance_pct < 100:
            statut = "demarrage"
        elif performance_pct >= 100:
            statut = "vert"
        elif performance_pct >= 80:
            statut = "orange"
        else:
            statut = "rouge"

    return {
        "reel": reel,
        "theorique": theorique,
        "performance_pct": performance_pct,
        "retard_min": retard_min,
        "statut": statut,
        "arret_en_cours": arret_en_cours,
        "prevision_fin_poste": prevision_fin_poste,
        "objectif_jour": round(qty_totale_jour),
    }