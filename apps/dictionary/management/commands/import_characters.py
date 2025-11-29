import json
import os
from django.core.management.base import BaseCommand, CommandError
from apps.dictionary.models import Character, Radical

class Command(BaseCommand):
    help = 'Imports Chinese characters, sets main radical, and links other radicals recursively'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Path to the characters.txt file')

    def handle(self, *args, **options):
        file_path = options['file_path']
        output_log_path = 'radical_import_log.txt'

        if not os.path.exists(file_path):
            raise CommandError(f'File "{file_path}" does not exist.')

        # --- STEP 0: LOAD RADICAL CACHE ---
        self.stdout.write(self.style.SUCCESS(f'Loading radicals from DB...'))
        
        radical_cache = {}
        radicals_qs = Radical.objects.all()
        
        for r in radicals_qs:
            radical_cache[r.character] = r
            if r.traditional_character:
                radical_cache[r.traditional_character] = r
            if r.simplified_character:
                radical_cache[r.simplified_character] = r
            if r.variants: 
                for v in r.variants:
                    radical_cache[v] = r
                    
        self.stdout.write(f'Cached {len(radicals_qs)} radicals.')

        # --- STEP 1: PRE-LOAD DECOMPOSITIONS (Pass 1) ---
        self.stdout.write(self.style.WARNING(f'Building decomposition map (Pass 1)...'))
        
        full_decomp_map = {}
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    data = json.loads(line)
                    char = data.get('character')
                    decomp = data.get('decomposition', '')
                    if char:
                        full_decomp_map[char] = decomp
                except json.JSONDecodeError:
                    continue
        
        self.stdout.write(f'Mapped decompositions for {len(full_decomp_map)} characters.')

        # --- RECURSIVE FUNCTION ---
        def get_recursive_radicals(char_str, visited=None):
            if visited is None:
                visited = set()

            found_radicals = set()
            
            for char in char_str:
                # 1. Skip structural markers
                if char in '⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻':
                    continue

                # 2. CHECK: Is this character ALREADY a known Radical?
                if char in radical_cache:
                    found_radicals.add(radical_cache[char])
                    # STOP recursion here. Treat this radical as an atomic unit.
                    continue 

                # 3. RECURSION: Dig deeper if it's not a radical
                if char in full_decomp_map and char not in visited:
                    visited.add(char)
                    child_decomp = full_decomp_map[char]
                    
                    child_radicals = get_recursive_radicals(child_decomp, visited)
                    found_radicals.update(child_radicals)

            return found_radicals


        # --- STEP 2: BATCH PROCESSING (Pass 2) ---
        self.stdout.write(self.style.SUCCESS(f'Starting main import process...'))
        
        BATCH_SIZE = 2000
        batch_data = []
        total_processed = 0

        with open(output_log_path, 'w', encoding='utf-8') as log_file:

            def process_batch(batch):
                if not batch: return

                hanzi_list = [item['hanzi'] for item in batch]
                
                # A. Upsert Characters and Main Radical
                existing_qs = Character.objects.filter(hanzi__in=hanzi_list)
                existing_map = {c.hanzi: c for c in existing_qs}
                
                to_create = []
                to_update = []

                for item in batch:
                    hanzi = item['hanzi']
                    
                    # 1. Resolve Main Radical Object here
                    explicit_rad_char = item.get('radical_char')
                    main_rad_obj = radical_cache.get(explicit_rad_char) # Returns None if not found
                    
                    # Update defaults to include the main_radical object
                    item['defaults']['main_radical'] = main_rad_obj
                    defaults = item['defaults']
                    
                    if hanzi in existing_map:
                        char_obj = existing_map[hanzi]
                        char_obj.definition = defaults['definition']
                        char_obj.pinyin = defaults['pinyin']
                        char_obj.decomposition = defaults['decomposition']
                        char_obj.etymology = defaults['etymology']
                        char_obj.main_radical = defaults['main_radical'] # Update FK
                        to_update.append(char_obj)
                    else:
                        to_create.append(Character(hanzi=hanzi, **defaults))

                if to_create:
                    Character.objects.bulk_create(to_create)
                if to_update:
                    # Added 'main_radical' to updated fields
                    Character.objects.bulk_update(
                        to_update, 
                        fields=['definition', 'pinyin', 'decomposition', 'etymology', 'main_radical']
                    )

                # B. Link Other Radicals (M2M)
                
                # 1. Get IDs for this batch
                char_id_map = dict(Character.objects.filter(hanzi__in=hanzi_list).values_list('hanzi', 'pk'))
                
                # Clear existing M2M relationships for this batch
                current_batch_ids = list(char_id_map.values())
                ThroughModel = Character.other_radicals.through # Updated related_name access
                
                if current_batch_ids:
                    ThroughModel.objects.filter(character_id__in=current_batch_ids).delete()

                m2m_relations = []
                log_entries = [] 

                for item in batch:
                    char_str = item['hanzi']
                    char_id = char_id_map.get(char_str)
                    if not char_id: continue

                    root_decomp = item['defaults']['decomposition']
                    main_rad_obj = item['defaults']['main_radical'] # Retrieved from previous step
                    
                    # Generate all radicals via recursive decomposition
                    recursive_radicals = set()
                    if root_decomp:
                        found = get_recursive_radicals(root_decomp, visited={char_str})
                        recursive_radicals.update(found)

                    # IMPORTANT: Exclude the Main Radical from the Other Radicals list
                    if main_rad_obj and main_rad_obj in recursive_radicals:
                        recursive_radicals.discard(main_rad_obj)

                    added_rads_log = []
                    for r_obj in recursive_radicals:
                        m2m_relations.append(
                            ThroughModel(character_id=char_id, radical_id=r_obj.pk)
                        )
                        added_rads_log.append(r_obj.character)

                    if added_rads_log:
                        log_entries.append(f"{char_str}: Main=[{main_rad_obj}] Other=[{', '.join(added_rads_log)}]\n")
                    else:
                        log_entries.append(f"{char_str}: Main=[{main_rad_obj}] No other radicals.\n")

                if m2m_relations:
                    ThroughModel.objects.bulk_create(m2m_relations)
                
                if log_entries:
                    log_file.writelines(log_entries)
                    log_file.flush()

            # Loop over file for Step 2
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try:
                        data = json.loads(line)
                        char_hanzi = data.get('character')
                        if not char_hanzi: continue

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
                            'radical_char': data.get('radical') # Extract raw radical char
                        }
                        
                        batch_data.append(item)
                        
                        if len(batch_data) >= BATCH_SIZE:
                            process_batch(batch_data)
                            total_processed += len(batch_data)
                            self.stdout.write(f"Processed {total_processed} characters...", ending='\r')
                            batch_data = []

                    except json.JSONDecodeError:
                        continue

            if batch_data:
                process_batch(batch_data)
                total_processed += len(batch_data)

        self.stdout.write(self.style.SUCCESS(f'\nImport complete. Processed {total_processed} characters.'))