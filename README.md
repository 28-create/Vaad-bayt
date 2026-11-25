# Vaad Bayt · Phase 1

Application Windows locale de gestion d’une caisse commune pour שחריי 14, 16 et 18.

## Lancer et reconstruire

Ouvrir `dist\VaadBayt.exe`. L’exécutable embarque Python, Tk et SQLite. Il fonctionne sans connexion Internet. Pour lancer les sources avec Python 3.14 et Tk installés, ouvrir `Lancer.cmd`. Pour reconstruire l’exécutable depuis les sources, installer PyInstaller dans l’environnement de développement puis lancer `Build.cmd`.

Exécuter les tests avec `py -3 -m unittest discover -s tests -v`. Les tests utilisent des bases temporaires.

## Organisation et modèle de données

- `vaad/store.py` ouvre SQLite, applique le schéma versionné, gère l’authentification locale et utilise l’API SQLite de sauvegarde.
- `vaad/001.sql` crée les tables `buildings`, `units`, `unit_status`, `fee_rates`, `categories`, `settings` et `entries`. SQLite vérifie les clés étrangères et l’unicité des cotisations.
- `vaad/ledger.py` gère l’historique des tarifs et des statuts, la génération mensuelle, les écritures et le calcul des soldes.
- `vaad/ui.py` fournit l’assistant et les six rubriques hébraïques. Les rapports imprimables s’ouvrent dans le navigateur sous forme de fichiers HTML locaux.
- `tests/test_finance.py` couvre les scénarios comptables, la sauvegarde, la restauration et l’authentification.

Les écritures enregistrent indépendamment le débit du compte de l’unité et le montant encaissé ou décaissé en agorot. Pour un paiement, ces deux valeurs appartiennent à la même ligne SQLite. Les affectations sont recalculées à partir du journal, en commençant par la dette d’ouverture puis par les cotisations les plus anciennes. Les annulations conservent leur propre date comptable, leur motif et le lien vers l’opération d’origine. Une annulation datée après la clôture du mois d’origine apparaît dans la période de sa propre date.

Les cotisations sont générées à l’ouverture de la session et le changement de mois est détecté pendant son utilisation. Pour un début en cours de mois, l’application génère une cotisation entière à la date de démarrage. Les changements de tarif et de statut sont appliqués au moment de générer la cotisation d’un mois, à partir du tarif et du statut applicables au premier jour du mois ou à la date de démarrage pour le premier mois. Les corrections de cotisation saisies aujourd’hui révisent le montant du mois sélectionné, avec une ligne distincte datée d’aujourd’hui dans la fiche de l’unité.

Les données sont conservées sous `%LOCALAPPDATA%\VaadBayt`. Le mot de passe est protégé par scrypt avec un sel aléatoire. Le fichier SQLite et ses sauvegardes sont lisibles par une personne disposant d’un accès à ces fichiers. Utiliser les permissions Windows et un espace de stockage protégé.

## Fonctionnalités et limites

La version comprend la configuration des 21 unités, les fiches des résidents, les cotisations, les paiements, les avances, les dépenses, les recettes, la caisse commune, les corrections traçables, les rapports, le CSV, le verrouillage, la sauvegarde et la restauration locale.

Les numéros non renseignés restent à identifier dans les fiches. Les soldes appartiennent aux unités, et l’application ne gère pas de sous-comptes individuels par occupant. Le passage d’un solde négatif à positif dans une fiche représente un changement d’avance en dette. Les exigences reportées en phase 2, dont la synchronisation, les reçus officiels et l’import bancaire, restent hors périmètre.

Le [guide en hébreu](Guide-he.md) décrit les opérations quotidiennes et le transfert vers un nouvel ordinateur.

