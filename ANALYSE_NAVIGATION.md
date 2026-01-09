# Analyse de la Navigation VND - Résumé

## Découvertes Clés

### 1. Structure des Scènes
Les scènes sont des records Type 0x00 contenant un fichier BMP de fond.

**Index des scènes (vérifié):**
```
Scene 0:  euroland\face.bmp
Scene 1:  euroland\bureaubanquier.bmp
Scene 2:  euroland\banque.bmp
Scene 3:  euroland\biblio.bmp
Scene 4:  euroland\maison.bmp
Scene 5:  euroland\transverteur2.bmp
Scene 6:  euroland\bdmusee.bmp
Scene 7:  euroland\armoire3.bmp          ← DESTINATION DE L'ARMOIRE
Scene 8:  euroland\infosac.bmp
...
Scene 14: euroland\bonus.bmp
...
```

### 2. Structure des Hotspots

Les hotspots sont définis en **plusieurs parties**:

#### A. Type 0x26 (HOTSPOT_TEXT)
Contient le texte affiché et les coordonnées de la zone:
```
Format: "x y width height flags Texte du hotspot"
Exemple: "1400 350 125 365 0 Une armoire bien remplie"
```

#### B. Type 0x01 (ACTION/TARGET)
Contient l'ID de destination (scène ou ressource):
```
Longueur: 6 bytes
Premier int32: Target ID
```

**Exemples trouvés:**
- "Une table avec plein de choses dessus" → Type 0x01 = **2**
- "Madame euro" → Type 0x01 = **0**

#### C. Type 0x03 (CONDITION/SCRIPT)
Contient des scripts conditionnels:
```
Exemple: "score < 0 then runprj ..\couleurs1\couleurs1.vnp 54"
```

### 3. Patterns Mystérieux: "1e", "51j", etc.

Ces patterns apparaissent dans les Type 0x02 avec la structure:
```
06 00 00 00          - Marqueur
[index: int32]       - Index (1 pour "1e", 2 pour "51j")
[pattern: string]    - Pattern ("1e", "51j", etc.)
00 00 00             - Padding
[count: int32]       - Nombre de points du polygone
[points: (x,y)*N]    - Coordonnées du polygone cliquable
```

**Association trouvée:**
- Pattern "51j" → Hotspot "Une table avec plein de choses dessus"
- Pattern "1e" → Hotspot proche de "SORTIE" (pas armoire!)

### 4. Problème Non Résolu

**Incohérence:**
- L'utilisateur dit: "armoire mène à armoire3.bmp"
- armoire3.bmp = Scene 7
- Mais le hotspot "Une armoire..." n'a PAS de Type 0x01, seulement un Type 0x03 (script)

**Hypothèses:**
1. Le hotspot "Une armoire..." montre seulement une erreur/condition
2. La vraie navigation de l'armoire est ailleurs (peut-être via "1e"?)
3. Le pattern "1e" pourrait indiquer une autre zone cliquable sur l'armoire
4. table_m.bmp n'est PAS une scène mais une surimpression (addbmp)

### 5. Structures Décompilées du DLL (fournies par l'utilisateur)

```cpp
struct VN_Hotspot {
    uint32_t id;                // ID du hotspot
    VN_Rect area;               // Zone (x, y, width, height)
    VN_Action action;           // Type d'action
    uint32_t target_id;         // ← ID de la scène cible OU ressource
    char script_cmd[256];       // Commande de script
    uint32_t cursor_id;         // ID du curseur
};

void VN_NavigateToScene(int targetId) {
    // Charge la nouvelle scène
    VN_Scene* nextScene = VN_Project_GetScene(targetId);
    VN_LoadBitmap(nextScene->background_file);
    // ...
}
```

## Prochaines Étapes

1. **Analyser le Type 0x01 en profondeur** dans le DLL pour comprendre comment le `target_id` est interprété
2. **Tracer l'exécution** depuis le clic sur un hotspot jusqu'à la navigation
3. **Vérifier** si les patterns "1e", "51j" définissent des ZONES CLIQUABLES séparées des textes
4. **Tester l'hypothèse** que Type 0x01 value = 2 pourrait signifier:
   - Soit: Scene 2 (banque.bmp)
   - Soit: Resource ID 2 → table_m.bmp en surimpression
5. **Chercher dans le DLL** la fonction qui résout resource_id → filename

## Code à Analyser dans le DLL

- Handler pour Type 0x01 (jump table à 0x40b0c0)
- Fonctions de navigation (VN_NavigateToScene)
- Fonctions de ressources (VN_LoadBitmap, addbmp)
- Parser de patterns ("1e", "51j")
