from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import Optional


class PaletteCreate(BaseModel):
    ligne_id: int
    # *** REVU 2026-09-17 *** : remplace of_id -- une palette se rattache désormais à un
    # item précis du planning hebdomadaire (ligne + jour + produit), pas à un OF (jamais
    # réellement "en cours" chez SIVOP). Optionnel : reste utilisable si, par exception,
    # aucun item de planning n'existe pour la ligne ce jour-là (saisie manuelle malgré
    # tout, cf. discussion écran tablette).
    planning_detail_id: Optional[int] = None
    numero_lot: str = Field(..., min_length=1, max_length=50)
    nb_cartons: int = Field(..., gt=0)
    colisage_carton: int = Field(..., gt=0)
    # False = "Palette partielle" (écran 7 des maquettes) -- l'opérateur ajuste alors
    # nb_cartons à la baisse par rapport au standard de la ligne.
    complete: bool = True
    # Motif de palette partielle (slide 6 du CDC, jamais câblé jusqu'ici côté saisie) --
    # optionnel, pertinent seulement si complete=False.
    motif_partielle: Optional[str] = Field(None, max_length=100)
    # *** AJOUT 2026-09-24 (Palier 1, TRS) *** : pièces rebutées pendant le remplissage de
    # cette palette, hors quantité de la palette -- optionnel, 0 par défaut.
    nb_rebuts: int = Field(0, ge=0, le=1_000_000)


class PaletteUpdate(BaseModel):
    """*** NOUVEAU 2026-09-17 *** : n'existait pas -- le bouton "Corriger" de
    LigneDetailView.vue appelait déjà PATCH /actions/palettes/{id}, mais aucune route ni
    schéma ne le servaient. Chaque champ modifié est tracé dans palettes_corrections
    (permission correction_palette)."""
    nb_cartons: Optional[int] = Field(None, gt=0)
    colisage_carton: Optional[int] = Field(None, gt=0)
    numero_lot: Optional[str] = Field(None, min_length=1, max_length=50)
    nb_rebuts: Optional[int] = Field(None, ge=0, le=1_000_000)  # 2026-09-24 : corrigeable, tracé comme le reste
    motif: Optional[str] = None  # motif de LA correction elle-même (journal d'audit)


class PaletteOut(BaseModel):
    id: int
    numero_palette: str
    ligne_id: int
    planning_detail_id: Optional[int] = None
    numero_lot: str
    date_expiration: Optional[date] = None
    nb_cartons: int
    colisage_carton: int
    quantite_totale: int
    complete: bool
    motif_partielle: Optional[str] = None
    nb_rebuts: int = 0
    operateur_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ArretCreate(BaseModel):
    ligne_id: int
    cause_id: int
    # Nullable -- cf. schema.sql : un arrêt "Manque personnel" ne concerne aucune machine
    # en particulier, contrairement à "Panne machine".
    equipement_id: Optional[int] = None
    commentaire: Optional[str] = None


class ArretOut(BaseModel):
    id: int
    ligne_id: int
    cause_id: int
    cause_libelle: Optional[str] = None
    equipement_id: Optional[int] = None
    commentaire: Optional[str] = None
    heure_debut: datetime
    heure_fin: Optional[datetime] = None
    operateur_id: int

    class Config:
        from_attributes = True