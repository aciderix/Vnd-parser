# Format VND - Visual Novel Data (Sopra Multimedia)

Documentation du reverse engineering du format binaire VND utilisé dans Europeo.

## Vue d'ensemble

Les fichiers `.vnd` contiennent toute la logique du jeu :
- Scènes (backgrounds)
- Hotspots (zones interactives)
- Variables et conditions
- Navigation entre scènes

**Résolution du jeu** : 640x480 pixels (dont 80px pour la barre d'outils en bas)

---

## Types de Records Découverts

| Type (hex) | Type (dec) | Description |
|------------|------------|-------------|
| 0x26 | 38 | Texte de hotspot |
| 0x27 | 39 | Définition de police |
| 0x69 | 105 | Polygone cliquable |
| 0x15 | 21 | Condition/Action |

---

## Structure d'un Hotspot Complet

Dans le fichier binaire, un hotspot est composé de plusieurs records séquentiels :

```
[VIDEO]     → fichier.avi (optionnel)
[FONT]      → "18 0 #000000 Comic sans MS"
[HOTSPOT]   → "X Y 125 365 layer Texte"
[CONDITIONS]→ "variable < 0 then action"
[POLYGON]   → type=0x69, count, [(x,y), ...]
```

### Record HOTSPOT (type 0x26)
```
Format: "X Y 125 365 layer Texte"

Exemple: "57 60 125 365 0 La bibliothèque"
         │  │  │   │   │  └── Texte affiché au survol
         │  │  │   │   └── Layer (0 = normal)
         │  │  │   └── Constante (hauteur ligne?)
         │  │  └── Constante (largeur max?)
         │  └── Position Y du texte
         └── Position X du texte
```

**IMPORTANT** : X et Y sont la position d'AFFICHAGE du texte, PAS la zone cliquable !

### Record POLYGON (type 0x69)
```
Structure binaire:
┌──────────────┬──────────────┬─────────────────────────┐
│ Type (4 oct) │ Count (4 oct)│ Points (count × 8 oct)  │
│    0x69      │      N       │ x1,y1,x2,y2,...,xN,yN   │
└──────────────┴──────────────┴─────────────────────────┘

Chaque point: int32 X + int32 Y (little-endian)
```

---

## Les 2 Types de Hotspots

### Type 1 : Hotspots AVEC Polygones (134 dans Euroland)

**Usage** : Zones complexes sur les cartes (bâtiments, personnages)

```
┌────────────────────────────────────────────────────────────┐
│  CARTE D'EUROLAND (face.bmp)                               │
│                                                            │
│         "La bibliothèque"  ← Texte à (57, 60)              │
│              ↓                                             │
│         ┌─────────┐                                        │
│         │ ░░░░░░░ │  ← Polygone 7 points                   │
│         │ ░BIBLI░ │    Zone: (35,120) → (189,267)          │
│         │ ░░░░░░░ │    = forme réelle du bâtiment          │
│         └─────────┘                                        │
│                                                            │
│   ┌───────────────┐                     ┌──────────┐       │
│   │    MAISON     │  "Ma maison"        │  BANQUE  │       │
│   │   ░░░░░░░░░   │  Texte: (89,375)    │ ░░░░░░░░ │       │
│   │   ░░░░░░░░░   │  Poly: (1,192)→     │ ░░░░░░░░ │       │
│   └───────────────┘       (149,395)     └──────────┘       │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

**Exemple concret - "La banque"** :
- Texte affiché à : (387, 351) - en bas à droite
- Zone cliquable : Polygone 13 points, bbox (389,150)→(639,374)
- Action : Jouer `bankbis.avi` puis entrer dans la banque

### Type 2 : Hotspots SANS Polygones (~1400 dans Euroland)

**Usage** : Objets dans les scènes, éléments d'interface

Ces hotspots utilisent des **images rollover** pour définir leur zone cliquable.

```
┌────────────────────────────────────────────────────────────┐
│  BUREAU DU BANQUIER (bureaubanquier.bmp)                   │
│                                                            │
│    ┌─────────┐  ┌─────────┐  ┌─────────┐                  │
│    │ AGENDA  │  │  CAFÉ   │  │  ENCRE  │  ← Images        │
│    │ ░░░░░░░ │  │ ░░░░░░░ │  │ ░░░░░░░ │    rollover      │
│    └─────────┘  └─────────┘  └─────────┘                  │
│         │                                                  │
│         └─── coffre.bmp (47KB) positionné à (0, 203)      │
│              La zone cliquable = dimensions de l'image     │
│                                                            │
│    Au survol de l'agenda:                                  │
│    ┌──────────────────────────────────────┐               │
│    │ "L'agenda du banquier"  ← Texte à (40, 350)          │
│    └──────────────────────────────────────┘               │
│                                                            │
│    ┌──────────────────────────┐                           │
│    │        SORTIE            │  ← Bouton                 │
│    └──────────────────────────┘    Action: goto scene 54  │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

## Images Rollover

Les images rollover sont des sprites placés sur le fond de scène.

### Commande `addbmp`
```
addbmp NAME path.bmp layer X Y

Exemple: addbmp coffre euroland\rollover\coffre.bmp 0 0 203
         │      │      │                            │ │  └─ Position Y
         │      │      │                            │ └─ Position X
         │      │      │                            └─ Layer
         │      │      └─ Chemin vers l'image
         │      └─ Nom de référence
         └─ Commande
```

### Types d'images rollover

| Préfixe | Signification | Exemple |
|---------|---------------|---------|
| `det*` | Détail visible | `detcal.bmp` (calculette visible) |
| `abs*` | Absent/caché | `abscal.bmp` (calculette absente) |
| `roll*` | État survol | Image qui change au hover |

### Zone cliquable
La zone cliquable = rectangle de l'image :
```
Position: (X, Y) depuis addbmp
Taille: dimensions du fichier .bmp
Zone: (X, Y) → (X + width, Y + height)
```

---

## Barre d'Outils (Inventaire)

Position Y >= 400 = barre d'outils (80px en bas de l'écran 640x480)

```
┌────────────────────────────────────────────────────────────┐
│                    ZONE DE JEU (400px)                     │
├────────────────────────────────────────────────────────────┤
│ [ACTIVE] [CALC] [TELEP] [SAC] [INFO] [FIOLE]              │
│  (163)   (246)   (316)  (384)  (452)   (197)              │
│                                                            │
│  Layer 6 = toujours au-dessus                             │
└────────────────────────────────────────────────────────────┘
```

Items d'inventaire :
- `telep.bmp` : Téléphone
- `calc1.bmp` : Calculette
- `sac.bmp` : Sac à dos
- `fiole.bmp` : Fiole (avec variantes f1.bmp à f12.bmp)

---

## Mécanismes d'Interaction

### 1. Survol (Hover)
```
SI curseur dans zone_cliquable ALORS
   Afficher texte_hotspot à (text_x, text_y)
   SI image_rollover_hover ALORS
      Remplacer image normale par image hover
FIN SI
```

### 2. Clic sur bâtiment (avec polygone)
```
SI clic dans polygone ALORS
   SI video ALORS
      Jouer video.avi
   FIN SI
   SI goto_scene ALORS
      Aller à scène N
   FIN SI
FIN SI
```

### 3. Clic sur objet (sans polygone)
```
SI clic dans rectangle_rollover ALORS
   SI action = "ramasser" ALORS
      Cacher objet (delbmp NAME)
      Ajouter à inventaire (addbmp dans barre)
      Incrémenter variable
   SINON SI action = "utiliser" ALORS
      Vérifier conditions
      Exécuter action
   FIN SI
FIN SI
```

### 4. Ramasser un objet
Séquence typique dans le VND :
```
1. addbmp coffre euroland\rollover\coffre.bmp 0 0 203  (objet visible)
2. Hotspot "Un coffre fermé à clé"
3. Condition: cle_jaune = 1 then ...
4. Action: delbmp coffre (disparaît de la scène)
5. Action: inc_var sacados 1 (ajouté à l'inventaire)
6. Action: addbmp sac ..\..\barre\images\sac.bmp 6 384 400
```

### 5. Conditions
```
Format: variable OPERATEUR valeur then ACTION [else ACTION]

Exemples:
- score < 0 then runprj ..\couleurs1\couleurs1.vnp 54
- cle_jaune = 1 then delbmp coffre
- espagne = 1 then dec_var espagne 1
```

---

## Algorithme de Détection de Clic (pour React)

```typescript
function handleClick(x: number, y: number) {
  // 1. Vérifier les hotspots avec polygones (priorité haute)
  for (const hotspot of currentScene.hotspots) {
    if (hotspot.polygon && isPointInPolygon({x, y}, hotspot.polygon.points)) {
      executeHotspotAction(hotspot);
      return;
    }
  }

  // 2. Vérifier les images rollover
  for (const rollover of currentScene.rollovers) {
    const rect = {
      x1: rollover.x,
      y1: rollover.y,
      x2: rollover.x + rollover.width,
      y2: rollover.y + rollover.height
    };
    if (isPointInRect({x, y}, rect)) {
      executeRolloverAction(rollover);
      return;
    }
  }
}

function isPointInPolygon(point, polygon) {
  // Algorithme ray-casting
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][0], yi = polygon[i][1];
    const xj = polygon[j][0], yj = polygon[j][1];

    if (((yi > point.y) !== (yj > point.y)) &&
        (point.x < (xj - xi) * (point.y - yi) / (yj - yi) + xi)) {
      inside = !inside;
    }
  }
  return inside;
}
```

---

## Fichiers Générés

| Fichier | Description |
|---------|-------------|
| `Doc/game_data_polygons.json` | Données complètes avec polygones |
| `tools/vnd_polygon_parser.py` | Parser Python |

### Structure JSON

```json
{
  "game": "Europeo",
  "resolution": {"width": 640, "height": 480},
  "countries": {
    "couleurs1": {
      "name": "Euroland",
      "scenes": [
        {
          "id": 1,
          "background": "face.bmp",
          "hotspots": [
            {
              "id": 1,
              "text": "La bibliothèque",
              "text_position": {"x": 57, "y": 60},
              "clickable_area": {
                "type": "polygon",
                "points": [[140,267], [181,260], ...],
                "bbox": {"x1": 35, "y1": 120, "x2": 189, "y2": 267}
              },
              "video": "bibliobis.avi"
            }
          ]
        }
      ]
    }
  }
}
```

---

## Statistiques

| Pays | Scènes | Hotspots | Avec polygones |
|------|--------|----------|----------------|
| Euroland | 213 | 144 | 36 |
| France | 171 | 64 | 4 |
| Angleterre | 182 | 63 | 16 |
| Bibliothèque | 563 | 655 | 43 |
| **TOTAL** | 3122 | ~1500 | 134 |

---

## Notes Techniques

1. **Encodage texte** : Latin-1 (ISO-8859-1)
2. **Entiers** : Little-endian
3. **Coordonnées** : Origine (0,0) en haut à gauche
4. **Les constantes 125 et 365** dans les hotspots sont des paramètres de formatage texte (probablement largeur max et hauteur ligne)
