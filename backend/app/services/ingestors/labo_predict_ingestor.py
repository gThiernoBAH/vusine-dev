"""
labo_predict_ingestor.py -- Prévision de VOLUME de production à venir PAR PRODUIT
(toutes lignes confondues) [F7], portage de app/services/ingestors/predict_ingestor.py (SIVOX) -- même moteur
(Prophet), même garde-fou d'historique minimal.

*** NUANCE IMPORTANTE (cf. cadrage) *** : ce n'est PAS une prévision de la demande
commerciale (ventes, clients) -- hors périmètre par décision explicite. C'est une
projection du volume réellement produit par produit, un proxy interne. Le
nom "prévision de volume" est utilisé partout à dessein, jamais "prévision de la
demande".

Différences avec l'original SIVOX :
  - Grain : produit uniquement (toutes lignes confondues) -- pas de hiérarchie produit
    (famille/groupe/gamme/section) chez Vusine, contrairement à SIVOX (5 grains).
  - Historique : 180 jours max (fenêtre profonde de l'ETL v2) contre plusieurs années
    chez SIVOX -- MIN_ACTIVE_DAYS abaissé en conséquence (cf. ci-dessous).
  - Un seul niveau (détail jour par jour, labo_prevision_volume).

*** REFONTE 2026-09-23 (diagnostic définitif du 'stan_backend') *** :
  La cause réelle n'était ni la compilation Stan ni la boucle serrée : cmdstanpy 1.3.0
  rejette le cmdstan allégé embarqué par prophet 1.1.6 (livré sans makefile). Prophet
  échouait donc à 100 %, et le repli moyenne mobile était compté comme 'success' --
  c'est ce qui a masqué la panne. Corrigé côté dépendances (cmdstanpy==1.2.5 dans
  requirements.txt). Dans ce fichier :
    - Vérification UNIQUE de Prophet en début de cycle. S'il est indisponible, un seul
      avertissement explicite et tout le cycle passe directement en repli (plus de
      tentatives inutiles ni de trace par couple).
    - Compteur 'fallback' distinct de 'success' : 'success' = Prophet réellement
      utilisé. Un fallback non nul est désormais visible au premier coup d'oeil.
    - Suppression du retry (mitigation d'une hypothèse fausse).
    - Logs cmdstanpy/prophet ramenés à WARNING ; les 'skipped' passent en DEBUG avec un
      résumé chiffré en fin de cycle.
    - Recalcul COMPLET et atomique de labo_prevision_volume (comme les autres
      ingestors) : avant, un couple repassé sous le seuil gardait ses anciennes
      prévisions indéfiniment, et elles continuaient d'alimenter F8/F9.

*** REFONTE 2026-09-23 (suite) *** :
    - Grain PRODUIT au lieu de (ligne, produit). La demande porte sur le produit ;
      répartir entre les lignes est le rôle de F8. Séries plus longues et moins
      bruitées. Corrige au passage un bug de F8 : quand un produit tournait sur
      plusieurs lignes, les prévisions de chaque ligne s'écrasaient au lieu de
      s'additionner (_load_prevision, labo_optimize_pp_ingestor.py).
    - Série prolongée jusqu'à J-2 avec des zéros, et prévision démarrant AUJOURD'HUI.
      Avant, la série s'arrêtait au dernier jour produit : un produit arrêté en mars
      recevait des "prévisions" datées de mars, que F9a consommait comme un besoin
      futur. Arrêt à J-2 et non J-1 : la saisie Odoo se fait le lendemain, la veille
      est donc systématiquement incomplète -- l'inclure ferait croire à une chute.
"""
import logging
from datetime import date, timedelta

# prophet.plot journalise un ERROR "Importing plotly failed" dès l'import -- sans
# conséquence (plotly ne sert qu'aux graphiques interactifs, inutilisés ici). Réglé AVANT
# l'import de prophet, sinon le message est déjà émis.
logging.getLogger("prophet.plot").setLevel(logging.CRITICAL)

import pandas as pd  # noqa: E402
from prophet import Prophet  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy import text as sqltext  # noqa: E402

from ...models.production import PrevisionVolume  # noqa: E402

logger = logging.getLogger(__name__)

HORIZON_JOURS = 14

# *** Repris de predict_ingestor.py (SIVOX), branche matière première (15j) plutôt que
# vente quotidienne de produit fini (30j) -- la production par (ligne, produit) chez
# Vusine est irrégulière par lots plutôt qu'un flux quotidien continu. À recalibrer si
# l'expérience montre un seuil plus juste. ***
MIN_ACTIVE_DAYS = 15

# Dernier jour pris en compte = aujourd'hui - DECALAGE_SAISIE_JOURS (cf. docstring).
DECALAGE_SAISIE_JOURS = 2
FENETRE_HISTORIQUE_JOURS = 180


def _reduire_bruit_logs_prophet():
    """cmdstanpy émet 5-6 lignes DEBUG/INFO par fit (fichiers temporaires, arguments
    CmdStan), prophet une ligne INFO ('Disabling yearly seasonality'...). Ramenés à
    WARNING : les vraies erreurs restent visibles. Efficace pour tous les fits du cycle
    réel (appelée juste après la vérification, cf. run_predict_cycle) -- pour le fit de
    vérification lui-même, voir logging.disable() dans _verifier_prophet ci-dessous."""
    for nom in ("cmdstanpy", "prophet"):
        logging.getLogger(nom).setLevel(logging.WARNING)


def _verifier_prophet() -> tuple[bool, str | None]:
    """Un fit sur données factices : renvoie (True, None) si Prophet/cmdstan fonctionne,
    (False, cause) sinon. Remplace l'ancien warm-up + retry : un environnement cassé
    l'est pour tous les produits, inutile de le redécouvrir à chaque produit.

    *** CORRIGÉ 2026-09-23 *** : cmdstanpy réinitialise le niveau de SON PROPRE logger
    lors de sa toute première utilisation (CmdStanModel, déclenché ici, au premier fit
    du process) -- après quoi _reduire_bruit_logs_prophet() reprend la main sans
    problème pour tout le reste du cycle (confirmé : aucune ligne DEBUG sur les 174
    fits suivants). Seul CE premier fit y échappait. logging.disable() coupe tout
    DEBUG/INFO, toutes bibliothèques confondues, le temps de ce seul appel -- plus
    robuste qu'un setLevel() qu'une bibliothèque tierce peut écraser."""
    logging.disable(logging.INFO)
    try:
        df_test = pd.DataFrame({
            "ds": pd.date_range("2024-01-01", periods=20, freq="D"),
            "y": [float(i % 5) for i in range(20)],
        })
        Prophet(daily_seasonality=False).fit(df_test)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        logging.disable(logging.NOTSET)


def _serie_produit(db: Session, produit_id: int, fin: date) -> pd.DataFrame:
    """Production quotidienne du produit, TOUTES LIGNES CONFONDUES, sur un calendrier
    COMPLET qui va du premier jour produit jusqu'à `fin` (J-2), jours sans production
    à 0. Prophet a besoin des vrais zéros -- y compris ceux de fin de série : un
    produit qui ne tourne plus doit être prévu à ~0, pas à son dernier niveau connu."""
    rows = db.execute(sqltext("""
        SELECT production_date AS ds, COALESCE(SUM(qty_planifiee), 0) AS y
        FROM of_cache
        WHERE usine = 'UPRINC' AND etat = 'done' AND produit_id = :produit_id
          AND production_date >= :debut AND production_date <= :fin
        GROUP BY production_date
        ORDER BY production_date
    """), {"produit_id": produit_id, "debut": fin - timedelta(days=FENETRE_HISTORIQUE_JOURS), "fin": fin}).fetchall()
    if not rows:
        return pd.DataFrame(columns=["ds", "y"])
    df = pd.DataFrame(rows, columns=["ds", "y"])
    df["ds"] = pd.to_datetime(df["ds"])
    # qty_planifiee est NUMERIC côté Postgres -> decimal.Decimal via psycopg2. Converti
    # une seule fois ici, à la source (cf. bug #6 du 22/09).
    df["y"] = df["y"].astype(float)
    calendrier = pd.date_range(df["ds"].min(), pd.Timestamp(fin), freq="D")
    df = df.set_index("ds").reindex(calendrier, fill_value=0.0).rename_axis("ds").reset_index()
    return df


def _prevision_prophet(df: pd.DataFrame, aujourdhui: date) -> pd.DataFrame:
    """Prévision de aujourd'hui à aujourd'hui + HORIZON_JOURS - 1. La série s'arrête à
    J-2 : on prévoit donc aussi J-1 (écarté ensuite) pour démarrer pile à aujourd'hui."""
    model = Prophet(interval_width=0.85, daily_seasonality=False)
    model.fit(df)
    nb_jours = (aujourdhui - df["ds"].max().date()).days - 1 + HORIZON_JOURS
    future = model.make_future_dataframe(periods=nb_jours)
    forecast = model.predict(future)
    previsions = forecast[forecast["ds"] >= pd.Timestamp(aujourdhui)][
        ["ds", "yhat", "yhat_lower", "yhat_upper"]].head(HORIZON_JOURS).reset_index(drop=True)
    for col in ("yhat", "yhat_lower", "yhat_upper"):
        previsions[col] = previsions[col].clip(lower=0.0)  # jamais de quantité négative
    return previsions


def _prevision_repli_statistique(df: pd.DataFrame, horizon_jours: int, aujourdhui: date) -> pd.DataFrame:
    """Repli quand Prophet est indisponible ou échoue sur une série précise : moyenne
    mobile sur les 30 derniers points + écart-type comme intervalle. Moins fin qu'une
    vraie saisonnalité, mais F8/F9a/F6 dépendent tous de labo_prevision_volume : sans
    repli, toute la chaîne en aval resterait vide."""
    valeurs = df["y"].tail(30).tolist()
    moyenne = sum(valeurs) / len(valeurs)
    ecart_type = (sum((v - moyenne) ** 2 for v in valeurs) / len(valeurs)) ** 0.5
    lignes = []
    for h in range(horizon_jours):
        lignes.append({
            "ds": pd.Timestamp(aujourdhui + timedelta(days=h)),
            "yhat": moyenne, "yhat_lower": max(0.0, moyenne - ecart_type),
            "yhat_upper": moyenne + ecart_type,
        })
    return pd.DataFrame(lignes)


def _calculer_previsions(db: Session, produit_id: int, prophet_disponible: bool, aujourdhui: date) -> str:
    """Ajoute à la session les prévisions d'un produit (le commit est fait une seule fois
    en fin de cycle). Retourne :
      'success'  -- Prophet a réellement produit la prévision ;
      'fallback' -- repli moyenne mobile (Prophet indisponible ou en échec sur ce produit) ;
      'skipped'  -- historique insuffisant, contrainte métier attendue ;
      'error'    -- ni Prophet ni le repli n'ont abouti."""
    df = _serie_produit(db, produit_id, aujourdhui - timedelta(days=DECALAGE_SAISIE_JOURS))
    if df.empty:
        return "skipped"

    nb_jours_actifs = int((df["y"] > 0).sum())
    if nb_jours_actifs < MIN_ACTIVE_DAYS:
        logger.debug(f"[LABO PREDICT] produit={produit_id} : "
                      f"{nb_jours_actifs} jours actifs < seuil {MIN_ACTIVE_DAYS} -- ignoré.")
        return "skipped"

    previsions = None
    statut = "success"
    if prophet_disponible:
        try:
            previsions = _prevision_prophet(df, aujourdhui)
        except Exception as e:
            # Prophet fonctionne globalement mais échoue sur CETTE série : inattendu,
            # donc WARNING (une ligne), trace complète seulement en DEBUG.
            logger.warning(f"[LABO PREDICT] Prophet a échoué pour produit={produit_id} : "
                            f"{type(e).__name__}: {e} -- repli sur moyenne mobile.")
            logger.debug("[LABO PREDICT] Trace complète :", exc_info=True)

    if previsions is None:
        statut = "fallback"
        try:
            previsions = _prevision_repli_statistique(df, HORIZON_JOURS, aujourdhui)
        except Exception as e:
            logger.error(f"[LABO PREDICT] Échec du repli statistique pour produit={produit_id} : "
                          f"{type(e).__name__}: {e}")
            return "error"

    for _, row in previsions.iterrows():
        db.add(PrevisionVolume(
            produit_id=produit_id, jour_horizon=row["ds"].date(),
            qte_prevue=int(round(float(row["yhat"]))),
            intervalle_bas=int(round(float(row["yhat_lower"]))),
            intervalle_haut=int(round(float(row["yhat_upper"]))),
        ))
    return statut


def run_predict_cycle(db: Session) -> dict:
    _reduire_bruit_logs_prophet()
    prophet_disponible, cause = _verifier_prophet()
    _reduire_bruit_logs_prophet()

    if prophet_disponible:
        logger.info("[LABO PREDICT] Prophet opérationnel.")
    else:
        logger.warning(
            f"[LABO PREDICT] Prophet INDISPONIBLE ({cause}) -- tout le cycle passe en repli "
            f"moyenne mobile. Cause déjà rencontrée : cmdstanpy>=1.3 incompatible avec "
            f"prophet 1.1.6 (vérifier `pip show cmdstanpy`, attendu 1.2.5).")

    aujourdhui = date.today()
    produits = [r[0] for r in db.execute(sqltext("""
        SELECT DISTINCT produit_id FROM of_cache
        WHERE usine = 'UPRINC' AND etat = 'done' AND produit_id IS NOT NULL
    """)).fetchall()]

    # Recalcul complet : on repart d'une table vide (non commité tant que le cycle n'est
    # pas terminé -- en cas de plantage, le rollback restaure les prévisions précédentes).
    db.query(PrevisionVolume).delete()
    resultats = {"success": 0, "fallback": 0, "skipped": 0, "error": 0}
    for produit_id in produits:
        statut = _calculer_previsions(db, produit_id, prophet_disponible, aujourdhui)
        resultats[statut] += 1
    db.commit()

    logger.info(f"[LABO PREDICT] Cycle terminé : {resultats} -- success = Prophet, "
                 f"fallback = moyenne mobile, skipped = moins de {MIN_ACTIVE_DAYS} jours actifs "
                 f"sur {FENETRE_HISTORIQUE_JOURS} jours ({resultats['skipped']}/{len(produits)} produits).")
    if prophet_disponible and resultats["fallback"]:
        logger.warning(f"[LABO PREDICT] {resultats['fallback']} produit(s) en repli alors que Prophet "
                        f"est opérationnel -- voir les avertissements par produit ci-dessus.")
    return resultats


if __name__ == "__main__":
    from ...core.database import SessionLocal
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    session = SessionLocal()
    try:
        print(run_predict_cycle(session))
    finally:
        session.close()
