-- =============================================================================
-- VUSINE -- params.sql
-- Données de référence -- à jouer APRÈS schema.sql sur une base fraîche.
-- Fusionne 02_auth_seed_data.sql (départements, seuils, compte admin) + les données
-- qui étaient embarquées dans les anciens fichiers DDL (sections Odoo, causes d'arrêt,
-- poste par défaut). Rejouable sans risque (ON CONFLICT DO NOTHING / DO UPDATE).
-- =============================================================================

-- --- Départements -----------------------------------------------------------------
INSERT INTO departements (id, name) VALUES
    (1, 'Direction'),
    (2, 'Ventes Export'),
    (3, 'Ventes Import'),
    (4, 'Transit'),
    (5, 'Achats'),
    (6, 'Fabrication'),
    (7, 'Comptabilité'),
    (8, 'Autres')
ON CONFLICT (id) DO NOTHING;

SELECT setval('departements_id_seq', (SELECT COALESCE(MAX(id), 1) FROM departements));

-- --- Paramètres (seuils performance, scoring) --------------------------------------
INSERT INTO params (key, value) VALUES
    ('seuil_vert_pct', '95'),
    ('seuil_orange_pct', '80'),
    ('seuil_silence_scan_minutes', '30'),
    ('duree_demarrage_min', '10'),
    -- *** AJOUT 2026-09-24 (coût des pertes, Palier 0) *** : valeur par défaut d'une pièce
    -- en FCFA, utilisée quand un produit n'a pas de valeur propre. 0 = non configurée :
    -- les coûts s'affichent « n/d » plutôt qu'un chiffre inventé. Le libellé dit ce que
    -- cette valeur représente (prix de vente, coût de revient, marge...) et est repris
    -- tel quel dans les écrans et exports.
    ('valeur_piece_defaut_fcfa', '0'),
    ('libelle_valeur_piece', 'Prix de vente unitaire'),
    -- *** AJOUT 2026-09-24 (Palier 1) *** : temps de marche minimal (minutes) avant
    -- d'afficher la prévision de fin de poste (projection linéaire).
    ('prevision_delai_min', '60'),
    -- *** AJOUT 2026-09-24 (Palier 1) *** : cible de TRS (%) affichée comme repère dans
    -- Rapports > TRS. 85 % est la référence « classe mondiale » usuelle -- à adapter.
    ('trs_cible_pct', '85'),
    -- *** AJOUT 2026-09-24 (Palier 1) *** : changements de série (SMED). Objectif en minutes
    -- (0 = pas d'objectif, aucun changement n'est alors marqué « dépassé »), et libellé de la
    -- cause d'arrêt qui désigne un changement de série sur la tablette.
    ('smed_objectif_min', '0'),
    ('cause_changement_produit', 'Changement produit'),
    -- *** AJOUT 2026-09-24 (Palier 1) *** : rapport matinal. Heure d'envoi (HH:MM) et jours de
    -- la semaine (1 = lundi ... 7 = dimanche). L'activation du job est dans .env
    -- (RAPPORT_MATINAL_ENABLED), pas ici.
    ('rapport_matinal_heure', '07:00'),
    ('rapport_matinal_jours', '1,2,3,4,5,6'),
    -- *** AJOUT 2026-09-24 (Palier 2) *** : scoring d'équipe. Sous cet effectif (personnes
    -- distinctes affectées à la ligne sur la période), le score de la ligne est MASQUÉ : une
    -- équipe d'une ou deux personnes identifierait quelqu'un. 0 = pas de masquage.
    ('scoring_equipe_effectif_min', '0'),
    -- *** AJOUT 2026-09-24 *** : nombre minimal de palettes sur la période pour que TRS et score
    -- d'équipe soient jugés représentatifs. En dessous, les écrans grisent les pourcentages
    -- (adoption des scans insuffisante, pas une vraie contre-performance).
    ('donnees_min_palettes', '10')
ON CONFLICT (key) DO NOTHING;

-- --- Comptes utilisateurs ----------------------------------------------------------
-- *** MODIFIÉ 2026-09-24 *** : plus AUCUN compte ni hash de mot de passe dans ce
-- fichier (il était versionné avec un hash bcrypt réel, un email et un téléphone
-- personnels). Le premier compte administrateur se crée avec un mot de passe saisi au
-- moment voulu, jamais écrit dans un fichier :
--     cd backend && python3 -m scripts.create_admin
-- reset_vusinedb_dev.sh l'appelle automatiquement à la fin du reset.

-- --- Sections Odoo (product.section) -- 28 sections capturées le 18/09/2026 -------
-- Une base fraîche a ainsi tout de suite les bons noms/codes, sans attendre le
-- premier passage ETL. Le prochain run_vusine_sync confirmera/mettra à jour ces mêmes
-- valeurs (sync_sections) -- aucun conflit.
INSERT INTO sections_cache (id, code, nom) VALUES
    (1, 'CLA', 'CLARIFIANT'), (2, 'DEN', 'DENTIFRICE'), (3, 'DIV', 'DIVERS'),
    (4, 'DEF', 'DEFRISANT'), (5, 'EMB', 'EMBALLAGE'), (6, 'ENT', 'Entretien'),
    (7, 'ETQ', 'Etiquettage'), (8, 'HYD', 'HYDRATANT'), (9, 'LAB', 'LABO'),
    (10, 'MEC', 'Mecanique'), (11, 'MI', 'Moules ( injection )'),
    (12, 'MMP', 'Magasin Matière Première'), (13, 'MP', 'Moule PET'),
    (14, 'MPF', 'MAGASIN PRODUIT FINI'), (15, 'MPP', 'MAGASIN MATIERE PREMIERE PLAS'),
    (16, 'MS', 'Moules soufflage'), (17, 'PAR', 'PARFUM'),
    (18, 'PI', 'Pièces détachées Injection'), (19, 'POM', 'POMMADE'),
    (20, 'PS', 'Pièces détachées Soufflage'), (21, 'PSG', 'PESAGE'),
    (22, 'RAV', 'Ravitaillement'), (23, 'SAV', 'SAVON'), (24, 'SER', 'Serigraphie'),
    (25, 'TAL', 'TALC'), (26, 'VTE', 'VENTES'), (27, 'MAN', 'MANCHONNAGE'),
    (28, 'FAB', 'FABRICATION')
ON CONFLICT (id) DO UPDATE SET code = EXCLUDED.code, nom = EXCLUDED.nom, synced_at = CURRENT_TIMESTAMP;

-- --- Causes d'arrêt (menu déroulant tablette, CDC slide 12) ------------------------
INSERT INTO causes_arret (libelle, ordre_affichage) VALUES
    ('Panne machine', 1),
    ('Réglage', 2),
    ('Changement produit', 3),
    ('Nettoyage', 4),
    ('Manque MP', 5),
    ('Manque emballage', 6),
    ('Contrôle qualité', 7),
    ('Manque personnel', 8),
    ('Attente maintenance', 9),
    ('Autre', 10)
ON CONFLICT (libelle) DO NOTHING;

-- --- Poste de travail par défaut ----------------------------------------------------
INSERT INTO configuration_poste (id, nom, heure_debut, heure_fin, pause_debut, pause_fin, actif)
VALUES (1, 'Poste unique', '07:30:00', '17:00:00', '12:30:00', '13:30:00', true)
ON CONFLICT (id) DO NOTHING;

SELECT setval('configuration_poste_id_seq', (SELECT COALESCE(MAX(id), 1) FROM configuration_poste));
