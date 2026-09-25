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
    # *** AJOUT 2026-09-24 (Palier 1) *** : projection linéaire de la production en fin de
    # poste, et quantité planifiée du jour (objectif) -- None tant que non calculables.
    prevision_fin_poste: Optional[int] = None
    objectif_jour: Optional[int] = None


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


# =============================================================
# *** AJOUT 2026-09-24 (Palier 0) *** : écran Andon (TV d'atelier).
# =============================================================

class AndonLigneOut(BaseModel):
    id: int
    code: str
    nom: str
    section_nom: Optional[str] = None
    statut: str  # "arret" | "rouge" | "orange" | "demarrage" | "vert" | "inactif"
    reel: int
    theorique: Optional[int] = None
    performance_pct: Optional[int] = None
    retard_min: int = 0
    prevision_fin_poste: Optional[int] = None
    objectif_jour: Optional[int] = None
    # Produit(s) planifié(s) aujourd'hui : « Produit A » ou « Produit A +1 ».
    produit: Optional[str] = None
    # Renseignés seulement si un arrêt est en cours sur la ligne.
    arret_cause: Optional[str] = None
    arret_depuis_min: Optional[int] = None
    arret_equipement: Optional[str] = None


class AndonOut(BaseModel):
    genere_a: str          # ISO, heure serveur -- affichée « mis à jour à hh:mm » côté écran
    jour: str
    resume: VueUsineResume
    lignes: list[AndonLigneOut]  # déjà triées : les problèmes d'abord
    # 2026-09-24 : aucun scan aujourd'hui sur le périmètre -> les retards affichés ne sont pas
    # représentatifs (adoption des scans), l'écran le dit au lieu d'alarmer.
    nb_palettes_jour: int = 0
    aucun_scan_aujourdhui: bool = False
    section: Optional[str] = None   # section affichée (compte kiosque d'atelier, ou ?section=)
