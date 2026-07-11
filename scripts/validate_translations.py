#!/usr/bin/env python3
"""
Translation Sync Validator

Ensures all language translation files have identical keys.
Run this before commits that modify translation files.

Usage:
    python scripts/validate_translations.py
    python scripts/validate_translations.py --fix  # Auto-create missing keys

Exit codes:
    0 - All translations in sync
    1 - Missing or extra keys found
"""

import json
import sys
from pathlib import Path
from typing import Dict, Set, List, Any
import argparse


TRANSLATIONS_DIR = Path(__file__).parent.parent / 'app' / 'i18n' / 'translations'
BASE_LANGUAGE = 'ko'


def extract_keys(data: Dict, prefix: str = '') -> Set[str]:
    """Extract all keys from a nested dictionary using dot notation."""
    keys = set()
    for key, value in data.items():
        if key == '_meta':
            continue
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys.update(extract_keys(value, full_key))
        else:
            keys.add(full_key)
    return keys


def load_translation_file(path: Path) -> Dict:
    """Load a JSON translation file."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_all_languages() -> List[str]:
    """Get list of all language directories."""
    return [d.name for d in TRANSLATIONS_DIR.iterdir() if d.is_dir()]


def get_translation_files(lang: str) -> List[Path]:
    """Get all translation files for a language."""
    lang_dir = TRANSLATIONS_DIR / lang
    return list(lang_dir.glob('*.json'))


def validate_sync() -> Dict[str, Dict[str, Any]]:
    """
    Validate that all languages have the same keys as the base language.

    Returns:
        Dict with validation results per file
    """
    results = {}
    languages = get_all_languages()

    if BASE_LANGUAGE not in languages:
        print(f"ERROR: Base language '{BASE_LANGUAGE}' not found!")
        return {'error': 'Base language not found'}

    # Get base language files
    base_files = get_translation_files(BASE_LANGUAGE)

    for base_file in base_files:
        namespace = base_file.stem
        base_data = load_translation_file(base_file)
        base_keys = extract_keys(base_data)

        results[namespace] = {
            'base_keys_count': len(base_keys),
            'languages': {}
        }

        # Check each other language
        for lang in languages:
            if lang == BASE_LANGUAGE:
                continue

            target_file = TRANSLATIONS_DIR / lang / f"{namespace}.json"

            if not target_file.exists():
                results[namespace]['languages'][lang] = {
                    'status': 'missing_file',
                    'missing_keys': list(base_keys),
                    'extra_keys': []
                }
                continue

            target_data = load_translation_file(target_file)
            target_keys = extract_keys(target_data)

            missing = base_keys - target_keys
            extra = target_keys - base_keys

            if missing or extra:
                results[namespace]['languages'][lang] = {
                    'status': 'out_of_sync',
                    'missing_keys': sorted(list(missing)),
                    'extra_keys': sorted(list(extra))
                }
            else:
                results[namespace]['languages'][lang] = {
                    'status': 'ok',
                    'missing_keys': [],
                    'extra_keys': []
                }

    return results


def create_missing_keys(target_file: Path, missing_keys: List[str], base_file: Path) -> None:
    """Create missing keys in target file with placeholder values."""
    if not target_file.exists():
        # Create new file with all base keys
        base_data = load_translation_file(base_file)
        target_data = {'_meta': base_data.get('_meta', {})}
        target_data['_meta']['language'] = target_file.parent.name
    else:
        target_data = load_translation_file(target_file)

    base_data = load_translation_file(base_file)

    for key in missing_keys:
        parts = key.split('.')
        # Get value from base
        base_value = base_data
        for part in parts:
            base_value = base_value.get(part, {})

        # Set in target with TODO marker
        current = target_data
        for i, part in enumerate(parts[:-1]):
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = f"[TODO: {base_value}]"

    with open(target_file, 'w', encoding='utf-8') as f:
        json.dump(target_data, f, ensure_ascii=False, indent=2)


def print_report(results: Dict[str, Dict[str, Any]]) -> int:
    """Print validation report and return exit code."""
    has_errors = False

    print("\n" + "=" * 60)
    print("TRANSLATION SYNC VALIDATION REPORT")
    print("=" * 60)

    for namespace, data in results.items():
        print(f"\n[{namespace}.json] - {data['base_keys_count']} keys in base ({BASE_LANGUAGE})")

        for lang, status in data.get('languages', {}).items():
            if status['status'] == 'ok':
                print(f"  {lang}: OK")
            elif status['status'] == 'missing_file':
                print(f"  {lang}: MISSING FILE!")
                has_errors = True
            else:
                print(f"  {lang}: OUT OF SYNC")
                if status['missing_keys']:
                    print(f"    Missing keys ({len(status['missing_keys'])}):")
                    for key in status['missing_keys'][:10]:
                        print(f"      - {key}")
                    if len(status['missing_keys']) > 10:
                        print(f"      ... and {len(status['missing_keys']) - 10} more")
                if status['extra_keys']:
                    print(f"    Extra keys ({len(status['extra_keys'])}):")
                    for key in status['extra_keys'][:5]:
                        print(f"      + {key}")
                has_errors = True

    print("\n" + "=" * 60)
    if has_errors:
        print("RESULT: FAILED - Translations are out of sync!")
        print("Run with --fix to auto-create missing keys with placeholders")
    else:
        print("RESULT: PASSED - All translations are in sync!")
    print("=" * 60 + "\n")

    return 1 if has_errors else 0


def main():
    parser = argparse.ArgumentParser(description='Validate translation file synchronization')
    parser.add_argument('--fix', action='store_true', help='Auto-create missing keys')
    args = parser.parse_args()

    results = validate_sync()

    if 'error' in results:
        print(f"ERROR: {results['error']}")
        return 1

    exit_code = print_report(results)

    if args.fix and exit_code != 0:
        print("\nFixing missing keys...")
        for namespace, data in results.items():
            base_file = TRANSLATIONS_DIR / BASE_LANGUAGE / f"{namespace}.json"
            for lang, status in data.get('languages', {}).items():
                if status['missing_keys']:
                    target_file = TRANSLATIONS_DIR / lang / f"{namespace}.json"
                    print(f"  Creating missing keys in {lang}/{namespace}.json...")
                    create_missing_keys(target_file, status['missing_keys'], base_file)
        print("\nDone! Please review and translate the [TODO: ...] placeholders")
        return 0

    return exit_code


if __name__ == '__main__':
    sys.exit(main())
