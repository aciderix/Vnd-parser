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
  - Commands (addbmp, delbmp, runprj, playtext, scene, etc.)
"""

import struct
import re
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any

BASE_DIR = Path(__file__).parent


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
class BmpAction:
    """A bitmap action with coordinates"""
    command: str  # 'addbmp' or 'delbmp'
    name: str
    path: Optional[str] = None
    layer: Optional[int] = None
    x: Optional[int] = None
    y: Optional[int] = None


@dataclass
class Hotspot:
    """Complete hotspot with text, polygon, and action"""
    id: int
    text: str = ""
    text_x: int = 0  # Text display position (NOT click zone!)
    text_y: int = 0
    layer: int = 0
    polygon: Optional[Polygon] = None
    video: Optional[str] = None
    goto_scene: Optional[int] = None
    actions: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    bmp_actions: List[BmpAction] = field(default_factory=list)
    offset: int = 0  # File offset for debugging


@dataclass
class SceneCommand:
    """A command that executes in the scene (playtext, playwav, etc.)"""
    command_type: str  # 'playtext', 'playwav', 'addbmp', 'scene', etc.
    full_command: str
    condition: Optional[str] = None


@dataclass
class Scene:
    """Game scene with background and hotspots"""
    id: int
    background: str
    audio: Optional[str] = None
    hotspots: List[Hotspot] = field(default_factory=list)
    commands: List[SceneCommand] = field(default_factory=list)
    offset: int = 0


class VndPolygonParser:
    """Parse VND binary files to extract complete hotspot data in sequential order"""

    RECORD_TYPE_HOTSPOT_TEXT = 0x26  # 38
    RECORD_TYPE_FONT = 0x27  # 39
    RECORD_TYPE_POLYGON = 0x69  # 105

    def __init__(self, filepath: Path):
        self.filepath = filepath
        with open(filepath, 'rb') as f:
            self.data = f.read()
        self.text_content = self.data.decode('latin-1', errors='replace')
        self.size = len(self.data)

    def read_polygon_at(self, offset: int) -> Optional[Polygon]:
        """Read a polygon at a specific offset"""
        if offset + 8 > self.size:
            return None

        record_type = struct.unpack_from('<I', self.data, offset)[0]
        if record_type != self.RECORD_TYPE_POLYGON:
            return None

        count = struct.unpack_from('<I', self.data, offset + 4)[0]

        if not (3 <= count <= 50):  # Valid polygon point count
            return None

        points = []
        for j in range(count):
            point_offset = offset + 8 + j * 8
            if point_offset + 8 > self.size:
                return None

            x = struct.unpack_from('<i', self.data, point_offset)[0]
            y = struct.unpack_from('<i', self.data, point_offset + 4)[0]

            # Validate coordinates (allow wider range for scrolling scenes)
            if not (-200 <= x <= 2000 and -200 <= y <= 600):
                return None

            points.append((x, y))

        if points:
            return Polygon(points=points)
        return None

    def find_all_backgrounds(self) -> List[Tuple[int, str]]:
        """Find all background image references with their offsets"""
        backgrounds = []

        # Look for .bmp files that are likely backgrounds (not rollover images)
        # Pattern: path\to\background.bmp or just background.bmp
        pattern = r'([\w\\]+\.bmp)'

        for match in re.finditer(pattern, self.text_content, re.IGNORECASE):
            name = match.group(1)
            offset = match.start()

            # Filter out rollover images (contain 'roll', 'over', 'det', 'abs', etc.)
            name_lower = name.lower()
            if any(x in name_lower for x in ['roll', 'over', 'det', 'abs', '\\interface\\', '\\barre\\']):
                continue

            # Only keep backgrounds that look like scene backgrounds
            if '\\' in name or name_lower.endswith('.bmp'):
                backgrounds.append((offset, name))

        return backgrounds

    def extract_text_at(self, offset: int, max_length: int = 100) -> str:
        """Extract readable text at offset"""
        end = min(offset + max_length, self.size)
        chunk = self.data[offset:end]
        try:
            text = chunk.decode('latin-1', errors='ignore')
            # Keep only printable characters
            text = ''.join(c for c in text if c.isprintable() or c in '\n\r\t')
            return text.strip()
        except:
            return ""

    def parse_sequential(self) -> List[Scene]:
        """Parse VND file sequentially, respecting natural scene boundaries"""

        # Find all background positions
        backgrounds = self.find_all_backgrounds()
        backgrounds = sorted(backgrounds, key=lambda x: x[0])

        if not backgrounds:
            return []

        scenes = []
        hotspot_global_id = 0

        # Parse each scene
        for scene_idx, (bg_offset, bg_name) in enumerate(backgrounds):
            # Determine the end of this scene (start of next scene or end of file)
            if scene_idx < len(backgrounds) - 1:
                scene_end = backgrounds[scene_idx + 1][0]
            else:
                scene_end = self.size

            scene = Scene(
                id=scene_idx + 1,
                background=bg_name,
                offset=bg_offset
            )

            # Search for hotspots within this scene's range
            search_start = bg_offset
            search_end = scene_end

            # First, find all FONT records (type 0x27 = 39) which mark hotspot boundaries
            # Pattern: "18 0 #ffffff Comic sans MS" or "24 0 #000000 Arial"
            font_pattern = r'(\d{1,2})\s+\d+\s+#[0-9A-Fa-f]{6}\s+([^\x00\n\r]{3,30})'

            scene_text = self.text_content[search_start:search_end]
            font_matches = list(re.finditer(font_pattern, scene_text))

            # Create a set of font positions for quick lookup
            font_positions = {search_start + m.start() for m in font_matches}

            # Now find hotspot text patterns
            # Pattern: X Y 125 365 layer text (the constants 125 and 365 identify hotspots)
            pattern = r'(\d{1,3})\s+(\d{1,3})\s+125\s+365\s+(\d+)\s+([^\x00\r\n]+)'

            for match in re.finditer(pattern, scene_text):
                hotspot_offset = search_start + match.start()
                x = int(match.group(1))
                y = int(match.group(2))
                layer = int(match.group(3))
                text = match.group(4)

                # Clean the text (remove control characters)
                text = ''.join(c for c in text if c.isprintable() or c in ' \t')
                text = text.strip()

                # Filter out obviously wrong matches
                # Note: x can be > 640 due to horizontal scrolling in some scenes
                if not (0 <= x <= 2000 and 0 <= y <= 480 and len(text) > 0):
                    continue

                # IMPORTANT: Filter out false positives
                # 1. Must be preceded by a FONT record within ~200 bytes
                has_font_before = False
                closest_font_distance = float('inf')
                for font_pos in font_positions:
                    if font_pos < hotspot_offset:
                        distance = hotspot_offset - font_pos
                        if distance < 200:
                            has_font_before = True
                            closest_font_distance = min(closest_font_distance, distance)

                if not has_font_before:
                    continue

                # 2. Skip ONLY if inside a playtext command AND font is far
                # If font is very close (< 100 bytes), it's a real hotspot even if inside a condition
                if closest_font_distance > 100:
                    context_before = self.text_content[max(0, hotspot_offset - 100):hotspot_offset]
                    skip_keywords = ['playtext', 'playwav']
                    should_skip = False
                    for keyword in skip_keywords:
                        if keyword in context_before.lower():
                            # Make sure the keyword is recent (within 50 chars)
                            last_index = context_before.lower().rfind(keyword)
                            if last_index >= len(context_before) - 50:
                                should_skip = True
                                break

                    if should_skip:
                        continue

                hotspot_global_id += 1
                hotspot = Hotspot(
                    id=hotspot_global_id,
                    text=text,
                    text_x=x,
                    text_y=y,
                    layer=layer,
                    offset=hotspot_offset
                )

                # Define search range for this hotspot's associated data
                # Look ahead up to 2000 bytes or until next font record
                next_font_offset = None
                for font_match in font_matches:
                    font_abs_offset = search_start + font_match.start()
                    if font_abs_offset > hotspot_offset + len(match.group(0)):
                        next_font_offset = font_abs_offset
                        break

                if next_font_offset:
                    hotspot_end = next_font_offset
                else:
                    hotspot_end = min(hotspot_offset + 2000, scene_end)

                # Extract associated data for this hotspot
                self._extract_hotspot_data(hotspot, hotspot_offset, hotspot_end)

                scene.hotspots.append(hotspot)

            # Merge multiline hotspots (same X position, consecutive Y positions)
            self._merge_multiline_hotspots(scene)

            # Extract ALL scene commands (playtext, playwav, addbmp, etc.)
            self._extract_scene_commands(scene, search_start, search_end)

            # Look for scene-wide audio
            audio_pattern = r'([\w]+\.wav)'
            scene_audio_text = self.text_content[search_start:min(search_start + 500, search_end)]
            for audio_match in re.finditer(audio_pattern, scene_audio_text, re.IGNORECASE):
                scene.audio = audio_match.group(1)
                break

            scenes.append(scene)

        return scenes

    def _merge_multiline_hotspots(self, scene: Scene):
        """Merge hotspots that are part of the same multiline text"""
        if not scene.hotspots:
            return

        merged = []
        i = 0

        while i < len(scene.hotspots):
            current = scene.hotspots[i]

            # Check if next hotspot(s) are continuations (same X, Y within 20 pixels)
            continuation_texts = [current.text]
            j = i + 1

            while j < len(scene.hotspots):
                next_hotspot = scene.hotspots[j]

                # Same X position and Y within 20 pixels = multiline
                if (current.text_x == next_hotspot.text_x and
                    0 < next_hotspot.text_y - current.text_y <= 30):
                    continuation_texts.append(next_hotspot.text)
                    current.text_y = next_hotspot.text_y  # Update to last line Y
                    j += 1
                else:
                    break

            # Merge texts if multiple lines found
            if len(continuation_texts) > 1:
                current.text = '\n'.join(continuation_texts)
                i = j  # Skip the merged hotspots
            else:
                i += 1

            merged.append(current)

        scene.hotspots = merged

    def _extract_scene_commands(self, scene: Scene, start_offset: int, end_offset: int):
        """Extract ALL commands in the scene (not just those attached to hotspots)"""
        region_text = self.text_content[start_offset:end_offset]

        # Extract playtext commands with conditions
        playtext_pattern = r'((\w+\s*[<>=!]+\s*\d+)\s+then\s+)?(playtext\s+[^\x00\n\r]+)'
        for match in re.finditer(playtext_pattern, region_text, re.IGNORECASE):
            condition = match.group(2) if match.group(2) else None
            command = match.group(3)
            command = ''.join(c for c in command if c.isprintable() or c in ' \t').strip()

            scene.commands.append(SceneCommand(
                command_type='playtext',
                full_command=command,
                condition=condition
            ))

        # Extract playwav commands with conditions
        playwav_pattern = r'((\w+\s*[<>=!]+\s*\d+)\s+then\s+)?(playwav\s+[^\x00\n\r]+)'
        for match in re.finditer(playwav_pattern, region_text, re.IGNORECASE):
            condition = match.group(2) if match.group(2) else None
            command = match.group(3)
            command = ''.join(c for c in command if c.isprintable() or c in ' \t').strip()

            scene.commands.append(SceneCommand(
                command_type='playwav',
                full_command=command,
                condition=condition
            ))

        # Extract scene navigation commands
        scene_cmd_pattern = r'((\w+\s*[<>=!]+\s*\d+)\s+then\s+)?(scene\s+\d+)'
        for match in re.finditer(scene_cmd_pattern, region_text, re.IGNORECASE):
            condition = match.group(2) if match.group(2) else None
            command = match.group(3)

            scene.commands.append(SceneCommand(
                command_type='scene',
                full_command=command,
                condition=condition
            ))

    def _extract_hotspot_data(self, hotspot: Hotspot, start_offset: int, end_offset: int):
        """Extract all data associated with a hotspot (polygon, video, actions, etc.)"""

        # Search region
        region_size = end_offset - start_offset

        # 1. Search for polygon (binary data)
        for offset in range(start_offset, min(start_offset + region_size, end_offset)):
            if offset + 8 > self.size:
                break
            polygon = self.read_polygon_at(offset)
            if polygon:
                hotspot.polygon = polygon
                break

        # 2. Search for video files (.avi)
        region_text = self.text_content[max(0, start_offset - 100):end_offset]
        video_pattern = r'([\w]+\.avi)'
        for video_match in re.finditer(video_pattern, region_text, re.IGNORECASE):
            hotspot.video = video_match.group(1)
            break

        # 3. Search for scene navigation (e.g., '1e', '51j')
        # Navigation pattern appears AFTER polygon/text, before next hotspot
        # Look in the binary region between hotspot and next hotspot
        nav_pattern = r'(?<!\d)(\d{1,3})([a-z])(?!\w)'

        # Search in full region including binary data
        region_binary = self.data[start_offset:end_offset]
        region_binary_text = region_binary.decode('latin-1', errors='replace')

        # Find the LAST navigation pattern (most likely to be the goto)
        nav_matches = list(re.finditer(nav_pattern, region_binary_text))
        if nav_matches:
            # Take the last one found (usually after polygon)
            last_nav = nav_matches[-1]
            scene_id = int(last_nav.group(1))
            if 1 <= scene_id <= 999:
                hotspot.goto_scene = scene_id

        # 4. Extract actions and conditions
        region_text_full = self.text_content[start_offset:end_offset]

        # Parse addbmp commands with coordinates
        # Pattern: addbmp name path layer x y
        addbmp_pattern = r'addbmp\s+(\w+)\s+([^\s]+\.bmp)\s+(\d+)\s+(\d+)\s+(\d+)'
        for match in re.finditer(addbmp_pattern, region_text_full, re.IGNORECASE):
            bmp_action = BmpAction(
                command='addbmp',
                name=match.group(1),
                path=match.group(2),
                layer=int(match.group(3)),
                x=int(match.group(4)),
                y=int(match.group(5))
            )
            hotspot.bmp_actions.append(bmp_action)

        # Parse delbmp commands
        delbmp_pattern = r'delbmp\s+(\w+)'
        for match in re.finditer(delbmp_pattern, region_text_full, re.IGNORECASE):
            bmp_action = BmpAction(
                command='delbmp',
                name=match.group(1)
            )
            hotspot.bmp_actions.append(bmp_action)

        # Actions: runprj, scene, playtext, playwav, set_var, inc_var, dec_var
        action_patterns = [
            r'(addbmp\s+[^\x00\n\r]+)',
            r'(delbmp\s+\w+)',
            r'(runprj\s+[^\x00\n\r]+)',
            r'(scene\s+\d+)',
            r'(playtext\s+[^\x00\n\r]+)',
            r'(playwav\s+[^\x00\n\r]+)',
            r'(set_var\s+\w+\s+\d+)',
            r'(inc_var\s+\w+\s+\d+)',
            r'(dec_var\s+\w+\s+\d+)',
        ]

        for pattern in action_patterns:
            for action_match in re.finditer(pattern, region_text_full, re.IGNORECASE):
                action = action_match.group(1)
                # Clean control characters
                action = ''.join(c for c in action if c.isprintable() or c in ' \t')
                action = action.strip()
                if action and action not in hotspot.actions:
                    hotspot.actions.append(action)

        # 5. Extract conditions (e.g., "variable = value then action")
        condition_pattern = r'(\w+)\s*([<>=!]+)\s*(\d+)\s+then\s+([^\n\r\x00]+)'
        for cond_match in re.finditer(condition_pattern, region_text_full):
            condition = cond_match.group(0)
            # Clean control characters
            condition = ''.join(c for c in condition if c.isprintable() or c in ' \t')
            condition = condition.strip()
            if condition and condition not in hotspot.conditions:
                hotspot.conditions.append(condition)

    def parse(self) -> Dict[str, Any]:
        """Parse complete VND file"""
        scenes = self.parse_sequential()

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
                'hotspots': [],
                'commands': []
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

                if hotspot.actions:
                    hotspot_dict['actions'] = hotspot.actions

                if hotspot.conditions:
                    hotspot_dict['conditions'] = hotspot.conditions

                if hotspot.bmp_actions:
                    hotspot_dict['bmp_actions'] = [
                        {
                            'command': bmp.command,
                            'name': bmp.name,
                            'path': bmp.path,
                            'layer': bmp.layer,
                            'position': {'x': bmp.x, 'y': bmp.y} if bmp.x is not None else None
                        }
                        for bmp in hotspot.bmp_actions
                    ]

                scene_dict['hotspots'].append(hotspot_dict)

            # Add scene commands
            for cmd in scene.commands:
                cmd_dict = {
                    'type': cmd.command_type,
                    'command': cmd.full_command
                }
                if cmd.condition:
                    cmd_dict['condition'] = cmd.condition
                scene_dict['commands'].append(cmd_dict)

            result['scenes'].append(scene_dict)

        return result


def parse_all_vnd_files() -> Dict[str, Any]:
    """Parse all VND files in the project"""
    vnd_files = [
        ('couleurs1', 'Euroland', 'couleurs1.vnd'),
        ('france', 'France', 'france.vnd'),
        ('allem', 'Allemagne', 'allem.vnd'),
        ('angleterre', 'Angleterre', 'angleterre.vnd'),
        ('autr', 'Autriche', 'autr.vnd'),
        ('belge', 'Belgique', 'belge.vnd'),
        ('danem', 'Danemark', 'danem.vnd'),
        ('ecosse', 'Écosse', 'ecosse.vnd'),
        ('espa', 'Espagne', 'espa.vnd'),
        ('finlan', 'Finlande', 'finlan.vnd'),
        ('grece', 'Grèce', 'grece.vnd'),
        ('holl', 'Pays-Bas', 'holl.vnd'),
        ('irland', 'Irlande', 'irland.vnd'),
        ('italie', 'Italie', 'italie.vnd'),
        ('portu', 'Portugal', 'portu.vnd'),
        ('suede', 'Suède', 'suede.vnd'),
        ('biblio', 'Bibliothèque', 'biblio.vnd'),
        ('barre', 'Barre outils', 'barre.vnd'),
        ('start', 'Démarrage', 'start.vnd'),
    ]

    all_data = {
        'game': 'Europeo',
        'version': '1.0',
        'resolution': {'width': 640, 'height': 480},
        'countries': {}
    }

    print("=" * 70)
    print("PARSING VND FILES WITH SEQUENTIAL EXTRACTION")
    print("=" * 70)

    for folder, name, filename in vnd_files:
        vnd_path = BASE_DIR / filename

        if not vnd_path.exists():
            print(f"\n{name}: VND not found at {vnd_path}")
            continue

        print(f"\n{name} ({filename}):")
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
            actions = sum(
                len(h.get('actions', []))
                for s in data['scenes']
                for h in s['hotspots']
            )
            print(f"  Scenes: {len(data['scenes'])}")
            print(f"  Hotspots: {total_hotspots} ({polygons} with polygons)")
            print(f"  Actions: {actions}")

        except Exception as e:
            print(f"  Error: {e}")
            import traceback
            traceback.print_exc()

    return all_data


def main():
    # Parse all VND files
    data = parse_all_vnd_files()

    # Save to JSON
    output_path = BASE_DIR / 'game_data_complete.json'

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
    print(f"Total hotspots: {total_hotspots}")


if __name__ == '__main__':
    main()
