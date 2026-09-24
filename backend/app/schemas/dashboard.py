from pydantic import BaseModel
from typing import Optional


class LignePerformanceOut(BaseModel):
    id: int
    code: str
    nom: str
    section_nom: Optional[str] = None
    reel: int
    theorique: Optional[int] = None
    performance_pct: Optional[int] = None
    retard_min: int
    statut: str  # "vert" | "orange" | "rouge" | "arret" | "inactif"
    prevision_fin_poste: Optional[int] = None


class VueUsineResume(BaseModel):
    total_lignes: int
    lignes_vertes: int          # statut "vert"
    lignes_orange: int          # statut "orange"
    lignes_rouges: int          # statut "rouge"
    lignes_a_larret: int        # statut "arret"
    total_reel: int
    total_theorique: int
    performance_usine_pct: Optional[int] = None  # slide 9 : "Performance usine 92,8%"


class VueUsineOut(BaseModel):
    resume: VueUsineResume
    lignes: list[LignePerformanceOut]


class ArretJourOut(BaseModel):
    id: int
    cause_libelle: str
    equipement_label: Optional[str] = None
    heure_debut: str
    heure_fin: Optional[str] = None
    duree_min: Optional[int] = None


class LigneDetailPerformanceOut(BaseModel):
    ligne: LignePerformanceOut
    arrets_du_jour: list[ArretJourOut] = []
    nb_palettes_du_jour: int = 0
