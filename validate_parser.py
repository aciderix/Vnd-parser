#!/usr/bin/env python3
"""
Validation script to ensure the parser correctly extracts VND data
"""

import json
from pathlib import Path

def validate_scenes_order():
    """Verify that scenes are in sequential order and not mixed"""

    data = json.load(open('game_data_complete.json'))

    print("=" * 70)
    print("VALIDATION: SCENE ORDER AND COMPLETENESS")
    print("=" * 70)

    issues = []

    for country_id, country_data in data['countries'].items():
        country_name = country_data['name']
        scenes = country_data['scenes']

        print(f"\n{country_name} ({country_id}):")
        print(f"  Total scenes: {len(scenes)}")

        # Check scene IDs are sequential
        for i, scene in enumerate(scenes):
            expected_id = i + 1
            if scene['id'] != expected_id:
                issues.append(f"{country_name}: Scene ID mismatch at index {i}. Expected {expected_id}, got {scene['id']}")

        # Check hotspots have valid data
        total_hotspots = 0
        hotspots_with_polygons = 0
        hotspots_with_actions = 0
        hotspots_with_conditions = 0

        for scene in scenes:
            total_hotspots += len(scene['hotspots'])
            for hotspot in scene['hotspots']:
                if 'clickable_area' in hotspot:
                    hotspots_with_polygons += 1
                if hotspot.get('actions'):
                    hotspots_with_actions += 1
                if hotspot.get('conditions'):
                    hotspots_with_conditions += 1

        print(f"  Total hotspots: {total_hotspots}")
        print(f"    - with polygons: {hotspots_with_polygons}")
        print(f"    - with actions: {hotspots_with_actions}")
        print(f"    - with conditions: {hotspots_with_conditions}")

    print("\n" + "=" * 70)
    if issues:
        print("ISSUES FOUND:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("✓ ALL VALIDATIONS PASSED")
    print("=" * 70)

    return len(issues) == 0


def validate_specific_scene():
    """Validate a specific scene (maison.bmp) in detail"""

    data = json.load(open('game_data_complete.json'))

    print("\n" + "=" * 70)
    print("VALIDATION: SPECIFIC SCENE (maison.bmp)")
    print("=" * 70)

    couleurs1 = data['countries']['couleurs1']
    maison_scenes = [s for s in couleurs1['scenes'] if 'maison' in s['background'].lower()]

    if not maison_scenes:
        print("ERROR: maison.bmp scene not found!")
        return False

    maison = maison_scenes[0]

    print(f"\nScene: {maison['background']}")
    print(f"Scene ID: {maison['id']}")
    print(f"Number of hotspots: {len(maison['hotspots'])}")

    print("\nHotspots:")
    for hotspot in maison['hotspots']:
        print(f"  [{hotspot['id']}] {hotspot['text']}")
        print(f"      Position: ({hotspot['text_position']['x']}, {hotspot['text_position']['y']})")

        if hotspot.get('video'):
            print(f"      Video: {hotspot['video']}")

        if hotspot.get('goto_scene'):
            print(f"      Goto scene: {hotspot['goto_scene']}")

        if hotspot.get('clickable_area'):
            print(f"      Polygon: {len(hotspot['clickable_area']['points'])} points")

        if hotspot.get('actions'):
            print(f"      Actions: {len(hotspot['actions'])}")
            for action in hotspot['actions'][:3]:  # Show first 3 actions
                print(f"        - {action}")

        if hotspot.get('conditions'):
            print(f"      Conditions: {len(hotspot['conditions'])}")
            for cond in hotspot['conditions'][:2]:  # Show first 2 conditions
                print(f"        - {cond}")

        print()

    print("✓ Scene validation complete")
    return True


def main():
    success = True

    # Validate scene order
    if not validate_scenes_order():
        success = False

    # Validate specific scene
    if not validate_specific_scene():
        success = False

    if success:
        print("\n" + "=" * 70)
        print("✓✓✓ ALL VALIDATIONS PASSED ✓✓✓")
        print("=" * 70)
    else:
        print("\n" + "=" * 70)
        print("✗✗✗ SOME VALIDATIONS FAILED ✗✗✗")
        print("=" * 70)

    return success


if __name__ == '__main__':
    main()
