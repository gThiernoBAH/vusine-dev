"""Schémas du scoring d'ÉQUIPE et du suivi individuel de formation.
*** REFONDU 2026-09-24 (Palier 2) *** : l'ancien PersonnelScoreOut (classement nominatif de
chaque CDI/CDD, avec rang et score par personne) a disparu -- voir scoring_service.py."""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class EquipeLigneOut(BaseModel):
    ligne_id: int
    code: str
    nom: str
    section_nom: Optional[str] = None
    jours: int                            # jours complets pris en compte
    effectif: Optional[int] = None        # personnes distinctes affectées ; None = affectations non renseignées
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
    total: EquipeTotalOut
    lignes: list[EquipeLigneOut] = []


class SuiviPersonneOut(BaseModel):
    user_id: int
    nom: str
    matricule: Optional[str] = None


class SuiviLigneOut(BaseModel):
    ligne_code: str
    ligne_nom: str
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
