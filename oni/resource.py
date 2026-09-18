__all__ = ['all_resources', 'RESOURCES']

RESOURCES = []


class ResourceMeta(type):

    def __repr__(cls):
        return cls.__name__


def all_resources():
    """Return a list of all resources"""
    return sorted(RESOURCES, key=str)


def _get_or_create_resource(name):
    if name not in globals():

        result = ResourceMeta(name, tuple(), {})
        globals()[name] = result
        RESOURCES.append(result)
        __all__.append(name)

    return globals()[name]


# Liquids and gases are auto-generated from the game's element data
# (oni/data/elements.json); see tools/extract_oni_data.py.

LIQUIDS = [
    _get_or_create_resource("Brine"),
    _get_or_create_resource("Chlorine"),
    _get_or_create_resource("CrudeOil"),
    _get_or_create_resource("DirtyWater"),
    _get_or_create_resource("Ethanol"),
    _get_or_create_resource("FishMilk"),
    _get_or_create_resource("Ink"),
    _get_or_create_resource("Latex"),
    _get_or_create_resource("LiquidCarbonDioxide"),
    _get_or_create_resource("LiquidGunk"),
    _get_or_create_resource("LiquidHydrogen"),
    _get_or_create_resource("LiquidMethane"),
    _get_or_create_resource("LiquidOxygen"),
    _get_or_create_resource("LiquidPhosphorus"),
    _get_or_create_resource("LiquidPropane"),
    _get_or_create_resource("LiquidSulfur"),
    _get_or_create_resource("Magma"),
    _get_or_create_resource("Mercury"),
    _get_or_create_resource("Milk"),
    _get_or_create_resource("MoltenAluminum"),
    _get_or_create_resource("MoltenCarbon"),
    _get_or_create_resource("MoltenCobalt"),
    _get_or_create_resource("MoltenCopper"),
    _get_or_create_resource("MoltenGlass"),
    _get_or_create_resource("MoltenGold"),
    _get_or_create_resource("MoltenIridium"),
    _get_or_create_resource("MoltenIron"),
    _get_or_create_resource("MoltenLead"),
    _get_or_create_resource("MoltenNickel"),
    _get_or_create_resource("MoltenNiobium"),
    _get_or_create_resource("MoltenSalt"),
    _get_or_create_resource("MoltenSteel"),
    _get_or_create_resource("MoltenSucrose"),
    _get_or_create_resource("MoltenTungsten"),
    _get_or_create_resource("MoltenUranium"),
    _get_or_create_resource("MoltenZinc"),
    _get_or_create_resource("Mucus"),
    _get_or_create_resource("MurkyBrine"),
    _get_or_create_resource("Naphtha"),
    _get_or_create_resource("NaturalResin"),
    _get_or_create_resource("NuclearWaste"),
    _get_or_create_resource("Petroleum"),
    _get_or_create_resource("PhytoOil"),
    _get_or_create_resource("RefinedLipid"),
    _get_or_create_resource("Resin"),
    _get_or_create_resource("SaltWater"),
    _get_or_create_resource("SugarWater"),
    _get_or_create_resource("SuperCoolant"),
    _get_or_create_resource("ViscoGel"),
    _get_or_create_resource("Water"),
]


GASES = [
    _get_or_create_resource("AluminumGas"),
    _get_or_create_resource("CarbonDioxide"),
    _get_or_create_resource("CarbonGas"),
    _get_or_create_resource("ChlorineGas"),
    _get_or_create_resource("CobaltGas"),
    _get_or_create_resource("ContaminatedOxygen"),
    _get_or_create_resource("CopperGas"),
    _get_or_create_resource("EthanolGas"),
    _get_or_create_resource("Fallout"),
    _get_or_create_resource("GoldGas"),
    _get_or_create_resource("Hydrogen"),
    _get_or_create_resource("IridiumGas"),
    _get_or_create_resource("IronGas"),
    _get_or_create_resource("LeadGas"),
    _get_or_create_resource("MercuryGas"),
    _get_or_create_resource("Methane"),
    _get_or_create_resource("NickelGas"),
    _get_or_create_resource("NiobiumGas"),
    _get_or_create_resource("Oxygen"),
    _get_or_create_resource("PhosphorusGas"),
    _get_or_create_resource("RockGas"),
    _get_or_create_resource("SaltGas"),
    _get_or_create_resource("SourGas"),
    _get_or_create_resource("Steam"),
    _get_or_create_resource("SteelGas"),
    _get_or_create_resource("SulfurGas"),
    _get_or_create_resource("SuperCoolantGas"),
    _get_or_create_resource("TungstenGas"),
    _get_or_create_resource("ZincGas"),
]
