#!/usr/bin/env python3
"""
VND Polygon Parser - Extract complete hotspot data including clickable polygons
Format: VNFILE 2.13 by Sopra Multimedia

This parser extracts:
- Scenes with background images
- Hotspots with:
  - Text labels and display positions
  - Clickable polygon areas (NOT text positions!)
  - Associated videos/actions
"""

import struct
import re
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Tuple, Optional, Any

BASE_DIR = Path(__file__).parent.parent


@dataclass
class Polygon:
    """Clickable polygon area"""
    points: List[Tuple[int, int]]

    @property
    def bbox(self) -> Tuple[int, int, int, int]:
        """Bounding box (x1, y1, x2, y2)"""
        if not self.points:
            return (0, 0, 0, 0)
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def center(self) -> Tuple[int, int]:
        """Center point"""
        bbox = self.bbox
        return ((bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2)


@dataclass
class Hotspot:
    """Complete hotspot with text, polygon, and action"""
    id: int
    text: str
    text_x: int  # Text display position (NOT click zone!)
    text_y: int
    layer: int
    polygon: Optional[Polygon] = None
    video: Optional[str] = None
    goto_scene: Optional[int] = None
    action: Optional[str] = None
    offset: int = 0  # File offset for debugging


@dataclass
class Scene:
    """Game scene with background and hotspots"""
    id: int
    background: str
    audio: Optional[str] = None
    hotspots: List[Hotspot] = field(default_factory=list)
    offset: int = 0


class VndPolygonParser:
    """Parse VND binary files to extract complete hotspot data"""

    RECORD_TYPE_HOTSPOT_TEXT = 0x26  # 38
    RECORD_TYPE_FONT = 0x27  # 39
    RECORD_TYPE_POLYGON = 0x69  # 105

    def __init__(self, filepath: Path):
        self.filepath = filepath
        with open(filepath, 'rb') as f:
            self.data = f.read()
        self.text_content = self.data.decode('latin-1', errors='replace')

    def find_polygons(self) -> List[Tuple[int, Polygon]]:
        """Find all polygon records in the file"""
        polygons = []
        i = 0

        while i < len(self.data) - 8:
            record_type = struct.unpack_from('<I', self.data, i)[0]

            if record_type == self.RECORD_TYPE_POLYGON:
                count = struct.unpack_from('<I', self.data, i + 4)[0]

                if 3 <= count <= 50:  # Valid polygon point count
                    points = []
                    valid = True

                    for j in range(count):
                        offset = i + 8 + j * 8
                        if offset + 8 > len(self.data):
                            valid = False
                            break

                        x = struct.unpack_from('<i', self.data, offset)[0]
                        y = struct.unpack_from('<i', self.data, offset + 4)[0]

                        # Validate coordinates
                        if not (-200 <= x <= 800 and -200 <= y <= 600):
                            valid = False
                            break

                        points.append((x, y))

                    if valid and points:
                        polygons.append((i, Polygon(points=points)))
                        i += 8 + count * 8  # Skip past polygon data
                        continue

            i += 1

        return polygons

    def find_font_records(self) -> List[int]:
        """Find all font definition records (marks start of hotspot groups)"""
        fonts = []
        # Pattern: "18 0 #000000 Comic sans MS" or similar
        pattern = r'(\d{1,2})\s+\d+\s+#[0-9A-Fa-f]{6}\s+[^\x00]+'

        for match in re.finditer(pattern, self.text_content):
            fonts.append(match.start())

        return sorted(fonts)

    def find_hotspot_texts(self) -> List[Tuple[int, str, int, int, int]]:
        """Find all hotspot text records (X Y 125 365 layer text)"""
        hotspots = []

        # Pattern: X Y 125 365 layer text
        # 125 and 365 are text formatting constants
        pattern = r'(\d{1,3})\s+(\d{1,3})\s+125\s+365\s+(\d+)\s+([^\x00\r\n]+)'

        for match in re.finditer(pattern, self.text_content):
            offset = match.start()
            x = int(match.group(1))
            y = int(match.group(2))
            layer = int(match.group(3))
            text = match.group(4).strip()

            # Filter out obviously wrong matches
            if 0 <= x <= 640 and 0 <= y <= 480 and len(text) > 1:
                hotspots.append((offset, text, x, y, layer))

        return hotspots

    def find_videos(self) -> List[Tuple[int, str]]:
        """Find all video references"""
        videos = []
        pattern = r'([\w]+\.avi)'

        for match in re.finditer(pattern, self.text_content, re.IGNORECASE):
            videos.append((match.start(), match.group(1)))

        return videos

    def find_backgrounds(self) -> List[Tuple[int, str]]:
        """Find background image references"""
        backgrounds = []

        # Look for standalone BMP filenames (not in paths)
        pattern = r'(?<![\\/:])(\w+\.bmp)(?!\w)'

        for match in re.finditer(pattern, self.text_content, re.IGNORECASE):
            name = match.group(1).lower()
            # Filter out rollover images
            if 'roll' not in name and 'over' not in name:
                backgrounds.append((match.start(), match.group(1)))

        return backgrounds

    def find_scene_navigations(self) -> List[Tuple[int, int]]:
        """Find scene navigation commands (e.g., '39i', '51j')"""
        navigations = []
        pattern = r'(?<!\d)(\d{1,3})([a-z])(?!\w)'

        for match in re.finditer(pattern, self.text_content):
            scene_id = int(match.group(1))
            if 1 <= scene_id <= 200:  # Valid scene range
                navigations.append((match.start(), scene_id))

        return navigations

    def associate_data(self) -> List[Scene]:
        """Associate all extracted data into scenes and hotspots"""
        # Extract all data
        polygons = self.find_polygons()
        hotspot_texts = self.find_hotspot_texts()
        videos = self.find_videos()
        backgrounds = self.find_backgrounds()
        navigations = self.find_scene_navigations()
        font_records = self.find_font_records()

        print(f"  Found: {len(polygons)} polygons, {len(hotspot_texts)} hotspots, "
              f"{len(videos)} videos, {len(backgrounds)} backgrounds")

        # Build scenes based on background positions
        scenes = []
        current_scene = None
        scene_id = 0

        # Sort backgrounds by offset
        backgrounds = sorted(backgrounds, key=lambda x: x[0])

        for bg_offset, bg_name in backgrounds:
            scene_id += 1
            current_scene = Scene(
                id=scene_id,
                background=bg_name,
                offset=bg_offset
            )
            scenes.append(current_scene)

        if not scenes:
            return []

        # Helper to find the next font record after an offset
        def find_next_font(offset: int) -> int:
            for font_offset in font_records:
                if font_offset > offset:
                    return font_offset
            return offset + 2000  # Default search limit

        # Associate hotspots with scenes based on file offsets
        hotspot_id = 0
        for text_offset, text, x, y, layer in hotspot_texts:
            # Find which scene this hotspot belongs to
            scene = None
            for s in reversed(scenes):
                if s.offset < text_offset:
                    scene = s
                    break

            if not scene:
                scene = scenes[0]

            hotspot_id += 1
            hotspot = Hotspot(
                id=hotspot_id,
                text=text,
                text_x=x,
                text_y=y,
                layer=layer,
                offset=text_offset
            )

            # Find the next font record to limit our search range
            next_font = find_next_font(text_offset)
            search_limit = min(next_font, text_offset + 1500)

            # Find associated polygon (between hotspot and next font record)
            for poly_offset, polygon in polygons:
                if text_offset < poly_offset < search_limit:
                    hotspot.polygon = polygon
                    break

            # Find associated video (can be BEFORE or AFTER the hotspot text, within range)
            # Videos often appear before the font/hotspot text group
            for vid_offset, video in videos:
                # Check both before (within 100 bytes) and after (within search limit)
                if text_offset - 100 < vid_offset < search_limit:
                    hotspot.video = video
                    break

            # Find navigation (after hotspot, within search limit)
            for nav_offset, goto in navigations:
                if text_offset < nav_offset < search_limit:
                    hotspot.goto_scene = goto
                    break

            scene.hotspots.append(hotspot)

        return scenes

    def parse(self) -> Dict[str, Any]:
        """Parse complete VND file"""
        scenes = self.associate_data()

        # Convert to dict for JSON serialization
        result = {
            'file': self.filepath.name,
            'scenes': []
        }

        for scene in scenes:
            scene_dict = {
                'id': scene.id,
                'background': scene.background,
                'audio': scene.audio,
                'hotspots': []
            }

            for hotspot in scene.hotspots:
                hotspot_dict = {
                    'id': hotspot.id,
                    'text': hotspot.text,
                    'text_position': {'x': hotspot.text_x, 'y': hotspot.text_y},
                    'layer': hotspot.layer,
                }

                if hotspot.polygon:
                    hotspot_dict['clickable_area'] = {
                        'type': 'polygon',
                        'points': hotspot.polygon.points,
                        'bbox': {
                            'x1': hotspot.polygon.bbox[0],
                            'y1': hotspot.polygon.bbox[1],
                            'x2': hotspot.polygon.bbox[2],
                            'y2': hotspot.polygon.bbox[3]
                        },
                        'center': {
                            'x': hotspot.polygon.center[0],
                            'y': hotspot.polygon.center[1]
                        }
                    }

                if hotspot.video:
                    hotspot_dict['video'] = hotspot.video

                if hotspot.goto_scene:
                    hotspot_dict['goto_scene'] = hotspot.goto_scene

                scene_dict['hotspots'].append(hotspot_dict)

            result['scenes'].append(scene_dict)

        return result


def parse_all_vnd_files() -> Dict[str, Any]:
    """Parse all VND files in the project"""
    vnd_folders = {
        'couleurs1': 'Euroland',
        'france': 'France',
        'allem': 'Allemagne',
        'angl': 'Angleterre',
        'autr': 'Autriche',
        'belge': 'Belgique',
        'danem': 'Danemark',
        'ecosse': 'Écosse',
        'espa': 'Espagne',
        'finlan': 'Finlande',
        'grece': 'Grèce',
        'holl': 'Pays-Bas',
        'irland': 'Irlande',
        'italie': 'Italie',
        'portu': 'Portugal',
        'suede': 'Suède',
        'biblio': 'Bibliothèque',
        'barre': 'Barre outils',
        'frontal': 'Démarrage',
    }

    all_data = {
        'game': 'Europeo',
        'version': '1.0',
        'resolution': {'width': 640, 'height': 480},
        'countries': {}
    }

    print("=" * 70)
    print("PARSING VND FILES WITH POLYGON EXTRACTION")
    print("=" * 70)

    for folder, name in sorted(vnd_folders.items()):
        vnd_path = BASE_DIR / folder / f"{folder}.vnd"

        # Handle special cases
        if folder == 'angl':
            vnd_path = BASE_DIR / 'angl' / 'angleterre.vnd'
        elif folder == 'frontal':
            vnd_path = BASE_DIR / 'frontal' / 'start.vnd'

        if not vnd_path.exists():
            print(f"\n{name}: VND not found at {vnd_path}")
            continue

        print(f"\n{name} ({folder}):")
        try:
            parser = VndPolygonParser(vnd_path)
            data = parser.parse()

            all_data['countries'][folder] = {
                'name': name,
                'folder': folder,
                **data
            }

            # Summary
            total_hotspots = sum(len(s['hotspots']) for s in data['scenes'])
            polygons = sum(
                1 for s in data['scenes']
                for h in s['hotspots']
                if 'clickable_area' in h
            )
            print(f"  Scenes: {len(data['scenes'])}")
            print(f"  Hotspots: {total_hotspots} ({polygons} with polygons)")

        except Exception as e:
            print(f"  Error: {e}")

    return all_data


def main():
    # Parse all VND files
    data = parse_all_vnd_files()

    # Save to JSON
    output_path = BASE_DIR / 'Doc' / 'game_data_polygons.json'
    output_path.parent.mkdir(exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 70}")
    print(f"OUTPUT SAVED TO: {output_path}")
    print(f"{'=' * 70}")

    # Summary
    total_scenes = sum(
        len(c.get('scenes', []))
        for c in data['countries'].values()
    )
    total_hotspots = sum(
        len(h)
        for c in data['countries'].values()
        for s in c.get('scenes', [])
        for h in [s.get('hotspots', [])]
    )

    print(f"\nTotal countries: {len(data['countries'])}")
    print(f"Total scenes: {total_scenes}")


if __name__ == '__main__':
    main()
