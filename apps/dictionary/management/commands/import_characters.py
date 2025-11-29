import json
import os
from django.core.management.base import BaseCommand, CommandError
from apps.dictionary.models import Character, Radical

class Command(BaseCommand):
    help = 'Imports Chinese characters and links ALL radicals found in decomposition (checking variants and traditional forms)'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Path to the characters.txt file')

    def handle(self, *args, **options):
        file_path = options['file_path']
        output_log_path = 'radical_import_log.txt'

        if not os.path.exists(file_path):
            raise CommandError(f'File "{file_path}" does not exist.')

        self.stdout.write(self.style.SUCCESS(f'Starting import from {file_path}...'))

        # --- CACHE LOGIC ---
        # We build a dictionary where the main character, simplified, traditional,
        # AND its variants all point to the same Radical object instance.
        radical_cache = {}
        radicals_qs = Radical.objects.all()
        
        for r in radicals_qs:
            # 1. Map the primary character (e.g., '水' or '讠')
            radical_cache[r.character] = r

            # 2. Map the Traditional form explicitly (e.g., '言') if it exists
            if r.traditional_character:
                radical_cache[r.traditional_character] = r

            # 3. Map the Simplified form explicitly if it exists
            if r.simplified_character:
                radical_cache[r.simplified_character] = r
            
            # 4. Map the variants (e.g., '氵', '氺')
            if r.variants: 
                for v in r.variants:
                    radical_cache[v] = r
                    
        self.stdout.write(f'Cached {len(radicals_qs)} radicals (mapped to {len(radical_cache)} total lookup keys).')

        BATCH_SIZE = 2000
        batch_data = []
        total_processed = 0

        # Open the log file
        with open(output_log_path, 'w', encoding='utf-8') as log_file:

            def process_batch(batch):
                """
                Process a batch of dictionaries.
                """
                if not batch:
                    return

                hanzi_list = [item['hanzi'] for item in batch]
                
                # --- STEP A: Create/Update the Character objects ---
                existing_qs = Character.objects.filter(hanzi__in=hanzi_list)
                existing_map = {c.hanzi: c for c in existing_qs}
                
                to_create = []
                to_update = []

                for item in batch:
                    hanzi = item['hanzi']
                    defaults = item['defaults']
                    
                    if hanzi in existing_map:
                        char_obj = existing_map[hanzi]
                        char_obj.definition = defaults['definition']
                        char_obj.pinyin = defaults['pinyin']
                        char_obj.decomposition = defaults['decomposition']
                        char_obj.etymology = defaults['etymology']
                        to_update.append(char_obj)
                    else:
                        to_create.append(Character(hanzi=hanzi, **defaults))

                if to_create:
                    Character.objects.bulk_create(to_create)
                
                if to_update:
                    Character.objects.bulk_update(
                        to_update, 
                        fields=['definition', 'pinyin', 'decomposition', 'etymology']
                    )

                # --- STEP B: Link Radicals ---
                
                # 1. Get the IDs of the characters we just processed
                # Assuming Character model still uses the default 'id'. 
                # If Character also uses a custom PK, change 'id' below to 'pk'.
                char_id_map = dict(Character.objects.filter(hanzi__in=hanzi_list).values_list('hanzi', 'pk'))
                
                # 2. Prepare the Many-to-Many Through table buffer
                m2m_relations = []
                log_entries = [] 
                ThroughModel = Character.radicals.through # Access the hidden table for optimization

                for item in batch:
                    char_str = item['hanzi']
                    char_id = char_id_map.get(char_str)
                    
                    if not char_id:
                        continue

                    # Determine which radicals to add
                    radicals_to_add_chars = set()

                    # 1. Add the "primary" radical defined in the file
                    if item.get('radical_char'):
                        radicals_to_add_chars.add(item.get('radical_char'))

                    # 2. Parse the "decomposition" string
                    decomp_string = item['defaults']['decomposition']
                    if decomp_string:
                        for char in decomp_string:
                            radicals_to_add_chars.add(char)

                    # 3. Create the DB Connections
                    added_rads_log = []
                    
                    for radical_char in radicals_to_add_chars:
                        radical_obj = radical_cache.get(radical_char)
                        
                        if radical_obj:
                            # FIX: Used .pk instead of .id
                            m2m_relations.append(
                                ThroughModel(character_id=char_id, radical_id=radical_obj.pk)
                            )
                            # Log which actual radical object was found
                            added_rads_log.append(f"{radical_char}→{radical_obj.character}")

                    # Log what we found for this character
                    if added_rads_log:
                        log_entries.append(f"{char_str}: linked to [{', '.join(added_rads_log)}]\n")
                    else:
                        log_entries.append(f"{char_str}: No valid radicals found in DB.\n")

                # --- STEP C: Commit Relations to DB ---
                if m2m_relations:
                    # ignore_conflicts=True prevents crashing if the link already exists
                    ThroughModel.objects.bulk_create(m2m_relations, ignore_conflicts=True)
                
                # Write logs
                if log_entries:
                    log_file.writelines(log_entries)
                    log_file.flush()

            # --- Main Loop Reading File ---
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue

                    try:
                        data = json.loads(line)
                        char_hanzi = data.get('character')
                        if not char_hanzi: continue

                        # Flatten pinyin list to string
                        pinyin_raw = data.get('pinyin', [])
                        pinyin_str = ", ".join(pinyin_raw) if isinstance(pinyin_raw, list) else str(pinyin_raw)

                        item = {
                            'hanzi': char_hanzi,
                            'defaults': {
                                'definition': data.get('definition', ''),
                                'pinyin': pinyin_str,
                                'decomposition': data.get('decomposition', ''),
                                'etymology': data.get('etymology', {}),
                            },
                            'radical_char': data.get('radical')
                        }
                        
                        batch_data.append(item)
                        
                        if len(batch_data) >= BATCH_SIZE:
                            process_batch(batch_data)
                            total_processed += len(batch_data)
                            self.stdout.write(f"Processed {total_processed} characters...", ending='\r')
                            batch_data = []

                    except json.JSONDecodeError:
                        continue

            # Process leftovers
            if batch_data:
                process_batch(batch_data)
                total_processed += len(batch_data)

        self.stdout.write(self.style.SUCCESS(f'\nImport complete. Processed {total_processed} characters.'))
        self.stdout.write(self.style.SUCCESS(f'Check {output_log_path} to see which radicals were linked.'))