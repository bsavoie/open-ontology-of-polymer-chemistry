"""Deterministic rules for the E3 property map (study analysis, not ontology vocabulary).

normalize() turns a finding's free-text `property` into the map key.
classify() returns (class_id, rule_index) for the first matching rule, or
(None, rule_index) when a rule deliberately defers the string to a manual
assignment, or (None, None) when no rule matches.
method() returns the measurement methods and standards named in the string.

Rules are ordered: deferrals and exceptions first, then method and instrument,
replicates, test conditions, specimen and preparation, composition and
formulation, and finally material properties, so that "tensile test
temperature" is a test condition and "tensile strength" a property. Each rule
has an include pattern and an optional exclude pattern; the first rule whose
include matches and whose exclude does not wins.
"""
import re
import unicodedata

_DASHES = re.compile("[‐‑‒–—―−⁃﹘﹣－]")
_QUOTES = str.maketrans({
    "‘": "'", "’": "'", "‛": "'", "′": "'", "´": "'", "`": "'",
    "“": '"', "”": '"', "‟": '"', "″": '"',
})


def normalize(text):
    """NFKC, unified dashes and quotes, lowercase, collapsed whitespace."""
    s = unicodedata.normalize("NFKC", text or "")
    s = _DASHES.sub("-", s)
    s = s.translate(_QUOTES)
    s = s.lower()
    return re.sub(r"\s+", " ", s).strip()


def strip_abbreviation(s):
    """The normalized string without parenthesized or bracketed groups."""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\s*\([^()]*\)", "", s)
        s = re.sub(r"\s*\[[^\[\]]*\]", "", s)
    return re.sub(r"\s+", " ", s).strip(" ,;")


# --------------------------------------------------------------------------
# Shared fragments
PROC = (r"(mou?ld|mou?lding|injection|extru|compound|mixing|mixer|blending|pressing|press\b|hot-press|"
        r"calender|printing|printed|print\b|nozzle|barrel|screw|\bdie\b|roll\b|roller|banbury|kneading|"
        r"sintering|film-blowing|film blowing|blown|cast-film|chill-roll|compaction|compression-forming|"
        r"compression forming|milling|\bmill\b|pelleti|granulat|dynamic packing|infill|additive manufacturing|"
        r"spinning|electrospinning|vulcani|curing|\bcure\b|casting|coating|polymeri[sz]ation|synthesis)")
TEST_CTX = r"(test|testing|tested|measurement|measuring|measured|assay|experiment)"

R = []  # (class or None, include, exclude)


def rule(cls, include, exclude=None):
    R.append((cls, re.compile(include), re.compile(exclude) if exclude else None))


# ---- 0. Exceptions and deferrals -----------------------------------------
rule("observation-interpretation",
     r"(proposed[- a-z]*mechanism|mechanism of|agreement between|^interpretation|author-proposed)")
rule("barrier-other", r"(water[- ]retention value|hydrogen retention|\bwrv\b)")
rule("property-retention-after-aging",
     r"((tensile|elongation|strength|modulus|hardness|impact|stress|strain|shore)[^;]*\b(retention|retained|change after|"
     r"after (heat|thermal|oven|uv|oil|fuel|fluid|hot|accelerated|ag(e)?ing|immersion|exposure|weathering|irradiation|"
     r"steam|hydrothermal))|\b(retention|change) (of|in) (tensile|elongation|hardness|shore|strength|modulus|impact)|"
     r"hardness change)",
     r"(ionic-liquid|test|method|temperature$|duration$)")
rule("molar-mass-loss",
     r"((molecular[- ]weight|molar[- ]mass|\bmn\b|\bmw\b|viscosity[- ]number|solution viscosity|intrinsic viscosity)"
     r"[^;]*(decrease|reduction|\bloss\b|retention)|residual (number|weight)-average|relative solution viscosity reduction)")
rule("dimensional-stability",
     r"(thickness swelling|(length|cross-section|width|dimensional|thickness) change|dimensional stability)",
     r"(temperature|humidity|duration|reference)")
rule("volume-swell", r"^(volume change|volume swell|volumetric swell)|volume swell|\(δv/v0\)",
     r"(duration|method|specimen|temperature|preparation|ratio)")
# Strings reporting a change, a statistic, a dependence or a threshold are assigned by hand.
rule(None, r"\b(change|changes|increase|increases|increased|decrease|decreases|decreased|enhancement|improvement|"
           r"reduction|difference|shift|dependence|effect of|effect on|influence of|versus|vs|relationship|"
           r"standard deviation|coefficient of variation|c\.o\.v|uncertainty|error|threshold|without detectable)\b")

# ---- 1. Method and instrument --------------------------------------------
rule("analysis-criterion",
     r"(criterion|criteria|definition|defining equation|\bdefined as\b|fitting interval|fitting range|calculation|"
     r"analysis method|estimation method|kinetic model|mass reference|enthalpy of (a |the )?100 ?%|"
     r"100 ?% crystalline|δh[mf]?0\b|δh[mf]?°|\bconvention\b|baseline determination|baseline correction|averaging|"
     r"used for (uptake|conversion|calculation)|reference[- a-z]*(enthalpy|heat of fusion)|fully crystalline|"
     r"δh100|strain interval|evaluation interval|accuracy|correction|basis of|reference-mass|mass-reference|"
     r"analysis interval|reference thickness|conversion inputs|experimental deviation|standard melting enthalpy)",
     r"(cloud point by|cloud-point range|thickness-normali[sz]ed convention)")
rule("instrument",
     r"(instrument|equipment|apparatus|machine|\btester\b|analy[sz]er|load[- ]?cell|crucible|\bpans?\b|container|"
     r"containment|enclosure|\bholder\b|calibration standard|\bdsc standard|spectrometer|spectrophotometer|microscope|"
     r"diffractometer|manufacturer|durometer type|viscometer$|rheometer$|chemiluminescence|balance range)",
     PROC[:-1] + r"|direction|instrumented|specimen preparation|specimen-preparation|fabrication|manufacturing|"
     r"maximum energy|pendulum energy)")

# ---- 2. Replicates -------------------------------------------------------
rule("replicate-count",
     r"(replicat|repetition|\b(specimen|sample|test|measurement|reading|repeat|filament)s? (count|number)\b|"
     r"number of (test |tested )?(replicates|specimens|samples|tests|measurements|repeats|runs)|specimens? per|"
     r"measurements? per|readings? per|^count$|averaging count|(dsc|tga|dma|tensile|impact|flexural|fracture|"
     r"hardness|electrical-test)[- a-z]*(sample|specimen|replicate|measurement|test) count)",
     r"(spun-yarn|yarn)")

# ---- 3. Test conditions --------------------------------------------------
rule("heating-cooling-rate",
     r"((heating|cooling|scan|scanning|ramp|temperature ramp|temperature scan|heating/cooling|"
     r"cooling/heating|heating and cooling|heating-and-cooling)[- ]?(rate|rates)|heating[- ]rate (range|series|increment))",
     r"(mou?ld|post-|anneal|cure-cycle|processing|voltammetry|dependence|at melting|quench|from the melt|angular|"
     r"imidization|preparation cooling|sintering)")
rule("thermal-program", r"((cycle|run|scan) used for|erasure)")
rule("thermal-program",
     r"((dsc|tga|dma|dmta|dta|tma|calorimet|thermogravimetr|dynamic mechanical|thermal analysis|\bhdt\b|heat deflection)"
     r"[^;]*(range|interval|endpoint|end point|upper|lower|maximum temperature|minimum temperature|final temperature|"
     r"starting temperature|initial temperature|hold|holding|isotherm|program|protocol|cycle|\brun\b|scan(?! rate)|"
     r"equilibration|modulation|melt temperature|melt-treatment|melt hold|loading temperature|precooling|reheating|"
     r"conditioning|heating interval|cooling interval|evaluation|heating step|heating run|first-heating|second heating|"
     r"cooling temperature|upper temperature|predrying|preheating))",
     r"(glass[- ]transition|\btg\b|melting (peak )?temperature|\btm\b|crystallinity|enthalpy|δh|mass loss|residu|"
     r"decomposition temperature|degradation temperature|onset temperature|peak temperature|half-time|replicate|"
     r"instrument|heating rate|heating-rate|cooling rate|scan rate|scanning rate|water-loss|mass-loss|specimen|outer-face|"
     r"deflection (endpoint|criterion))")
rule("test-method-standard",
     r"(\bmethod\b|\bmethods\b|\bstandard\b|\bstandards\b|procedure|protocol|technique|\bastm\b|\bmode\b(?![- ]i\b)|"
     r"measurement$|\bmeasured by\b|characterization method|co2 measurement)",
     r"(preparation|synthesis|compounding|casting|processing|fabrication|mou?lding|mixing|polymeri[sz]ation|"
     r"standard deviation|analysis method|calculation|specimen standard|draw|drying|storage|anneal|cooling|cleaning|"
     r"replacement|pressing|applied stress|, method [ab]$|in methods|standard melting|heating rate)")
rule("test-atmosphere",
     r"(atmosphere|purge|air sweep|sweep gas|carrier gas|heating medium|(nitrogen|argon|helium|\bair\b|oxygen|\bgas\b|"
     r"\bn2\b)[- ](volumetric )?(flow|purity|supply)|gas flow|flow of nitrogen|vacuum level|electrical measurement "
     r"pressure|test-gas purity)",
     r"(melt|solution|feed|electrospinning|anneal|water|device|condition|irradiation)")
rule("test-rate",
     r"(crosshead|cross-head|cross head|test(ing)? speed|test(ing)? rate|strain rate|extension rate|elongation rate|"
     r"displacement rate|loading rate|deformation rate|pulling rate|stretching speed|travel speed|separation (rate|speed)|"
     r"jaw speed|testing velocity|(tensile|flexural|compression|compressive|fracture|tear|peel|mechanical|bending|"
     r"cyclic tensile|elastic-recovery|modulus|yield strength)[- a-z]*(speed|rate)$|traverse velocity|"
     r"sliding (speed|velocity))",
     r"(drawing|\bdraw|electrospinning|spinning|winding|extrusion|screw|roll|injection|creep rate|strength rate|cooling|"
     r"glass transition|notching)")
rule("test-frequency-amplitude",
     r"(frequency|frequencies|amplitude|shear rate|oscillation|strain sweep|frequency sweep|mean level|force-track|"
     r"analysis deformation|(dmta|dma|oscillatory|measurement|rheometry|gelation measurement)[- a-z()]* strain$|"
     r"^oscillatory strain)",
     r"(crossover|relaxation frequency|half-power|piston|packing|\bat\b|film-forming|washing|roll)")
rule("test-load",
     r"(test stress|applied (flexural |tensile )?stress|loading stress|test load|applied load|normal load|load per|"
     r"fibre stress|fiber stress|pendulum (energy|capacity|height|potential|impact speed)|pendulum capacity|"
     r"impact-test hammer|impact velocity|drop height|drop weight|dart mass|striker|apparatus maximum energy|"
     r"tester pendulum|applied (compression|compressive|strain|elongation|deformation|pressure|force|voltage|current|"
     r"load)|compressive strain|compressed thickness fraction|compressive force$|pre-force|preload|pre-load|"
     r"(hdt|heat deflection)[^;]*(stress|load\b|deflection endpoint|deflection criterion|endpoint displacement)|"
     r"heat-deflection endpoint|test pressure|feed pressure|upstream pressure|pressure differential|"
     r"transmembrane pressure|surface pressure|(mfr|melt flow|melt mass-flow|melt volume-flow)[^;]*(load|weight\b|mass\b)|"
     r"deflection (criterion|endpoint)|measurement pressure|cyclic peak stress|maximum extension criterion|"
     r"applied elongation|feed-pressure|cyclic[- a-z]*maximum[- a-z]*(strain|stretch)|outer-face strain|"
     r"piezoelectric measurement dynamic force|viscosity extrusion pressure|maximum-stretch sequence)",
     r"(anneal|retention|mou?lding|electrospinning|forming|strength)")
rule("test-geometry",
     r"(support span|\bspan\b|clamp|grip (distance|separation)|gauge separation|chuck separation|jaw separation|"
     r"plate (diameter|gap)|rheometer (plate|gap|geometry)|\bgap\b|exposed (specimen )?area|exposure area|"
     r"permeation area|test area|cell area|effective area|die dimensions|capillary (die|length|diameter|nozzle)|"
     r"\bl/d\b|probe spacing|electrode (distance|spacing)|free (bending|clamping) length|grip distance|indenter|anvil|"
     r"orifice|spacer height|contact geometry|exposed specimen diameter)",
     r"(casting|knife|coating|electrospinning|needle-to-collector|syringe|printing|nozzle temperature|band gap|"
     r"energy gap|\bmill\b|nip)")
rule("test-duration",
     r"(test|immersion|immersed|ag(e)?ing|exposure|incubation|soak|soaking|hold|holding|compost|composting|burial|"
     r"hydrolysis|degradation|swelling|storage|absorption|sorption|permeation|permeability|measurement|weathering|"
     r"irradiation|cryogenic|\boil\b|fuel|water|recovery|sampling|weighing|drainage|biodegradation|preheating|reading|"
     r"gelation)[- a-z()]*(duration|period|interval|time)$",
     r"(half-time|half-life|induction|time to|saturation time|gel time|cure time|scorch|dissolution time|lag|"
     r"relaxation time|breakthrough|drying|dry|anneal|cure|curing|vulcan|mou?ld|extru|mixing|compounding|pressing|"
     r"casting|conditioning|synthesis|polymeri[sz]ation|reaction|spinning|coating|heat-treatment|evaporation|"
     r"preparation|quench|blending|\bpre-|\bpost-|premelting|cooling time|holding time|hold time|temperature|onset|"
     r"pretest|coagulation|doping|washing|stretched|precrystallization)")
rule("exposure-conditions",
     r"((ag(e)?ing|immersion|immersed|hydrolysis|hydrolytic|degradation (medium|buffer|test|incubation|assay|solution)|"
     r"compost|composting|incubation|burial|weathering|exposure|soak|hydrothermal|\boil\b|\bfuel\b|\bfluid\b|"
     r"buffer|enzyme|enzymatic|cryogenic|seawater|biodegradation|\buv\b|irradiation|radiation|gamma|chlorine|"
     r"naocl|boiling|autoclave|leaching|medium|wet annealing|water-conditioning|degradation incubation)"
     r"[- a-z()0-9]*\b(temperature|ph|concentration|volume|medium|media|dose|irradiance|intensity|humidity|"
     r"moisture content|water content|loading|agitation|stirring speed|fluid|liquid|environment|conditions|"
     r"identity|activity|mass|pressure)$|irradiation dose|absorbed dose|gamma dose)",
     r"(half-life|mass loss|weight loss|test method|naphthenic|paraffinic|circosol|oil loading|relaxation|signal|"
     r"product|drying|test sample mass|sample loading)")
rule("test-humidity",
     r"(water activity during|water vapou?r pressure during|water-vapor permeability test (high|low)-side)")
rule("test-humidity", r"(relative humidity|relative-humidity|\brh\b|humidity|water activity$|% rh)",
     r"(condition|storage|stored|anneal|equilibrat|ambient dry-state|drying|absorption at|saturation)")
rule("test-temperature",
     r"(" + TEST_CTX + r"|viscometry|rheolog\w*|rheometry|permeation|permeability|sorption|swelling|transmission|"
     r"impact|tensile|flexural|fracture|hardness)[- a-z()]* temperature$|^temperature of measurement|^test temperature",
     r"(transition|melting|softening|deflection|crystalli[sz]ation|decomposition|onset|peak|\btg\b|\btm\b|"
     r"brittle|gelation|cloud|failure|condition|mou?lding|pressing|heat-treatment|anneal|drying|pretest heating)")
rule("test-temperature",
     r"((measurement|test|testing) temperature (range|interval)$|temperature sweep range|measurement temperature "
     r"stability|test temperature interval)")
rule("measurement-solution",
     r"(polymer (mass )?concentration|solution (mass )?concentration|specimen concentration|sample concentration|"
     r"dispersion concentration|measurement solvent|solvent for (measurement|viscosity)|test solution|viscosity[^;]*"
     r"(concentration|solvent)|(gpc|solubility|viscosity)[- a-z]*solvent (composition|volume)|titrant concentration)",
     r"(casting|film-forming|electrospinning|spinning|coating|dope|preparation|synthesis|polymeri[sz]ation|"
     r"crosslinker|feed)")
rule("test-condition-other",
     r"(^blank (carbon|control|co2)|inoculum|^control loading|measurement current|electrical-test current|"
     r"test current|cycle count$|potential range|electrolyte concentration|electrode (conditioning|polishing)|"
     r"wear-test|counterface|angular scan range|wavelength range|measurement wavelength|transmittance wavelength|"
     r"control specimen|cup solution volume|test water volume|weighing count|acquisition (interval|settings)|"
     r"exhaust-cycle|endpoint dwell|deflection-zeroing|saturated bath composition)",
     r"(molding)")

# ---- 4. Specimen and preparation -----------------------------------------
rule("specimen-thickness", r"thickness",
     r"(swelling|normali[sz]ed|lamell|crystal|fraction|casting (thickness|knife)|casting-frame|draw-bar|applicator|"
     r"printed layer|layer height|change|recovered thickness|reference thickness|wet casting)")
rule("specimen-mass",
     r"((specimen|sample|test portion|\bdsc\b|\btga\b|\bdvs\b|swelling|compost test)[- a-z()]* (mass|weight)$|"
     r"(sample|specimen) (mass|weight)\b)",
     r"(loss|change|gain|fraction|ratio|molecular|molar|residual)")
rule("specimen-dimensions",
     r"((specimen|sample|\bbar\b|plate|plaque|film|disc|disk|piece|coupon|dumbbell|tensile|impact|flexural|charpy|"
     r"izod|\bdma\b|dmta|\bhdt\b|compression-set|compact-tension|fracture|absorption|uptake|degradation|compost|"
     r"composting|dielectric|optical|rheology|membrane|sheet|device|tear|wear|mould|mold)[- a-z()]*"
     r"(dimension|dimensions|\bwidth|\blength|\bdiameter|geometry|cross section|cross-section|shape|\btype\b|"
     r"gauge|notch (depth|angle|radius|type|configuration)|\barea\b|\bheight|planar|volume \(vdry\)|designation)|"
     r"gauge length|gage length|notch depth|notch-tip|notch angle|notch radius|crack length|crack-length|ligament|"
     r"kerf|specimen type)",
     r"(particle|pore|crystal|lamell|spherulite|domain|bead|powder|filler|change|swelling ratio|molecular|chain|"
     r"\bdraw|elongation|exposed|exposure area|permeation area|test area|effective area|strength|resistance|energy|"
     r"screw|spacer|stretching|ratio$|wavelength|optical absorption)")
rule("specimen-preparation",
     r"((specimen|sample|test piece|\bbar\b|film|membrane|plaque|plate|coupon|characterization specimen|substrate)"
     r"[- a-z()]* (preparation|form|provenance|origin|source|fabrication|history|processing|state|sampling location|"
     r"configuration|orientation|description|support|cleaning|initial condition)|preparation method|preparation route|"
     r"preparation procedure|processing history|processing route|film preparation|membrane preparation|"
     r"specimen preparation|sample preparation|as-mou?lded|mou?lding history|specimen form|^processing$|"
     r"substrate preparation|control design|specimen manufacturing|impact test orientation)",
     r"(temperature$|duration$|time$|pressure$|concentration$|speed$|rate$)")
rule("drying",
     r"(drying|dried|pre-?dry|predry|dehydrat|desiccat|dry-conditioning|dry conditioning|dry-reference|bone dry|oven-dry)",
     r"(mass loss|weight loss|\bloss\b|thickness|effect of|shrinkage|dry-mass|interval|range|gain)")
rule("conditioning",
     r"(conditioning|conditioned|pre-?condition|preconditioning|equilibrat|storage (temperature|duration|humidity|"
     r"relative|time|before|method|condition)|stored|pre-[a-z]* storage|desiccator storage|pre-test|pretest|acclimat|"
     r"^sample conditioning)",
     r"(water content|\bcontent\b|electrode|buffer|storage modulus|storage-modulus)")
rule("annealing-thermal-history",
     r"(anneal|heat[- ]?set|heat[- ]treat|thermal[- ]history|quench|isothermal crystallization (temperature|duration|time)|"
     r"premelting|pre-melting|post-annealing|post-mou?lding cooling|mou?ld cooling rate|second-quench|"
     r"thermal treatment|cross-linking heat-treatment|cooling rate from|cooling rate to isothermal|"
     r"crystallization temperature for|precrystallization)",
     r"(conductivity|ftir|threshold|without|dependence|uptake|absorption)")
rule("cure-schedule",
     r"((cure|curing|post-?cure|post-?curing|vulcani[sz]ation|vulcani[sz]ing|crosslinking|cross-linking|hardening)"
     r"[- a-z()0-9°]*(temperature|duration|time|schedule|pressure|cycle|condition|conditions|protocol|atmosphere|"
     r"profile|ramp|rate)$|cure schedule|curing schedule|cure-cycle|cure-ramp|imidization heating rate)",
     r"(optimum cure time|cure time \(t|curing time \(t|t90|scorch|gel time|activation|enthalpy|kinetic|rate constant|"
     r"peak temperature|onset temperature|exotherm|cure rate index|reaction rate)")
rule("melt-processing-conditions",
     PROC + r"[- a-z()0-9/]*(temperature|pressure|duration|time|speed|rate|profile|condition|conditions|count|ratio|"
     r"infill|infill density|cycle|protocol|equipment|instrument|machine|force|load|load per area|history|method|"
     r"throughput|output|feed|height|step|step count|speed|rotation speed|temperatures|setting|settings|"
     r"melt temperature|sequence)$|(melt temperature|cylinder temperature|chill-roll|bed temperature|infill|"
     r"calendering|roll-mixing|two-roll mixing|mixing count|layer height|printed layer thickness|screw diameter|"
     r"\bnip gap)",
     r"(melt flow|melt viscosity|melt strength|processing window|processability|shrinkage|draw ratio|"
     r"casting|coating|electrospinning|spinning solution|curing|\bcure\b|vulcani|polymeri[sz]ation|synthesis|"
     r"hardener|drawing|test-fluid)")
rule("solution-processing-conditions",
     r"(casting|\bcast\b|film-forming|film forming|coating|electrospinning|electrospun|spinning solution|spin-coat|"
     r"spin coat|\bdope\b|coagulation|solvent evaporation|knife|draw-bar|applicator|deposition|dip-coat|"
     r"solution preparation|dissolution (temperature|duration)|syringe|needle-to-collector|collector|"
     r"casting-frame)",
     r"(glycerol|plastici)")
rule("drawing-conditions",
     r"(draw ratio|drawing|draw-ratio|stretch(ing)? ratio|stretching temperature|stretching area ratio|"
     r"biaxial (draw|stretch)|orientation ratio|blow-up ratio|take-up ratio|\(tur\)|drawdown|drawing roller)",
     r"(maximum draw ratio|ultimate draw ratio|λmax|at maximum|at onset|onset of|at strain-induced|usaxs|invariant|"
     r"cyclic stretching)")
rule("synthesis-conditions",
     r"(polymeri[sz]ation (temperature|time|duration|method|conditions|route|pressure)|synthesis|synthesi[sz]ed|"
     r"reaction (temperature|time|duration)|feed (ratio|composition|mass)|monomer feed|grafting (temperature|time)|"
     r"esterification (temperature|time)|^preparation method$)",
     r"(degree of polymeri|initiator loading|catalyst (loading|concentration))")
rule("post-treatment",
     r"(irradiated|electron[- ]beam|e-beam|plasma|sterili[sz]|acid-doping|doping (duration|temperature|time)|"
     r"corona|surface treatment|treatment (temperature|duration|time))",
     r"(level|ratio)")

# ---- 5. Composition and formulation --------------------------------------
rule("cure-system",
     r"(sulfur|sulphur|accelerator|peroxide|dicumyl|\bdcp\b|hardener|curing agent|curing-agent|curative|crosslinker|"
     r"cross-linker|crosslinking agent|initiator|catalyst|cocatalyst|zinc oxide|\bzno\b|stearic acid|mbts|tmtd|\bcbs\b|"
     r"tbbs|hmta|hexamine|hexamethylenetetramine|activator|cure system|cure composition|cure formulation|curing system|"
     r"vulcanizing agent|cobalt|dimethylaniline|diphenylguanidine|zimate|thiuram|sulfenamide|magnesium oxide|"
     r"\bmgo\b|stoichiometr|resin-to-hardener|novolac-to-hmta|nco/oh|epoxy-to-amine|hydrogen equivalent)",
     r"(residu|temperature$|duration$|schedule|before)")
rule("plasticizer",
     r"(plastici[sz]|glycerol|sorbitol|\batbc\b|tributyl citrate|citrate|\bdop\b|\bdehp\b|phthalate|adipate|sebacate|"
     r"process oil|processing oil|extender oil|naphthenic|paraffinic|aromatic oil|\boil (loading|content)|circosol|"
     r"sundex|silicone oil loading)",
     r"(exudation|fogging|migration|effect|efficiency|induced)")
rule("filler-reinforcement",
     r"(filler|carbon black|silica|glass fib|glass-fib|carbon fib|carbon-fib|fib(re|er) (content|loading|mass)|"
     r"\bclay\b|montmorillonite|\bmmt\b|\btalc\b|calcium carbonate|caco3|graphene|nanotube|\bcnts?\b|mwcnt|"
     r"cellulose nanocrystal|nanoparticle|nanofiller|\bmica\b|wollastonite|kaolin|hydroxyapatite|alumina|titania|"
     r"\btio2\b|reinforcement|reinforcing|wood flour|marble waste|zeolite|mxene|nanosheet|whisker|cellulose mass fraction|"
     r"nanocellulose)[- a-z()0-9]*(loading|content|fraction|phr|concentration|amount|addition|level|ratio|type|"
     r"identity|size|grade|surface area|status|$)",
     r"(critical|nucleating)")
rule("additive",
     r"(antioxidant|stabili[sz]er|flame retardant|compatibili[sz]er|nucleating|nucleator|lubricant|pigment|\bdye\b|"
     r"uv absorber|processing aid|antistatic|\bwax\b|tackifier|extender|chain extender|chain-extender|"
     r"vulkanox|irganox|additive|surfactant|blowing agent|coupling agent|silane|anti-?block|slip agent|rosin|"
     r"epoxidized soybean|\bpdadmac\b)",
     r"(exudation|migration|retained)")
rule("copolymer-composition",
     r"(glycolide composition|\bhv composition|ethylene-to-propylene|styrene:butadiene|terephthalic/isophthalic|"
     r"vinylidene chloride/acrylonitrile composition|comonomer)")
rule("blend-composition",
     r"(blend|compound composition|formulation|mass ratio|weight ratio|mixing ratio|polymer mass fraction|"
     r"polymer content|rubber loading|base polymer loading|resin loading|^composition$|preparation composition|"
     r"\bcomposition$|matrix content|-to-[a-z0-9 ]+ ratio|/[a-z0-9]+ (mass |weight )?ratio|composition ratio)",
     r"(copolymer|comonomer|monomer|segment|repeat|chemical composition|phase composition|crystal|polymorph|"
     r"water|moisture|gel|ash|casting|electrospinning|cure|curing|moisture regain|wrv|hardener|hmta|solvent)")
rule("material-identity",
     r"(material grade|grade description|grade designation|^grade$|commercial (grade|name|material|resin|"
     r"formulation)|resin grade|trade ?name|supplier$|^supplier|and supplier|producer|polymer identity|"
     r"material identity|chemical identity|material identification|product (name|grade|code|designation)|"
     r"\bidentity$|polymer type|resin type|material type|specimen provenance|\bgrade$)",
     r"(phase|crystal|polymorph|structural|viscosity|melting)")

# ---- 6. Material properties ----------------------------------------------
# thermal transitions
rule("equilibrium-melting-temperature", r"(equilibrium melting|\btm0\b|\btm°|tm ?\^0)")
rule("heat-capacity", r"(heat[- ]capacity|δcp|\bcp\b\)?$|specific heat)", r"(cloud)")
rule("thermal-other",
     r"(for glass transition observation|water volume fraction at glass|water activity at glass|tg∞|tg = |fox|"
     r"gordon-taylor|enthalpy recovery|enthalpy relaxation|physical ag(e)?ing)")
rule("glass-transition-temperature",
     r"(glass[- ]transition|glass[- ]rubber|\btg\b|\btg[,0-9]|\(tg|calorimetric tg|onset tg|"
     r"tan ?(δ|delta)[- ](peak|maximum) temperature|loss-factor peak temperature)",
     r"(for glass transition|accuracy|correction|basis of)")
rule("melting-enthalpy",
     r"(melting enthalpy|enthalpy of (fusion|melting)|heat of fusion|fusion enthalpy|melting heat|δhm\b|δhf\b|"
     r"δh_?m\b|δhm |melting-enthalpy|first-heating melting enthalpy|second-heating (dsc )?melting enthalpy)")
rule("crystallization-enthalpy",
     r"(crystalli[sz]ation enthalpy|enthalpy of (cold )?crystalli[sz]ation|cold-crystalli[sz]ation enthalpy|"
     r"crystalli[sz]ation heat|heat of crystalli[sz]ation|δhc\b|δhcc\b|cooling enthalpy|"
     r"cooling[- ]crystalli[sz]ation enthalpy)")
rule("cold-crystallization-temperature", r"(cold[- ]crystalli[sz]ation[- a-z()]*(temperature|peak|onset)|\btcc\b)")
rule("crystallization-kinetics",
     r"(half-time|half time|t1/2|t1⁄2|avrami|crystalli[sz]ation rate|crystallization kinetic|spherulite growth|"
     r"growth rate|nucleation (density|rate)|crystalli[sz]ation time|crystalli[sz]ation induction|"
     r"time to \d+ ?% relative crystallinity)")
rule("melting-temperature",
     r"(melting (peak |onset |endset |end |point|temperature|range|peak)|melting-peak temperature|"
     r"melting-temperature|\btm\b|\btm[0-9α-ω,]|\(tm\b|\(tm[0-9α-ω,]|fusion temperature|melt(ing)? peak|"
     r"peak melting|hard-phase melting|tmα|dsc melting|melting temperatures|supplier melting)",
     r"(enthalpy|measurement|modulus|preparation|relative to|offset|above melting)")
rule("crystallization-temperature",
     r"(crystalli[sz]ation (peak |onset )?(temperature|peak)|crystalli[sz]ation peak temperature|\btc\b|\(tc\)|"
     r"\btc[0-9,]|onset crystallization|peak crystallization|crystallization onset|dsc crystallization temperature)",
     r"(isothermal|cold)")
rule("softening-temperature", r"(vicat|softening (point|temperature)|\bvst\b)")
rule("heat-deflection-temperature", r"(heat deflection|heat distortion|deflection temperature|\bhdt\b|\bdtul\b)")
rule("service-temperature",
     r"(service temperature|continuous (use|service|heat)|relative thermal index|\brti\b|heat resistance|"
     r"temperature index|maximum (use|operating) temperature|upper use temperature)")
rule("thermal-expansion", r"(thermal expansion|\bcte\b|\bclte\b|expansion coefficient|coefficient of (linear )?expansion)")
rule("thermal-conductivity", r"(thermal conductivity|thermal diffusivity|thermal effusivity)")
rule("brittleness-temperature",
     r"(brittleness temperature|brittle(ness)? point|ductile[- ]to[- ]brittle|ductile-brittle|brittle-ductile|"
     r"low-temperature brittleness|brittleness)")
rule("piezo-ferroelectric", r"(piezoelectric|\bd33\b|\bd31\b|remanent polari|coercive|curie|ferroelectric)")
rule("other-transition-temperature",
     r"((β|beta|γ|gamma|α|alpha|secondary)[- ]relaxation|relaxation peak temperature|sub-tg|order-disorder|"
     r"isotropi[sz]ation|clearing|nematic|smectic|liquid[- ]crystal|exotherm(ic)? peak|endotherm(ic)? peak|"
     r"hard-phase disappearance|dissociation temperature)",
     r"(cure|curing)")
# thermal stability
rule("oxidation-induction-time", r"(oxidation induction|oxidative induction|\boit\b|\boot\b|oxidation onset temperature)")
rule("decomposition-activation-energy",
     r"((degradation|decomposition|pyrolysis|thermal|oxidative|oxidative-degradation)[- a-z()]*activation energy|"
     r"activation energy[- a-z()]*(degradation|decomposition|pyrolysis))",
     r"(hydroly|enzym|biodeg)")
rule("max-decomposition-rate-temperature",
     r"((maximum|peak) (mass[- ]loss|weight[- ]loss|degradation|decomposition)[- ]rate|dtg[- a-z()]*peak|"
     r"derivative thermogravimetric|\btmax\b|tpeak|maximum (decomposition|degradation) temperature|"
     r"(degradation|decomposition)[- a-z]* \(tp\)|thermogravimetric peak temperature|maximum mass-loss temperature)",
     r"rate$")
rule("decomposition-temperature-at-mass-loss",
     r"(temperature (at|for) \d+(\.\d+)? ?%|\bt-?d?\d+(\.\d+)? ?%|\btd?\d+(\.\d+)?%|\d+ ?% (mass|weight)[- ]loss temperature|"
     r"weight-loss temperature|mass-loss temperature|\bt5\b|\bt10\b|\bt50\b|\btd5\b|\btd10\b)",
     r"(interval|range|major|maximum)")
rule("char-yield",
     r"(char yield|char residue|char content|residue at|residual mass at|\bchar\b|carbon yield|ceramic yield|"
     r"(tga|thermogravimetric) residu)",
     r"(interval|oxidation)")
rule("thermal-mass-loss",
     r"((thermogravimetric|\btga\b|isothermal|thermal|heating|pyrolysis|decomposition-step|first-step|"
     r"principal thermal degradation|pre-carbonization|post-stabilization)[- a-z()0-9]*(mass|weight)[- ]loss|"
     r"(mass|weight) loss (at|on heating|upon heating) \d|volatile (content|matter))",
     r"interval")
rule("thermal-degradation-other",
     r"(decomposition[- a-z()]*(interval|range|stage|step|products|end)|degradation (end|stage|step|interval|range)|"
     r"pyroly|monomer yield|combustion completion|char oxidation|cellulose-skeleton degradation|chain decomposition|"
     r"dehydration temperature interval|thermal (decomposition|degradation) (behaviou?r|mechanism|products)|"
     r"mass-loss temperature interval|water-loss temperature interval|final decomposition|decomposition rate|"
     r"mass-loss rate|mass-loss temperature)")
rule("decomposition-onset-temperature",
     r"((decomposition|degradation|pyrolysis)[- a-z()]*(onset|initial|initiation|start)|(onset|initial|initiation)"
     r"[- a-z]* (thermal )?(decomposition|degradation)|thermal (decomposition|degradation|stability) temperature|"
     r"decomposition temperature|thermal degradation temperature|\btd\b|\btonset\b|\bidt\b)",
     r"(interval|range|cure|melting)")
# electrical (before mechanical damping)
rule("dielectric-loss", r"(dielectric loss|loss tangent|dissipation factor|dielectric[^;]*tan ?δ|tan ?δ[^;]*dielectric)")
rule("dielectric-constant", r"(dielectric constant|permittivity|\bdk\b)")
rule("dielectric-strength", r"(dielectric strength|breakdown (strength|voltage|field)|electric strength|arc resistance|tracking)")
rule("ionic-conductivity",
     r"(proton conductivity|ionic conductivity|ion conductivity|hydroxide conductivity|anion conductivity|"
     r"transference number)")
rule("electrical-conductivity",
     r"(electrical conductivity|electric conductivity|electronic conductivity|^conductivity$|conductivity \(σ|"
     r"in-plane[- a-z]*conductivity|dc conductivity|sheet conductance)")
rule("electrical-resistivity",
     r"(resistivity|sheet resistance|surface resistance|volume resistance|contact resistance|insulation resistance|"
     r"electrical resistance)")
rule("thermoelectric", r"(seebeck|thermopower|power factor|thermoelectric|\bzt\b)")
rule("electrochemical",
     r"(capacitance|specific capacity|redox|oxidation potential|reduction potential|electrochemical (window|stability)|"
     r"charge capacity|discharge capacity|coulombic)")
rule("electronic-structure", r"(\bhomo\b|\blumo\b|work function|mobility|ionization potential|electron affinity)")
# impact, fracture, tear
rule("tear-strength", r"\btear")
rule("fracture-toughness",
     r"(fracture toughness|fracture-toughness|fracture energy|\bkic\b|\bk1c\b|kicsb|\bgic\b|\bg1c\b|stress intensity|"
     r"strain energy release|energy release rate|j-integral|\bjic\b|essential work|crack resistance|"
     r"fracture resistance|critical energy release|specific fracture energy|work of fracture)")
rule("unnotched-izod-impact", r"((unnotched|un-notched|un notched)[^;]*izod|izod[^;]*unnotched)")
rule("unnotched-charpy-impact", r"((unnotched|un-notched|un notched)[^;]*charpy|charpy[^;]*unnotched)")
rule("notched-izod-impact", r"izod")
rule("notched-charpy-impact", r"(notched[^;]*charpy|charpy[^;]*notched)")
rule(None, r"charpy")  # Charpy without a notch statement is assigned by hand
rule("impact-strength-other",
     r"(impact strength|impact resistance|impact energy|\bdart\b|falling weight|drop impact|drop-weight|gardner|"
     r"tensile impact|pendulum impact|puncture|impact toughness|notched impact|notched-bar impact|\bimpact\b)")
# hardness and elastomer behaviour
rule("compression-set", r"(compression set|compression-set|compressive set|\(cs\)|equilibrium compression set)")
rule("shore-a-hardness", r"shore[- ]a\b|shore a hardness|\(shore a\)")
rule("shore-d-hardness", r"shore[- ]d\b")
rule("hardness-other",
     r"(hardness|durometer|rockwell|barcol|\birhd\b|pencil|vickers|brinell|knoop|nanoindentation|indentation)",
     r"loss")
rule("crosslink-density",
     r"(cross-?link(ing)? density|network density|\bmc\b|between cross-?links|molar mass between|gel (content|fraction)|"
     r"gel-content|insoluble fraction|sol fraction|degree of cross-?linking|cross-?linking degree|\bdxl\b)",
     r"moisture")
rule("resilience-recovery",
     r"(resilience|rebound|hysteresis|elastic recovery|recovery ratio|shape recovery|shape fixity|tension set|"
     r"permanent set|set after|strain recovery|recovered strain|recovery rate|energy loss|energy dissipation|"
     r"mullins|stress softening|residual strain|non-recoverable|recoverable|recovered thickness)",
     r"dry-mass")
# mechanical
rule("dynamic-mechanical-modulus",
     r"(storage modulus|loss modulus|\be'|\be''|\bg'|\bg''|dynamic modulus|complex modulus|rubbery plateau|"
     r"plateau modulus|storage-modulus)",
     r"(melt|crossover|solution)")
rule("damping-tan-delta", r"(tan ?δ|tan delta|loss factor|damping)")
rule("creep-stress-relaxation",
     r"(creep|stress relaxation|stress-relaxation|relaxation modulus|compressive force loss|force decay|sealing force)")
rule("fatigue", r"(fatigue|cycles to failure|cycle count at (premature )?failure|endurance limit|flex(ing)? life|de mattia)")
rule("poisson-ratio", r"poisson")
rule("flexural-modulus", r"(flexural|bending|three-point|3-point|four-point)[^;]*(modulus|stiffness)")
rule("flexural-strain", r"(flexural|bending)[^;]*(strain|deflection|elongation)")
rule("flexural-strength", r"(flexural|bending)[^;]*(strength|stress|yield)|modulus of rupture")
rule("compressive-modulus", r"(compress(ive|ion)[^;]*(modulus|young))")
rule("compressive-strength", r"(compress(ive|ion)[^;]*(strength|stress|yield))")
rule("shear-properties",
     r"(shear (strength|modulus|yield)|torsion(al)? modulus|interlaminar shear)",
     r"(lap|bond|adhesive|joint)")
rule("tensile-toughness",
     r"(tensile toughness|toughness \(|energy to break|energy at break|work to break|break energy|^toughness$|"
     r"toughness modulus|modulus of toughness)")
rule("stress-at-strain",
     r"(stress at \d+ ?%|\d+ ?% modulus|modulus at \d+|modulus \(\d+ ?%\)|\bm100\b|\bm300\b|\bm50\b|\bm200\b|"
     r"tensile stress at \d+)")
rule("yield-strain", r"(yield strain|strain at yield|elongation at yield|yield elongation|\bεy\b)")
rule("tensile-yield-strength",
     r"(yield (strength|stress|point)|tensile yield|\bσy\b|strength at yield|stress at yield|offset yield)")
rule("elongation-at-break",
     r"(elongation at break|elongation-at-break|strain at break|strain-at-break|strain at failure|elongation at failure|"
     r"ultimate elongation|ultimate strain|breaking (strain|elongation)|elongation to break|strain to (break|failure)|"
     r"\bεb\b|^elongation$|tensile elongation|elongation at rupture|extensibility|maximum elongation|rupture strain)",
     r"maximum tensile stress")
rule("tensile-modulus",
     r"(young's modulus|youngs modulus|elastic modulus|modulus of elasticity|tensile modulus|tensile elastic|"
     r"elasticity modulus|secant[- a-z]*modulus|initial[- a-z']*modulus|chord modulus|e-modulus|\bym\b|tensile stiffness|"
     r"^modulus|tensile young)")
rule("tensile-strength",
     r"(tensile strength|ultimate tensile|\buts\b|tensile stress at break|stress at break|tensile (breaking )?stress|"
     r"breaking stress|stress at failure|break(ing)? strength|tenacity|maximum tensile|strength at break|\bσb\b|"
     r"\bσmax\b|tensile break stress|^strength$|ultimate strength|tensile failure stress|engineering tensile)",
     r"(elongation at|relative tensile breaking)")
# rheology, melt, cure
rule("melt-flow-rate", r"(melt flow|melt[- ]mass[- ]flow|melt volume[- ]flow|\bmfr\b|\bmfi\b|\bmvr\b|melt index)")
rule("processability",
     r"(processability|processing window|drawability|maximum draw ratio|ultimate draw ratio|λmax|spinnability|"
     r"printability|mou?ldability)")
rule("gelation-temperature",
     r"(gelation temperature|gel(ation)? point temperature|sol-gel|thermal gelation|gelation onset|gel temperature|"
     r"thermogelation|incipient gelation)")
rule("melt-viscosity",
     r"(melt viscosity|complex viscosity|zero-shear melt viscosity|apparent melt viscosity|melt or complex viscosity|"
     r"dynamic melt viscosity|elongational viscosity|extensional viscosity)")
rule("melt-rheology-other",
     r"(flow activation energy|melt strength|die swell|extrudate swell|carreau|power-law index|shear[- ]thinning|"
     r"crossover|viscous flow)")
rule("cure-kinetics",
     r"((cure|curing|crosslinking|cross-linking|vulcani[sz]ation)[- a-z()]*(activation energy|enthalpy|reaction order|"
     r"rate constant|pre-exponential|kinetic|conversion|exponent|heat)|(activation energy|reaction order|"
     r"kinetic exponent|pre-exponential factor)[- a-z()]*(cure|curing)|degree of cure|cure (reaction )?enthalpy|"
     r"reaction enthalpy|\bδhr\b|fitted reaction order|autocatalytic|degree of conversion|cure exotherm|"
     r"isoconversional|\bea\)?$|\beα\b)",
     r"(degradation|decomposition|creep|flow|permeation)")
rule("cure-characteristics",
     r"(gel time|gelation time|gel point|cure time|curing time|\bt90\b|t ?c90|scorch|\bts2\b|\bts1\b|optimum cure|"
     r"torque|cure rate index|\bcri\b|pot life|working time|tack-free)")
# barrier and transport
rule("gas-selectivity", r"(selectivity|separation factor|permselectivity)")
rule("barrier-other",
     r"(permeation activation energy|activation energy (of|for) permeation|breakthrough time|tortuosity|"
     r"permeation[- a-z]*activation)")
rule("co2-permeability", r"(co2|carbon dioxide|carbon-dioxide)[^;]*(permeab|permeance|transmission|permeation)")
rule("oxygen-transmission-rate",
     r"(oxygen transmission rate|\botr\b|(?<!c)o2 transmission|oxygen gas transmission|\bo2tr\b|oxygen permeance|"
     r"oxygen transmission$)")
rule("oxygen-permeability",
     r"(oxygen[- ]permeab|oxygen gas[- ]permeab|(?<!c)o2 permeab|\bpo2\b|p o2|p_o2|\(op\)|oxygen permeation|\bo2p\b|"
     r"oxygen barrier)")
rule("water-vapor-transmission-rate",
     r"(water[- ]vapou?r transmission|\bwvtr\b|moisture vapou?r transmission|\bmvtr\b|water vapou?r transfer|"
     r"water[- ]vapou?r permeance|water[- ]vapou?r flux)")
rule("water-vapor-permeability",
     r"(water[- ]vapou?r permeab|\bwvp\b|\bpwv\b|\bwvpc\b|moisture permeab)")
rule("membrane-separation",
     r"(water flux|pure-water flux|rejection|bubble[- ]point|permeate flux|flux recovery|water permeability coefficient)")
rule("gas-permeability-other",
     r"((nitrogen|\bn2\b|helium|\bhe\b|hydrogen|\bh2\b|argon|methane|\bch4\b|methanol|ethanol|\bgas\b|vapou?r|"
     r"toluene|hexane|solvent|fuel)[- a-z()0-9]*(permeab|permeance|transmission|permeation rate|flux)|"
     r"permeability coefficient|^permeability|gas permeab)")
rule("diffusion-coefficient", r"(diffusion coefficient|diffusivity|diffusion constant)")
rule("sorption-solubility-coefficient",
     r"(solubility coefficient|(?<!ab)sorption coefficient|langmuir|bet monolayer|\bgab\b|monolayer (water )?capacity|"
     r"henry|(?<!ab)sorption capacity|sorption isotherm|clustering|c0h|c'h|hole saturation|solubility-pressure)")
rule("water-absorption",
     r"(water absorption|water uptake|water-absorption|water-uptake|water gain|absorbed water|"
     r"absorption capacity|(saturation|equilibrium) water (content|uptake|absorption)|water absorbency)")
rule("moisture-sorption",
     r"(moisture (content|absorption|uptake|regain|gain|sorption|level|pick-?up)|equilibrium moisture|"
     r"\bemc\b|water content|hygroscop|water vapou?r (sorption|uptake)|moisture mass gain|water sorption|"
     r"humidity absorption)")
rule("swelling-ratio",
     r"(swelling ratio|swelling degree|degree of swelling|equilibrium swelling|swelling index|swelling capacity|"
     r"swell(ing)? ratio|mass swelling)")
# optical
rule("haze", r"(haze|opacity|clarity)")
rule("light-transmittance",
     r"(transmittance|light transmission|transparency|luminous transmittance|\bt550\b|optical transmission)",
     r"(wavelength|reference|\bloss\b)")
rule("refractive-index", r"(refractive index|refractive-index|birefringence|abbe number)")
rule("color-yellowness", r"(yellowness|colou?r|whiteness|\byi\b)")
rule("gloss", r"\bgloss")
rule("optical-absorption-emission",
     r"(absorbance|absorption coefficient|absorption coefficients|absorption peak|absorption band|absorption edge|"
     r"absorption feature|absorption wavelength|band ?gap|optical gap|energy gap|uv cut|cut-off wavelength|"
     r"photoluminescence|fluorescence|emission (peak|wavelength|maximum)|quantum yield|extinction coefficient|"
     r"optical absorption|absorption maximum|terahertz)",
     r"(infrared|\bir\b|ftir|raman)")
# degradation and environment
rule("weathering-photo-oxidation",
     r"(carbonyl index|hydroxyl index|vinyl index|photo-?oxidation|photo-?degradation|uv stability|uv resistance|"
     r"weathering|weatherability|chalking|yellowing|oxidation evidence)")
rule("enzymatic-degradation", r"(enzymatic|lipase|proteinase|cutinase|petase|hydrolase)", r"(panel)")
rule("biodegradation",
     r"(biodegrad|minerali[sz]|compost|soil[- ]burial|soil burial|disintegration|\bbod\b|oxygen demand|co2 evolution|"
     r"carbon dioxide evolution|co2-based|respirometr|bio-?assimilation)",
     r"(sample loading|compost age)")
rule("hydrolytic-degradation", r"(hydroly(sis|tic))", r"degree of hydrolysis")
rule("chemical-resistance",
     r"(chemical resistance|solvent resistance|environmental stress[- ]crack|\besc\b|\bescr\b|stress[- ]crack|"
     r"resistance to (chemicals|solvents|acids|alkali)|chlorine resistance|acid resistance|alkali resistance|crazing)")
rule("emissions-migration",
     r"(emission|migration|exudation|fogging|\bbleed|blooming|leach(ing|ed)|outgassing|volatile organic|\bvoc\b|odou?r)",
     r"(configuration|substrate)")
# molecular
rule("weight-average-molecular-weight", r"^mw and (dispersity|pdi)")
rule("number-average-molecular-weight", r"^mn and (dispersity|pdi)")
rule("molecular-weight-other", r"molecular-weight averages")
rule("dispersity",
     r"(dispersity|polydispersity|\bpdi\b|mw/mn|\bđ\b|molecular weight distribution|molar mass distribution|\bmwd\b)")
rule("weight-average-molecular-weight", r"(weight[- ]average|\bmw\b|m_w)")
rule("number-average-molecular-weight", r"(number[- ]average|\bmn\b)")
rule("intrinsic-viscosity",
     r"(intrinsic viscosity|\[η\]|inherent viscosity|reduced viscosity|viscosity number|k-value|\bk value|"
     r"limiting viscosity|\biv\b|relative viscosity|specific viscosity)")
rule("molecular-weight-other",
     r"(viscosity[- ]average|\bmv\b|z-average|\bmz\b|peak molecular|molecular weight|molar mass|molecular mass|"
     r"degree of polymeri[sz]ation|\bdp\b\)?$|chain length)")
rule("copolymer-composition",
     r"(comonomer|co-monomer|vinyl acetate content|\bva content|ethylene content|acrylonitrile (content|mass fraction)|"
     r"styrene content|butadiene content|chlorine content|fluorine content|\bhv content|\b3hv\b|3-hydroxy|\b4hb\b|"
     r"hard[- ]segment|soft[- ]segment content|segment content|d-lactide|d-lactic|l-lactide content|lactide content|"
     r"monomer (composition|ratio|content)|copolymer composition|vinyl chloride content|"
     r"vinylidene chloride content|vinyl alcohol content|methacrylic acid content|acrylic acid content|"
     r"maleic anhydride content|graft(ing)? (degree|ratio|content|yield)|degree of grafting|block (ratio|composition)|"
     r"fraction in diamines|isophthal|terephthal)",
     r"polybutadiene content")
rule("degree-of-substitution",
     r"(degree of substitution|substitution|\bds\b|\(ms\)|molar substitution|acetyl|methoxyl|ethoxyl|hydroxypropoxyl|"
     r"butyryl|propionyl|deacetylation|\bdda\b|degree of acetylation|degree of hydrolysis|degree of sulfonation|"
     r"sulfonation|degree of (partial )?neutrali[sz]ation|degree of esterification|carboxymethyl|degree of oxidation|"
     r"degree of amination|degree of functionali)")
rule("chain-microstructure",
     r"(tactic|pentad|triad|\bdiad|\bdyad|\[rrrr\]|\[mmmm\]|\bmeso\b|racemo|regio|head-to-head|\bcis\b|\btrans\b|"
     r"vinyl content|1,2-content|1,4-content|branch|sequence (distribution|length|alternation)|methylene sequence|"
     r"alternation|blockiness|stereo|methyl content|methyl-group content)")
rule("functional-group-content",
     r"(ion[- ]exchange capacity|\biec\b|equivalent weight|\bew\b\)?$|hydroxyl (number|value|content)|"
     r"epoxy (equivalent|value|content)|\beew\b|acid (number|value|capacity)|amine (number|value)|end[- ]group|"
     r"carboxyl end|isocyanate content|nco content|available acid|acid doping level)")
rule("residual-monomer-impurities",
     r"(residual monomer|free monomer|oligomer content|ash content|\bash\b|extractable|catalyst residue|impurit|"
     r"residual solvent|metal content|free formaldehyde|residual catalyst)")
rule("chemical-structure-other", r"(repeat unit|chemical structure|architecture|end-capping|extent of stabilization)")
# morphology and crystallinity
rule("crystal-structure-phase",
     r"(polymorph|crystal (form|phase|structure|modification)|crystalline (phase|form|structure)|phase (identity|"
     r"fraction|content|composition|detection)|β-phase|β phase|γ-phase|electroactive|\bfea\b|unit cell|lattice|"
     r"structural phase|mesomorphic|mesophase content|d-spacing|interplanar|ftir β fraction)")
rule("degree-of-crystallinity",
     r"(crystallinity|crystalline fraction|crystalline content|\bxc\b|\(xc|\bχc\b|crystallinity index|"
     r"degree of crystal|relative crystallinity|\bwc,?x\b)",
     r"draw ratio at")
rule("crystallite-lamellar-dimensions",
     r"(crystallite size|crystal size|lamellar thickness|lamella thickness|long period|spherulite (size|diameter|radius)|"
     r"lamellar|coherence length|crystal thickness)")
rule("orientation", r"(orientation (factor|function|index|parameter|degree)|herman|degree of orientation|orientation$)")
rule("phase-morphology",
     r"(phase separation|domain (size|spacing)|microphase|phase morphology|dispersed[- ]phase|interdomain|"
     r"co-continuous|phase structure)")
rule("porosity-pore-size",
     r"(porosity|pore (size|diameter|radius|volume)|specific surface area|bet surface|surface area|void (content|fraction)|"
     r"\bpore\b)",
     r"filtration")
rule("particle-fiber-size",
     r"(fib(er|re) diameter|filament diameter|linear density|denier|\bdtex\b|\btiter\b|bead size|particle size|"
     r"powder (size|particle)|nanofib(er|re) diameter)",
     r"(test specimen|solubility-test)")
# solution behaviour
rule("cloud-point-lcst",
     r"(cloud point|cloud-point|clouding|\blcst\b|\bucst\b|lower critical solution|upper critical solution|"
     r"phase[- ]transition temperature|volume phase transition|coil-globule|demixing)",
     r"identification")
rule("solution-thermodynamics",
     r"(flory|huggins|interaction parameter|second virial|solubility parameter|hansen|hildebrand|radius of gyration|"
     r"hydrodynamic radius|mark-houwink|theta (solvent|temperature)|persistence length)")
rule("solubility", r"(solubility|soluble|dissolution time|dissolution rate|dissolv)", r"(soluble mass fraction)")
rule("solution-viscosity",
     r"(solution viscosity|solution dynamic viscosity|dynamic viscosity|kinematic viscosity|brookfield|ball-drop|"
     r"ford cup|viscosity grade|nominal viscosity)",
     r"(melt)")
# density and dimensional
rule("density",
     r"(density|specific gravity|specific volume|\bρ\b)",
     r"(crosslink|cross-link|linear density|infill|current density|energy density|charge density|optical density|"
     r"nucleation|power density|network density|fluctuation|wear|solvent density)")
rule("shrinkage", r"(shrinkage|\bshrink)")
rule("free-volume", r"(free volume|\bffv\b|positron|o-ps)")
# flammability
rule("flammability",
     r"(oxygen index|\bloi\b|ul[- ]?94|flammab|flame spread|heat release|\bhrr\b|\bphrr\b|burning (rate|time|behaviou?r)|"
     r"combustion|time to ignition|\btti\b|smoke|self-extinguish)")
# surface, adhesion and tribology
rule("contact-angle-surface-energy", r"(contact angle|surface (free )?energy|surface tension|wettability|wetting)")
rule("adhesion-strength",
     r"(adhesion|adhesive strength|lap[- ]shear|\bpeel\b|pull-off|bond strength|bonding strength|interfacial (shear )?strength|"
     r"joint strength)")
rule("friction-wear", r"(friction|\bwear\b|abrasion|tribolog|scratch)", r"test")
rule("surface-roughness", r"(roughness|\bra\b|\brq\b)")
rule("surface-other", r"(surface pressure|collapse pressure|zeta potential|surface charge)")
# biological
rule("biological-response",
     r"(cytotox|cell viability|cell adhesion|antibacterial|antimicrobial|bacteri|hemoly|haemoly|biocompat|"
     r"protein adsorption|platelet)")
# spectroscopic signatures and generic leftovers
rule("spectroscopic-signature",
     r"(infrared|\bir\b|ftir|raman|\bnmr\b|\bxps\b|absorbance-band|band position|wavenumber|chemical shift|"
     r"carbonyl band|ftir bands|spectral comparison)",
     r"(carbonyl index|crystallinity|phase fraction|electroactive|β/γ separation)")
rule("degradation-other",
     r"(degradation|erosion|chain scission|remaining (mass|weight))",
     r"(temperature|onset)")


# --------------------------------------------------------------------------
METHODS = [
    ("DSC", r"(\bm?dsc\b|tmdsc|differential scanning calorimetr|calorimetric|(first|second)[- ]heating)"),
    ("DMA", r"(\bdma\b|\bdmta\b|\bdms\b|dynamic mechanical|dynamic-mechanical)"),
    ("TGA", r"(\btga\b|thermogravimetr|\bdtg\b)"),
    ("TMA", r"(\btma\b|thermomechanical analysis)"),
    ("DTA", r"\bdta\b"),
    ("WAXD/XRD", r"(\bwaxd\b|\bwaxs\b|\bxrd\b|x-ray diffraction|x-ray crystalline|wide-angle x-ray)"),
    ("SAXS", r"(\bsaxs\b|\busaxs\b|small-angle x-ray)"),
    ("FTIR", r"(\bftir\b|ft-ir|infrared|ftir-atr)"),
    ("Raman", r"\braman\b"),
    ("NMR", r"\bnmr\b"),
    ("GPC/SEC", r"(\bgpc\b|\bsec\b|size[- ]exclusion|gel permeation)"),
    ("light scattering", r"(light scattering|\bmals\b|\bdls\b)"),
    ("viscometry", r"(viscometr|ubbelohde)"),
    ("rheometry", r"(rheometr|rheolog|oscillatory)"),
    ("dielectric spectroscopy", r"(dielectric spectroscopy|\bbds\b)"),
    ("DVS", r"(dynamic vapou?r sorption|\bdvs\b)"),
    ("gravimetry", r"(?<!thermo)gravimetr"),
    ("AFM", r"(\bafm\b|atomic force)"),
    ("SEM", r"\bsem\b"),
    ("TEM", r"\btem\b"),
    ("POM", r"(\bpom\b|polari[sz]ed optical)"),
    ("nanoindentation", r"nanoindent"),
    ("UV-vis", r"(uv-vis|spectrophotomet)"),
    ("ellipsometry", r"ellipsometr"),
    ("PALS", r"(positron|\bpals\b)"),
    ("tan δ peak", r"tan ?(δ|delta)[- ](peak|max)|tan δ maximum|loss-factor peak"),
    ("storage-modulus onset", r"storage-modulus (onset|step)|e' (extrapolated )?onset"),
    ("loss-modulus peak", r"(e'' (peak|maximum)|loss-modulus maximum)"),
]
METHODS = [(label, re.compile(p)) for label, p in METHODS]
_STANDARD = re.compile(r"\b(astm|iso|din|jis|gb/t|iec|ul|bs|tappi)\s?-?\s?([a-z]?\s?-?\d{2,5}(?:[-./]\d+)*)")


def method(s):
    """Methods and standards named in the normalized string, joined with '; ', or None."""
    found = []
    for label, pat in METHODS:
        if pat.search(s) and label not in found:
            found.append(label)
    for m in _STANDARD.finditer(s):
        code = m.group(1).upper() + " " + m.group(2).upper().replace(" ", "")
        if code not in found:
            found.append(code)
    return "; ".join(found) or None


def classify(s):
    """(class_id, rule_index) for the first matching rule; class_id None means deferred or unmatched."""
    for i, (cls, inc, exc) in enumerate(R):
        if inc.search(s) and not (exc and exc.search(s)):
            return cls, i
    return None, None
