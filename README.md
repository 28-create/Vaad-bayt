# Vaad Bayt · Version 3.0 (שחראי 14, 16 ו-18)

Application desktop Windows **100 % hors ligne (OFFLINE)** en hébreu RTL pour la gestion d’une caisse commune unique regroupant les immeubles **שחראי 14, 16 et 18** (20 appartements physiques / 21 unités de facturation).

## Lancer, tester et compiler

- **Lancer l’exécutable** : ouvrir `dist\VaadBayt.exe` (autonome : Python, Tk et SQLite embarqués, sans Internet).
- **Lancer depuis les sources** : double-cliquer sur `Lancer.cmd` (ou `python -m vaad`).
- **Exécuter la suite de tests** : `python -m unittest discover -s tests -v`.
- **Reconstruire `dist\VaadBayt.exe`** : exécuter `Build.cmd` (lance les tests puis PyInstaller avec `VaadBayt.spec`).

## Fonctionnalités intégrées (v2.0)

- **Tableau de bord complet** : 8 cartes KPI cliquables (solde caisse, revenus/dépenses du mois, dettes, nombre d’unités payées/impayées, taux de recouvrement, avances), **graphique interactif Revenus vs Dépenses sur 12 mois**, alerte d’échéances récurrentes, mouvements récents et principaux débiteurs.
- **Unités, résidents & fiche personnelle (`כרטסת אישית`)** : ajout/édition d’unités, suivi de l’historique des occupants (`occupants`), solde détaillé avec moyen de paiement, **export Excel (`.xlsx`) / PDF / impression**, et **reçu de paiement numéroté (`אישור תשלום / קבלה`)**.
- **Collecte mensuelle & Import bancaire (`ייבוא תנועות בנק`)** : génération automatique sans doublons (100 ₪ / 50 ₪ pour l’appartement divisé), ajustements/exemptions traçables, **import CSV & Excel (`.xlsx`) bancaire** avec suggestion automatique du résident, validation manuelle avant intégration, prévention des doublons (`bank_imports`) et marquage « non lié au Vaad ».
- **Mouvements, factures jointes & dépenses récurrentes** : pièces jointes (PDF, images, documents) associées aux mouvements et visibles sur la fiche fournisseur, gestion complète des modèles de dépenses récurrentes (création, modification, désactivation, rapprochement résilient aux annulations).
- **Fournisseurs (`ספקים`)** : fiche complète par fournisseur avec historique des paiements (net des annulations), filtre par période et visionneuse de factures jointes.
- **9+ rapports financiers** : solde de caisse mensuel, revenus mensuels, dépenses mensuelles, dettes ouvertes, paiements par unité, dépenses par fournisseur, dépenses par catégorie, bilan annuel, comparaison revenus/dépenses (avec graphique SVG), et journal complet — tous exportables en **Excel (`.xlsx`), PDF, HTML imprimable et CSV**.
- **Utilisateurs, rôles & journal d’audit** : 3 niveaux de permissions (`מנהל ראשי`, `חבר ועד`, `צפייה בלבד`), journal d’audit complet (`audit_log`), verrouillage automatique après inactivité.
- **Sauvegardes complètes & migration** : sauvegardes manuelles et automatiques (avec rotation) au format **ZIP incluant la base SQLite vérifiée + toutes les factures/reçus joints**, historique des sauvegardes, restauration rétrocompatible (`.zip` et `.sqlite3`), et export complet portable (ZIP Excel multi-onglets + pièces jointes).

## Architecture

- `vaad/001.sql`, `vaad/002.sql`, `vaad/003.sql` — migrations SQLite versionnées (schéma v3).
- `vaad/store.py` — SQLite, migrations, authentification `scrypt` & RBAC, journal d’audit, pièces jointes, sauvegardes ZIP & restauration, logging rotatif.
- `vaad/ledger.py` — moteur comptable en *agorot*, unités, occupants, fournisseurs, dépenses récurrentes, séries mensuelles et reçus.
- `vaad/excel.py` — lecteur/générateur `.xlsx` pur Python (zéro dépendance externe) avec support hébreu RTL natif.
- `vaad/banking.py` — parseur de relevés bancaires CSV/XLSX, empreintes anti-doublons et suggestion intelligente de résidents.
- `vaad/reports.py` — rapports HTML RTL professionnels, graphiques SVG, reçus, export PDF natif (Edge/Chrome headless) et archive d’export complet.
- `vaad/ui.py`, `vaad/ui_widgets.py`, `vaad/ui_bank.py`, `vaad/ui_settings.py`, `vaad/theme.py` — interface desktop hébreu RTL modulaire.

Le [guide complet en hébreu](Guide-he.md) détaille l’utilisation quotidienne, les sauvegardes et le transfert vers un nouvel ordinateur.
