"""Schémas du scoring d'ÉQUIPE et du suivi individuel de formation.
*** REFONDU 2026-09-24 (Palier 2) *** : l'ancien PersonnelScoreOut (classement nominatif de
chaque CDI/CDD, avec rang et score par personne) a disparu -- voir scoring_service.py.
*** RÉINTRODUIT 2026-09-25 *** : PersonnelClassementOut, plus bas -- cf. le commentaire
détaillé en tête de scoring_routes.py (demande explicite du client, en connaissance de
Palier 2)."""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class EquipeLigneOut(BaseModel):
    ligne_id: int
    code: str
    nom: str
    section_nom: Optional[str] = None
    jours: int                            # jours complets pris en compte
    effectif: Optional[int] = None        # personnes distinctes ; None = ni affectation ni scan sur la période
    effectif_estime: bool = False         # True : déduit des scans (« au moins N »), aucune affectation saisie
    score_pct: Optional[float] = None     # None si masqué ou sans jour évaluable
    attendu: int = 0                      # pièces attendues, arrêts non imputables neutralisés
    produit: int = 0                      # production brute (conforme + rebuts)
    minutes_arret_imputables: int = 0
    minutes_neutralisees: int = 0
    masque: bool = False
    masque_raison: Optional[str] = None


class EquipeTotalOut(BaseModel):
    score_pct: Optional[float] = None
    attendu: int = 0
    produit: int = 0


class EquipeScoringOut(BaseModel):
    date_debut: date
    date_fin: date
    nb_jours: int
    effectif_min: int                     # seuil de masquage (0 = aucun)
    causes_imputables: list[str] = []     # les SEULES causes d'arrêt comptées contre une équipe
    aucune_cause_imputable: bool = True   # alors aucun arrêt ne pénalise personne
    # 2026-09-24 : peu de scans -> pourcentages non représentatifs ; lignes sans planning non évaluées.
    nb_palettes: int = 0
    nb_lignes_sans_planning: int = 0
    donnees_insuffisantes: bool = False
    total: EquipeTotalOut
    lignes: list[EquipeLigneOut] = []


class SuiviPersonneOut(BaseModel):
    user_id: int
    nom: str
    matricule: Optional[str] = None


# *** AJOUT 2026-09-25 *** : cf. commentaire en tête de scoring_routes.py (classement
# nominatif réintroduit sur demande explicite du client, après Palier 2).
class PersonnelClassementOut(BaseModel):
    rang: Optional[int] = None   # None si aucune donnée sur la période (pas classé, pas 0)
    user_id: int
    nom: str
    matricule: Optional[str] = None
    user_type: str
    categorie_personnel: Optional[str] = None
    nb_lignes: int
    heures: float
    score_pct: Optional[float] = None
    tendance: Optional[str] = None   # *** AJOUT 2026-09-25 *** : 'hausse' | 'baisse' | 'stable' | None (pas de comparaison possible)


class SuiviLigneOut(BaseModel):
    ligne_code: str
    ligne_nom: str
    section_nom: Optional[str] = None   # *** AJOUT 2026-09-25 *** : filtre par section côté opérateur
    jours_presence: int
    heures: float
    resultat_equipe_pct: Optional[float] = None   # résultat de L'ÉQUIPE pendant sa présence
    equipe_masquee: bool = False


class SuiviIndividuelOut(BaseModel):
    user_id: int
    nom: str
    matricule: Optional[str] = None
    date_debut: date
    date_fin: date
    heures_totales: float
    lignes: list[SuiviLigneOut] = []
    resultat_equipe_pct: Optional[float] = None
    avertissement: str


class AccesSuiviOut(BaseModel):
    id: int
    consulte_le: datetime
    consulte_par_nom: str
    personne_nom: str
    periode_debut: date
    periode_fin: date