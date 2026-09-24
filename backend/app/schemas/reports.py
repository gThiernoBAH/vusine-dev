from datetime import date as date_type, datetime
from typing import Optional

from pydantic import BaseModel


class RapportLigneOut(BaseModel):
    """Une ligne du tableau 'Par ligne' (slide 14) -- agrégée sur la période demandée.
    Champs alignés sur RapportsView.vue (r.ligne_id, r.code, r.nom, r.reel_total, ...)."""
    ligne_id: int
    code: str
    nom: str
    reel_total: int
    theorique_total: int
    performance_moyenne: Optional[int] = None  # None si aucun jour avec théorique > 0 sur la période
    nb_palettes: int
    temps_arret_min: int


class RapportProduitOut(BaseModel):
    """Une ligne du tableau 'Par produit' (slide 14). Agrégée depuis les palettes
    rattachées à un produit via planning_detail_cache -- l'ancien "OF" (of_cache) n'est
    plus la source de vérité depuis le 2026-09-17, cf. reports_service.rapport_par_produit."""
    produit_id: int
    nom: str
    quantite_totale: int
    nb_palettes: int
    nb_palettes_completes: int
    nb_palettes_partielles: int


class RapportSectionOut(BaseModel):
    """'Performance par atelier' de la Vue Direction (slide 14) -- regroupe le rapport
    'par ligne' par section_nom (synchronisé depuis Odoo depuis le 2026-09-18, cf.
    investigate_sections.py -- fiable, contrairement à avant cette date)."""
    section_nom: str
    reel_total: int
    theorique_total: int
    performance_moyenne: Optional[int] = None
    nb_lignes: int


class TopFlopLigneOut(BaseModel):
    ligne_id: int
    code: str
    performance_moyenne: Optional[int] = None


class PerteCauseOut(BaseModel):
    cause: str
    duree_min: int


class EvolutionJourOut(BaseModel):
    jour: date_type
    performance_pct: Optional[int] = None  # None si aucune ligne n'a de snapshot ce jour-là


class RapportDirectionOut(BaseModel):
    """Vue Direction (slide 14) : top/flop 5, pertes par cause, évolution quotidienne,
    performance par atelier."""
    top: list[TopFlopLigneOut]
    flop: list[TopFlopLigneOut]
    pertes_par_cause: list[PerteCauseOut]
    evolution_quotidienne: list[EvolutionJourOut]
    par_atelier: list[RapportSectionOut] = []


# =============================================================
# *** AJOUT 2026-09-23 *** : historique des scans (palettes) par opérateur -- écran
# Rapports (Direction, tous les opérateurs) et écran tablette "Mon historique"
# (opérateur/ouvrier, restreint à ses propres scans -- cf. reports_routes.py).
# =============================================================

class HistoriqueScanOut(BaseModel):
    id: int
    created_at: datetime
    ligne_id: int
    ligne_code: str
    produit_nom: Optional[str] = None  # absent si la palette n'a pas de planning_detail_id
    numero_lot: str
    nb_cartons: int
    colisage_carton: int
    quantite_totale: int
    complete: bool
    motif_partielle: Optional[str] = None
    operateur_id: int
    operateur_nom: str
    operateur_matricule: Optional[str] = None

    class Config:
        from_attributes = True
