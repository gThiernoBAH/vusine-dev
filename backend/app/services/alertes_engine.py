from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session

from ..core import crud
from ..models.production import LigneCache, Palette, Alerte, PlanningDetailCache, PlanningCache
from .ligne_helpers import get_planning_du_jour
from .performance_service import calculer_performance_ligne, _bornes_poste_du_jour, _duree_pause_ecoulee_s

SEUIL_SILENCE_DEFAUT_MIN = 30
FENETRE_RALENTISSEMENT_MIN = 60
SEUIL_RALENTISSEMENT_PCT = 70  # en-dessous de 70% du rythme attendu sur la fenêtre récente


def _upsert_alerte_ligne(db: Session, type_: str, ligne_id: int, niveau: str, message: str) -> bool:
    """Dédoublonnage par (type, ligne_id) -- une alerte non résolue de ce type pour
    cette ligne est mise à jour (message/niveau/horodatage) plutôt que dupliquée, car
    le message des catégories 1/2/5 change à chaque cycle (minutes, %) -- comparer le
    message exact créait un doublon à chaque passage. Retourne True si CRÉÉE."""
    existante = (
        db.query(Alerte)
        .filter(Alerte.type == type_, Alerte.ligne_id == ligne_id, Alerte.resolue.is_(False))
        .first()
    )
    if existante:
        existante.message = message
        existante.niveau = niveau
        existante.created_at = datetime.now()
        return False
    db.add(Alerte(type=type_, niveau=niveau, ligne_id=ligne_id, message=message))
    return True


def _alerte_deja_ouverte(db: Session, type_: str, ligne_id: int, message: str) -> bool:
    """Pour les catégories 3/4 (message stable -- numéro de palette fixe) : dédoublonnage
    par message exact, toujours valide ici."""
    return (
        db.query(Alerte)
        .filter(Alerte.type == type_, Alerte.ligne_id == ligne_id, Alerte.message == message, Alerte.resolue.is_(False))
        .first()
        is not None
    )


def _resoudre_alertes_performance_si_retablies(db: Session, ligne_id: int, statut_actuel: str):
    """Si la ligne n'est plus en orange/rouge, ferme les alertes performance encore
    ouvertes pour cette ligne."""
    if statut_actuel in ("orange", "rouge"):
        return
    db.query(Alerte).filter(
        Alerte.type == "performance", Alerte.ligne_id == ligne_id, Alerte.resolue.is_(False)
    ).update({"resolue": True})


def _detecter_ralentissement(db: Session, ligne: LigneCache, items_planning_jour: list[PlanningDetailCache], maintenant: datetime) -> str | None:
    """*** REVU 2026-09-17 *** : rythme récent comparé au rythme "équivalent" dérivé du
    planning hebdomadaire (qty_totale_jour / heures nettes de poste), plus une cadence
    de référence par produit unique -- cohérent avec calculer_performance_ligne.

    Ne se déclenche jamais hors horaires de poste, pendant la pause programmée, ou un
    jour de fermeture (mêmes garde-fous que performance_service, cf. _bornes_poste_du_jour)."""
    if not items_planning_jour:
        return None
    qty_totale_jour = sum(float(item.qty) for item in items_planning_jour if item.qty)
    if qty_totale_jour <= 0:
        return None

    aujourd_hui = maintenant.date()
    bornes = _bornes_poste_du_jour(db, aujourd_hui)
    if not bornes or bornes.get("ferme"):
        return None  # poste non configuré ou usine fermée ce jour -- pas de signal fiable

    poste_debut_dt = datetime.combine(aujourd_hui, bornes["heure_debut"])
    poste_fin_dt = datetime.combine(aujourd_hui, bornes["heure_fin"])
    if maintenant < poste_debut_dt or maintenant > poste_fin_dt:
        return None  # hors horaires de poste -- pas de rythme attendu à ce moment

    pause_debut = bornes.get("pause_debut")
    pause_fin = bornes.get("pause_fin")
    duree_pause_totale_s = 0.0
    if pause_debut and pause_fin:
        duree_pause_totale_s = max(0.0, (datetime.combine(aujourd_hui, pause_fin) - datetime.combine(aujourd_hui, pause_debut)).total_seconds())
    duree_totale_disponible_s = max(0.0, (poste_fin_dt - poste_debut_dt).total_seconds() - duree_pause_totale_s)
    if duree_totale_disponible_s <= 0:
        return None
    cadence_equivalente_horaire = qty_totale_jour / (duree_totale_disponible_s / 3600)

    fenetre_debut = max(maintenant - timedelta(minutes=FENETRE_RALENTISSEMENT_MIN), poste_debut_dt)
    duree_pause_fenetre_s = _duree_pause_ecoulee_s(pause_debut, pause_fin, aujourd_hui, fenetre_debut, maintenant)
    duree_fenetre_h = ((maintenant - fenetre_debut).total_seconds() - duree_pause_fenetre_s) / 3600
    if duree_fenetre_h < 0.25:  # pas assez de recul pour un signal fiable (poste tout juste démarré)
        return None

    reel_recent = (
        db.query(Palette)
        .filter(Palette.ligne_id == ligne.id, Palette.created_at >= fenetre_debut)
        .with_entities(Palette.quantite_totale)
        .all()
    )
    reel_recent_total = sum(q for (q,) in reel_recent)
    attendu_recent = cadence_equivalente_horaire * duree_fenetre_h
    if attendu_recent <= 0:
        return None

    taux = round(reel_recent_total / attendu_recent * 100)
    if taux < SEUIL_RALENTISSEMENT_PCT:
        return f"Ralentissement sur {ligne.code} : {taux}% du rythme attendu sur les {FENETRE_RALENTISSEMENT_MIN} dernières minutes."
    return None


def executer_cycle_alertes(db: Session) -> int:
    """Un passage complet du moteur d'alertes (slide 13) -- appelé par POST
    /alertes/run-now ou le scheduler périodique (toutes les 5 min). Retourne le nombre
    d'alertes CRÉÉES (les mises à jour d'alertes existantes ne comptent pas, cf.
    _upsert_alerte_ligne)."""
    nb_creees = 0
    seuil_silence_str = crud.get_param(db, "seuil_silence_scan_minutes")
    seuil_silence_min = int(seuil_silence_str) if seuil_silence_str else SEUIL_SILENCE_DEFAUT_MIN
    maintenant = datetime.now()
    aujourd_hui = date.today()
    bornes_du_jour = _bornes_poste_du_jour(db, aujourd_hui)
    poste_debut_dt = (
        datetime.combine(aujourd_hui, bornes_du_jour["heure_debut"])
        if bornes_du_jour and not bornes_du_jour.get("ferme") else None
    )

    lignes = db.query(LigneCache).filter(LigneCache.actif.is_(True)).all()
    for ligne in lignes:
        items = get_planning_du_jour(db, ligne.id, aujourd_hui)
        perf = calculer_performance_ligne(db, ligne, items)

        # --- Catégorie 1 : performance (vert/orange/rouge configurable) ---
        if perf["statut"] in ("orange", "rouge"):
            niveau = "rouge" if perf["statut"] == "rouge" else "orange"
            message = f"Performance {perf['performance_pct']}% sur {ligne.code} (retard {perf['retard_min']} min)."
            if _upsert_alerte_ligne(db, "performance", ligne.id, niveau, message):
                nb_creees += 1
        else:
            _resoudre_alertes_performance_si_retablies(db, ligne.id, perf["statut"])

        # --- Catégorie 2 : rythme palettes (silence de scan) ---
        if items and perf["statut"] not in ("inactif", "arret"):
            derniere_palette = (
                db.query(Palette)
                .filter(Palette.ligne_id == ligne.id, Palette.created_at >= (poste_debut_dt or datetime.combine(aujourd_hui, datetime.min.time())))
                .order_by(Palette.created_at.desc())
                .first()
            )
            # Référence = dernière palette scannée aujourd'hui, sinon le début de poste
            # (plus de "date_debut d'OF" -- le planning n'a pas d'horodatage de départ).
            reference = derniere_palette.created_at if derniere_palette else poste_debut_dt
            if reference:
                minutes_ecoulees = (maintenant - reference).total_seconds() / 60
                if minutes_ecoulees > seuil_silence_min:
                    message = f"Aucun scan depuis {round(minutes_ecoulees)} min sur {ligne.code}."
                    if _upsert_alerte_ligne(db, "silence_scan", ligne.id, "orange", message):
                        nb_creees += 1
                else:
                    db.query(Alerte).filter(
                        Alerte.type == "silence_scan", Alerte.ligne_id == ligne.id, Alerte.resolue.is_(False)
                    ).update({"resolue": True})

            # --- Catégorie 5 : ralentissement progressif (signal précoce, slide 13) ---
            message_ralentissement = _detecter_ralentissement(db, ligne, items, maintenant)
            if message_ralentissement:
                if _upsert_alerte_ligne(db, "ralentissement_progressif", ligne.id, "orange", message_ralentissement):
                    nb_creees += 1
            else:
                db.query(Alerte).filter(
                    Alerte.type == "ralentissement_progressif", Alerte.ligne_id == ligne.id, Alerte.resolue.is_(False)
                ).update({"resolue": True})

    # --- Catégorie 3 : traçabilité -- palette partielle sans motif ---
    # Dédoublonnage par message exact conservé (stable : numéro de palette fixe).
    palettes_sans_motif = (
        db.query(Palette)
        .filter(Palette.complete.is_(False), Palette.motif_partielle.is_(None))
        .all()
    )
    for p in palettes_sans_motif:
        message = f"Palette {p.numero_palette} partielle sans motif renseigné."
        if not _alerte_deja_ouverte(db, "partielle_non_justifiee", p.ligne_id, message):
            db.add(Alerte(type="partielle_non_justifiee", niveau="orange", ligne_id=p.ligne_id, message=message))
            nb_creees += 1

    # --- Catégorie 4 : traçabilité -- désynchronisation planning/terrain ---
    # *** REVU 2026-09-17 *** : "OF clôturé mais scan supplémentaire" n'a plus de sens
    # (of_cache n'est plus la source de vérité). Réinterprété comme l'équivalent réel :
    # une palette rattachée à un item de planning dont l'en-tête est passé à 'cancel'
    # APRÈS que la palette a été scannée -- même signal de désynchronisation terrain/Odoo.
    palettes_planning_annule = (
        db.query(Palette)
        .join(PlanningDetailCache, Palette.planning_detail_id == PlanningDetailCache.id)
        .join(PlanningCache, PlanningDetailCache.planning_id == PlanningCache.id)
        .filter(PlanningCache.etat == "cancel")
        .all()
    )
    for p in palettes_planning_annule:
        message = f"Palette {p.numero_palette} scannée sur un planning annulé depuis côté Odoo."
        if not _alerte_deja_ouverte(db, "of_termine_scan", p.ligne_id, message):
            db.add(Alerte(type="of_termine_scan", niveau="orange", ligne_id=p.ligne_id, message=message))
            nb_creees += 1

    db.commit()
    return nb_creees