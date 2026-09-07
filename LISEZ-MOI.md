# Vigilance PACA · Occitanie — app auto-mise à jour

## ▶ Voir l'app tout de suite (sans rien installer)
Dézippe le dossier et **double-clique sur `demo.html`** : l'écran s'ouvre dans ton
navigateur avec des alertes d'exemple (dont les types : orages, crues, canicule...).
C'est juste pour voir le rendu — les données ne sont pas réelles.

Pour l'app **réelle et auto-mise à jour**, installée sur Android, suis la mise en
place ci-dessous (une seule fois).

Tu ouvres l'app → elle affiche les **vrais niveaux de vigilance du jour** pour les
19 départements de PACA et Occitanie, et tu vois immédiatement s'il faut envoyer
des instructions. Aucune saisie manuelle.

## Comment ça marche
- Un **robot** (GitHub Actions, gratuit) récupère les niveaux **toutes les heures**
  depuis les données publiques Météo-France et écrit un fichier `vigilance.json`.
- L'**app** lit ce fichier à chaque ouverture (et quand tu la remets au premier plan).
- Le bouton **« Générer l'e-mail équipes »** s'active dès qu'un département est en
  jaune/orange/rouge et pré-remplit le mail (avec un emplacement `[À COMPLÉTER]`
  pour tes instructions, que tu me donneras).

## Contenu du dossier
```
index.html                       <- l'app
manifest.webmanifest, sw.js      <- installation Android + hors-ligne
icon-*.png                       <- icônes
scripts/build_vigilance.py       <- le robot (récupère la vigilance)
.github/workflows/vigilance.yml  <- planificateur (toutes les heures)
```

## Mise en place (~10 min, une seule fois)

1. **Crée un dépôt GitHub public** (ex. `vigilance-pacao`). Public = Actions et
   Pages gratuits et illimités.
2. **Dépose tout le contenu de ce dossier** à la racine du dépôt (garde bien les
   sous-dossiers `scripts/` et `.github/`).
3. **Autorise le robot à écrire** : Settings -> Actions -> General ->
   *Workflow permissions* -> coche **« Read and write permissions »** -> Save.
   (Sans ça, le robot ne pourra pas publier `vigilance.json`.)
4. **Lance le robot une première fois** : onglet **Actions** -> *Mise a jour
   vigilance* -> **Run workflow**. Ça crée `vigilance.json`. Ensuite il tourne seul
   toutes les heures.
5. **Active le site** : Settings -> Pages -> Source : branche `main`, dossier `/root`
   -> Save. GitHub affiche l'URL `https://<toncompte>.github.io/vigilance-pacao/`.
6. **Installe sur Android** : ouvre cette URL dans Chrome -> menu ⋮ ->
   **Ajouter à l'écran d'accueil**. L'icône se comporte comme une app.

> Les horaires de GitHub Actions peuvent avoir quelques minutes de décalage, sans
> impact ici. Le robot ne « commit » que lorsqu'un niveau change.

## Vérifier / dépanner
- Après le 1er *Run workflow*, ouvre les logs de l'Action : la ligne `[schema] ...`
  montre les champs détectés et `[ok] vigilance.json écrit — N département(s)...`.
- Si tu vois `[ERREUR] champs non identifiés`, copie-moi l'exemple de record affiché
  dans les logs : j'ajuste le robot en une ligne.
- Dans l'app, la mention en bas indique la source et l'heure de mise à jour, ou
  « Hors ligne » si le fichier n'est pas encore là.

## Phase 2 — envoi automatique de l'e-mail (optionnel)
Ton besoin (« ouvrir et savoir ») est déjà couvert ci-dessus. Si tu veux en plus que
le mail parte **tout seul**, le même robot peut l'envoyer quand un département >= jaune :
il faudra ton texte d'instructions + un accès e-mail (SMTP, via *Secrets* GitHub).
Envoie-moi le contenu du mail et je te livre cette partie.


## Voir le type d'alerte (vent, crues, orages...)
Dès qu'un département est **orange ou rouge**, la tuile affiche directement les
phénomènes concernés (ex. « Orages », « Crues », « Vent violent »), chacun avec la
couleur de son propre niveau. Un appui sur la tuile ouvre le détail complet
(tous les phénomènes + leur niveau), et l'e-mail généré liste aussi ces types.

Le fichier `vigilance.sample.json` est un **exemple** : renomme-le en
`vigilance.json` (ou ouvre-le tel quel) si tu veux prévisualiser le rendu avant que
le robot ne tourne. Le robot l'écrasera ensuite avec les vraies données.

## Réglages dans l'app
- **⚙︎ Réglages -> adresse e-mail destinataire** : pour pré-remplir le mail.
- **URL des données** : à laisser vide (l'app lit `vigilance.json` à côté d'elle).
- Tu peux toujours forcer un niveau à la main (appui sur une tuile) ; la prochaine
  actualisation reprend les données réelles.
