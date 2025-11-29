import json
import os
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.dictionary.models import Radical

class Command(BaseCommand):
    help = "Import Kangxi Radicals from a JSON file."

    def add_arguments(self, parser):
        parser.add_argument('json_path', type=str, help='Path to radical.json file')
        parser.add_argument('--truncate', action='store_true', help='Delete all radicals before import')

    def handle(self, *args, **options):
        path = options['json_path']
        truncate = options['truncate']

        if not os.path.exists(path):
            raise CommandError(f"File not found: {path}")

        # Optional Truncate
        if truncate:
            self.stdout.write(self.style.WARNING("Deleting all existing Radicals..."))
            Radical.objects.all().delete()

        # Load JSON
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise CommandError(f"Invalid JSON in {path}: {e}")

        self.stdout.write(f"Found {len(data)} radicals in file. Importing...")

        created_count = 0
        updated_count = 0

        # Use atomic transaction ensures data integrity
        with transaction.atomic():
            for entry in data:
                # 1. Map JSON keys to variables
                # JSON keys based on your previous input: no, radical, simplified, etc.
                kangxi_num = entry.get('no')
                traditional = entry.get('radical')
                simplified = entry.get('simplified') # Can be None/null

                # Validate essential data
                if not kangxi_num or not traditional:
                    self.stdout.write(self.style.ERROR(f"Skipping invalid entry (missing no or radical): {entry}"))
                    continue

                # 2. Determine Primary Character Display
                # If simplified exists, it is the primary 'character', otherwise traditional.
                primary_char = simplified if simplified else traditional

                # 3. Update or Create
                obj, created = Radical.objects.update_or_create(
                    kangxi_number=kangxi_num,
                    defaults={
                        'traditional_character': traditional,
                        'simplified_character': simplified,
                        'character': primary_char, # Explicitly setting this ensures it's correct
                        
                        # Existing fields
                        'pinyin': entry.get('pinyin', ''),
                        'english': entry.get('meaning', ''),      # JSON 'meaning' -> Model 'english'
                        'stroke_count': entry.get('strokes', 0),  # JSON 'strokes' -> Model 'stroke_count'
                        'frequency': entry.get('frequency', 0),   
                        'variants': entry.get('variants', []),
                        
                        # New Name Fields
                        'name_simplified': entry.get('name_simplified', ''),
                        'name_pinyin': entry.get('name_pinyin', ''),
                    }
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created: {created_count}, Updated: {updated_count}, Total: {Radical.objects.count()}"
        ))