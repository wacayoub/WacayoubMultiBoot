# Wacayoub MultiBoot

Gestionnaire multiboot pour Enigma2, inspiré du « Multiboot Manager » d'Octagon (fonctions seulement, code écrit de zéro).
Paquet : `packages/enigma2-plugin-extensions-wmultiboot_1.0.0_all.ipk` (Python 2.7 et 3.x, `Architecture: all`).

Ouverture : Menu Plugins, menu Extensions, ou Menu > Système.

## Fonctions

| Touche | Action |
|---|---|
| OK | Actions du slot : démarrer, démarrer **une seule fois** (retour automatique), installer, sauvegarder, taille, supprimer |
| Vert | Démarrer sur le slot choisi (puis propose de redémarrer) |
| Jaune | Installer une image : **Images en ligne** (OpenATV, OpenPLi, OpenViX, OpenBH, OpenSPA, EGAMI, teamBlue, filtrées pour le modèle détecté), une URL, ou un zip / une sauvegarde `.tar.gz` sur les disques |
| Bleu | Sauvegarder le slot en `.tar.gz` dans `<disque>/WMultiBoot/backups` (restaurable avec Jaune) |
| Rouge | Supprimer un slot |
| MENU | Actualiser, espace disque, journal, aide |

Affichage : nom, version, date de chaque image, slot en cours, prochain démarrage, espace libre des disques.
Polices : Roboto / Liberation / DejaVu si l'image les a, sinon la police `Regular` du skin.

## Sécurité

- L'image en cours n'est jamais écrite, effacée ni supprimée : contrôle par inode (`/`), pas par nom.
- Chaque action vérifie d'abord : espace libre, archive zip (CRC), présence d'un `rootfs.tar.*`, modèle du récepteur
  (dossier `vuplus/<modèle>/` et `box_type` de l'image), noyau du slot. Message clair en cas de refus.
- Extraction dans `<nom>.partial`, renommé seulement si l'image est valide ; nettoyage en cas d'échec ou d'annulation.
- Le slot choisi pour le prochain démarrage ne peut pas être supprimé.
- Toute erreur de l'interface affiche un message au lieu de planter Enigma2 ; journal : `/tmp/wmultiboot.log`.

## Récepteurs et structures pris en charge

Détection automatique, dans cet ordre :

| Structure | Récepteurs | Démarrage | Installation | Comment |
|---|---|---|---|---|
| **eMMC `STARTUP_n`** | GigaBlue 4K, Zgemma H7/H9…, Octagon SF8008/SF8008m (mode 1/12), Edision OS mio, AX/Maxytec, Dinobot, Vu+ 4K en kexec, et toute box OpenATV/OpenPLi « multiboot » | copie `STARTUP_n` → `STARTUP` | dans le dossier `linuxrootfsN` du slot + noyau (`dd` sur la partition, ou fichier pour kexec) | partition de démarrage trouvée par label (`boot`, `bootoptions`) ou parmi `mmcblk0p1/3/4`, `mmcblk1p1` |
| **HDD/USB (omb-init)** | Vu+ 4K sans kexec (**Vu+ Zero 4K testé**), toute box où `/sbin/init` → `omb-init` | `etc/omb/boot.conf` sur la flash, option « une seule fois » | nouveau slot dans `<disque>/OnlineMultiBoot/images/` (ext4) | compatible avec le plugin OnlineMultiBoot ; lit aussi `open-multiboot/`, `ImageBoot/` |
| **OpenMultiboot classique** | anciennes Vu+/MIPS avec `open_multiboot` | `.<box>-selected` | nouveau slot + `.kernels/<nom>.bin` | |
| **Dreambox** | DM900/920, One/Two | menu Dreambox | — | affichage + sauvegarde |
| **Sans multiboot / inconnu** | toute autre box | — | — | affichage + sauvegarde, aucun plantage |

Testé en vrai : Vu+ Zero 4K, OpenATV 8.0.1 (structure omb-init). Les structures STARTUP et OpenMultiboot sont testées
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
