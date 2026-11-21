# Passerelle locale Pixel Clocks

GabeCubeAura 1.6.2-beta.2 est compatible avec Pixel Clocks beta 6 Light en pilotage Automatique. Dans les réglages Faceplate de GCA, le suivi doit être activé et la priorité doit laisser GCA piloter l’écran.

## Parcours Decky

Le panneau compact GCA affiche le contrôle Pixel Clocks après une poignée de main vivante et compatible. Les quatre choix sont exactement `À l’accueil`, `En jeu`, `Les deux`, `Aucun` (identifiants `home`, `game`, `both`, `none`). Les deux panneaux modifient la même référence : les préférences atomiques Home/Game de GCA, avec leur révision.

Sélectionner les deux destinations effectue un seul commit. Avant de prendre une destination, la passerelle mémorise son choix précédent. `Aucun` restaure uniquement les destinations qui pointent encore sur Pixel Clocks ; une modification manuelle ultérieure dans GCA n'est jamais écrasée. Un compagnon absent peut être retiré depuis GCA. Une présence détectée n'active aucune route automatiquement.

Les affectations ordinaires restent lisibles par la stable. Revenir au canal stable réactive ces affectations. Les deux panneaux distinguent choix enregistré, préparation, réception confirmée, réception incertaine, déconnexion et suspension par priorité ou écran éteint.

## Transport local

- Répertoire par défaut : `~/.local/share/gabecubeaura/pixel-clocks` sous `DECKY_USER_HOME` si défini.
- Pour une recette isolée : variable `GCA_PIXEL_CLOCKS_RUNTIME`.
- `control.sock` : socket Unix privé, une requête JSON délimitée par LF par connexion.
- `credential.json` : protocole, version, jeton de capacité, identifiant de démarrage serveur et chemin du socket. Lecture backend uniquement ; ne jamais transmettre le jeton au frontend ou aux diagnostics.
- UID pair vérifié par le noyau, permissions 0700/0600, liens symboliques et objets étrangers refusés ; deux connexions simultanées maximum.
- Version du protocole 1 ; messages de 131 072 octets maximum ; présence expirant après huit secondes sans échange.

Enveloppe :

```json
{
  "protocol": "pixel-clocks-bridge",
  "version": 1,
  "request_id": "identifiant-unique",
  "op": "status",
  "token": "lu-dans-le-fichier-prive",
  "boot_id": "demarrage-serveur-courant",
  "client_boot_id": "demarrage-pixel-clocks-courant",
  "args": {}
}
```

Réponse : `{ "ok": true, "request_id": "…", "boot_id": "…", "result": { … } }`, ou `ok:false` avec `error.code`. Les mutations conservent 64 reçus bornés : même identifiant et même contenu renvoient le même résultat ; réutiliser l'identifiant avec un autre contenu échoue. Une révision périmée est refusée, jamais réappliquée arbitrairement.

| Opération | Arguments |
|---|---|
| `hello` | `models` (identifiants sans graphismes), `selected_model` |
| `status` | `selected_model` facultatif ; renouvelle la présence |
| `set_destinations` | `destination`, `expected_revision` |
| `configure_weather` | `location`, `unit` (`celsius`/`fahrenheit`), `expected_revision`, `expected_weather_revision` |
| `publish` | `expected_revision`, `weather_revision`, `context`, `model`, `display_at`, `end_at`, `sha256`, `gif_base64` |
| `bye` | Aucun ; invalide le producteur et ses paquets sans modifier les préférences |

Un nouveau démarrage serveur invalide les anciennes sessions. Un nouveau démarrage du compagnon doit refaire `hello`. Le statut comprend révisions, routes, destination, contexte, modèle sélectionné, présence, données météo normalisées, âge de la source, SHA accepté et SHA confirmé. `standalone_allowed` reste faux : une panne de liaison ne donne jamais la permission de prendre le port USB.

## Météo

La poignée de main crée un consommateur météo même si le thème météo, la barre supérieure et les routes météo GCA sont désactivés. Aucun de ces réglages n'est forcé. La ville et l'unité restent celles de GCA ; le réglage local du compagnon peut les modifier par `configure_weather`.

Le fournisseur conserve les horaires solaires de la veille, du jour et du lendemain obtenus dans la requête existante (ajout de `past_days=1`). Il choisit le jour courant par la date des conditions, pas par l'indice zéro. Les horloges peuvent ainsi calculer la progression nocturne réelle sans seconde requête indépendante. Un code météo inconnu ne devient pas arbitrairement nuageux ; un échantillon trop ancien ne devient pas du soleil. Les révisions météo invalident les paquets de l'ancienne ville ou unité.

## Paquets minute et propriétaire USB

Le compagnon prépare un GIF fini de 64 × 54, de 32 767 octets maximum en Light, couvrant la minute et une garde d’au plus seize secondes. Le parseur isolé vérifie le LZW, les rectangles, les palettes, l’opacité initiale, chaque délai et le budget de 1 024 images.

GCA conserve son worker et son unique coordinateur série. Les paquets sont rejetés s’ils visent un ancien contexte, une ancienne route, un ancien modèle, une ancienne ville ou une ancienne session. La rotation à 180° conserve les pixels et les délais décodés, avec le même plafond d’octets.

Pendant la préparation d’un GIF et tant que la liaison est active, le worker laisse l’écran courant. Si la liaison expire ou que le dernier GIF confirmé se termine sans remplacement, le worker reprend la scène GCA précédemment choisie pour le contexte. Les destinations Pixel restent enregistrées. Une nouvelle minute valide reprend automatiquement la route Pixel. Les priorités et l’écran éteint restent pris en compte. Le statut distingue `awaiting-packet` pendant la préparation, puis `fallback-route-pending` (ou `fallback-pending` pour l’horloge native) et `fallback-route` si un repli est nécessaire.

Les données sont envoyées avant la frontière de minute ; seule cette nouvelle route peut demander à la couche série d'attendre `display_at` avant `GIF_END`. L'attente contrôle l'annulation toutes les 20 ms. Une priorité, un changement de contexte/route/modèle, un arrêt, une perte de session ou un saut d'horloge annule le commit ; un créneau dépassé de plus de 350 ms est refusé. Ce contrat vise la commande hôte ; le délai physique du firmware reste à mesurer.

Les transferts ordinaires de GCA ne reçoivent pas cette option et gardent leur comportement. Une réception confirmée est distincte de l'acceptation du paquet par le service.

## Vérifications locales

- 16 tests de passerelle, dont des échanges réels sur socket Unix, restauration après redémarrage, CAS/idempotence, changement manuel, retrait après déconnexion, météo et annulation avant commit.
- Vérification indépendante Pillow de la rotation des palettes locales et rectangles partiels : RGB et délais identiques.
- Trois tests du composant livré : grammaire identique, rejet d'un ancien poll après mutation et resynchronisation complète après conflit de révision.
- 196 tests historiques ciblés horloges, météo, routes, runtime, horloge native, protection flash et activation/livraison artwork, arrêt du plugin et budget de fermeture, plus les 16 tests nouveaux (212 au total).
- Typage TypeScript, compilation Rollup et suite frontend existante exécutés localement.

Aucune validation Decky/SteamOS, USB, firmware, luminosité optique ou appareil physique n'est déduite de ces tests. Les tests complets de la paire et les paquets locaux sont vérifiés dans le rapport du dossier parent.
