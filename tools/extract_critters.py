"""Extract critter configuration from ONI assembly sources.

This is deliberately a static-source export: every record points back to the
config class that creates the critter. Fields are omitted when the value is
dynamic at runtime rather than guessed from the UI.
"""
import os
import re


def _matching(text, start, opener='(', closer=')'):
    depth, quote, escape = 0, False, False
    for i in range(start, len(text)):
        char = text[i]
        if quote:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                quote = False
        elif char == '"':
            quote = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _args(text):
    result, start, depth, quote, escape = [], 0, 0, False, False
    for i, char in enumerate(text):
        if quote:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                quote = False
        elif char == '"':
            quote = True
        elif char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        elif char == ',' and depth == 0:
            result.append(text[start:i].strip())
            start = i + 1
    last = text[start:].strip()
    if last:
        result.append(last)
    return result


def _call_arguments(text, marker, start=0):
    pos = text.find(marker, start)
    if pos < 0:
        return None
    opening = pos + len(marker)
    if opening >= len(text) or text[opening] != '(':
        return None
    closing = _matching(text, opening)
    return _args(text[opening + 1:closing]) if closing >= 0 else None


def _methods(text):
    """Return method name -> (parameter names, body), for simple C# methods."""
    out = {}
    pattern = re.compile(r'(?:public|private|internal|protected)\s+(?:static\s+)?'
                         r'(?:virtual\s+)?[\w.<>\[\]]+\s+(\w+)\s*\(([^()]*)\)\s*\{')
    for match in pattern.finditer(text):
        end = _matching(text, match.end() - 1, '{', '}')
        if end < 0:
            continue
        params = []
        for param in _args(match.group(2)):
            words = param.split('=')[0].split()
            if words:
                params.append(words[-1])
        out.setdefault(match.group(1), (params, text[match.end():end]))
    return out


class Values:
    """Resolve the scalar expressions commonly used by creature configs."""
    def __init__(self, texts):
        self.expressions = {}
        self.cache = {}
        for text in texts.values():
            cls = re.search(r'\b(?:static\s+)?class\s+(\w+)', text)
            if not cls:
                continue
            class_name = cls.group(1)
            declarations = re.compile(
                    r'\b(?:(?:public|private|internal|protected)\s+)?(?:const|static(?:\s+readonly)?)\s+'
                    r'(?:float|int|double)\s+(\w+)\s*=\s*([^;]+);')
            for match in declarations.finditer(text):
                self.expressions[f'{class_name}.{match.group(1)}'] = match.group(2)
            # TUNING uses nested classes (e.g. CREATURES.SPACE_REQUIREMENTS).
            # Preserve that path so the per-critter PEN_SIZE constants resolve.
            for nested in re.finditer(r'\bclass\s+(\w+)\s*\{', text):
                end = _matching(text, nested.end() - 1, '{', '}')
                if end < 0:
                    continue
                for match in declarations.finditer(text[nested.end():end]):
                    self.expressions[f'{class_name}.{nested.group(1)}.{match.group(1)}'] = match.group(2)

    def number(self, expression, local=None, seen=None):
        if expression is None:
            return None
        expr = expression.strip()
        expr = re.sub(r'^(\w+)\s*:\s*', '', expr)
        if local and expr in local:
            expr = local[expr]
        key = expr
        if key in self.cache:
            return self.cache[key]
        if seen is None:
            seen = set()
        if key in seen:
            return None
        seen.add(key)

        def replace(match):
            name = match.group(0)
            candidates = [name, name.removeprefix('TUNING.')]
            if '.' not in name and local and name in local:
                value = self.number(local[name], local, seen)
                if value is not None:
                    return repr(value)
            for candidate in candidates:
                if candidate in self.expressions:
                    value = self.number(self.expressions[candidate], local, seen)
                    if value is not None:
                        return repr(value)
            return name

        expr = re.sub(r'(?<=\d)f\b', '', expr)
        expr = re.sub(r'\b(?:TUNING\.)?[A-Za-z_]\w*(?:\.\w+)+\b', replace, expr)
        if local:
            expr = re.sub(r'\b[A-Za-z_]\w*\b', replace, expr)
        if re.search(r'[A-Za-z_]', expr) or not re.fullmatch(r'[\d\s.+\-*/()]+', expr):
            return None
        try:
            value = float(eval(expr, {'__builtins__': {}}, {}))
        except (ArithmeticError, SyntaxError):
            return None
        self.cache[key] = value
        return value


def _tag(expression, constants):
    if expression is None:
        return None
    expr = re.sub(r'^\w+\s*:\s*', '', expression.strip())
    if expr in constants:
        return _tag(constants[expr], constants)
    if expr in ('Tag.Invalid', 'default(Tag)', 'null'):
        return None
    match = re.search(r'SimHashes\.(\w+)', expr)
    if match:
        return match.group(1)
    match = re.search(r'"([^"]+)"\s*\.ToTag\(\)', expr)
    if match:
        return match.group(1)
    match = re.search(r'"([^"]+)"', expr)
    if match:
        return match.group(1)
    match = re.search(r'(\w+Config)\.ID', expr)
    if match:
        return match.group(1).removesuffix('Config')
    return None


def _constants(text):
    result = {}
    for match in re.finditer(r'\b(?:(?:public|private|internal|protected)\s+)?'
                           r'(?:(?:const|static(?:\s+readonly)?)\s+)?'
                           r'(?:Tag|SimHashes|string)\s+(\w+)\s*=\s*([^;]+);', text):
        result[match.group(1)] = match.group(2)
    return result


def _number_constants(text):
    result = {}
    for match in re.finditer(r'\b(?:(?:public|private|internal|protected)\s+)?'
                           r'(?:const|static(?:\s+readonly)?)\s+'
                           r'(?:float|int|double)\s+(\w+)\s*=\s*([^;]+);', text):
        result[match.group(1)] = match.group(2)
    return result


def _name(text, strings, fallback):
    match = re.search(r'(?:(STRINGS)\.)?(CREATURES\.SPECIES\.[A-Z0-9_.]+\.NAME)', text)
    if not match:
        return fallback
    name = strings.get('STRINGS.' + match.group(2), fallback)
    return re.sub(r'<[^>]+>', '', name)


def _temperatures(method_body, methods, values):
    """Find warning/lethal temperatures from a creation helper or its base call."""
    candidates = [method_body]
    for call in re.finditer(r'\b(\w+Config)\.(\w+)\s*\(', method_body):
        helper = methods.get(f'{call.group(1)}.{call.group(2)}')
        if helper:
            candidates.append(helper[1])
    for body in candidates:
        nums = []
        for token in re.findall(r'(?<![\w.])-?[\w.]+(?:\s*[+*/-]\s*[\w.]+)*f?', body):
            value = values.number(token)
            if value is not None and 150 <= value <= 800:
                nums.append(value)
        for i in range(len(nums) - 3):
            group = nums[i:i + 4]
            if group[0] <= group[1] and group[2] <= group[3] and group[2] <= group[0]:
                return {'warning_low_k': group[0], 'warning_high_k': group[1],
                        'lethal_low_k': group[2], 'lethal_high_k': group[3]}
    return None


def _egg_chances(expression, texts, values):
    if not expression:
        return None
    parts = expression.strip().split('.')
    class_name, name = (parts[-2], parts[-1]) if len(parts) > 1 else (None, parts[-1])
    for filename, text in texts.items():
        if class_name and not re.search(r'\bclass\s+' + re.escape(class_name) + r'\b', text):
            continue
        marker = re.search(r'\b' + re.escape(name) + r'\s*=\s*new\s+'
                           r'List<FertilityMonitor\.BreedingChance>\s*\{', text)
        if not marker:
            continue
        opening = text.index('{', marker.end() - 1)
        closing = _matching(text, opening, '{', '}')
        body = text[opening:closing]
        result = []
        for item in re.finditer(r'egg\s*=\s*"([^"]+)"\.ToTag\(\).*?weight\s*=\s*([^,}\n]+)', body, re.S):
            result.append({'egg': item.group(1), 'weight': values.number(item.group(2))})
        return result or None
    return None


def _fertility(prefab_body, texts, values):
    args = _call_arguments(prefab_body, 'EntityTemplates.ExtendEntityToFertileCreature')
    if not args:
        return None
    egg_index = next((i for i, arg in enumerate(args) if re.fullmatch(r'"[^"]*Egg"', arg)), None)
    baby_index = next((i for i, arg in enumerate(args[egg_index + 1:], egg_index + 1)
                       if re.fullmatch(r'"[^"]*Baby"', arg)), None) if egg_index is not None else None
    if egg_index is None or baby_index is None:
        return None
    result = {'egg_id': args[egg_index].strip('"'),
              'egg_mass_kg': values.number(args[egg_index + 4]) if egg_index + 4 < len(args) else None,
              'baby_id': args[baby_index].strip('"'),
              'fertility_cycles': values.number(args[baby_index + 1]) if baby_index + 1 < len(args) else None,
              'incubation_cycles': values.number(args[baby_index + 2]) if baby_index + 2 < len(args) else None}
    chances = _egg_chances(args[baby_index + 3] if baby_index + 3 < len(args) else None, texts, values)
    if chances:
        result['egg_chances'] = chances
    fish = next((arg for arg in args if 'add_fish_overcrowding_monitor:' in arg), None)
    if fish:
        result['fish_overcrowding'] = fish.endswith('true')
    ranchable = next((arg for arg in args if 'is_ranchable:' in arg), None)
    result['ranchable'] = not ranchable or ranchable.endswith('true')
    return {key: value for key, value in result.items() if value is not None}


def _diet_helpers(method_body, methods, values, constants, numeric_constants):
    """Trace common Base*Config.*Diet helper calls used by critter morphs."""
    inputs, outputs = [], []
    for match in re.finditer(r'\b(\w+Config)\.(\w*Diet)\s*\(', method_body):
        if match.group(2) == 'SetupDiet':
            continue
        opening = method_body.index('(', match.end() - 1)
        closing = _matching(method_body, opening)
        args = _args(method_body[opening + 1:closing])
        helper = methods.get(f'{match.group(1)}.{match.group(2)}')
        if not helper or len(args) < 3 or 'new Diet.Info' not in helper[1]:
            continue
        tags = [_tag(token, constants) for token in re.findall(
            r'(?:SimHashes\.\w+\.CreateTag\(\)|"[^"]+"\.ToTag\(\))', helper[1])]
        tags = sorted(set(tag for tag in tags if tag))
        produced = _tag(args[0], constants)
        per_kg, ratio = values.number(args[1], numeric_constants), values.number(args[2], numeric_constants)
        if tags:
            inputs.append({'elements': tags, 'calories_per_kg': per_kg})
        if produced:
            outputs.append({'element': produced, 'conversion_ratio': ratio})
    return inputs, outputs


def _diet(method_body, methods, values, constants, numeric_constants):
    inputs, outputs, calories_per_cycle = [], [], None
    for match in re.finditer(r'Amounts\.Calories\.deltaAttribute\.Id,\s*\(0f\s*-\s*([^)]*)\)\s*/\s*600f', method_body):
        calories_per_cycle = values.number(match.group(1), numeric_constants)
        if calories_per_cycle is not None:
            break
    for match in re.finditer(r'\b\w+Config\.SetupDiet\s*\(', method_body):
        opening = method_body.index('(', match.end() - 1)
        closing = _matching(method_body, opening)
        args = _args(method_body[opening + 1:closing])
        if len(args) >= 5:
            consumed, produced = _tag(args[1], constants), _tag(args[2], constants)
            per_kg, rate = values.number(args[3], numeric_constants), values.number(args[4], numeric_constants)
            if consumed:
                inputs.append({'elements': [consumed], 'calories_per_kg': per_kg})
            if produced:
                outputs.append({'element': produced, 'conversion_ratio': rate})
    hash_sets = {}
    for match in re.finditer(r'HashSet<Tag>\s+(\w+)\s*=\s*new\s+HashSet<Tag>\s*\([^;]*\);', method_body):
        name = match.group(1)
        section = method_body[match.end():]
        tags = [_tag(expr, constants) for expr in re.findall(
            re.escape(name) + r'\.Add\(([^)]+(?:\)[^)]*)?)\);', section)]
        hash_sets[name] = [tag for tag in tags if tag]
    for match in re.finditer(r'new\s+Diet\.Info\s*\(', method_body):
        opening = method_body.index('(', match.end() - 1)
        closing = _matching(method_body, opening)
        args = _args(method_body[opening + 1:closing])
        if len(args) < 4:
            continue
        produced = _tag(args[1], constants)
        per_kg, rate = values.number(args[2], numeric_constants), values.number(args[3], numeric_constants)
        if produced:
            outputs.append({'element': produced, 'conversion_ratio': rate})
        tags = hash_sets.get(args[0].strip(), [])
        if not tags:
            tags = [_tag(item, constants) for item in re.findall(r'(?:SimHashes\.\w+\.CreateTag\(\)|"[^"]+"\.ToTag\(\))', args[0])]
        if tags:
            inputs.append({'elements': [tag for tag in tags if tag], 'calories_per_kg': per_kg})
    helper_inputs, helper_outputs = _diet_helpers(method_body, methods, values, constants, numeric_constants)
    inputs.extend(helper_inputs)
    outputs.extend(helper_outputs)
    if not inputs and not outputs and calories_per_cycle is None:
        return None
    if calories_per_cycle is not None:
        for entry in inputs:
            per_kg = entry.get('calories_per_kg')
            if per_kg:
                entry['kg_per_cycle'] = calories_per_cycle / per_kg
        if len(inputs) == 1 and len(outputs) == 1 and inputs[0].get('kg_per_cycle') is not None:
            for entry in outputs:
                ratio = entry.get('conversion_ratio')
                if ratio is not None:
                    entry['kg_per_cycle'] = inputs[0]['kg_per_cycle'] * ratio
    for entry in inputs + outputs:
        for key in [key for key, value in entry.items() if value is None]:
            del entry[key]
    result = {}
    if calories_per_cycle is not None:
        result['calories_per_cycle'] = calories_per_cycle
    if inputs:
        result['inputs'] = inputs
    if outputs:
        result['outputs'] = outputs
    return result


def _merge_diets(primary, inherited):
    if not inherited:
        return primary
    if not primary:
        return inherited
    result = dict(primary)
    for key in ('inputs', 'outputs'):
        if inherited.get(key):
            result[key] = inherited[key] + result.get(key, [])
    result.setdefault('calories_per_cycle', inherited.get('calories_per_cycle'))
    return {key: value for key, value in result.items() if value is not None}


def _life(method_body, values):
    result = {}
    for label, attribute in (('max_age_cycles', 'Age'), ('hit_points', 'HitPoints'), ('stomach_calories', 'Calories')):
        match = re.search(r'Amounts\.' + attribute + r'\.maxAttribute\.Id,\s*([^,]+)', method_body)
        if match:
            value = values.number(match.group(1))
            if value is not None:
                result[label] = value
    return result


def _space(method_body, values):
    args = _call_arguments(method_body, 'EntityTemplates.ExtendEntityToWildCreature')
    return values.number(args[1]) if args and len(args) > 1 else None


def _behaviour(method_body, methods):
    """Static movement and vulnerability flags from the basic-creature helper."""
    bodies = [method_body]
    for call in re.finditer(r'\b(\w+Config)\.(\w+)\s*\(', method_body):
        helper = methods.get(f'{call.group(1)}.{call.group(2)}')
        if helper:
            bodies.append(helper[1])
    for body in bodies:
        nav = re.search(r'\bNavType\.(\w+)', body)
        drown = re.search(r'drownVulnerable\s*:\s*(true|false)', body)
        entomb = re.search(r'entombVulnerable\s*:\s*(true|false)', body)
        if nav or drown or entomb:
            result = {}
            if nav:
                result['nav_type'] = nav.group(1).lower()
            if drown:
                result['drown_vulnerable'] = drown.group(1) == 'true'
            if entomb:
                result['entomb_vulnerable'] = entomb.group(1) == 'true'
            return result
    return None


def extract_critters(source_dir, strings):
    """Return the versioned critter export document for ``critter.yaml``."""
    texts = {}
    for directory, _subdirs, filenames in os.walk(source_dir):
        for filename in sorted(filenames):
            if filename.endswith('.cs'):
                path = os.path.join(directory, filename)
                relative = os.path.relpath(path, source_dir)
                with open(path, encoding='utf-8', errors='replace') as source:
                    texts[relative] = source.read()
    method_index = {}
    for text in texts.values():
        cls = re.search(r'\b(?:static\s+)?class\s+(\w+)', text)
        if cls:
            method_index.update({f'{cls.group(1)}.{name}': (method[0], method[1], text)
                                 for name, method in _methods(text).items()})
    values, records = Values(texts), {}
    for filename, text in texts.items():
        if ': IEntityConfig' not in text or 'IBuildingConfig' in text:
            continue
        if not any(marker in text for marker in ('ExtendEntityToBasicCreature', 'ExtendEntityToWildCreature',
                                                  'CreatureCalorieMonitor', 'AddCreatureBrain')):
            continue
        id_match = re.search(r'\b(?:public|private)\s+const\s+string\s+ID\s*=\s*"([^"]+)"', text)
        if not id_match or id_match.group(1).endswith('Baby'):
            continue
        critter_id, methods = id_match.group(1), _methods(text)
        prefab = methods.get('CreatePrefab', ([], text))[1]
        factory_match = re.search(r'\b(Create\w+)\s*\(\s*"' + re.escape(critter_id) + r'"', prefab)
        factory = methods.get(factory_match.group(1), ([], prefab))[1] if factory_match else prefab
        record = {'name': _name(prefab + factory, strings, critter_id), 'config': filename}
        trait = re.search(r'\bBASE_TRAIT_ID\s*=\s*"([^"]+)"', text)
        if trait:
            record['base_trait_id'] = trait.group(1)
        space = _space(factory, values)
        if space is not None:
            record['ranching'] = {'tiles_per_critter': space}
        behaviour = _behaviour(factory, method_index)
        if behaviour:
            record['behaviour'] = behaviour
        temperatures = _temperatures(factory, method_index, values)
        if temperatures:
            record['temperature'] = temperatures
        life = _life(factory, values)
        if life:
            record['life'] = life
        reproduction = _fertility(prefab, texts, values)
        if reproduction:
            record['reproduction'] = reproduction
        diet = _diet(factory, method_index, values, _constants(text), _number_constants(text))
        # A number of creatures put their common diet in a Base*Config factory
        # (Pacu is the notable example). Include that inherited static diet.
        for call in re.finditer(r'\b(Base\w+Config)\.(\w+)\s*\(', factory):
            helper = method_index.get(f'{call.group(1)}.{call.group(2)}')
            if (call.group(2).startswith(('Create', 'Base')) and helper
                    and 'new Diet.Info' in helper[1]):
                inherited = _diet(helper[1], method_index, values,
                                  _constants(helper[2]), _number_constants(helper[2]))
                diet = _merge_diets(diet, inherited)
        if diet:
            record['diet'] = diet
        dlc = re.search(r'GetRequiredDlcIds\(\)\s*\{\s*return\s+([^;]+);', text)
        if dlc:
            ids = re.findall(r'DlcManager\.(\w+)', dlc.group(1))
            if ids:
                record['required_dlc'] = ids
        records[critter_id] = record
    return {'schema_version': 1,
            'units': {'temperature': 'kelvin', 'mass': 'kg', 'time': 'cycles',
                      'space': 'tiles per critter'},
            'critters': dict(sorted(records.items()))}
