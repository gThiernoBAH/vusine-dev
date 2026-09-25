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
    section_nom: Optional[str] = None   # *** AJOUT 2026-09-25 *** : filtre par section côté opérateur
    produit_nom: Optional[str] = None  # absent si la palette n'a pas de planning_detail_id
    numero_lot: str
    nb_cartons: int
    colisage_carton: int
    quantite_totale: int
    complete: bool
    motif_partielle: Optional[str] = None
    nb_rebuts: int = 0
    operateur_id: int
    operateur_nom: str
    operateur_matricule: Optional[str] = None

    class Config:
        from_attributes = True


# =============================================================
# *** AJOUT 2026-09-24 (Palier 0) *** : Pareto des causes d'arrêt, avec coût estimé.
# =============================================================

class ParetoLigneOut(BaseModel):
    ligne_id: int
    ligne_code: str
    duree_min: int
    nb_arrets: int
    cout_fcfa: Optional[int] = None  # None = non valorisable (planning ou valeur manquants)


class ParetoEquipementOut(BaseModel):
    equipement: str  # « Non précisé » quand l'arrêt ne pointe aucune machine (ex. Manque MP)
    duree_min: int
    nb_arrets: int


class ParetoCauseOut(BaseModel):
    rang: int
    cause_id: int
    cause: str
    duree_min: int
    nb_arrets: int
    pct: float          # part de cette cause dans la durée totale d'arrêt
    pct_cumule: float   # cumul, dans l'ordre décroissant -- la courbe de Pareto
    cout_fcfa: Optional[int] = None
    minutes_non_valorisees: int = 0
    par_ligne: list[ParetoLigneOut] = []
    par_equipement: list[ParetoEquipementOut] = []


class ParetoArretsOut(BaseModel):
    date_debut: date_type
    date_fin: date_type
    total_duree_min: int
    total_nb_arrets: int
    total_cout_fcfa: Optional[int] = None
    minutes_non_valorisees: int = 0
    # True si au moins une valeur de pièce est renseignée (globale ou par produit) --
    # sinon l'écran invite à la configurer plutôt que d'afficher des « n/d » partout.
    valorisation_configuree: bool = False
    libelle_valeur: str = "Valeur unitaire"
    # Arrêts jamais clôturés : comptés jusqu'à la fin de la période demandée (ou jusqu'à
    # maintenant), donc à vérifier -- une saisie oubliée gonfle la durée.
    nb_arrets_non_clotures: int = 0
    causes: list[ParetoCauseOut] = []


# =============================================================
# *** AJOUT 2026-09-24 (Palier 1) *** : TRS décomposé (disponibilité x performance x qualité).
# =============================================================

class TrsLigneOut(BaseModel):
    ligne_id: Optional[int] = None   # None pour la ligne de total « USINE »
    code: str
    nom: str
    jours: int                        # jours complets pris en compte (planning > 0, poste ouvert)
    qte_planifiee: int
    production_conforme: int          # pièces conformes palettisées (= quantite_totale)
    rebuts: int
    minutes_arret: int                # minutes d'arrêt PENDANT les heures de poste
    disponibilite_pct: Optional[float] = None
    performance_pct: Optional[float] = None
    qualite_pct: Optional[float] = None
    trs_pct: Optional[float] = None
    # Décomposition en PIÈCES de l'écart entre le planifié et le conforme :
    # planifié - conforme = arrêts + cadence + rebuts (à l'arrondi près).
    pertes_arrets_pieces: int = 0
    pertes_cadence_pieces: int = 0    # négatif = la ligne a dépassé sa cadence de référence
    pertes_rebuts_pieces: int = 0
    # Production attendue PENDANT le temps de marche (planifié x disponibilité) -- base de la
    # « performance » des rapports et du rapport matinal (2026-09-24).
    pieces_theoriques: int = 0


class TrsJourOut(BaseModel):
    jour: date_type
    trs_pct: Optional[float] = None
    disponibilite_pct: Optional[float] = None
    performance_pct: Optional[float] = None
    qualite_pct: Optional[float] = None


class TrsOut(BaseModel):
    date_debut: date_type
    date_fin: date_type
    cible_pct: float                  # paramètre trs_cible_pct (défaut 85)
    nb_jours: int                     # jours complets pris en compte
    jour_en_cours_exclu: bool = False # le jour d'aujourd'hui, poste non terminé, n'est pas compté
    # False tant qu'aucun rebut n'a été déclaré sur la période : la Qualité affichée (100 %)
    # serait alors un défaut, pas une mesure -- l'écran doit le dire.
    qualite_renseignee: bool = False
    # Pièces palettisées un jour TERMINÉ sans planning pour la ligne, ou un jour fermé : hors
    # TRS, signalées pour que l'écart soit visible. Le jour en cours n'est jamais compté ici.
    pieces_hors_planning: int = 0
    # 2026-09-24 : palettes de la période, lignes du périmètre sans aucun planning, et drapeau
    # « données insuffisantes » (peu de scans : les pourcentages ne sont pas représentatifs).
    nb_palettes: int = 0
    nb_lignes_sans_planning: int = 0
    donnees_insuffisantes: bool = False
    usine: TrsLigneOut
    lignes: list[TrsLigneOut] = []
    evolution: list[TrsJourOut] = []


# =============================================================
# *** AJOUT 2026-09-24 (Palier 1) *** : chronométrage des changements de série (SMED).
# =============================================================

class SmedChangementOut(BaseModel):
    ligne_id: int
    ligne_code: str
    jour: date_type
    produit_avant: str
    produit_apres: str
    dernier_scan_avant: datetime
    premier_scan_apres: datetime
    # Écart entre le dernier scan du produit A et le premier scan du produit B, hors pause
    # et hors heures de poste. C'est une BORNE HAUTE du vrai changement : il inclut le
    # temps de remplissage de la première palette du produit B.
    ecart_scans_min: int
    # Temps déclaré sur la tablette (arrêts « Changement produit ») dans cet intervalle ;
    # None si aucun arrêt de cette cause ne le recoupe.
    arret_declare_min: Optional[int] = None
    au_dessus_objectif: bool = False


class SmedLigneOut(BaseModel):
    ligne_id: int
    ligne_code: str
    nb_changements: int
    moyenne_min: int
    mediane_min: int
    meilleur_min: int
    pire_min: int
    moyenne_declaree_min: Optional[int] = None


class SmedOut(BaseModel):
    date_debut: date_type
    date_fin: date_type
    objectif_min: Optional[int] = None   # paramètre smed_objectif_min (0 = pas d'objectif)
    nb_changements: int
    moyenne_min: Optional[int] = None
    mediane_min: Optional[int] = None
    meilleur_min: Optional[int] = None
    nb_au_dessus_objectif: int = 0
    lignes: list[SmedLigneOut] = []
    changements: list[SmedChangementOut] = []