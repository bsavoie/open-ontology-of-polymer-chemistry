"""Private questions and a fresh knowledge snapshot for the authorized 200-task run.

Ran in `.oopc/loop/harness/2026-10-03-200/` and still writes there; moved to the repository on 2026-10-13 unchanged
except imports and paths."""
import hashlib, json, os, shutil, sqlite3, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # studies/macromolecules, for common
from common import CODE, ROOT, run_dir  # noqa: E402  (common puts CODE first on sys.path)
BASE=run_dir('2026-10-03-200')
from oopc import ask, knowledge, loop
from oopc.util import atomic_json, now, resolve_release
# Each row names a material and four distinct, bounded scientific requests.
TOPICS=[
('PET','water-vapor permeability in neat films','enzymatic depolymerization conversion and its denominator','crystallinity changes after annealing','whether transmission can be converted to permeability'),
('PMMA','molecular-weight dependence of glass-transition temperature','DSC Tg determination and scan history','solvent casting effects on measured mechanical properties','whether Tg can be transferred across tacticity and molecular-weight distributions'),
('EVOH','relative-humidity effects on oxygen permeability','oxygen permeability measurement in a specified film','ethylene-content effects on barrier performance','comparison of neat EVOH and multilayer oxygen transmission'),
('PBAT','controlled-compost CO2 mineralization endpoint','CO2 measurement method and blank correction in composting','film preparation effects on biodegradation endpoints','distinction between disintegration, mass loss and mineralization'),
('PVDF','FTIR beta-phase fraction in a specified film','FTIR phase-fraction equations and gamma-band overlap','annealing effects on alpha, beta and gamma polymorphs','conditions under which an FTIR estimate establishes piezoelectric performance'),
('PNIPAM','aqueous cloud-point temperature in a specified solution','turbidimetry versus DSC transition measurements','salt and concentration effects on the aqueous transition','whether a cloud point can be treated as a universal LCST'),
('PLA','hydrolytic molecular-weight loss at a specified pH and temperature','gravimetric degradation measurement and drying protocol','annealing effects on crystallinity and hydrolytic degradation','transfer of accelerated alkaline hydrolysis to environmental biodegradation'),
('PBS','second-heating DSC melting and glass-transition temperatures','soil or compost biodegradation endpoint measurement','processing effects on crystallinity and tensile behavior','distinguishing soil mass loss from controlled-compost mineralization'),
('PCL','hydrolysis in aqueous buffer near 37 degrees C','DSC crystallinity calculation with its reference enthalpy','electrospinning effects on specimen mechanical behavior','distinction between neat-polymer hydrolysis and enzymatic degradation'),
('PHB','tensile properties of neat processed films','DSC crystallinity calculation and thermal cycle','thermal processing effects on molecular-weight degradation','transfer of film measurements to injection-molded specimens'),
('PHBV','hydroxyvalerate-content dependence of melting temperature','measurement and reporting basis of hydroxyvalerate composition','processing history effects on crystallinity','copolymer composition effects distinguished from PHB blend effects'),
('PA6','dry versus moisture-conditioned tensile modulus','water-content conditioning and tensile-test protocol','annealing effects on crystalline phases','evidence distinguishing moisture plasticization from chain scission'),
('PA66','water absorption and tensile strength in a neat specimen','DSC melting-cycle and heating-rate effects','injection-molding effects on morphology and mechanics','limitations when comparing dry and humid nylon grades'),
('PEEK','neat-polymer DSC melting temperature','DSC crystallinity calculation and melting/cold-crystallization terms','cooling-rate effects on crystallinity and tensile behavior','transfer of supplier nominal melting points to measured specimen results'),
('PPS','oxidative aging effects on a specified mechanical property','thermal oxidation measurement and exposure conditions','cooling history effects on crystallinity','distinguishing oxidation, crosslinking and chain scission from available tests'),
('polypropylene','beta-nucleation effects on a specified impact result','WAXD beta-phase fraction calculation','cooling-rate effects on polymorphs and mechanical properties','limitations of inferring impact strength from crystallinity alone'),
('HDPE','short-chain branching effects on crystallinity','oxygen or water-vapor permeability measurement','drawing effects on tensile behavior and orientation','distinguishing experimental branching evidence from simulation predictions'),
('LDPE','oxygen permeability of neat films','DSC crystallinity measurement and reference enthalpy','film-blowing effects on morphology or mechanics','limitations when comparing branched polyethylene grades'),
('LLDPE','comonomer-content effects on tensile behavior','measurement of molecular-weight distribution and branching','processing effects on puncture or tear performance','comparison of density-matched LDPE and LLDPE specimens'),
('polystyrene','DSC heating-rate effects on apparent Tg','molecular-weight and Tg measurement definitions','physical aging effects below Tg','distinguishing measured glass transition from an equilibrium phase transition'),
('polycarbonate','physical aging below Tg and a measured property change','heat-deflection measurement with its load and conditioning','processing-induced orientation effects on mechanics','distinguishing physical aging from chemical chain scission'),
('PVC','plasticizer-loading effects on Tg or tensile modulus','plasticizer migration measurement and denominator','processing-temperature effects on thermal degradation','comparison of plasticizer identities with different loading bases'),
('PDMS','oxygen permeability of a crosslinked membrane','permeability units and membrane-test configuration','cure ratio effects on elastic modulus','distinguishing bulk permeability from oxygen flux in a device'),
('PVA','hydrolysis-degree effects on water uptake or solubility','water-uptake measurement and dry-mass denominator','freeze-thaw processing effects on hydrogel mechanics','hydrolysis effects distinguished from molecular-weight and crystallinity confounding'),
('TPU','hard-segment-content effects on elastic modulus','measurement of phase separation in a specified formulation','annealing or solvent processing effects on morphology','comparison of composition expressed by mass and molar fractions'),
('PAN','oxidative stabilization of precursor fibers','FTIR or DSC stabilization indices and their equations','heating-program effects on stabilization','distinguishing cyclization and oxidative stabilization from carbonization'),
('PEDOT:PSS','solvent-treatment effects on film conductivity','four-probe conductivity measurement and thickness measurement','annealing effects on conductivity and morphology','distinguishing conductivity from sheet resistance and contact effects'),
('alginate','calcium-crosslinked hydrogel elastic modulus','compression versus oscillatory shear modulus measurement','calcium-delivery and gelation effects on mechanics','limits on comparing gels with different guluronate contents'),
('cellulose acetate','degree-of-substitution effects on water uptake','degree-of-substitution determination and reporting basis','casting solvent effects on membrane morphology','distinguishing neat-polymer water uptake from filler and blend effects'),
('chitosan','degree-of-deacetylation effects on water uptake or mechanics','degree-of-deacetylation measurement by titration or spectroscopy','crosslinking effects on swelling','limits on transferring acidic-solution results to neutral-water solubility'),
('PTFE','creep in a specified neat specimen','DSC melting and crystallinity measurement','sintering history effects on density and mechanics','distinguishing bulk PTFE properties from expanded porous PTFE'),
('PES','water permeability of a specified polyethersulfone membrane','membrane flux and permeability normalization','phase-inversion processing effects on pore structure','distinguishing intrinsic polymer permeability from porous-membrane permeance'),
('polysulfone','glass-transition temperature in a specified specimen','DSC versus DMA glass-transition measurement','physical aging effects on gas separation','limits on comparing gas selectivity across pressure and aging conditions'),
('polyimide','gas permeability and selectivity of a specified chemistry','gas permeability measurement and units','thermal treatment effects on free volume and transport','whether a polymer-family label predicts a specific gas-transport result'),
('PEI','DMA storage modulus of neat polyetherimide','DSC versus DMA Tg determination','additive-manufacturing thermal history effects on mechanics','limits on transferring printed-polymer properties to molded specimens'),
('ABS','processing-dependent tensile or impact properties','impact-test geometry and notched versus unnotched definitions','reprocessing effects on mechanical performance','separation of blend morphology from universal polymer-family property claims'),
('POM','crystallinity and tensile behavior of neat polyoxymethylene','DSC crystallinity measurement and thermal history','annealing effects on specimen mechanics','limits on comparing homopolymer and copolymer POM grades'),
('natural rubber','strain-induced crystallization and a measured mechanical result','WAXD evidence and strain conditions','vulcanization or crosslink-density effects on modulus','distinguishing strain crystallization from a general entropy-elasticity explanation'),
('SBR','styrene-content effects on Tg or tensile properties','dynamic-mechanical measurement of Tg and frequency effects','vulcanization effects on crosslink density and mechanical behavior','comparison of filled and unfilled styrene-butadiene rubber'),
('poly(acrylic acid)','pH-dependent swelling of a crosslinked hydrogel','swelling-ratio definition and ionic-strength conditions','crosslink-density effects on swelling','limits on inferring polymer ionization from swelling alone')]
TAIL=' Use saved findings for covered parts and an open primary source for gaps. Give material or grade, specimen, numerical result with units and uncertainty if reported, conditions, and exact source locations. State missing requested details explicitly; label your own reasoning and preserve source inconsistencies.'
rows=[]
for angle in range(4):
 for index,topic in enumerate(TOPICS):
  material,target=topic[0],topic[angle+1]
  if angle==0: question=f'For {material}, find one open primary study of {target}. Report one bounded quantitative result and the conditions needed to interpret it.'
  elif angle==1: question=f'For {material}, explain {target} using one open primary study. Supply the reported method, any defining equation, units, controls and specimen preparation needed to reproduce the measurement.'
  elif angle==2: question=f'For {material}, find one open primary study of {target}. Give a bounded before/after comparison, composition, processing conditions and test protocol; distinguish measured effects from inferred mechanisms.'
  else: question=f'For {material}, assess {target}. Ground the answer in one or two specimen-specific open primary results, identify what can be concluded and what extra measurements or matching conditions would be needed.'
  rows.append(dict(number=len(rows)+1,material=material,angle=angle,group='distinct',question=question+TAIL,depth='standard',parent=None,checkSample=False))
for index,topic in enumerate(TOPICS):
 parent=((index//2)%4)*40+index+1
 original=rows[parent-1]; selected=index%2==0
 original['checkSample']=selected
 rows.append(dict(original,number=len(rows)+1,group='repeat',parent=parent,checkSample=selected))
for row in rows: row['taskId']=hashlib.md5(('oopc-owner-200-2026-10-03-'+str(row['number'])).encode()).hexdigest()
assert len(rows)==200 and len({r['question'] for r in rows})==160
assert sum(r['checkSample'] for r in rows)==40
assert len({r['taskId'] for r in rows})==200
atomic_json(BASE/'questions.json',rows,private=True)
bench=BASE/'workspace'
if bench.exists(): raise RuntimeError('Preserve the existing harness workspace; do not reset it.')
bench.mkdir(mode=0o700); (bench/'releases').mkdir()
release=resolve_release(ROOT); (bench/'releases'/release.name).symlink_to(release,target_is_directory=True)
shutil.copy2(ROOT/'releases/current.json',bench/'releases/current.json')
knowledge.database(bench).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
source=sqlite3.connect(knowledge.database(ROOT).as_uri()+'?mode=ro',uri=True); target=sqlite3.connect(knowledge.database(bench))
try: source.backup(target)
finally: source.close();target.close()
knowledge.database(bench).chmod(0o600)
loop.update_settings(bench,loop.settings(ROOT))
loop.update_settings(bench,{'researchPerWeek':0})
atomic_json(BASE/'baseline.json',dict(at=now(),revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE,text=True).strip(),promptVersion=ask.prompt_version(),settings=loop.settings(bench),knowledge=knowledge.summary(bench),seedHash=hashlib.sha256((ROOT/'config/seed-lock.json').read_bytes()).hexdigest(),releaseManifestHash=hashlib.sha256((release/'manifest.json').read_bytes()).hexdigest()),private=True)
(BASE/'researcher-prompt.txt').write_text(ask.RESEARCHER); (BASE/'researcher-prompt.txt').chmod(0o600)
print('Prepared 200 tasks: 160 distinct, 40 exact repeats; 40 independent whole-answer checks.')
