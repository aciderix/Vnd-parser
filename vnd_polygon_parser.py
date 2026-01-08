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
class DisplayText:
    """Text displayed when hovering over a hotspot (may differ from label)"""
    text: str
    x: int
    y: int


@dataclass
class Type09Record:
    """Type 0x09 record data - can be action strings or binary data"""
    count: int
    subtype: int
    data: bytes
    decoded_action: Optional[str] = None  # For subtype=0 (action strings like "euroland\bankbis.avi 1")


@dataclass
class Hotspot:
    """Complete hotspot with text, polygon, and action"""
    id: int
    text: str = ""  # Label of the hotspot (e.g., "Un litd")
    text_x: int = 0  # Label display position
    text_y: int = 0
    layer: int = 0
    polygon: Optional[Polygon] = None
    video: Optional[str] = None
    goto_scene: Optional[int] = None
    actions: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    bmp_actions: List[BmpAction] = field(default_factory=list)
    display_text: Optional[DisplayText] = None  # Alternative text shown on hover
    type_09_record: Optional[Type09Record] = None  # Type 0x09 special record (video actions, associations, etc.)
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
    RECORD_TYPE_09 = 0x09  # 9 - Special record (actions, video, associations)

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

    def read_type_09_at(self, offset: int, max_search_distance: int = 300) -> Optional[Type09Record]:
        """Read a Type 0x09 record at a specific offset

        Type 0x09 format:
        - Bytes 0-3: Type (0x09 0x00 0x00 0x00)
        - Byte 4: Count
        - Byte 5: Subtype (0 = action string, 3 = binary data/associations)
        - Bytes 6-7: Padding (0x00 0x00)
        - Bytes 8+: Data (variable length)

        The data length is determined by finding the next known record type.
        """
        if offset + 8 > self.size:
            return None

        record_type = struct.unpack_from('<I', self.data, offset)[0]
        if record_type != self.RECORD_TYPE_09:
            return None

        # Read header
        count = self.data[offset + 4]
        subtype = self.data[offset + 5]

        # Find the end of this record by searching for next known record type
        data_start = offset + 8
        data_end = None

        known_types = [self.RECORD_TYPE_HOTSPOT_TEXT, self.RECORD_TYPE_FONT,
                      self.RECORD_TYPE_POLYGON, 0x15]  # 0x15 = condition record

        for search_offset in range(data_start, min(data_start + max_search_distance, self.size), 4):
            if search_offset + 4 > self.size:
                break

            check_type = struct.unpack_from('<I', self.data, search_offset)[0]
            if check_type in known_types:
                data_end = search_offset
                break

        if data_end is None:
            data_end = min(data_start + max_search_distance, self.size)

        # Extract data
        data = self.data[data_start:data_end]

        # Try to decode as action string if subtype=0
        decoded_action = None
        if subtype == 0 and len(data) > 0:
            try:
                # Try to decode as string
                decoded = data.decode('latin-1', errors='ignore')

                # Type 0x09 subtype=0 format: "path\file.avi [params...]"
                # After the .avi there are binary parameters - stop before them
                # Look for .avi or .wav extension and take everything before the binary garbage
                if '.avi' in decoded.lower():
                    # Find .avi and take only up to ~20 chars after it (for parameters)
                    avi_pos = decoded.lower().find('.avi')
                    # Take text up to .avi + 20 chars max (for parameters like "1")
                    decoded = decoded[:avi_pos + 4 + 20]

                    # Stop at first non-printable or excessive garbage character
                    clean_parts = []
                    for c in decoded:
                        if c.isprintable() or c in ' \t\\':
                            clean_parts.append(c)
                        else:
                            break
                    decoded = ''.join(clean_parts).strip()

                elif '.wav' in decoded.lower():
                    # Same for .wav files
                    wav_pos = decoded.lower().find('.wav')
                    decoded = decoded[:wav_pos + 4 + 10]
                    clean_parts = []
                    for c in decoded:
                        if c.isprintable() or c in ' \t\\':
                            clean_parts.append(c)
                        else:
                            break
                    decoded = ''.join(clean_parts).strip()

                else:
                    # Generic cleanup - remove control characters
                    decoded = ''.join(c for c in decoded if c.isprintable() or c in ' \t\\')
                    decoded = decoded.strip()

                if decoded:
                    decoded_action = decoded
            except:
                pass

        return Type09Record(
            count=count,
            subtype=subtype,
            data=data,
            decoded_action=decoded_action
        )

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

    def clean_hotspot_text(self, text: str) -> str:
        """Clean hotspot text by removing trailing garbage characters

        VND files often have a padding/flag byte after text data that gets captured
        by regex. These appear as trailing single letters like 'd', 'j', 'k', 'i', etc.
        """
        if not text or len(text) < 2:
            return text

        # Common garbage characters: d, j, k, i, h, f, l (bytes like 0x64, 0x6a, 0x6b, etc.)
        # These appear as the last byte of the Type 0x26 record data
        garbage_chars = 'dfjhijkl'

        # Check if last character is a suspicious garbage byte
        if text[-1] in garbage_chars:
            # Additional checks to avoid removing legitimate text:
            # - If preceded by a vowel, it's likely a word ending (like "litd" from "lit")
            # - If preceded by 'e' or 'r', check context
            # - If preceded by space/punctuation, it's likely garbage

            if text[-2] in ' .!?':
                # Definitely garbage (space or punctuation before)
                return text[:-1]

            elif text[-2] in 'aeiouèéêëàâùûîïôœ':
                # Vowel before the letter - likely NOT a valid French word ending
                # (French words rarely end in vowel + d/j/k)
                return text[:-1]

            elif len(text) >= 3 and text[-2:] in ['td', 'ej', 'nd', 'rj', 'sd', 'ij', 'uj', 'xj', 'sk', 'xk', 'xd',
                                                     'Ef', 'Eh', 'tf', 'ld', 'li', 'lj', 'Od', 'ah', 'eh', 'oh']:
                # Suspicious 2-letter combos that don't exist in French
                return text[:-1]

            elif len(text) >= 4 and text[-3:] in ['usj', 'uxj', 'aud', 'eud', 'oid', 'rik', 'tik', 'IEf', 'IEh',
                                                     'Old', 'ald', 'ntf', 'eli', 'olj']:
                # Suspicious 3-letter combos
                return text[:-1]

        return text

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

                # Remove trailing garbage characters (padding bytes from VND records)
                text = self.clean_hotspot_text(text)

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

            # Associate display texts with triggering hotspots
            self._associate_display_texts(scene)

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

    def _associate_display_texts(self, scene: Scene):
        """Associate display texts with their triggering hotspots

        VND structure pattern:
        FONT #1 → Display text(s) without polygon
        FONT #2 → Clickable hotspot with polygon

        The display text from FONT #1 should be shown when hovering the hotspot from FONT #2
        """
        if not scene.hotspots:
            return

        pending_display_texts = []
        final_hotspots = []

        for hotspot in scene.hotspots:
            # Check if this is a display-only text (no polygon, no bmp_actions, no goto, no Type 0x09)
            is_display_only = (
                hotspot.polygon is None and
                not hotspot.bmp_actions and
                hotspot.goto_scene is None and
                not hotspot.video and
                hotspot.type_09_record is None  # Type 0x09 makes it interactive
            )

            if is_display_only:
                # This is a text that will be displayed on hover of next hotspot
                pending_display_texts.append(hotspot)
            else:
                # This is a real interactive hotspot
                if pending_display_texts:
                    # Merge all pending texts into display_text
                    merged_text = '\n'.join(h.text for h in pending_display_texts)
                    last_text = pending_display_texts[-1]

                    hotspot.display_text = DisplayText(
                        text=merged_text,
                        x=last_text.text_x,
                        y=last_text.text_y
                    )

                    pending_display_texts.clear()

                final_hotspots.append(hotspot)

        # Keep remaining display-only hotspots (they are autonomous)
        final_hotspots.extend(pending_display_texts)

        scene.hotspots = final_hotspots

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

        # 1. Search for Type 0x09 record (special actions/associations)
        for offset in range(start_offset, min(start_offset + region_size, end_offset)):
            if offset + 8 > self.size:
                break
            type_09 = self.read_type_09_at(offset, max_search_distance=min(300, end_offset - offset))
            if type_09:
                hotspot.type_09_record = type_09
                break

        # 2. Search for polygon (binary data)
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

                # Add display_text if different from label
                if hotspot.display_text:
                    hotspot_dict['display_text'] = {
                        'text': hotspot.display_text.text,
                        'position': {'x': hotspot.display_text.x, 'y': hotspot.display_text.y}
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

                if hotspot.type_09_record:
                    hotspot_dict['type_09_record'] = {
                        'count': hotspot.type_09_record.count,
                        'subtype': hotspot.type_09_record.subtype,
                        'data_length': len(hotspot.type_09_record.data)
                    }
                    if hotspot.type_09_record.decoded_action:
                        hotspot_dict['type_09_record']['action'] = hotspot.type_09_record.decoded_action

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
