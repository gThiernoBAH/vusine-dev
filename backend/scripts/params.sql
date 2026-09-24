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
    ('duree_demarrage_min', '10')
ON CONFLICT (key) DO NOTHING;

-- --- Compte admin de production -----------------------------------------------------
-- Mot de passe hashé -- identique à celui utilisé jusqu'ici (même hash). Ajuster
-- is_super_admin à la main ensuite si ce compte doit avoir accès au Labo :
--   UPDATE users SET is_super_admin = true WHERE username = 'admin';
INSERT INTO users (
    id, username, matricule, password_hash, nom, email, telephone, user_type,
    categorie_personnel, is_active, is_admin, is_super_admin, departement_id
) VALUES (
    1, 'admin', '3318', '$2b$12$yWxhW8.h25AUVWpipO8vOesuCuPryIh0drMS2W0IoypikqbG.45kC',
    'Admin', 'g.thiernobah@gmail.com', '0708625708', 'direction',
    'CDI', true, true, true, 1),
    (2, 'directeur', '1111', '$2b$12$yWxhW8.h25AUVWpipO8vOesuCuPryIh0drMS2W0IoypikqbG.45kC',
    'Directeur', NULL, NULL, 'direction',
    'CDI', true, true, false, 1)    
ON CONFLICT (id) DO NOTHING;
-- *** CORRIGÉ 2026-09-23 *** : email/téléphone du compte 'directeur' passés de '' à NULL.
-- Un email vide ('') faisait échouer GET /auth/users (erreur 500 : UserResponse
-- validait l'email et refusait la chaîne vide) -> écran Personnel inutilisable.

SELECT setval('users_id_seq', (SELECT COALESCE(MAX(id), 1) FROM users));

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
