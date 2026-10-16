"""The campaign's question bank: 800 standard-depth tasks in three waves (150, 250, 400), private.

Distinct questions combine a polymer with a property, factor or comparison group that makes chemical sense for it
(by category), in five kinds. Revisits ask an earlier wave's question again (exact), reworded with the same meaning
(paraphrase), or about the same polymer and property from another angle (sibling); they only point back to earlier
waves or the 200-task run, so no task in a wave waits for another. Deterministic: the same seed gives the same bank.

Ran in `.oopc/loop/harness/2026-10-campaign/`, where it wrote questions.json (and still does); moved to the repository
on 2026-10-13 unchanged except imports and paths.
"""
import hashlib, json, random, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import STUDY, run_dir  # noqa: E402

BASE = run_dir("2026-10-campaign")
OLD_RUN = run_dir("2026-10-03-200")
SEED = "oopc-campaign-2026-10"
WAVES = {1: dict(size=150, revisits=15, property=50, method=25, effect=25, assessment=17, comparison=18),
         2: dict(size=250, revisits=50, property=75, method=37, effect=38, assessment=25, comparison=25),
         3: dict(size=400, revisits=80, property=120, method=60, effect=60, assessment=40, comparison=40)}
CHECK_SHARE = 0.08

# Per category: properties, and each factor with the properties it plausibly changes (indices into the list).
CATEGORIES = {
    "semicrystalline": (["glass transition and melting temperatures (Tg, Tm) by DSC", "degree of crystallinity from DSC or WAXD",
                         "tensile modulus and tensile strength", "elongation at break", "heat deflection temperature",
                         "water absorption at saturation", "oxygen permeability", "notched impact strength"],
                        {"annealing": [1, 2, 6, 7], "the cooling rate from the melt": [1, 2, 7], "a nucleating agent": [0, 1, 2, 4],
                         "molecular weight": [2, 3, 7], "drawing or orientation": [1, 2, 3, 6]}),
    "amorphous": (["glass transition temperature (Tg)", "tensile modulus and yield strength", "notched impact strength",
                   "light transmittance or haze", "heat deflection temperature", "water absorption",
                   "melt flow rate or melt viscosity"],
                  {"physical aging below Tg": [1, 2], "molecular weight": [0, 2, 6], "rubber or impact-modifier content": [1, 2, 3],
                   "thermal or UV aging": [2, 3]}),
    "biodegradable": (["glass transition and melting temperatures by DSC", "tensile properties of films",
                       "hydrolytic degradation (mass or molecular-weight loss)", "enzymatic degradation rate",
                       "biodegradation in compost or soil", "oxygen or water-vapor permeability"],
                      {"crystallinity": [2, 3, 5], "comonomer content": [0, 1, 2], "blending with another polymer": [1, 4, 5],
                       "a plasticizer": [0, 1], "molecular weight": [1, 2]}),
    "elastomer": (["Shore A hardness of a vulcanizate", "tensile strength and elongation at break of a vulcanizate",
                   "glass transition temperature by DSC or DMA", "compression set", "volume swell in oil or a solvent",
                   "crosslink density by equilibrium swelling"],
                  {"carbon black or silica loading": [0, 1, 3], "the cure system or crosslink density": [0, 1, 3, 4],
                   "heat aging": [0, 1, 3], "plasticizer or oil content": [0, 2]}),
    "tpe": (["Shore hardness", "tensile strength and elongation at break",
             "melting or order-disorder transition of the hard phase",
             "hysteresis or elastic recovery under cyclic loading", "glass transition of the soft phase"],
            {"hard-segment or styrene content": [0, 1, 2, 3], "annealing": [1, 2, 3], "oil or plasticizer content": [0, 1, 4]}),
    "thermoset": (["glass transition temperature by DMA", "flexural modulus and strength", "fracture toughness (KIC or GIC)",
                   "cure kinetics (activation energy) by DSC", "thermal decomposition and char yield by TGA", "water uptake"],
                  {"the curing agent or cure schedule": [0, 1, 3], "post-cure temperature": [0, 1],
                   "hygrothermal aging": [0, 1, 5], "a toughening additive": [0, 1, 2], "filler or fiber loading": [1, 2, 4]}),
    "cellulosic": (["solubility or water uptake as a function of degree of substitution", "tensile properties of cast films",
                    "solution viscosity or thermal gelation temperature", "water-vapor permeability of films",
                    "thermal degradation by TGA"],
                   {"degree of substitution": [1, 2, 3, 4], "a plasticizer": [1, 3], "molecular weight or viscosity grade": [1, 2],
                    "relative humidity": [1, 3]}),
    "water_soluble": (["swelling ratio of a crosslinked gel", "intrinsic viscosity or solution viscosity",
                       "tensile properties of films", "glass transition temperature and its dependence on water content",
                       "thermal degradation by TGA"],
                      {"crosslinker concentration": [0, 2], "molecular weight": [1, 2, 3], "pH or ionic strength": [0, 1],
                       "water content": [2, 3]}),
    "fluoropolymer": (["melting temperature and crystallinity", "tensile strength and elongation at break",
                       "dielectric constant and loss", "gas permeability", "thermal stability by TGA"],
                      {"comonomer content": [0, 1, 3], "annealing or sintering": [0, 1, 3], "irradiation": [0, 1, 4],
                       "the cooling rate": [0, 1]}),
    "ionomer": (["proton conductivity versus relative humidity", "water uptake and dimensional swelling",
                 "ion exchange capacity", "methanol or gas crossover", "tensile properties of hydrated membranes"],
                {"degree of sulfonation or equivalent weight": [0, 1, 3, 4], "annealing or heat treatment": [0, 1, 3],
                 "the casting solvent": [0, 1, 4]}),
    "conductive": (["electrical conductivity of films", "optical absorption or band gap",
                    "Seebeck coefficient or thermoelectric performance", "thermal stability", "charge-carrier mobility"],
                   {"doping level or dopant": [0, 1, 2], "annealing temperature": [0, 1, 4],
                    "solvent or additive treatment": [0, 2], "molecular weight or regioregularity": [1, 4]}),
    "fiber": (["tensile strength and modulus of fibers", "thermal decomposition temperature", "moisture regain",
               "creep or stress relaxation"],
              {"heat treatment or drawing": [0, 2, 3], "UV or thermal aging": [0], "moisture": [0, 3]}),
}

# The 40 polymers of the 200-task run (memory exists) and new ones, each with its category.
OLD = {"PET": "semicrystalline", "PMMA": "amorphous", "EVOH": "semicrystalline", "PBAT": "biodegradable",
       "PVDF": "fluoropolymer", "PNIPAM": "water_soluble", "PLA": "biodegradable", "PBS": "biodegradable",
       "PCL": "biodegradable", "PHB": "biodegradable", "PHBV": "biodegradable", "PA6": "semicrystalline",
       "PA66": "semicrystalline", "PEEK": "semicrystalline", "PPS": "semicrystalline", "polypropylene": "semicrystalline",
       "HDPE": "semicrystalline", "LDPE": "semicrystalline", "LLDPE": "semicrystalline", "polystyrene": "amorphous",
       "polycarbonate": "amorphous", "PVC": "amorphous", "PDMS": "elastomer", "PVA": "water_soluble", "TPU": "tpe",
       "PAN": "fiber", "PEDOT:PSS": "conductive", "alginate": "water_soluble", "cellulose acetate": "cellulosic",
       "chitosan": "water_soluble", "PTFE": "fluoropolymer", "PES": "amorphous", "polysulfone": "amorphous",
       "polyimide": "amorphous", "PEI": "amorphous", "ABS": "amorphous", "POM": "semicrystalline",
       "natural rubber": "elastomer", "SBR": "elastomer", "poly(acrylic acid)": "water_soluble"}
NEW = {
    "semicrystalline": ["poly(ethylene 2,5-furandicarboxylate) (PEF)", "poly(butylene terephthalate) (PBT)",
                        "poly(trimethylene terephthalate) (PTT)", "poly(ethylene naphthalate) (PEN)", "polyamide 11 (PA11)",
                        "polyamide 12 (PA12)", "polyamide 1010 (PA1010)", "polyamide 46 (PA46)", "polyamide 610 (PA610)",
                        "poly(m-xylylene adipamide) (MXD6)", "polyamide 9T (PA9T)", "isotactic polypropylene (iPP)",
                        "syndiotactic polypropylene (sPP)", "poly(1-butene) (PB-1)", "poly(4-methyl-1-pentene) (PMP)",
                        "ultra-high-molecular-weight polyethylene (UHMWPE)", "poly(ether ketone ketone) (PEKK)",
                        "aliphatic polyketone (POK)", "thermotropic liquid-crystalline polyester (LCP)",
                        "poly(vinylidene chloride) (PVDC)", "poly(ethylene oxide) (PEO)", "ethylene-vinyl acetate copolymer (EVA)",
                        "ethylene-methacrylic acid ionomer (Surlyn)"],
    "amorphous": ["styrene-acrylonitrile copolymer (SAN)", "acrylonitrile-styrene-acrylate (ASA)", "high-impact polystyrene (HIPS)",
                  "cyclic olefin copolymer (COC)", "cyclo-olefin polymer (COP)", "polyphenylsulfone (PPSU)",
                  "glycol-modified PET (PETG)", "chlorinated PVC (CPVC)", "poly(vinyl butyral) (PVB)", "PC/ABS blend",
                  "poly(phenylene ether)/polystyrene blend (PPE/PS)", "polyarylate (PAR)"],
    "biodegradable": ["poly(glycolic acid) (PGA)", "poly(L-lactide) (PLLA)", "poly(lactide-co-glycolide) (PLGA)",
                      "poly(3-hydroxybutyrate-co-3-hydroxyhexanoate) (PHBHHx)", "poly(butylene succinate-co-adipate) (PBSA)",
                      "poly(propylene carbonate) (PPC)"],
    "elastomer": ["nitrile butadiene rubber (NBR)", "hydrogenated nitrile rubber (HNBR)", "EPDM rubber", "butyl rubber (IIR)",
                  "polychloroprene rubber (CR)", "methyl-vinyl silicone rubber (VMQ)", "FKM fluoroelastomer",
                  "polybutadiene rubber (BR)", "acrylic rubber (ACM)"],
    "tpe": ["styrene-butadiene-styrene block copolymer (SBS)", "styrene-ethylene/butylene-styrene block copolymer (SEBS)",
            "styrene-isoprene-styrene block copolymer (SIS)", "thermoplastic copolyester elastomer (TPC-ET)",
            "polyether block amide (PEBA)", "thermoplastic vulcanizate (TPV)"],
    "thermoset": ["bisphenol A diglycidyl ether (DGEBA) epoxy", "epoxy novolac resin", "resole phenolic resin",
                  "novolac phenolic resin", "orthophthalic unsaturated polyester resin", "bisphenol A epoxy vinyl ester resin",
                  "melamine-formaldehyde resin", "urea-formaldehyde resin", "cyanate ester resin", "bismaleimide (BMI) resin",
                  "polybenzoxazine"],
    "cellulosic": ["methyl cellulose (MC)", "hydroxypropyl methylcellulose (HPMC)", "carboxymethyl cellulose (CMC)",
                   "ethyl cellulose (EC)", "cellulose triacetate (CTA)", "cellulose acetate butyrate (CAB)",
                   "regenerated cellulose", "thermoplastic starch (TPS)"],
    "water_soluble": ["poly(vinylpyrrolidone) (PVP)", "polyacrylamide (PAM)", "poly(2-hydroxyethyl methacrylate) (PHEMA)",
                      "poly(diallyldimethylammonium chloride) (PDADMAC)"],
    "fluoropolymer": ["poly(vinyl fluoride) (PVF)", "ethylene-tetrafluoroethylene copolymer (ETFE)",
                      "ethylene-chlorotrifluoroethylene copolymer (ECTFE)", "fluorinated ethylene propylene (FEP)",
                      "perfluoroalkoxy alkane (PFA) fluoropolymer", "poly(chlorotrifluoroethylene) (PCTFE)"],
    "ionomer": ["perfluorosulfonic acid ionomer (Nafion)", "sulfonated poly(ether ether ketone) (SPEEK)",
                "phosphoric-acid-doped polybenzimidazole (PBI)"],
    "conductive": ["poly(3-hexylthiophene) (P3HT)", "polyaniline (PANI)", "polypyrrole (PPy)", "MEH-PPV"],
    "fiber": ["poly(p-phenylene terephthalamide) (PPTA, aramid)", "poly(p-phenylene benzobisoxazole) (PBO)",
              "poly(m-phenylene isophthalamide) (PMIA)"],
}
COMPARISONS = [
    (["PET", "poly(ethylene 2,5-furandicarboxylate) (PEF)", "poly(ethylene naphthalate) (PEN)"],
     ["oxygen permeability", "glass transition temperature", "tensile modulus"]),
    (["PET", "poly(butylene terephthalate) (PBT)", "poly(trimethylene terephthalate) (PTT)"],
     ["crystallization rate or half-time", "melting temperature", "elastic recovery of fibers"]),
    (["PA6", "PA66", "polyamide 12 (PA12)"], ["water absorption at saturation", "tensile modulus dry and conditioned", "melting temperature"]),
    (["polyamide 11 (PA11)", "polyamide 12 (PA12)", "polyamide 1010 (PA1010)"], ["tensile modulus", "water absorption", "melting temperature"]),
    (["PLA", "PBS", "PBAT"], ["biodegradation in controlled composting", "tensile modulus and elongation of films", "water-vapor permeability"]),
    (["PHB", "PHBV", "poly(3-hydroxybutyrate-co-3-hydroxyhexanoate) (PHBHHx)"], ["melting temperature", "elongation at break", "degree of crystallinity"]),
    (["nitrile butadiene rubber (NBR)", "hydrogenated nitrile rubber (HNBR)", "FKM fluoroelastomer"],
     ["volume swell in oil", "heat-aging resistance", "low-temperature flexibility or Tg"]),
    (["EPDM rubber", "butyl rubber (IIR)", "natural rubber"], ["compression set", "gas permeability", "tensile strength of vulcanizates"]),
    (["PEEK", "poly(ether ketone ketone) (PEKK)", "PPS"], ["glass transition and melting temperatures", "tensile modulus", "crystallization rate"]),
    (["polysulfone", "PES", "polyphenylsulfone (PPSU)"], ["glass transition temperature", "notched impact strength", "water absorption"]),
    (["ethylene-tetrafluoroethylene copolymer (ETFE)", "fluorinated ethylene propylene (FEP)", "PTFE"],
     ["tensile elongation at break", "melting temperature", "dielectric constant"]),
    (["perfluorosulfonic acid ionomer (Nafion)", "sulfonated poly(ether ether ketone) (SPEEK)"],
     ["proton conductivity at a stated humidity", "water uptake", "methanol permeability"]),
    (["PEDOT:PSS", "poly(3-hexylthiophene) (P3HT)", "polyaniline (PANI)"], ["electrical conductivity of films", "thermal stability", "Seebeck coefficient"]),
    (["styrene-butadiene-styrene block copolymer (SBS)", "styrene-ethylene/butylene-styrene block copolymer (SEBS)",
      "styrene-isoprene-styrene block copolymer (SIS)"], ["tensile strength and elongation", "UV or thermal aging resistance", "Shore hardness"]),
    (["bisphenol A diglycidyl ether (DGEBA) epoxy", "bisphenol A epoxy vinyl ester resin", "orthophthalic unsaturated polyester resin"],
     ["glass transition temperature", "fracture toughness", "cure shrinkage"]),
    (["methyl cellulose (MC)", "hydroxypropyl methylcellulose (HPMC)", "carboxymethyl cellulose (CMC)"],
     ["solution viscosity at a stated concentration", "thermal gelation or solubility behavior", "film tensile strength"]),
    (["PVA", "poly(vinylpyrrolidone) (PVP)", "poly(ethylene oxide) (PEO)"], ["glass transition temperature", "water uptake", "film tensile strength"]),
    (["PMMA", "polycarbonate", "polystyrene"], ["refractive index or light transmittance", "notched impact strength", "glass transition temperature"]),
    (["isotactic polypropylene (iPP)", "syndiotactic polypropylene (sPP)", "polypropylene"], ["melting temperature", "notched impact strength", "crystallinity"]),
    (["ultra-high-molecular-weight polyethylene (UHMWPE)", "HDPE", "LDPE"], ["wear rate", "tensile strength", "crystallinity"]),
    (["PVDF", "poly(vinyl fluoride) (PVF)", "poly(chlorotrifluoroethylene) (PCTFE)"], ["melting temperature", "water-vapor or gas permeability", "dielectric constant"]),
    (["cyclic olefin copolymer (COC)", "cyclo-olefin polymer (COP)", "PMMA"], ["water absorption", "light transmittance", "glass transition temperature"]),
    (["high-impact polystyrene (HIPS)", "ABS", "acrylonitrile-styrene-acrylate (ASA)"], ["notched impact strength", "weathering or UV aging", "tensile strength"]),
    (["poly(glycolic acid) (PGA)", "poly(lactide-co-glycolide) (PLGA)", "poly(L-lactide) (PLLA)"], ["hydrolytic degradation rate", "glass transition temperature", "tensile strength"]),
    (["chitosan", "alginate", "carboxymethyl cellulose (CMC)"], ["swelling ratio of a crosslinked film or gel", "film tensile strength", "water-vapor permeability"]),
    (["poly(p-phenylene terephthalamide) (PPTA, aramid)", "poly(p-phenylene benzobisoxazole) (PBO)", "poly(m-phenylene isophthalamide) (PMIA)"],
     ["tensile strength and modulus of fibers", "thermal decomposition temperature", "moisture regain"]),
    (["melamine-formaldehyde resin", "urea-formaldehyde resin", "resole phenolic resin"], ["formaldehyde emission", "water resistance", "thermal decomposition by TGA"]),
    (["polyamide 9T (PA9T)", "polyamide 46 (PA46)", "PA66"], ["melting temperature", "water absorption", "heat deflection temperature"]),
]

PHRASES = {
    "property": ["What {p} has been reported for {m}? Give the value with units, the specimen or grade, and how it was measured.",
                 "Find a published measurement of {p} for {m}. Report the number with its units and the conditions needed to interpret it.",
                 "For {m}, what does the open literature report for {p}? Include specimen details, test method and conditions."],
    "method": ["How is {p} of {m} measured in a published study? Give the method, specimen preparation and test conditions, and the value obtained.",
               "Describe, from a primary source, the procedure used to measure {p} of {m}: instrument, specimen preparation, conditions and the reported result.",
               "For {m}, which test method and conditions does a published study use for {p}, and what value does it report?"],
    "effect": ["How does {f} change {p} of {m}? Give one published before/after comparison with the conditions of both.",
               "What effect of {f} on {p} has been measured for {m}? Report values for the compared specimens and how they were prepared.",
               "For {m}, report a measured change in {p} caused by {f}, with composition, processing and test conditions; separate measured effects from proposed mechanisms."],
    "assessment-grades": ["Can a single reported {p} for {m} be used across grades and processing histories? Ground the answer in specimen-specific published measurements and say what extra information is needed.",
                          "For {m}, how far does {p} vary between grades or processing histories in published measurements, and when is one value safe to use?"],
    "assessment-method": ["For {m}, how much does the test method or condition change the reported {p}? Compare published values obtained under different methods or conditions.",
                          "Do different measurement methods give different {p} for {m}? Report published values with their methods and judge whether the differences are real."],
    "comparison": ["Compare {p} of {ms} using published measurements. Give the values with their conditions and say whether they are comparable.",
                   "Rank {ms} by {p} from measured values in open sources, noting differences in specimen and test conditions."],
}
TAILS = [" Cite exact table or figure locations.", " State any requested detail you could not find.",
         " Distinguish measured results from your own interpretation."]
# The 200-task run's topics, for siblings and paraphrases of its questions.
OLD_ANGLES = ["find one open primary study of {t}. Report one bounded quantitative result and the conditions needed to interpret it.",
              "explain {t} using one open primary study. Supply the reported method, any defining equation, units, controls and specimen preparation needed to reproduce the measurement.",
              "find one open primary study of {t}. Give a bounded before/after comparison, composition, processing conditions and test protocol; distinguish measured effects from inferred mechanisms.",
              "assess {t}. Ground the answer in one or two specimen-specific open primary results, identify what can be concluded and what extra measurements or matching conditions would be needed."]


def joined(names):
    return " and ".join(names) if len(names) == 2 else ", ".join(names[:-1]) + " and " + names[-1]


def old_topics():
    """The 200-task run's (material, four targets) rows, read from its private preparer."""
    text = (STUDY / "observation_200" / "prepare.py").read_text()
    return {row[0]: row[1:] for row in eval(text[text.index("TOPICS=[") + 7:text.index("]\nTAIL")] + "]")}


def build():
    rng = random.Random(SEED)
    category = dict(OLD)
    for name, members in NEW.items():
        category.update({m: name for m in members})
    pairs = [(m, p) for m, c in category.items() for p in CATEGORIES[c][0]]
    effects = [(m, f, CATEGORIES[c][0][rng.choice(fits)]) for m, c in category.items() for f, fits in CATEGORIES[c][1].items()]
    groups = [(ms, p) for ms, props in COMPARISONS for p in props]
    for pool in (pairs, effects, groups):
        rng.shuffle(pool)
    used_pairs, bank = set(), {k: [] for k in ("property", "method", "effect", "assessment", "comparison")}

    def take_pair():
        while pairs:
            pair = pairs.pop()
            if pair not in used_pairs:
                used_pairs.add(pair)
                return pair
        raise RuntimeError("Not enough polymer-property pairs")
    for wave, plan in WAVES.items():
        for kind in bank:
            for _ in range(plan[kind]):
                variant = rng.randrange(3)
                if kind in ("property", "method"):
                    m, p = take_pair()
                    item = dict(kind=kind, materials=[m], property=p, variant=variant,
                                question=PHRASES[kind][variant].format(p=p, m=m))
                elif kind == "assessment":
                    m, p = take_pair()
                    form = rng.choice(["assessment-grades", "assessment-method"])
                    item = dict(kind=kind, form=form, materials=[m], property=p, variant=variant % 2,
                                question=PHRASES[form][variant % 2].format(p=p, m=m))
                elif kind == "effect":
                    m, f, p = effects.pop()
                    used_pairs.add((m, p))
                    item = dict(kind=kind, materials=[m], property=p, factor=f, variant=variant,
                                question=PHRASES[kind][variant].format(p=p, m=m, f=f))
                else:
                    ms, p = groups.pop()
                    item = dict(kind=kind, materials=ms, property=p, variant=variant % 2,
                                question=PHRASES[kind][variant % 2].format(p=p, ms=joined(ms)))
                if rng.random() < 0.25:
                    item["question"] += rng.choice(TAILS)
                bank[kind].append(dict(item, wave=wave))
    return bank, category, rng


def paraphrase(parent, rng):
    """The parent's question in another phrasing of the same kind, with the same meaning."""
    kind = parent["kind"]
    if kind == "old":
        material, target, angle = parent["materials"][0], parent["property"], parent["angle"]
        phrasings = {0: "What does an open primary study report for {t} in {m}? Give one quantitative result with the conditions needed to read it.",
                     1: "Using one open primary study on {m}, explain {t}: the method, any defining equation, units, controls and specimen preparation.",
                     2: "In one open primary study on {m}, how did {t} play out? Give the before/after values, composition, processing and test protocol, separating measurements from inferred mechanisms.",
                     3: "For {m}, what can be concluded about {t} from one or two specimen-specific open primary results, and what further measurements would be needed?"}
        return phrasings[angle].format(t=target, m=material)
    form = parent.get("form", kind)
    options = [i for i in range(len(PHRASES[form])) if i != parent["variant"]]
    p, ms = parent["property"], parent["materials"]
    return PHRASES[form][rng.choice(options)].format(p=p, m=ms[0], f=parent.get("factor", ""), ms=joined(ms))


def sibling(parent, rng):
    """The same polymer and property asked from another angle."""
    m, p = parent["materials"][0], parent["property"]
    if parent["kind"] == "old":
        angle = (parent["angle"] + 1) % 4
        return "For {m}, ".format(m=m) + OLD_ANGLES[angle].format(t=p), "old"
    kind = {"property": "method", "method": "property", "assessment": "property", "effect": "property",
            "comparison": "property"}[parent["kind"]]
    return PHRASES[kind][rng.randrange(3)].format(p=p, m=m), kind


def task_id(number):
    return hashlib.md5((SEED + "-" + str(number)).encode()).hexdigest()


def main():
    bank, category, rng = build()
    topics = old_topics()
    old_questions = json.loads((OLD_RUN / "questions.json").read_text())
    earlier = [dict(kind="old", materials=[q["material"]], property=topics[q["material"]][q["angle"]], angle=q["angle"],
                    question=q["question"], taskId=q["taskId"], number=None, origin="200-task run", wave=0)
               for q in old_questions if q["group"] == "distinct"]
    rows, number = [], 0
    for wave, plan in WAVES.items():
        distinct = [item for kind in bank for item in bank[kind] if item["wave"] == wave]
        rng.shuffle(distinct)
        # Revisits point back only to earlier waves (and the 200-task run), a third of each type.
        pool = earlier[:]
        rng.shuffle(pool)
        revisits = []
        for index in range(plan["revisits"]):
            parent = pool[index]
            kind = ("exact", "paraphrase", "sibling")[index % 3]
            if kind == "exact":
                question, asked = parent["question"], parent["kind"]
            elif kind == "paraphrase":
                question, asked = paraphrase(parent, rng), parent["kind"]
            else:
                question, asked = sibling(parent, rng)
            revisits.append(dict(kind=asked, revisit=kind, materials=parent["materials"], property=parent["property"],
                                 question=question, parent=parent["taskId"], parentNumber=parent["number"],
                                 parentWave=parent["wave"], wave=wave))
        tasks = distinct + revisits
        rng.shuffle(tasks)
        checks = set(rng.sample([i for i, t in enumerate(tasks) if t.get("revisit")], round(CHECK_SHARE * plan["size"] / 2)))
        checks |= set(rng.sample([i for i, t in enumerate(tasks) if not t.get("revisit")],
                                 round(CHECK_SHARE * plan["size"]) - len(checks)))
        for index, task in enumerate(tasks):
            number += 1
            task.update(number=number, taskId=task_id(number), depth="standard", checkSample=index in checks,
                        covered=any(m in OLD for m in task["materials"]),
                        categories=sorted({category[m] for m in task["materials"]}))
            task.setdefault("revisit", None)
            rows.append(task)
        earlier += [dict(t) for t in tasks if not t.get("revisit")]
    assert len(rows) == 800 and len({r["taskId"] for r in rows}) == 800
    assert len({r["question"] for r in rows if not r["revisit"]}) == 655, "distinct questions repeat"
    path = BASE / "questions.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    path.chmod(0o600)
    return rows


if __name__ == "__main__":
    import collections
    rows = main()
    for wave in WAVES:
        part = [r for r in rows if r["wave"] == wave]
        print("wave", wave, len(part), dict(collections.Counter(r["kind"] for r in part)),
              dict(collections.Counter(r["revisit"] for r in part if r["revisit"])),
              "checks", sum(r["checkSample"] for r in part), "covered", sum(r["covered"] for r in part),
              "polymers", len({m for r in part for m in r["materials"]}))
