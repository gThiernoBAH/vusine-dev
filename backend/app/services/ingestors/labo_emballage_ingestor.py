"""
labo_emballage_ingestor.py -- F6 (alerte manque d'emballage anticipé, priorisée par
l'historique réel des arrêts).

Croise labo_alertes_achat (F9b, "cette matière va manquer, tel jour") avec :
  1. les lignes qui consomment cette matière (via labo_formules_explosion -> quels
     produits finis en ont besoin -> labo_lignes_eligibles_produit -> quelles lignes
     les fabriquent) ;
  2. l'historique réel des arrêts "Manque MP"/"Manque emballage" sur ces lignes
     (table arrets, 90 derniers jours).

Une ligne qui a DÉJÀ subi ce type d'arrêt et qui est concernée par une alerte F9b en
cours reçoit la priorité 'haute' -- c'est la valeur ajoutée de F6 par rapport à F9b
seul : hiérarchiser l'attention entre plusieurs alertes simultanées.
"""
import logging
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import text as sqltext

from ...models.production import AlerteEmballageLigne

logger = logging.getLogger(__name__)

FENETRE_HISTORIQUE_JOURS = 90


def recalculer_alertes_emballage(db: Session) -> int:
    db.query(AlerteEmballageLigne).delete()

    # 1. Historique des arrêts "manque" par ligne (90 derniers jours).
    arrets = db.execute(sqltext("""
        SELECT a.ligne_id, COUNT(*) AS nb
        FROM arrets a
        JOIN causes_arret c ON c.id = a.cause_id
        WHERE c.libelle IN ('Manque MP', 'Manque emballage')
          AND a.heure_debut >= CURRENT_DATE - (:jours || ' days')::interval
        GROUP BY a.ligne_id
    """), {"jours": FENETRE_HISTORIQUE_JOURS}).fetchall()
    nb_arrets_par_ligne = {ligne_id: nb for ligne_id, nb in arrets}

    # 2. Pour chaque alerte d'achat (F9b), les lignes qui fabriquent un produit fini
    #    consommant cette matière (jointure formules explosées <-> éligibilité).
    correspondances = db.execute(sqltext("""
        SELECT DISTINCT aa.matiere_code, aa.date_limite_commande, e.ligne_id
        FROM labo_alertes_achat aa
        JOIN labo_formules_explosion fe ON fe.composant_code = aa.matiere_code
        JOIN produits_cache p ON p.default_code = fe.produit_fini_code
        JOIN labo_lignes_eligibles_produit e ON e.produit_id = p.id
    """)).fetchall()

    par_ligne_matiere: dict[tuple, dict] = {}
    for matiere_code, date_limite, ligne_id in correspondances:
        par_ligne_matiere[(ligne_id, matiere_code)] = date_limite

    nb = 0
    for (ligne_id, matiere_code), date_limite in par_ligne_matiere.items():
        nb_historique = nb_arrets_par_ligne.get(ligne_id, 0)
        db.add(AlerteEmballageLigne(
            ligne_id=ligne_id, matiere_code=matiere_code,
            nb_arrets_manque_historique=nb_historique,
            date_limite_commande=date_limite,
            priorite="haute" if nb_historique > 0 else "normale",
        ))
        nb += 1
    db.commit()
    logger.info(f"[LABO EMBALLAGE] {nb} alerte(s) emballage/matière calculée(s) "
                f"({sum(1 for v in nb_arrets_par_ligne.values() if v > 0)} ligne(s) avec historique de manque).")
    return nb


if __name__ == "__main__":
    from ...core.database import SessionLocal
    session = SessionLocal()
    try:
        print({"alertes_emballage": recalculer_alertes_emballage(session)})
    finally:
        session.close()
