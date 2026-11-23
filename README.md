# Wacayoub MultiBoot

Gestionnaire multiboot pour Enigma2, inspiré du « Multiboot Manager » d'Octagon (fonctions seulement, code écrit de zéro).
Paquet : `packages/enigma2-plugin-extensions-wmultiboot_1.5.0_all.ipk` (Python 2.7 et 3.x, `Architecture: all`).

Ouverture : Menu Plugins, menu Extensions, ou Menu > Système.

## Nouveautés 1.5.0
- **Plugins au choix** : à la sauvegarde et à la restauration, une liste de tous les plugins installés
  (type, version, taille) ; on coche exactement ceux à garder. Ceux déjà installés dans l'image cible sont décochés.
- **Plugins hors feed** (vos plugins GitHub, Wacayoub Panel, BOP 2…) : recréés en `.ipk` depuis les fichiers
  installés et rangés dans la sauvegarde (`wmb-ipk/`). Seuls les fichiers de plugin sont pris
  (`usr/lib/enigma2`, `usr/share/enigma2`, polices, `etc/enigma2`, picons) : jamais de scripts de démarrage ni de binaires.
- **Mettre à jour (tout garder)** (MENU ou OK sur une image) : trouve la dernière version stable de la même
  distribution (pastille NOUVEAU / À JOUR), ou une autre image en ligne / un zip. Étapes : sauvegarde des éléments
  choisis, installation dans un **nouveau** slot, restauration de tout dedans, copie de Wacayoub MultiBoot,
  plugins programmés pour le premier démarrage. L'ancienne image n'est jamais modifiée ; ensuite
  « Démarrer une fois pour tester » (conseillé) ou « définitivement ».
- **Premier démarrage** : `/etc/rc3.d/S98wmbfirstboot` (avant Enigma2) installe les plugins depuis le feed, sinon
  depuis le `.ipk` sauvegardé, avec des limites de temps, remet ensuite les réglages restaurés par-dessus ceux des
  paquets, et s'efface. Un message résume le résultat au démarrage d'Enigma2.
- Restaurer des plugins dans une autre image fonctionne maintenant (via ce même premier démarrage).
- 28 tests sur la box (nouveaux : outils plugins, `.ipk` accepté par opkg, script du premier démarrage avec faux opkg,
  recherche de mise à jour, mise à jour complète et annulation).

## Nouveautés 1.4.0

- Boutons de couleur redessinés : vrais boutons arrondis avec icône (Supprimer, Démarrer, Installer, Sauvegarder,
  Menu) ; un bouton disparaît si l'action n'est pas possible sur le récepteur.
- MENU : grille de 8 tuiles avec icônes (Restaurer, Sauvegarder, Installer, Sauvegardes, Espace disque, Actualiser,
  Aide, Journal), navigation avec les flèches.
- Bas de chaque liste : pastilles OK / EXIT / vert / jaune au lieu du texte.
- Leçon : OpenATV exécute comme du code tout ce qui n'est pas une méthode dans onLayoutFinish/onShown ; un lambda y
  fait échouer l'ouverture de l'écran. tests/check_screen_names.py le vérifie maintenant.

## Nouveautés 1.3.2

- EGAMI : leur liste publique ne contient que certaines marques (Zgemma, Dreambox, HD51, Novaler…). Pour les Vu+,
  les images sont réservées aux donateurs (pages Vu+ sans lien sur image.egami-image.com). Le plugin l'explique et
  indique la marche à suivre : télécharger le zip avec un compte donateur, le copier dans <disque>/images, touche JAUNE.

## Nouveautés 1.3.1

- Images en ligne : ajout de **Neutrino (NI)** (neutrino-images.de, nightly + release, lu depuis la liste du dossier).
  Neutrino n'est pas Enigma2 : il démarre en multiboot comme les autres, mais sans vos plugins Enigma2.
- Les distributions sans image pour votre récepteur (EGAMI, teamBlue, OpenHDF…) apparaissent grisées « VIDE ».
- Pas ajoutées (pas de liste publique utilisable) : HD Satelit (seulement Amiko Viper 4K), TNAP (pas de Vu+),
  PKT Hyperion (abandonné), BPanther Neutrino (refuse les téléchargements automatiques, erreur 403),
  VTi (compte forum nécessaire). Elles restent installables avec « Adresse internet (URL) » ou un fichier zip.

## Nouveautés 1.3.0

- Sauvegarder et Restaurer sont séparés :
  - **BLEU = Sauvegarder** (création seulement) : « Choisir quoi sauvegarder… » ou « Image complète ».
  - **MENU → Restaurer une sauvegarde** : image d'origine → date → éléments à cocher → image de destination → confirmation.
    Aussi dans le menu OK d'une image : « Restaurer une sauvegarde dans cette image » (la destination est déjà choisie).
  - **MENU → Gérer les sauvegardes** : voir le contenu, supprimer.

## Nouveautés 1.2.x

- 1.2.1 : sauvegardes groupées par image (logo, nombre, date, taille) ; « Sauvegardes de cette image » dans le menu OK ;
  l'étape « calcul de la taille » s'annule aussi tout de suite.


- Sauvegarde « choisir quoi » : cases à cocher avec la taille de chaque élément — chaînes et favoris, satellites,
  réglages Enigma2, réglages des plugins, liste des plugins installés, softcam (identifiants), réseau (mot de passe
  Wi-Fi), picons. Chaque sauvegarde contient un manifeste (image, date, contenu).
- Restauration « choisir quoi et où » : le plugin affiche le contenu de la sauvegarde, vous cochez les éléments,
  puis vous choisissez l'image : une autre image (écriture directe) ou l'image en cours (sauvegarde de sécurité
  automatique, puis redémarrage de l'interface). La liste des plugins est réinstallée depuis le feed.
- Jamais restaurés, même s'ils sont dans l'archive : scripts de démarrage (/etc/init.d, rc*, rc.local), crontab,
  passwd/shadow, clés SSH/dropbear, programmes (/usr/bin, /lib…), liens vers l'extérieur, chemins avec « .. ».
- EXIT annule tout de suite (sans question) : le travail en cours est arrêté et les fichiers partiels supprimés.

## Nouveautés 1.1.x

- 1.1.1 : PurE2, OpenDroid, OpenVision et OpenHDF dans les images en ligne ; catalogues lus en parallèle (2-3 s).

- Interface moderne : logo de chaque image (tuiles OpenATV, OpenPLi, OpenViX, OpenBH, OpenSPA, EGAMI…), icônes Lucide,
  pastilles d'état (EN COURS, PROCHAIN DÉMARRAGE, UNE FOIS, VIDE), menus en plein écran avec icônes.
  Les logos sont des tuiles dessinées par nous (couleur + nom court), pas les logos officiels.
- Espace disque : place restante et « place pour environ N nouvelles images » (~800 Mo par image), affichés partout ;
  refus clair s'il faut libérer de la place.
- Sauvegardes (touche BLEUE) : sauvegarde complète d'une image, sauvegarde « réglages et chaînes » seule, liste des
  sauvegardes, restauration comme nouvelle image, restauration des réglages dans une autre image, suppression.
- Plus simple : après une installation, le plugin propose de copier vos chaînes et favoris dans la nouvelle image,
  puis de démarrer dessus une fois pour l'essayer. Une ligne d'aide en bas change selon l'image choisie.

## Fonctions

| Touche | Action |
|---|---|
| OK | Actions du slot : démarrer, démarrer **une seule fois** (retour automatique sur l'image d'avant), installer, sauvegarder, taille, supprimer |
| Vert | Démarrer sur le slot choisi (puis propose de redémarrer) |
| Jaune | Installer une image : **Images en ligne** (OpenATV, OpenPLi, OpenViX, OpenBH, OpenSPA, PurE2, OpenDroid, OpenVision, OpenHDF, EGAMI, teamBlue, filtrées pour le modèle détecté), une URL, ou un zip / une sauvegarde `.tar.gz` sur les disques |
| Bleu | Sauvegarder : choisir quoi, ou l'image complète (`<disque>/WMultiBoot/backups`) |
| MENU | Restaurer une sauvegarde, gérer les sauvegardes (voir, supprimer), espace disque, aide |
| Rouge | Supprimer un slot |

Affichage : nom, version, date de chaque image, slot en cours, prochain démarrage, espace libre des disques.
Polices : Roboto / Liberation / DejaVu si l'image les a, sinon la police `Regular` du skin.

## Sécurité

- L'image en cours n'est jamais écrite, effacée ni supprimée : contrôle par inode (`/`), pas par nom.
- Chaque action vérifie d'abord : espace libre, archive zip (CRC), présence d'un `rootfs.tar.*`, modèle du récepteur
  (dossier `vuplus/<modèle>/` et `box_type` de l'image), noyau du slot. Message clair en cas de refus.
- Extraction dans `<nom>.partial`, renommé seulement si l'image est valide ; nettoyage en cas d'échec ou d'annulation.
- Le slot choisi pour le prochain démarrage ne peut pas être supprimé.
- Toute erreur de l'interface affiche un message au lieu de planter Enigma2 ; journal : `/tmp/wmultiboot.log`.

## Démarrage « une seule fois » (HDD/USB)

Le plugin écrit `ONCE=1` dans `boot.conf` et dépose dans l'image choisie un petit script `/etc/rcS.d/S99wmbreturn`
qui remet l'ancien choix de démarrage puis s'efface. Si ce script ne peut pas tourner, omb-init renvoie de toute façon
sur la flash : la box ne reste jamais bloquée.

## Récepteurs et structures pris en charge

Détection automatique, dans cet ordre :

| Structure | Récepteurs | Démarrage | Installation | Comment |
|---|---|---|---|---|
| **eMMC `STARTUP_n`** | GigaBlue 4K, Zgemma H7/H9…, Octagon SF8008/SF8008m (mode 1/12), Edision OS mio, AX/Maxytec, Dinobot, Vu+ 4K en kexec, et toute box OpenATV/OpenPLi « multiboot » | copie `STARTUP_n` → `STARTUP` | dans le dossier `linuxrootfsN` du slot + noyau (`dd` sur la partition, ou fichier pour kexec) | partition de démarrage trouvée par label (`boot`, `bootoptions`) ou parmi `mmcblk0p1/3/4`, `mmcblk1p1` |
| **HDD/USB (omb-init)** | Vu+ 4K sans kexec (**Vu+ Zero 4K testé**), toute box où `/sbin/init` → `omb-init` | `etc/omb/boot.conf` sur la flash, option « une seule fois » | nouveau slot dans `<disque>/OnlineMultiBoot/images/` (ext4) | compatible avec le plugin OnlineMultiBoot ; lit aussi `open-multiboot/`, `ImageBoot/` |
| **OpenMultiboot classique** | anciennes Vu+/MIPS avec `open_multiboot` | `.<box>-selected` | nouveau slot + `.kernels/<nom>.bin` | |
| **Dreambox** | DM900/920, One/Two | menu Dreambox | — | affichage + sauvegarde |
| **Sans multiboot / inconnu** | toute autre box | — | — | affichage + sauvegarde, aucun plantage |

Testé en vrai : Vu+ Zero 4K, OpenATV 8.0.1 (structure omb-init) — image OpenPLi 9.2 téléchargée depuis la liste en ligne,
installée sur le HDD, démarrée « une seule fois », puis retour automatique sur OpenATV 8.0.1 (22/11/2026). Les structures STARTUP et OpenMultiboot sont testées
sur des données simulées (`tests/box_tests.py`), pas encore sur une vraie GigaBlue/Octagon/Zgemma.

## Tests

- `tests/box_tests.py` (sur la box) : 21 tests — détection, protections du slot en cours, installation/sauvegarde/restauration/suppression
  sur un disque de test virtuel, zip corrompu, zip tronqué, CRC faux, rootfs corrompu, zip sans rootfs, image UBI,
  mauvaise box, disque plein (avant et pendant l'extraction), sauvegarde sur disque plein, annulation, URL invalides,
  box inconnue, aucun multiboot / aucun slot, structures STARTUP et OpenMultiboot simulées, catalogue en ligne.
- `tests/check_screen_names.py` (sur la box) : refuse les noms qui écrasent ceux de la classe `Screen` d'Enigma2
  (un méthode `shown` provoquait un plantage, corrigé).
- `tests/WMBTestHook` : petit plugin de test pour ouvrir l'écran à distance (installé seulement pendant les tests).
- Captures : `screenshots/`.

```
scp -O tests/box_tests.py src/WMultiBoot/core.py vu:/tmp/
ssh vu python3 /tmp/box_tests.py /tmp/core.py
```

## Construire

```
python tools/build.py      # -> packages/enigma2-plugin-extensions-wmultiboot_<version>_all.ipk
```
