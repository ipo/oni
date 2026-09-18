#!/usr/bin/env python3
"""Extract game data (elements, buildings, recipes) from an Oxygen Not Included install.

Usage:
    python3 tools/extract_oni_data.py \
        --game-dir /path/to/OxygenNotIncluded \
        --decompiled-dir /path/to/decompiled/Assembly-CSharp \
        --out-dir oni/data

The decompiled dir is produced by ilspycmd:
    ilspycmd OxygenNotIncluded_Data/Managed/Assembly-CSharp.dll -o out --nested-directories

Outputs:
    elements.json   - all sim elements with thermal/phase data
    buildings.json  - all constructable buildings with power/consumption/production
    recipes.json    - all fabricator/refinery recipes
"""
import argparse
import json
import os
import re

import yaml


# --------------------------------------------------------------------------
# Small C#-ish parsing helpers
# --------------------------------------------------------------------------

def find_matching(text, start, opener='(', closer=')'):
    """Return index of the closer matching the opener at text[start]."""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i
    return -1


def split_args(text):
    """Split a C# argument list on top-level commas."""
    args, depth, cur, in_str, esc = [], 0, [], False, False
    for c in text:
        if in_str:
            cur.append(c)
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            cur.append(c)
        elif c in '([{':
            depth += 1
            cur.append(c)
        elif c in ')]}':
            depth -= 1
            cur.append(c)
        elif c == ',' and depth == 0:
            args.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(c)
    if ''.join(cur).strip():
        args.append(''.join(cur).strip())
    return args


def camel_to_snake(name):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()


def parse_named_args(arglist):
    """Split args into (positional, named) respecting `name: value` syntax.

    Named args get camelCase names normalized to snake_case.
    """
    pos, named = [], {}
    for a in arglist:
        m = re.match(r'^(\w+)\s*:\s*(.+)$', a, re.S)
        if m:
            named[camel_to_snake(m.group(1))] = m.group(2).strip()
        else:
            pos.append(a)
    return pos, named


# --------------------------------------------------------------------------
# Constant table built from the decompiled sources
# --------------------------------------------------------------------------

class ConstTable:
    """Collects `const` / `static readonly` scalar and array declarations.

    Keys are dotted paths like 'TUNING.BUILDINGS.CONSTRUCTION_MASS_KG.TIER3'.
    """

    DECL_RE = re.compile(
        r'^\s*(?:public|private|internal|protected)?\s*'
        r'(?:static\s+)?(?:readonly\s+)?(?:const\s+)?'
        r'(float|int|string|bool|float\[\]|string\[\]|int\[\])\s+'
        r'(\w+)\s*=\s*(.+?);?\s*$')

    CLASS_RE = re.compile(
        r'^\s*(?:public|private|internal)?\s*(?:static\s+|abstract\s+|partial\s+|sealed\s+)*'
        r'(?:class|struct)\s+(\w+)')

    NS_RE = re.compile(r'^\s*namespace\s+([\w.]+)\s*;?\s*$')

    EFFECTOR_RE = re.compile(
        r'^\s*(?:public|private|internal)?\s*(?:static\s+)?(?:readonly\s+)?'
        r'EffectorValues\s+(\w+)\s*=\s*new EffectorValues\s*\{?')

    def __init__(self):
        self.table = {}

    def load_dir(self, root):
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if fn.endswith('.cs'):
                    self.load_file(os.path.join(dirpath, fn))

    def load_file(self, path):
        try:
            text = open(path, encoding='utf-8', errors='replace').read()
        except OSError:
            return
        scope = []
        depth = 0
        # depth at which each scope entry opened
        scope_depths = []
        pending_effector = None
        for line in text.splitlines():
            stripped = line.strip()
            if pending_effector is not None:
                am = re.match(r'^\s*(\w+)\s*=\s*(-?[\d.]+)f?,?\s*$', line)
                if am:
                    pending_effector[1][am.group(1)] = float(am.group(2))
                if '}' in line or ';' in line:
                    self.table['.'.join(scope + [pending_effector[0]])] = \
                        pending_effector[1]
                    pending_effector = None
                continue
            delta = line.count('{') - line.count('}')
            pushed = False
            m = self.NS_RE.match(line)
            if m and 'namespace' in stripped:
                if not scope:
                    scope = [m.group(1)]
            else:
                cm = self.CLASS_RE.match(line)
                if cm and '=' not in stripped:
                    scope.append(cm.group(1))
                    # marker = depth of the class body; pop once we go below it
                    new_depth = depth + delta
                    scope_depths.append(new_depth if '{' in line else new_depth + 1)
                    pushed = True
            dm = self.DECL_RE.match(line)
            if dm and scope:
                typ, name, expr = dm.group(1), dm.group(2), dm.group(3)
                val = self._literal(expr.strip(), typ)
                if val is not None:
                    self.table['.'.join(scope + [name])] = val
            else:
                em = self.EFFECTOR_RE.match(line)
                if em and scope:
                    body = line[line.index('{') + 1:] if '{' in line else ''
                    vals = dict(re.findall(r'(\w+)\s*=\s*(-?[\d.]+)f?', body))
                    vals = {k: float(v) for k, v in vals.items()}
                    if '}' in body:
                        self.table['.'.join(scope + [em.group(1)])] = vals
                    else:
                        pending_effector = (em.group(1), vals)
            depth += delta
            if not pushed:
                while scope_depths and depth < scope_depths[-1]:
                    scope_depths.pop()
                    scope.pop()

    def _literal(self, expr, typ):
        expr = expr.rstrip(';').strip()
        if typ in ('float', 'int'):
            m = re.match(r'^(-?[\d.]+)f?$', expr)
            if m:
                v = float(m.group(1))
                return int(v) if typ == 'int' else v
            return None
        if typ == 'string':
            m = re.match(r'^"(.*)"$', expr)
            return m.group(1) if m else None
        if typ == 'bool':
            return expr == 'true' if expr in ('true', 'false') else None
        if typ in ('float[]', 'int[]', 'string[]'):
            m = re.match(r'^new\s+[\w\[\]]+\s*(\[\d*\])?\s*\{(.*)\}$', expr, re.S)
            if not m:
                return None
            items = split_args(m.group(2))
            out = []
            elem = typ[:-2]
            for it in items:
                v = self._literal(it, elem)
                if v is None:
                    return None
                out.append(v)
            return out
        return None

    def lookup(self, path):
        if path in self.table:
            return self.table[path]
        for prefix in ('TUNING.', 'STRINGS.'):
            if prefix + path in self.table:
                return self.table[prefix + path]
        matches = [k for k in self.table if k.endswith('.' + path)]
        if len(matches) == 1:
            return self.table[matches[0]]
        return None


# --------------------------------------------------------------------------
# Expression resolution
# --------------------------------------------------------------------------

class Resolver:
    def __init__(self, consts):
        self.consts = consts

    def resolve(self, expr, local=None):
        """Resolve a C# expression to a Python value, or {'raw': expr}."""
        expr = expr.strip()
        local = local or {}
        # string literal
        m = re.match(r'^"(.*)"$', expr, re.S)
        if m:
            return m.group(1)
        # number
        m = re.match(r'^(-?[\d.]+)f?$', expr)
        if m:
            v = float(m.group(1))
            return int(v) if re.match(r'^-?\d+$', m.group(1)) else v
        if expr in ('true', 'false'):
            return expr == 'true'
        # new Tag("X") / "X".CreateTag() / SimHashes.X.CreateTag()
        m = re.match(r'^new Tag\("([^"]+)"\)$', expr)
        if m:
            return m.group(1)
        m = re.match(r'^"([^"]+)"\.CreateTag\(\)$', expr)
        if m:
            return m.group(1)
        m = re.match(r'^"([^"]+)"\.ToTag\(\)$', expr)
        if m:
            return m.group(1)
        m = re.match(r'^SimHashes\.(\w+)(?:\.CreateTag\(\)|\.ToString\(\))?$', expr)
        if m:
            return m.group(1)
        m = re.match(r'^GameTagExtensions\.Create\(SimHashes\.(\w+)\)$', expr)
        if m:
            return m.group(1)
        m = re.match(r'^ElementLoader\.FindElementByHash\(SimHashes\.(\w+)\)\.tag$', expr)
        if m:
            return m.group(1)
        m = re.match(r'^GameTags\.(\w+)$', expr)
        if m:
            return m.group(1)
        # simple enum member access -> bare member name
        m = re.match(r'^(ConduitType|BuildLocationRule|PermittedRotations)\.(\w+)$', expr)
        if m:
            return m.group(2)
        # CellOffset
        if expr.startswith('new CellOffset('):
            inner = expr[len('new CellOffset('):-1]
            args = split_args(inner)
            if len(args) == 2:
                return {'x': self.resolve(args[0], local),
                        'y': self.resolve(args[1], local)}
        # arrays
        m = re.match(r'^new\s+[\w.\[\]]+\s*(\[\d*\])?\s*\{(.*)\}$', expr, re.S)
        if m:
            return [self.resolve(a, local) for a in split_args(m.group(2))]
        # element access into known array constant, e.g. TIER5[0]
        m = re.match(r'^([\w.]+)\[(\d+)\]$', expr)
        if m:
            arr = self._lookup(m.group(1), local)
            if isinstance(arr, list):
                return arr[int(m.group(2))]
        # plain dotted path / identifier
        if re.match(r'^[\w.]+$', expr):
            if expr in local:
                return local[expr]
            v = self._lookup(expr, local)
            if v is not None:
                return v
            return {'raw': expr}
        return {'raw': expr}

    def _lookup(self, path, local):
        if path in local:
            return local[path]
        return self.consts.lookup(path)


def collect_local_consts(text):
    """Collect simple `float x = 1f;`-style locals from a config file."""
    out = {}
    for m in re.finditer(r'^\s*(?:public|private|internal|protected)?\s*'
                         r'(?:static\s+)?(?:const\s+)?'
                         r'(float|int|string|bool)\s+(\w+)\s*=\s*([^;=]+);',
                         text, re.M):
        typ, name, expr = m.groups()
        expr = expr.strip()
        if typ in ('float', 'int'):
            mm = re.match(r'^(-?[\d.]+)f?$', expr)
            if mm:
                out[name] = float(mm.group(1))
        elif typ == 'string':
            mm = re.match(r'^"(.*)"$', expr)
            if mm:
                out[name] = mm.group(1)
        else:
            if expr in ('true', 'false'):
                out[name] = expr == 'true'
    return out


# --------------------------------------------------------------------------
# Building config extraction
# --------------------------------------------------------------------------

CREATE_DEF_PARAMS = [
    'id', 'width', 'height', 'anim', 'hitpoints', 'construction_time',
    'construction_mass', 'construction_materials', 'melting_point',
    'build_location_rule', 'decor', 'noise', 'temperature_modification_mass_scale',
]

# BaseBatteryConfig.CreateBuildingDef(id, width, height, hitpoints, anim,
#   construction_time, construction_mass, construction_materials,
#   melting_point, exhaust_kw, self_heat_kw, decor, noise)
BATTERY_DEF_PARAMS = [
    'id', 'width', 'height', 'hitpoints', 'anim', 'construction_time',
    'construction_mass', 'construction_materials', 'melting_point',
    'exhaust_heat_kw', 'self_heat_kw', 'decor', 'noise',
]

BUILDING_PROPS = {
    'EnergyConsumptionWhenActive': 'power_consumption',
    'EnergyConsumptionWhenInactive': 'power_consumption_idle',
    'GeneratorWattageRating': 'power_generation',
    'ExhaustKilowattsWhenActive': 'exhaust_heat_kw',
    'SelfHeatKilowattsWhenActive': 'self_heat_kw',
    'Overheatable': 'overheatable',
    'OverheatTemperature': 'overheat_temperature',
    'Floodable': 'floodable',
    'Entombable': 'entombable',
    'RequiresPowerInput': 'requires_power_input',
    'RequiresPowerOutput': 'requires_power_output',
    'RequiresGasInput': 'requires_gas_input',
    'RequiresGasOutput': 'requires_gas_output',
    'RequiresLiquidInput': 'requires_liquid_input',
    'RequiresLiquidOutput': 'requires_liquid_output',
    'InputConduitType': 'input_conduit_type',
    'OutputConduitType': 'output_conduit_type',
    'BuildLocationRule': 'build_location_rule',
    'ConstructionTime': 'construction_time',
    'WidthInCells': 'width',
    'HeightInCells': 'height',
    'HitPoints': 'hitpoints',
}

INTERESTING_COMPONENTS = {
    'ElementConverter', 'EnergyGenerator', 'ConduitConsumer', 'ConduitDispenser',
    'ElementConsumer', 'BuildingElementEmitter', 'Storage', 'ElementChunkEmitter',
    'EnergyConsumer', 'Pump', 'ValveBase', 'SpaceHeater', 'AirConditioner',
    'PoweredActiveController', 'LiquidCooledRefinery',
}


def extract_call(text, marker, start=0):
    """Find `marker(` and return (arg_string, end_index) or (None, -1)."""
    idx = text.find(marker, start)
    if idx < 0:
        return None, -1
    open_idx = idx + len(marker)
    if open_idx >= len(text) or text[open_idx] != '(':
        return None, -1
    close_idx = find_matching(text, open_idx)
    if close_idx < 0:
        return None, -1
    return text[open_idx + 1:close_idx], close_idx


def parse_building_def(text, resolver, local):
    m = re.search(r'BuildingTemplates\.CreateBuildingDef\(', text)
    if not m:
        return None
    open_idx = text.index('(', m.start())
    close_idx = find_matching(text, open_idx)
    argstr = text[open_idx + 1:close_idx]
    pos, named = parse_named_args(split_args(argstr))
    return resolve_def_params(pos, named, CREATE_DEF_PARAMS, resolver, local)


def resolve_def_params(pos, named, params, resolver, local):
    out = {}
    for i, pname in enumerate(params):
        expr = named.get(pname)
        if expr is None and i < len(pos):
            expr = pos[i]
        if expr is None:
            continue
        val = resolver.resolve(expr, local)
        if isinstance(val, dict) and 'raw' in val and pname in ('decor', 'noise'):
            # keep the tier path for unresolvable effector values
            v = val['raw']
            v = re.sub(r'^(TUNING\.)?BUILDINGS\.DECOR\.', 'DECOR.', v)
            v = re.sub(r'^(TUNING\.)?', '', v)
            val = v
        out[pname] = val
    return out


def parse_assignments(text, varname):
    """Return dict of prop -> raw expr for `<varname>.<prop> = <expr>;` statements."""
    out = {}
    for m in re.finditer(r'(?<![\w.])' + re.escape(varname) + r'\.(\w+)\s*=\s*', text):
        prop = m.group(1)
        i = m.end()
        depth, in_str = 0, False
        j = i
        while j < len(text):
            c = text[j]
            if in_str:
                if c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c in '([{':
                depth += 1
            elif c in ')]}':
                depth -= 1
            elif c == ';' and depth == 0:
                break
            j += 1
        out[prop] = text[i:j].strip()
    return out


def parse_element_list(text, resolver, local, ctor, argnames):
    """Parse all `new ElementConverter.ConsumedElement(...)` style ctor calls."""
    items = []
    for m in re.finditer(re.escape(ctor) + r'\s*\(', text):
        open_idx = text.index('(', m.end() - 1)
        close_idx = find_matching(text, open_idx)
        args = split_args(text[open_idx + 1:close_idx])
        pos, named = parse_named_args(args)
        item = {}
        filled = set()
        for k, v in named.items():
            if k in argnames:
                item[k] = resolver.resolve(v, local)
                filled.add(argnames.index(k))
        pi = 0
        for i, aname in enumerate(argnames):
            if i in filled:
                continue
            if pi < len(pos):
                item[aname] = resolver.resolve(pos[pi], local)
                pi += 1
        items.append(item)
    return items


def parse_config_file(path, resolver):
    text = open(path, encoding='utf-8', errors='replace').read()
    if 'IBuildingConfig' not in text and 'BaseBatteryConfig' not in text:
        return None
    cls = re.search(r'public (?:abstract )?class (\w+)\s*:\s*([\w,\s]+)', text)
    if not cls:
        return None
    bases = cls.group(2)
    if 'IBuildingConfig' not in bases and 'BaseBatteryConfig' not in bases:
        return None

    local = collect_local_consts(text)
    rec = {'config_class': cls.group(1)}
    is_battery = 'BaseBatteryConfig' in bases and cls.group(1) != 'BaseBatteryConfig'
    if 'IBuildingConfig' in bases and cls.group(1) == 'BaseBatteryConfig':
        return None  # abstract base; subclasses carry the real data

    mid = re.search(r'public const string ID = "([^"]+)";', text)
    if mid:
        rec['id'] = mid.group(1)

    bdef = parse_building_def(text, resolver, local)
    if bdef is None and is_battery:
        m = re.search(r'=\s*CreateBuildingDef\(', text)
        if m:
            open_idx = text.index('(', m.start())
            close_idx = find_matching(text, open_idx)
            pos, named = parse_named_args(split_args(text[open_idx + 1:close_idx]))
            bdef = resolve_def_params(pos, named, BATTERY_DEF_PARAMS, resolver, local)
    if bdef:
        rec.update(bdef)
        rec.setdefault('id', bdef.get('id'))
    if 'id' not in rec:
        rec['id'] = cls.group(1).removesuffix('Config')
    if not isinstance(rec['id'], str):
        rec['id'] = cls.group(1).removesuffix('Config')

    # DLC restrictions
    dlc = re.search(r'GetRequiredDlcIds\(\)\s*\{\s*return ([^;]+);', text)
    if dlc:
        ids = re.findall(r'\b(\w*_ID)\b', dlc.group(1))
        if ids:
            rec['required_dlc'] = ids

    # BuildingDef property assignments (obj.X = ... / def.X = ...)
    defvar = re.search(r'BuildingDef (\w+) = BuildingTemplates\.CreateBuildingDef', text)
    if defvar:
        for prop, expr in parse_assignments(text, defvar.group(1)).items():
            if prop in BUILDING_PROPS:
                key = BUILDING_PROPS[prop]
                if key not in rec:
                    rec[key] = resolver.resolve(expr, local)

    # Components: `Type var = go.AddOrGet<Type>();` (or AddComponent)
    decls = list(re.finditer(
        r'(\w+)\s+(\w+)\s*=\s*go\.(?:AddOrGet|AddComponent)<(\w+)>\(\);', text))
    for idx, m in enumerate(decls):
        end = decls[idx + 1].start() if idx + 1 < len(decls) else len(text)
        section = text[m.start():end]
        vartype, varname = m.group(3), m.group(2)
        if vartype not in INTERESTING_COMPONENTS:
            continue
        props = parse_assignments(text, varname)
        comp = {}
        for prop, expr in props.items():
            if prop in ('consumedElements', 'outputElements', 'formula'):
                continue
            comp[prop] = resolver.resolve(expr, local)
        if vartype == 'ElementConverter':
            consumed = parse_element_list(
                section, resolver, local, 'new ElementConverter.ConsumedElement',
                ['element', 'kg_per_second', 'is_active'])
            produced = parse_element_list(
                section, resolver, local, 'new ElementConverter.OutputElement',
                ['kg_per_second', 'element', 'min_temperature', 'use_entity_temperature',
                 'store_output', 'offset_x', 'offset_y'])
            if consumed:
                comp['consumed'] = consumed
            if produced:
                comp['produced'] = produced
        if vartype == 'EnergyGenerator':
            args, _ = extract_call(section, 'EnergyGenerator.CreateSimpleFormula')
            if args:
                pos, named = parse_named_args(split_args(args))
                names = ['element', 'kg_per_second', 'max_stored_kg', 'output_element',
                         'output_kg_per_second', 'store_output_mass', 'output_offset',
                         'min_output_temperature']
                formula = {}
                for i, aname in enumerate(names):
                    expr = named.get(aname)
                    if expr is None and i < len(pos):
                        expr = pos[i]
                    if expr is not None:
                        formula[aname] = resolver.resolve(expr, local)
                comp['formula'] = formula
            inputs = parse_element_list(
                section, resolver, local, 'new EnergyGenerator.InputItem',
                ['element', 'kg_per_second', 'max_stored_kg'])
            outputs = parse_element_list(
                section, resolver, local, 'new EnergyGenerator.OutputItem',
                ['element', 'kg_per_second', 'store', 'offset', 'min_temperature'])
            if inputs:
                comp.setdefault('formula', {})['inputs'] = inputs
            if outputs:
                comp.setdefault('formula', {})['outputs'] = outputs
        comps = rec.setdefault('components', {})
        key = vartype
        n = 2
        while key in comps:
            key = f'{vartype}#{n}'
            n += 1
        comps[key] = comp

    # inline chained: go.AddOrGet<Storage>().capacityKg = 10f;
    for m in re.finditer(r'go\.AddOrGet<(\w+)>\(\)\.(\w+)\s*=\s*([^;]+);', text):
        ctype, prop, expr = m.groups()
        if ctype in INTERESTING_COMPONENTS:
            rec.setdefault('components', {}).setdefault(ctype, {})[prop] = \
                resolver.resolve(expr, local)

    return rec


# --------------------------------------------------------------------------
# Recipe extraction (static recipes only)
# --------------------------------------------------------------------------

def parse_recipes(path, resolver):
    text = open(path, encoding='utf-8', errors='replace').read()
    if 'ComplexRecipe' not in text:
        return []
    local = collect_local_consts(text)

    arrays = {}
    for m in re.finditer(
            r'ComplexRecipe\.RecipeElement\[\]\s+(\w+)\s*=\s*new\s+'
            r'ComplexRecipe\.RecipeElement\s*\[\s*\d*\s*\]\s*\{', text):
        varname = m.group(1)
        open_idx = text.index('{', m.end() - 1)
        close_idx = find_matching(text, open_idx, '{', '}')
        body = text[open_idx:close_idx + 1]
        elems = []
        for em in re.finditer(r'new ComplexRecipe\.RecipeElement\(', body):
            eo = body.index('(', em.end() - 1)
            ec = find_matching(body, eo)
            args = split_args(body[eo + 1:ec])
            pos, named = parse_named_args(args)
            elem = {}
            names = ['material', 'amount', 'temperature_operation', 'store_element']
            for i, aname in enumerate(names):
                expr = named.get(aname)
                if expr is None and i < len(pos):
                    expr = pos[i]
                if expr is not None:
                    elem[aname] = resolver.resolve(expr, local)
            elems.append(elem)
        arrays[varname] = elems

    recipes = []
    for m in re.finditer(r'(?:(\w+)\s*=\s*)?new ComplexRecipe\(', text):
        varname = m.group(1) or ''
        open_idx = text.index('(', m.end() - 1)
        close_idx = find_matching(text, open_idx)
        args = split_args(text[open_idx + 1:close_idx])
        rec = {'ingredients': [], 'results': []}
        if len(args) >= 3:
            rec['ingredients'] = arrays.get(args[1], [])
            rec['results'] = arrays.get(args[2], [])
        mid = re.search(r'MakeRecipeID\("([^"]+)"', args[0])
        if mid:
            rec['fabricator'] = mid.group(1)
        # object initializer right after ctor: { time = 40f, ... }
        im = re.match(r'\s*\{', text[close_idx + 1:close_idx + 400])
        if im:
            bo = text.index('{', close_idx + 1)
            bc = find_matching(text, bo, '{', '}')
            body = text[bo + 1:bc]
            tm = re.search(r'time\s*=\s*([^,}]+)', body)
            if tm:
                rec['time'] = resolver.resolve(tm.group(1), local)
            fm = re.search(r'TagManager\.Create\("([^"]+)"\)', body)
            if fm and 'fabricator' not in rec:
                rec['fabricator'] = fm.group(1)
        if varname:
            tm = re.search(re.escape(varname) + r'\.time\s*=\s*([\w.]+)f?;', text)
            if tm:
                rec['time'] = resolver.resolve(tm.group(1), local)
        if rec['ingredients'] or rec['results']:
            recipes.append(rec)
    return recipes


# --------------------------------------------------------------------------
# Elements / strings
# --------------------------------------------------------------------------

def load_elements(elements_dir, strings):
    elements = {}
    for fn in sorted(os.listdir(elements_dir)):
        if not fn.endswith('.yaml'):
            continue
        with open(os.path.join(elements_dir, fn), encoding='utf-8') as f:
            data = yaml.safe_load(f)
        for e in data.get('elements', []):
            eid = e.get('elementId')
            if not eid:
                continue
            rec = {
                'state': e.get('state'),
                'dlc': e.get('dlcId') or None,
                'disabled': e.get('isDisabled', False),
                'specific_heat_capacity': e.get('specificHeatCapacity'),
                'thermal_conductivity': e.get('thermalConductivity'),
                'molar_mass': e.get('molarMass'),
                'hardness': e.get('hardness'),
                'default_temperature': e.get('defaultTemperature'),
                'max_mass': e.get('maxMass'),
                'material_category': e.get('materialCategory'),
                'tags': e.get('tags') or [],
                'offgas_percentage': e.get('offGasPercentage'),
                'sublimation_rate': e.get('sublimateRate'),
                'sublimation_target': e.get('sublimateId'),
            }
            loc = e.get('localizationID')
            if loc and loc in strings:
                rec['name'] = clean_name(strings[loc])
            for direction in ('low', 'high'):
                target = e.get(f'{direction}TempTransitionTarget')
                if target:
                    rec[f'{direction}_temp_transition'] = {
                        'temperature': e.get(f'{direction}Temp'),
                        'target': target,
                        'ore': e.get(f'{direction}TempTransitionOreId'),
                        'ore_mass_conversion': e.get(f'{direction}TempTransitionOreMassConversion'),
                    }
            elements[eid] = {k: v for k, v in rec.items() if v is not None}
    return elements


def load_strings(pot_path):
    strings = {}
    ctx = None
    for line in open(pot_path, encoding='utf-8', errors='replace'):
        m = re.match(r'msgctxt "((?:[^"\\]|\\.)*)"', line)
        if m:
            ctx = m.group(1)
            continue
        m = re.match(r'msgid "((?:[^"\\]|\\.)*)"', line)
        if m and ctx:
            val = m.group(1).replace('\\"', '"').replace('\\n', '\n')
            if val:
                strings[ctx] = val
            ctx = None
    return strings


def clean_name(s):
    """Strip <link> markup from localized names."""
    return re.sub(r'<[^>]+>', '', s)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game-dir', required=True,
                    help='Path to the OxygenNotIncluded install directory')
    ap.add_argument('--decompiled-dir', required=True,
                    help='Path to decompiled Assembly-CSharp sources')
    ap.add_argument('--out-dir', required=True)
    args = ap.parse_args()

    sa = os.path.join(args.game_dir, 'OxygenNotIncluded_Data', 'StreamingAssets')
    os.makedirs(args.out_dir, exist_ok=True)

    print('loading strings...')
    strings = load_strings(os.path.join(sa, 'strings', 'strings_template.pot'))
    print(f'  {len(strings)} strings')

    print('loading elements...')
    elements = load_elements(os.path.join(sa, 'elements'), strings)
    with open(os.path.join(args.out_dir, 'elements.json'), 'w') as f:
        json.dump(elements, f, indent=1, sort_keys=True)
    print(f'  {len(elements)} elements -> elements.json')

    print('building constant table...')
    consts = ConstTable()
    consts.load_dir(args.decompiled_dir)
    print(f'  {len(consts.table)} constants')
    resolver = Resolver(consts)

    buildings, recipes, failed = {}, {}, 0
    for fn in sorted(os.listdir(args.decompiled_dir)):
        if not fn.endswith('Config.cs'):
            continue
        path = os.path.join(args.decompiled_dir, fn)
        try:
            rec = parse_config_file(path, resolver)
        except Exception as e:
            print(f'  WARN: {fn}: {e}')
            failed += 1
            continue
        if rec:
            bid = rec.pop('id')
            name_key = f'STRINGS.BUILDINGS.PREFABS.{bid.upper()}.NAME'
            if name_key in strings:
                rec['name'] = clean_name(strings[name_key])
            buildings[bid] = rec
        for r in parse_recipes(path, resolver):
            key = r.get('fabricator', fn.removesuffix('.cs'))
            recipes.setdefault(key, []).append(r)
    with open(os.path.join(args.out_dir, 'buildings.json'), 'w') as f:
        json.dump(buildings, f, indent=1, sort_keys=True)
    with open(os.path.join(args.out_dir, 'recipes.json'), 'w') as f:
        json.dump(recipes, f, indent=1, sort_keys=True)
    print(f'  {len(buildings)} buildings -> buildings.json '
          f'({failed} files failed to parse)')
    print(f'  {sum(len(v) for v in recipes.values())} recipes across '
          f'{len(recipes)} fabricators -> recipes.json')


if __name__ == '__main__':
    main()
