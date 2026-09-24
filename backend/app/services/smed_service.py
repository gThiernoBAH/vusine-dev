"""
smed_service.py -- chronométrage des changements de série (SMED : réduction du temps de
changement de série). *** NOUVEAU 2026-09-24 (Palier 1) ***

PRINCIPE : sur une même ligne et un même jour, quand les palettes scannées passent du produit
A au produit B, le changement de série est l'intervalle entre le DERNIER scan du produit A et
le PREMIER scan du produit B. Aucune saisie nouvelle : tout vient des horodatages de palettes
et de leur rattachement à un produit (planning_detail_cache).

LIMITES ASSUMÉES (à lire avant d'interpréter les chiffres)
  - `ecart_scans_min` est une BORNE HAUTE : il inclut le remplissage de la première palette
    du produit B. Il sert à SUIVRE une tendance et à comparer des lignes, pas à mesurer le
    changement au chronomètre.
  - Le temps « Changement produit » déclaré sur la tablette (arrêts) est donné à part
    (`arret_declare_min`) : les deux mesures se recoupent, aucune n'est parfaite seule.
  - Pause et heures hors poste sont retirées de l'écart (un changement à cheval sur la
    pause déjeuner ne « coûte » pas l'heure de pause).
  - Une palette sans produit connu (pas de planning_detail_id) est ignorée : elle ne peut ni
    créer ni interrompre un changement.
  - Seuls les changements d'un MÊME jour comptent : entre deux jours, la nuit n'est pas un
    changement de série.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from typing import Optional

from sqlalchemy.orm import Session

from ..core import crud
from ..models.production import Arret, CauseArret, LigneCache, Palette, PlanningDetailCache, ProduitCache
from ..schemas.reports import SmedChangementOut, SmedLigneOut, SmedOut
from .performance_service import _bornes_poste_du_jour
from .pertes_service import bornes_periode, minutes_entre, minutes_productives

CAUSE_CHANGEMENT_DEFAUT = "Changement produit"


def _moyenne(valeurs: list[float]) -> int:
    return round(sum(valeurs) / len(valeurs))


def changements_de_serie(
    db: Session, date_debut: date, date_fin: date,
    ligne_id: Optional[int] = None, section_scope: Optional[str] = None,
) -> SmedOut:
    try:
        objectif = int(float(crud.get_param(db, "smed_objectif_min") or 0)) or None
    except ValueError:
        objectif = None
    libelle_cause = (crud.get_param(db, "cause_changement_produit") or CAUSE_CHANGEMENT_DEFAUT).strip().lower()

    q = db.query(LigneCache)
    if section_scope:
        q = q.filter(LigneCache.section_nom == section_scope)
    if ligne_id:
        q = q.filter(LigneCache.id == ligne_id)
    lignes = {l.id: l for l in q.all()}
    borne_debut, borne_fin = bornes_periode(date_debut, date_fin)

    rows = []
    if lignes:
        rows = (
            db.query(Palette.ligne_id, Palette.created_at, PlanningDetailCache.produit_id, ProduitCache.nom)
            .join(PlanningDetailCache, Palette.planning_detail_id == PlanningDetailCache.id)
            .join(ProduitCache, PlanningDetailCache.produit_id == ProduitCache.id)
            .filter(Palette.ligne_id.in_(list(lignes)), Palette.created_at >= borne_debut, Palette.created_at < borne_fin)
            .order_by(Palette.ligne_id, Palette.created_at)
            .all()
        )

    # Arrêts « Changement produit » de la période, par ligne.
    cause_ids = [c.id for c in db.query(CauseArret).all() if c.libelle.strip().lower() == libelle_cause]
    arrets_declares: dict[int, list[tuple[datetime, datetime]]] = defaultdict(list)
    if cause_ids and lignes:
        maintenant = datetime.now()
        for a in db.query(Arret).filter(
            Arret.cause_id.in_(cause_ids), Arret.ligne_id.in_(list(lignes)),
            Arret.heure_debut < borne_fin,
        ):
            arrets_declares[a.ligne_id].append((a.heure_debut, a.heure_fin or maintenant))

    postes: dict[date, Optional[dict]] = {}
    par_groupe: dict[tuple[int, date], list] = defaultdict(list)
    for lid, cree, produit_id, nom in rows:
        par_groupe[(lid, cree.date())].append((cree, produit_id, nom))

    changements: list[SmedChangementOut] = []
    for (lid, jour), scans in par_groupe.items():
        precedent = None
        for cree, produit_id, nom in scans:          # déjà triés par heure
            if precedent and precedent[1] != produit_id:
                fin_a, debut_b = precedent[0], cree
                if jour not in postes:
                    postes[jour] = _bornes_poste_du_jour(db, jour)
                bornes = postes[jour]
                if bornes and not bornes.get("ferme"):
                    ecart = minutes_productives(fin_a, debut_b, jour, bornes)
                else:
                    ecart = minutes_entre(fin_a, debut_b)
                declare = sum(
                    max(0.0, minutes_entre(max(d, fin_a), min(f, debut_b)))
                    for d, f in arrets_declares.get(lid, []) if min(f, debut_b) > max(d, fin_a)
                )
                changements.append(SmedChangementOut(
                    ligne_id=lid, ligne_code=lignes[lid].code, jour=jour,
                    produit_avant=precedent[2], produit_apres=nom,
                    dernier_scan_avant=fin_a, premier_scan_apres=debut_b,
                    ecart_scans_min=round(ecart),
                    arret_declare_min=round(declare) if declare > 0 else None,
                    au_dessus_objectif=bool(objectif and round(ecart) > objectif),
                ))
            precedent = (cree, produit_id, nom)

    changements.sort(key=lambda c: c.premier_scan_apres, reverse=True)

    par_ligne: dict[int, list[SmedChangementOut]] = defaultdict(list)
    for c in changements:
        par_ligne[c.ligne_id].append(c)
    lignes_out = []
    for lid, cs in par_ligne.items():
        ecarts = [c.ecart_scans_min for c in cs]
        declares = [c.arret_declare_min for c in cs if c.arret_declare_min is not None]
        lignes_out.append(SmedLigneOut(
            ligne_id=lid, ligne_code=lignes[lid].code, nb_changements=len(cs),
            moyenne_min=_moyenne(ecarts), mediane_min=round(median(ecarts)),
            meilleur_min=min(ecarts), pire_min=max(ecarts),
            moyenne_declaree_min=_moyenne(declares) if declares else None,
        ))
    lignes_out.sort(key=lambda l: l.ligne_code)

    tous = [c.ecart_scans_min for c in changements]
    return SmedOut(
        date_debut=date_debut, date_fin=date_fin, objectif_min=objectif, nb_changements=len(changements),
        moyenne_min=_moyenne(tous) if tous else None, mediane_min=round(median(tous)) if tous else None,
        meilleur_min=min(tous) if tous else None,
        nb_au_dessus_objectif=sum(1 for c in changements if c.au_dessus_objectif),
        lignes=lignes_out, changements=changements,
    )
