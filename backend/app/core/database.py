from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from .settings import settings

# Base transactionnelle unique de Vusine -- contrairement à SIVOX, pas de second moteur
# SQL Server (pas de DWH séparé côté Vusine : cf. décision de cadrage, base propre à l'app,
# alimentée en lecture par synchro périodique du référentiel Odoo, écrite par lot).
#
# *** AJOUT 2026-09-23 (erreur réelle en prod, cf. trace uvicorn) *** :
#   psycopg2.OperationalError: SSL connection has been closed unexpectedly
# Le pool SQLAlchemy réutilisait une connexion que Postgres (ou un pare-feu/proxy entre
# les deux) avait fermée après une période d'inactivité -- la connexion restait valide
# côté pool, invalide côté serveur, et la première requête dessus plantait.
#   - pool_pre_ping=True : un SELECT 1 minimal avant chaque emprunt de connexion au
#     pool ; une connexion morte est discrètement remplacée, invisible pour l'appelant.
#     Léger coût par requête (un aller-retour réseau très court), largement compensé
#     par l'absence d'erreur 500 aléatoire.
#   - pool_recycle=1800 : une connexion n'est de toute façon jamais gardée plus de
#     30 minutes, avant même qu'un pre-ping échoue -- se prémunit contre un timeout
#     serveur/pare-feu plus agressif qu'attendu.
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
