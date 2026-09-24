import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..core.database import SessionLocal
from ..core.settings import settings
from .snapshot_service import snapshoter_performance_du_jour
from .odoo_sync_service import synchroniser_tout, synchroniser_historique, OdooSyncError
from .alertes_engine import executer_cycle_alertes
from .rapport_matinal_service import envoyer_rapport_matinal
# *** AJOUTS (chantier Labo) ***
from .ingestors import (
    labo_eligibilite_ingestor, labo_predict_ingestor, labo_optimize_pp_ingestor,
    labo_matiere_ingestor, labo_simulation_ingestor, labo_ecritures_ingestor,
    labo_emballage_ingestor,
)

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# *** AJOUT 2026-09-17 *** : intervalle du cycle d'alertes -- pas de flag .env dédié
# pour l'instant (settings.py jamais vu, pour éviter de deviner un nom d'attribut qui
# n'existe pas côté pydantic) -- raccroché au même interrupteur maître que le snapshot
# (SNAPSHOT_SCHEDULER_ENABLED), cf. start_scheduler ci-dessous. À isoler dans son propre
# flag plus tard si besoin de le piloter indépendamment.
ALERTES_INTERVALLE_MINUTES = 5


def _snapshot_job():
    db = SessionLocal()
    try:
        nb = snapshoter_performance_du_jour(db)
        logger.info(f"[SNAPSHOT] Performance figée pour {nb} ligne(s).")
    except Exception as e:
        logger.error(f"[SNAPSHOT] Échec du snapshot quotidien : {e}", exc_info=True)
    finally:
        db.close()


def _odoo_sync_job():
    db = SessionLocal()
    try:
        resultats = synchroniser_tout(db)
        logger.info(f"[SYNC ODOO] {resultats}")
    except OdooSyncError as e:
        logger.error(f"[SYNC ODOO] Échec : {e}")
    except Exception as e:
        logger.error(f"[SYNC ODOO] Échec inattendu : {e}", exc_info=True)
    finally:
        db.close()


def _alertes_job():
    """*** AJOUT 2026-09-17 *** : n'existait pas -- le récap annonçait 3 jobs planifiés
    (snapshot, synchro Odoo, cycle d'alertes), mais seuls 2 étaient réellement câblés
    ici. Sans ce job, les alertes ne se génèrent JAMAIS automatiquement, quel que soit
    l'état des lignes -- uniquement via le clic manuel "Actualiser maintenant"."""
    db = SessionLocal()
    try:
        nb = executer_cycle_alertes(db)
        logger.info(f"[ALERTES] Cycle exécuté -- {nb} nouvelle(s) alerte(s) créée(s).")
    except Exception as e:
        logger.error(f"[ALERTES] Échec du cycle d'alertes : {e}", exc_info=True)
    finally:
        db.close()


def _rapport_matinal_job():
    """*** AJOUT 2026-09-24 (Palier 1) *** : appelé toutes les 15 min -- c'est
    envoyer_rapport_matinal qui décide s'il faut envoyer (jour, heure, fenêtre, déjà
    envoyé), ce qui rattrape un redémarrage du serveur ou un échec SMTP passager."""
    db = SessionLocal()
    try:
        r = envoyer_rapport_matinal(db)
        if r["envoye"] or r["email_echecs"] or r["telegram_echecs"] or r["raison"] == "tous les envois ont échoué":
            logger.info(f"[RAPPORT MATINAL] {r}")
    except Exception as e:
        logger.error(f"[RAPPORT MATINAL] Échec inattendu : {e}", exc_info=True)
    finally:
        db.close()


def _odoo_sync_historique_job():
    """*** AJOUT (chantier Labo) *** : passage nocturne, fenêtre profonde (180j) +
    référentiels complets (formules, stock matières, écarts inventaire, fournisseurs).
    Distinct de _odoo_sync_job (rythme rapide, fenêtre 30j) -- les deux tournent,
    aucun ne remplace l'autre."""
    db = SessionLocal()
    try:
        resultats = synchroniser_historique(db)
        logger.info(f"[SYNC ODOO HISTORIQUE] {resultats}")
    except Exception as e:
        logger.error(f"[SYNC ODOO HISTORIQUE] Échec inattendu : {e}", exc_info=True)
    finally:
        db.close()


def _labo_recalcul_job():
    """*** AJOUT (chantier Labo) *** : recalcul nocturne de F1, F2 (base), F7, F8, F9,
    F10, F5 (export) -- dans l'ordre des dépendances (éligibilité/capacité avant plan
    optimisé, prévision avant besoins matières). Chaque étape est indépendante : un
    échec sur l'une n'empêche jamais les suivantes, même principe que les autres jobs."""
    db = SessionLocal()
    try:
        logger.info(f"[LABO] Éligibilité/capacité : {labo_eligibilite_ingestor.run_eligibilite_cycle(db)}")
    except Exception as e:
        logger.error(f"[LABO] Échec éligibilité/capacité : {e}", exc_info=True)
        db.rollback()
    try:
        logger.info(f"[LABO] Prévision volume (F7) : {labo_predict_ingestor.run_predict_cycle(db)}")
    except Exception as e:
        logger.error(f"[LABO] Échec prévision volume : {e}", exc_info=True)
        db.rollback()
    try:
        logger.info(f"[LABO] Plan optimisé (F8) : {labo_optimize_pp_ingestor.run_optimize_cycle(db)}")
    except Exception as e:
        logger.error(f"[LABO] Échec plan optimisé : {e}", exc_info=True)
        db.rollback()
    try:
        logger.info(f"[LABO] Matières (F9) : {labo_matiere_ingestor.run_matiere_cycle(db)}")
    except Exception as e:
        logger.error(f"[LABO] Échec matières : {e}", exc_info=True)
        db.rollback()
    try:
        logger.info(f"[LABO] Alertes emballage (F6, dépend de F9b) : "
                     f"{labo_emballage_ingestor.recalculer_alertes_emballage(db)}")
    except Exception as e:
        logger.error(f"[LABO] Échec alertes emballage : {e}", exc_info=True)
        db.rollback()
    try:
        logger.info(f"[LABO] Simulation productible (F10) : "
                     f"{labo_simulation_ingestor.recalculer_simulation_productible(db)}")
    except Exception as e:
        logger.error(f"[LABO] Échec simulation productible : {e}", exc_info=True)
        db.rollback()
    try:
        logger.info(f"[LABO] Écritures proposées (F5 export) : {labo_ecritures_ingestor.run_ecritures_cycle(db)}")
    except Exception as e:
        logger.error(f"[LABO] Échec écritures proposées : {e}", exc_info=True)
        db.rollback()
    db.close()


def start_scheduler():
    """Trois jobs indépendants, chacun avec son propre comportement d'échec isolé
    (un job qui plante n'affecte jamais les autres, jobs APScheduler indépendants) :
      - snapshot performance quotidien, à 23:50
      - cycle d'alertes, toutes les ALERTES_INTERVALLE_MINUTES (défaut 5 min)
      - synchro Odoo périodique, toutes les ODOO_SYNC_INTERVAL_MINUTES (défaut 10 min,
        propre flag ODOO_SYNC_SCHEDULER_ENABLED -- désactivable indépendamment des deux
        autres, utile tant que seule la base recette est accessible)."""
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(_snapshot_job, CronTrigger(hour=23, minute=50), id="snapshot_performance_quotidien")
    _scheduler.add_job(
        _alertes_job, IntervalTrigger(minutes=ALERTES_INTERVALLE_MINUTES), id="cycle_alertes_periodique",
    )
    logger.info(f"[SCHEDULER] Cycle d'alertes planifié toutes les {ALERTES_INTERVALLE_MINUTES} min.")

    if settings.RAPPORT_MATINAL_ENABLED:
        _scheduler.add_job(_rapport_matinal_job, IntervalTrigger(minutes=15), id="rapport_matinal")
        logger.info("[SCHEDULER] Rapport matinal : contrôle toutes les 15 min (envoi à l'heure configurée).")

    if settings.ODOO_SYNC_SCHEDULER_ENABLED:
        _scheduler.add_job(
            _odoo_sync_job,
            IntervalTrigger(minutes=settings.ODOO_SYNC_INTERVAL_MINUTES),
            id="sync_odoo_periodique",
        )
        logger.info(f"[SCHEDULER] Synchro Odoo planifiée toutes les {settings.ODOO_SYNC_INTERVAL_MINUTES} min.")

        # *** AJOUTS (chantier Labo) *** : deux jobs nocturnes, rattachés au même
        # interrupteur que la synchro Odoo (ODOO_SYNC_SCHEDULER_ENABLED) -- pas de sens
        # de recalculer le Labo sans synchro Odoo active. 2h30 (historique) puis 3h00
        # (recalcul Labo, qui dépend des données fraîchement synchronisées).
        _scheduler.add_job(_odoo_sync_historique_job, CronTrigger(hour=2, minute=30), id="sync_odoo_historique_nocturne")
        _scheduler.add_job(_labo_recalcul_job, CronTrigger(hour=3, minute=0), id="labo_recalcul_nocturne")
        logger.info("[SCHEDULER] Synchro Odoo historique (2h30) et recalcul Labo (3h00) planifiés.")
    else:
        logger.info("[SCHEDULER] Synchro Odoo périodique désactivée (ODOO_SYNC_SCHEDULER_ENABLED=False) -- POST /sync/run-now uniquement.")

    _scheduler.start()
    logger.info("[SCHEDULER] Démarré (snapshot performance quotidien + cycle d'alertes).")


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None