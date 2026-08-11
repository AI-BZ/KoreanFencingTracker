#!/usr/bin/env python3
"""
Populate translations for competitions, organizations, and players in Supabase.

Usage:
    python scripts/populate_translations.py --competitions
    python scripts/populate_translations.py --organizations
    python scripts/populate_translations.py --all
    python scripts/populate_translations.py --dry-run  # Preview without updating
    python scripts/populate_translations.py --sync-verified  # Sync hardcoded verified mappings to DB
    python scripts/populate_translations.py --sync-verified --dry-run  # Preview sync
"""

import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client, Client
from app.translation_service import TranslationService, VERIFIED_COMPETITION_MAPPINGS
from app.international_data import VERIFIED_NAME_MAPPINGS
from app.organization_identity import VERIFIED_ORG_MAPPINGS

# Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def get_supabase() -> Client:
    """Get Supabase client."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def populate_competition_translations(dry_run: bool = False):
    """Populate translations for competitions table."""
    print("\n=== Populating Competition Translations ===\n")

    supabase = get_supabase()
    ts = TranslationService()

    # Get all competitions
    result = supabase.table('competitions').select('id', 'comp_name', 'translations').execute()

    if not result.data:
        print("No competitions found.")
        return

    updated = 0
    skipped = 0

    for comp in result.data:
        comp_id = comp['id']
        comp_name = comp.get('comp_name', '')
        existing_translations = comp.get('translations', {})

        # Skip if already has verified translation
        if isinstance(existing_translations, dict):
            en_data = existing_translations.get('en', {})
            if isinstance(en_data, dict) and en_data.get('verified'):
                print(f"  [SKIP] {comp_name[:50]} (already verified)")
                skipped += 1
                continue

        # Generate translation
        translation = ts.translate_competition_name(comp_name)
        english_name = translation.get('en', {}).get('name', '')

        if dry_run:
            print(f"  [DRY-RUN] {comp_name[:40]}")
            print(f"            -> {english_name[:40]}")
        else:
            # Update in database
            try:
                supabase.table('competitions').update({
                    'translations': translation
                }).eq('id', comp_id).execute()

                print(f"  [OK] {comp_name[:40]} -> {english_name[:40]}")
                updated += 1
            except Exception as e:
                print(f"  [ERROR] {comp_name[:40]}: {e}")

    print(f"\nSummary: Updated {updated}, Skipped {skipped}")


def populate_organization_translations(dry_run: bool = False):
    """Populate translations for organizations table."""
    print("\n=== Populating Organization Translations ===\n")

    supabase = get_supabase()
    ts = TranslationService()

    # Get all organizations
    result = supabase.table('organizations').select('id', 'name', 'translations').execute()

    if not result.data:
        print("No organizations found.")
        return

    updated = 0
    skipped = 0

    for org in result.data:
        org_id = org['id']
        org_name = org.get('name', '')
        existing_translations = org.get('translations', {})

        # Skip if already has verified translation
        if isinstance(existing_translations, dict):
            en_data = existing_translations.get('en', {})
            if isinstance(en_data, dict) and en_data.get('verified'):
                print(f"  [SKIP] {org_name[:50]} (already verified)")
                skipped += 1
                continue

        # Generate translation
        translation = ts.translate_organization_name(org_name)
        english_name = translation.get('en', {}).get('name', '')

        if dry_run:
            print(f"  [DRY-RUN] {org_name[:40]}")
            print(f"            -> {english_name[:40]}")
        else:
            # Update in database
            try:
                supabase.table('organizations').update({
                    'translations': translation
                }).eq('id', org_id).execute()

                print(f"  [OK] {org_name[:40]} -> {english_name[:40]}")
                updated += 1
            except Exception as e:
                print(f"  [ERROR] {org_name[:40]}: {e}")

    print(f"\nSummary: Updated {updated}, Skipped {skipped}")


def populate_player_translations(dry_run: bool = False, limit: int = 100):
    """Populate translations for players table."""
    print(f"\n=== Populating Player Translations (limit: {limit}) ===\n")

    supabase = get_supabase()
    ts = TranslationService()

    # Get players without translations
    result = supabase.table('players').select(
        'id', 'player_name', 'translations'
    ).limit(limit).execute()

    if not result.data:
        print("No players found.")
        return

    updated = 0
    skipped = 0

    for player in result.data:
        player_id = player['id']
        player_name = player.get('player_name', '')
        existing_translations = player.get('translations', {})

        # Skip if already has translation
        if isinstance(existing_translations, dict):
            en_data = existing_translations.get('en', {})
            if isinstance(en_data, dict) and en_data.get('name'):
                skipped += 1
                continue

        # Generate translation
        translation = ts.translate_player_name(player_name)
        english_name = translation.get('en', {}).get('name', '')

        if dry_run:
            print(f"  [DRY-RUN] {player_name} -> {english_name}")
        else:
            # Update in database
            try:
                supabase.table('players').update({
                    'translations': translation
                }).eq('id', player_id).execute()

                print(f"  [OK] {player_name} -> {english_name}")
                updated += 1
            except Exception as e:
                print(f"  [ERROR] {player_name}: {e}")

    print(f"\nSummary: Updated {updated}, Skipped {skipped}")


def sync_verified_mappings(dry_run: bool = False):
    """Sync hardcoded VERIFIED_NAME_MAPPINGS, VERIFIED_ORG_MAPPINGS, and
    VERIFIED_COMPETITION_MAPPINGS to DB with verified=true."""
    print("\n=== Syncing Verified Mappings to DB ===\n")

    supabase = get_supabase()
    ts = TranslationService()
    now = datetime.utcnow().isoformat() + "Z"

    # 1. Sync verified player names
    print("--- Player Names ---")
    player_synced = 0
    for korean_name, info in VERIFIED_NAME_MAPPINGS.items():
        en_given = info.get('en_given', '')
        en_surname = info.get('en_surname', '')
        en_name = f"{en_given} {en_surname}" if en_given and en_surname else info.get('en_name', '')

        translation = {
            "en": {
                "name": en_name,
                "name_order": "western",
                "verified": True,
                "source": "verified",
                "fie_id": info.get('fie_id'),
                "fencingtracker_id": info.get('fencingtracker_id'),
                "updated_at": now,
            }
        }

        if dry_run:
            print(f"  [DRY-RUN] {korean_name} -> {en_name} (verified=True)")
        else:
            try:
                result = supabase.table('players').select('id').eq(
                    'player_name', korean_name
                ).execute()
                if result.data:
                    for row in result.data:
                        supabase.table('players').update({
                            'translations': translation
                        }).eq('id', row['id']).execute()
                    print(f"  [OK] {korean_name} -> {en_name} ({len(result.data)} records)")
                    player_synced += 1
                else:
                    print(f"  [SKIP] {korean_name} (not found in DB)")
            except Exception as e:
                print(f"  [ERROR] {korean_name}: {e}")

    print(f"  Players synced: {player_synced}/{len(VERIFIED_NAME_MAPPINGS)}")

    # 2. Sync verified organization names
    print("\n--- Organization Names ---")
    org_synced = 0
    for korean_name, info in VERIFIED_ORG_MAPPINGS.items():
        name_en = info.get('name_en', '')
        translation = {
            "en": {
                "name": name_en,
                "verified": True,
                "source": "verified",
                "updated_at": now,
            }
        }

        if dry_run:
            print(f"  [DRY-RUN] {korean_name[:40]} -> {name_en[:40]} (verified=True)")
        else:
            try:
                result = supabase.table('organizations').select('id').eq(
                    'name', korean_name
                ).execute()
                if result.data:
                    for row in result.data:
                        supabase.table('organizations').update({
                            'translations': translation
                        }).eq('id', row['id']).execute()
                    print(f"  [OK] {korean_name[:40]} -> {name_en[:40]}")
                    org_synced += 1
                else:
                    print(f"  [SKIP] {korean_name[:40]} (not in DB)")
            except Exception as e:
                print(f"  [ERROR] {korean_name[:40]}: {e}")

    print(f"  Organizations synced: {org_synced}/{len(VERIFIED_ORG_MAPPINGS)}")

    # 3. Sync verified competition names
    print("\n--- Competition Names ---")
    comp_synced = 0
    for korean_name, en_name in VERIFIED_COMPETITION_MAPPINGS.items():
        if korean_name.startswith("테스트"):
            continue
        translation = {
            "en": {
                "name": en_name,
                "verified": True,
                "source": "verified",
                "updated_at": now,
            }
        }

        if dry_run:
            print(f"  [DRY-RUN] {korean_name[:40]} -> {en_name[:40]} (verified=True)")
        else:
            try:
                result = supabase.table('competitions').select('id').eq(
                    'comp_name', korean_name
                ).execute()
                if result.data:
                    for row in result.data:
                        supabase.table('competitions').update({
                            'translations': translation
                        }).eq('id', row['id']).execute()
                    print(f"  [OK] {korean_name[:40]} -> {en_name[:40]}")
                    comp_synced += 1
                else:
                    print(f"  [SKIP] {korean_name[:40]} (not in DB)")
            except Exception as e:
                print(f"  [ERROR] {korean_name[:40]}: {e}")

    print(f"  Competitions synced: {comp_synced}/{len(VERIFIED_COMPETITION_MAPPINGS)}")

    print("\n=== Sync Complete ===")
    print(f"  Players: {player_synced}, Organizations: {org_synced}, Competitions: {comp_synced}")


def main():
    parser = argparse.ArgumentParser(description='Populate translations in Supabase')
    parser.add_argument('--competitions', action='store_true', help='Translate competitions')
    parser.add_argument('--organizations', action='store_true', help='Translate organizations')
    parser.add_argument('--players', action='store_true', help='Translate players')
    parser.add_argument('--all', action='store_true', help='Translate all tables')
    parser.add_argument('--sync-verified', action='store_true',
                        help='Sync hardcoded verified mappings to DB (players, orgs, competitions)')
    parser.add_argument('--dry-run', action='store_true', help='Preview without updating')
    parser.add_argument('--limit', type=int, default=100, help='Limit for players (default: 100)')

    args = parser.parse_args()

    if not any([args.competitions, args.organizations, args.players, args.all, args.sync_verified]):
        parser.print_help()
        return

    if args.sync_verified:
        sync_verified_mappings(dry_run=args.dry_run)

    if args.all or args.competitions:
        populate_competition_translations(dry_run=args.dry_run)

    if args.all or args.organizations:
        populate_organization_translations(dry_run=args.dry_run)

    if args.all or args.players:
        populate_player_translations(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
