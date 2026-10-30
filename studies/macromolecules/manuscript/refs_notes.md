# refs.bib notes (checked 2026-10-19)

Claim numbers refer to the nine Introduction claims in the request. "Crossref" means the metadata (authors, title, venue, year, volume, pages, DOI) was read from `https://api.crossref.org/works/<DOI>`. "arXiv" means it was read from the `arxiv.org/abs/<id>` page. "NeurIPS page" means it was read from proceedings.neurips.cc. Only DOIs, arXiv IDs and titles were sent to external services.

The relevance sentence is based on the abstract (from Crossref, OpenAlex-by-DOI or arXiv) unless the line says **[abstract not retrieved]**. In that case the summary rests on the title and general background. Check the full text before you cite a specific number from one of those papers.

## Entries

### Claim 1: polymer informatics
- `Audus2017Polymer`: 1. A viewpoint arguing that polymer informatics is held back mainly by how polymer systems and their properties are reported. Verified: Crossref 10.1021/acsmacrolett.7b00228.
- `Chen2021Polymer`: 1. A review of the polymer-informatics ecosystem (data, fingerprints, ML models, design) and its critical next steps. **[abstract not retrieved]** Verified: Crossref 10.1016/j.mser.2020.100595. Note: Crossref lists the user's "Tran" as family "Huan", given "Tran Doan", and the .bib keeps that form.

### Claim 2: polymer databases, data structures, ontologies
- `Otsuka2011PoLyInfo`: 2, 9. Describes the NIMS PoLyInfo database, curated mainly from academic papers, which records processing methods of samples and measurement conditions alongside properties. Verified: Crossref 10.1109/EIDWT.2011.13 (IEEE proceedings article).
- `Kim2018PolymerGenome`: 1, 2. Introduces Polymer Genome, ML property prediction built on a carefully accumulated dataset of computed and experimental polymer properties (including Tg). Verified: Crossref 10.1021/acs.jpcc.8b02913.
- `Ma2020PI1M`: 2. States that large-scale open polymer data are not readily available. It trains a generative model on about 12,000 polymers taken manually from PolyInfo to produce about 1 million hypothetical polymers. Verified: Crossref 10.1021/acs.jcim.0c00726.
- `Walsh2023CRIPT`: 2. Presents the CRIPT data model, motivated by polymers being large stochastic molecules with hierarchical structure that small-molecule cheminformatics handles poorly. Verified: Crossref 10.1021/acscentsci.3c00011.
- `Lin2019BigSMILES`: 2. Proposes BigSMILES, a line notation for stochastic macromolecules, because small-molecule identifiers do not fit polymer ensembles. Verified: Crossref 10.1021/acscentsci.9b00476.
- `Tchoua2016Blending`: 2. Notes that most property databases were built by decades of labour-intensive manual harvesting from the literature, and builds a thermodynamic property database by semi-automated, student-assisted curation. Verified: Crossref 10.1021/acs.jchemed.5b01032. This is the work usually cited for PPPDB, but the abstract does not name PPPDB, so confirm in the full text.
- `McCusker2020NanoMine`: 2, 8. Describes the NanoMine knowledge graph and ontology for polymer nanocomposite data (ISWC 2020, LNCS). **[abstract not retrieved]** Verified: Crossref 10.1007/978-3-030-62466-8_10.
- `Liu2023Ontology`: 2, 9. Builds a process ontology and data repository for conjugated-polymer OFETs. It reports that OFET mobility for a given polymer can vary by orders of magnitude with processing and measurement settings, and argues that FAIR records need sample provenance and process history. Verified: Crossref 10.1021/acs.chemmater.3c01842.

### Claim 3: text mining and LLM data extraction
- `Swain2016ChemDataExtractor`: 3. ChemDataExtractor is a chemistry-aware NLP toolkit that extracts entities, properties and measurements from text, tables and figures to fill structured databases. Verified: Crossref 10.1021/acs.jcim.6b00207.
- `Kononova2021TextMining`: 3. Reviews text mining and NLP in materials science and notes that general NLP tools struggle with technical scientific text. Verified: Crossref 10.1016/j.isci.2021.102155.
- `Shetty2023Pipeline`: 3. Polymer-abstract extraction pipeline with MaterialsBERT, giving about 300,000 property records from about 130,000 abstracts. Verified: Crossref 10.1038/s41524-023-01003-w.
- `Gupta2024LLM`: 2, 3. Uses LLMs (GPT-3.5, LLaMa 2) plus MaterialsBERT to extract over 1 million records for 24 properties of about 106,000 polymers from full-text articles, and evaluates cost against accuracy. Verified: Crossref 10.1038/s43246-024-00708-9 (Communications Materials 5, 269; the user's guess was correct).
- `Polak2024Extracting`: 3, 6. ChatExtract (the name is stripped from the Crossref abstract text) applies engineered prompts to a conversational LLM. Follow-up questions check each extracted value, reaching about 90% precision and recall with GPT-4 on materials data. Verified: Crossref 10.1038/s41467-024-45914-8.
- `Dagdelen2024Structured`: 3. Fine-tunes LLMs (GPT-3, Llama-2) for joint entity and relation extraction of structured materials records. Verified: Crossref 10.1038/s41467-024-45563-x.
- `Cheung2024POLYIE`: 3. POLYIE is an expert-annotated dataset of 146 full polymer papers with material, property, value and condition entities and their N-ary relations, close to this paper's finding schema. Verified: Crossref 10.18653/v1/2024.naacl-long.131 (NAACL 2024); abstract from arXiv 2311.07715.
- `Tshitoyan2019Embeddings`: 3. Shows that unsupervised word embeddings trained on materials-science abstracts encode latent structure-property knowledge. **[abstract not retrieved]** Verified: Crossref 10.1038/s41586-019-1335-8.

### Claim 4: LLM agents for chemistry and literature
- `Boiko2023Coscientist`: 4. Coscientist is a GPT-4 agent that uses web and documentation search, code execution and lab automation to plan and run experiments autonomously. Verified: Crossref 10.1038/s41586-023-06792-0.
- `Bran2024ChemCrow`: 4. ChemCrow augments GPT-4 with 18 expert chemistry tools and plans and executes syntheses. Verified: Crossref 10.1038/s42256-024-00832-8. Crossref gives the first author as family "M. Bran", given "Andres", and the .bib keeps that; the paper itself presents him as Andres M. Bran.
- `Lala2023PaperQA`: 4, 5. PaperQA is a retrieval-augmented agent over full-text papers that cites its answers, motivated by hallucination and provenance. It introduces LitQA. Verified: arXiv 2312.07559.
- `Skarlinski2024PaperQA2`: 4. PaperQA2 matches or exceeds subject-matter experts on literature retrieval, summarization and contradiction-detection tasks, and writes cited summaries. Verified: arXiv 2409.13740 (no Crossref version found).
- `White2023Language`: 4. A Nature Reviews Chemistry comment arguing that natural language and LLMs will become a central interface for chemistry. **[abstract not retrieved]** Verified: Crossref 10.1038/s41570-023-00502-0.
- `Jablonka2024Leveraging`: 4. Shows that fine-tuned GPT-3 answering chemistry questions in natural language rivals dedicated ML models, especially in the low-data regime. Verified: Crossref 10.1038/s42256-023-00788-1.
- `Lu2024AIScientist`: 4. The AI Scientist is an end-to-end LLM framework that generates ideas, runs experiments and writes papers. Verified: arXiv 2408.06292 (no Crossref version found).
- `Gottweis2026CoScientist`: 4. Co-Scientist is a Gemini-based multi-agent system that generates, critiques and refines hypotheses for experimental validation. Verified: Crossref 10.1038/s41586-026-10644-y (Nature 655, 487–496, 2026). This replaces the 2025 arXiv preprint; see the substitutions below.

### Claim 5: retrieval and memory for LLM agents
- `Lewis2020RAG`: 5. Retrieval-augmented generation combines a parametric generator with a retrieved non-parametric memory and names provenance and knowledge updating as motivations. Verified: NeurIPS page (Advances in Neural Information Processing Systems 33, 9459–9474; no DOI); abstract from arXiv 2005.11401.
- `Park2023Generative`: 5. Generative agents store a natural-language record of experiences, reflect on them, and retrieve memories to plan. Verified: Crossref 10.1145/3586183.3606763 (UIST '23).
- `Packer2023MemGPT`: 5. MemGPT uses OS-style virtual context management to page information between memory tiers beyond the context window. Verified: arXiv 2310.08560.
- `Wang2023Voyager`: 5. Voyager keeps an ever-growing skill library of executable code that it stores and retrieves for lifelong learning. Verified: arXiv 2305.16291.
- `Shinn2023Reflexion`: 5, 7. Reflexion agents improve through verbal reflections stored in an episodic memory buffer rather than weight updates. Verified: Crossref 10.52202/075280-0377 and NeurIPS page (NeurIPS 36, 8634–8652).

### Claim 6: hallucination, fabricated citations, LLM judges, claim verification
- `Ji2023Survey`: 6. Survey of hallucination in natural language generation: metrics, mitigation and task-specific findings. Verified: Crossref 10.1145/3571730 (ACM Comput. Surv. 55(12), pages 1–38 as Crossref gives them; the ACM article number is not in the Crossref record).
- `Walters2023Fabrication`: 6. In 636 citations from ChatGPT-written literature reviews, 55% of GPT-3.5 and 18% of GPT-4 citations were fabricated, and many real ones contained substantive errors. Verified: Crossref 10.1038/s41598-023-41032-5.
- `Zheng2023Judging`: 6. Studies LLM-as-a-judge, its position, verbosity and self-enhancement biases, and its agreement with human preferences (MT-Bench, Chatbot Arena). Verified: Crossref 10.52202/075280-2020 and NeurIPS page (NeurIPS 36 Datasets and Benchmarks Track, 46595–46623).
- `Wadden2020SciFact`: 6. Defines scientific claim verification and the SciFact dataset of 1.4K expert claims, each with supporting or refuting abstracts and rationales. Verified: Crossref 10.18653/v1/2020.emnlp-main.609; abstract from arXiv 2004.14974.

### Claim 7: automated prompt and scaffold improvement
- `Yang2023OPRO`: 7. OPRO has an LLM optimize prompts by proposing new solutions from a prompt that lists earlier solutions and their scores. Verified: arXiv 2309.03409 (the arXiv comments say ICLR 2024).
- `Khattab2023DSPy`: 7. DSPy compiles declarative LM pipelines and optimizes their prompts and demonstrations automatically. Verified: arXiv 2310.03714.
- `Yuksekgonul2025TextGrad`: 7. TextGrad back-propagates LLM-written textual feedback to optimize the components of compound AI systems. Verified: Crossref 10.1038/s41586-025-08661-4 (Nature 639, 609–616); abstract from arXiv 2406.07496.
- `Zhang2025Darwin`: 7. The Darwin Gödel Machine is a self-improving coding agent that repeatedly rewrites its own code and validates each change empirically, keeping an open-ended archive of variants. Verified: arXiv 2505.22954.

### Claim 8: provenance and FAIR data
- `Wilkinson2016FAIR`: 8. Sets out the FAIR principles (findable, accessible, interoperable, reusable), with emphasis on machine-actionable reuse. Verified: Crossref 10.1038/sdata.2016.18 (all 53 authors as Crossref lists them).
- `Lebo2013PROVO`: 8. W3C Recommendation expressing the PROV data model in OWL2 for representing and exchanging provenance. Verified: W3C TR page https://www.w3.org/TR/2013/REC-prov-o-20130430/ (editors Lebo, Sahoo and McGuinness, 30 April 2013; no DOI).

### Claim 9: property values depend on grade, specimen, method and conditions
- `FoxFlory1950Second`: 9. Tg and specific volume of fractionated polystyrenes rise with molecular weight toward limits reached near M ≈ 30,000, with a 1/Mn dependence (the Fox–Flory relation). Verified: Crossref 10.1063/1.1699711.
- `Hutchinson2009Glass`: 9. A review of how Tg is determined by different techniques, how the values correlate, and the effect of structural heterogeneity. **[abstract not retrieved; summary from title and subtitle]** Verified: Crossref 10.1007/s10973-009-0268-0 (Crossref stores the subtitle separately; the .bib joins them).
- `GraciaFernandez2010Comparative`: 9. Compares the frequency-dependent ("dynamic") Tg measured by DMA with that from temperature-modulated DSC. **[abstract not retrieved; summary from title]** Verified: Crossref 10.1016/j.polymertesting.2010.09.005.
- `Moynihan1974Heating`: 9. A classic analysis of how the measured Tg shifts with heating and cooling rate. As far as I know it is general glass physics, not polymer-specific. **[abstract not retrieved; summary from title]** Verified: Crossref 10.1021/j100619a008.
- `Aucejo1999Water`: 9. By DSC on four EVOH grades equilibrated at different relative humidities, Tg falls from about 50 °C dry to below room temperature at high RH (water plasticization), while crystallinity is essentially unchanged. Verified: Crossref 10.1002/(SICI)1097-4628(19991031)74:5<1201::AID-APP17>3.0.CO;2-8.
- `Muramatsu2003Oxygen`: 9. Measures EVOH film oxygen permeability and positron free-volume hole size as functions of temperature and humidity. **[abstract not retrieved; summary from title]** Verified: Crossref 10.1016/S0969-806X(03)00231-7.
- `Mokwena2012EVOH`: 9. A review of EVOH oxygen-barrier properties stressing their moisture sensitivity and the effect of food-processing conditions. Verified: Crossref 10.1080/10408398.2010.504903.
- `Nunes1982MolecularWeight`: 9. Reviews how thermal and mechanical properties (stress–strain, impact, fracture, fatigue, creep, crazing) depend on molecular weight and its distribution; they generally rise with MW up to a limiting value. Verified: Crossref 10.1002/pen.760220402.
- `Perego1996PLA`: 9. For PLA, molecular weight, tacticity (PLLA versus PDLLA) and annealing-induced crystallinity change modulus, impact strength and heat resistance. Verified: Crossref 10.1002/(SICI)1097-4628(19960103)59:1<37::AID-APP6>3.0.CO;2-N.
- `Jha2019Uncertainty`: 1, 9. Curates Tg from many sources, shows the widespread variation in values reported for the same polymer from intrinsic and extrinsic measurement factors, and studies how that spread affects ML models. Verified: Crossref 10.1088/1361-651X/aaf8ca.

### Methods and data source (coordinator additions)
- `Seabold2010Statsmodels`: methods (statistics software). The statsmodels paper. Verified: Crossref 10.25080/Majora-92bf1922-011 (Proceedings of the 9th Python in Science Conference, 92–96).
- `WOP2026Wiki`: the seed data source. **NOT VERIFIED.** It is the author's own repository and was added exactly as the coordinator specified.

## Substitutions and corrections to the request
- **AI co-scientist (Gottweis et al.)**: now published as Gottweis et al., *Nature* 655, 487–496 (2026), titled "Accelerating scientific discovery with Co-Scientist". arXiv 2502.18864 v1 (2025) was titled "Towards an AI co-scientist". The .bib cites the Nature version (key `Gottweis2026CoScientist`, not 2025).
- **TextGrad**: the Nature 2025 version exists and is cited, titled "Optimizing generative AI by backpropagating language model feedback". The arXiv preprint 2406.07496 has a different title ("TextGrad: Automatic 'Differentiation' via Text") and one fewer author; Pan Lu was added in Nature.
- **Reflexion**: cited as the NeurIPS 2023 paper. The proceedings and Crossref list 5 authors; arXiv v4 also lists Edward Berman.
- **LLM-as-a-judge (Zheng et al.)**: NeurIPS 2023 Datasets and Benchmarks Track, which has a DOI (10.52202/075280-2020).
- **POLYIE**: the published version is NAACL 2024 (with a DOI). Crossref gives the first author as "Cheung, Jerry"; arXiv gives "Jerry Junyang".
- **PPPDB (Tchoua et al.)**: no paper titled after PPPDB was found. The .bib uses Tchoua et al. 2016 *J. Chem. Educ.* (semi-automated creation of a thermodynamic property database). Confirm that this is the PPPDB citation you want.
- **Polymer ontology papers**: a Crossref title search found no general "polymer ontology" paper. Substituted Liu et al. 2023 *Chem. Mater.* (conjugated-polymer process ontology) and McCusker et al. 2020 ISWC (NanoMine knowledge graph for polymer nanocomposites). A 2025 MDPI *Polymers* paper (10.3390/polym17192612, ontology modelling of PVC systems) exists but was left out as less established.
- **Aucejo1999Water (coordinator request)**: the paper is real, but it measures water's effect on EVOH **Tg and morphology** (DSC), not oxygen permeability. For oxygen permeability versus RH, use `Muramatsu2003Oxygen`, with `Mokwena2012EVOH` as the review.
- **"DSC vs DMA" Tg (coordinator's GraciaFernandez2010Comparative)**: real and verified, but it compares DMA with **temperature-modulated** DSC (TMDSC), not conventional DSC. `Hutchinson2009Glass` covers the broader comparison between methods.
- **Darwin Gödel Machine**: the arXiv title field is ASCII ("Darwin Godel Machine") and the .bib keeps it exactly. Change it to `G{\"o}del` if you prefer. A Crossref record with the same title exists (10.70777/si.v2i3.15063) in a minor journal; it was not used.
- **Key format**: `FoxFlory1950Second` and `GraciaFernandez2010Comparative` follow the coordinator's requested keys rather than strict FirstAuthorYearWord.

## Not verifiable / no published version found
- `WOP2026Wiki`: not verified, by instruction.
- PaperQA2, The AI Scientist, MemGPT, Voyager, DSPy and the Darwin Gödel Machine: arXiv only. No Crossref record for a published version was found (Crossref title search, 2026-10-19). Voyager and DSPy are often cited as TMLR 2024 and ICLR 2024 respectively, but that was not verified here.
- Content checks: abstracts could not be retrieved (publisher bot challenges, no Crossref or OpenAlex abstract) for Chen2021, McCusker2020, Tshitoyan2019, White2023, Hutchinson2009, GraciaFernandez2010, Moynihan1974 and Muramatsu2003. Their bibliographic metadata is verified; their one-line summaries are not abstract-checked.

## Verified on Crossref but not included (optional alternates)
- Ito et al. 2001 *Macromolecules* 34, 6153–6155, 10.1021/ma001813a: EVOH oxygen permeability versus PALS free volume.
- Lagaron, Catalá, Gavara 2004 *Mater. Sci. Technol.* 20, 1–7, 10.1179/026708304225010442: structural factors behind high-barrier polymers, with EVOH as the benchmark.
- Williams, Landel, Ferry 1955 *J. Am. Chem. Soc.* 77, 3701–3707, 10.1021/ja01619a008: the WLF equation; the time–temperature (frequency) dependence of relaxations.
- Cabedo et al. 2006 *Polym. Test.* 25, 860–867, 10.1016/j.polymertesting.2006.04.012: water sorption changes EVOH mechanical properties.
- Tao, Varshney, Li 2021 *J. Chem. Inf. Model.* 61, 5395–5413, 10.1021/acs.jcim.1c01031: benchmark of ML models for Tg.
- Jenkins et al. 1996 *Pure Appl. Chem.* 68, 2287–2311, 10.1351/pac199668122287: IUPAC glossary of basic polymer terms.

## Added 2026-10-29 (introduction: agent memory and harnesses)
- `Sumers2024CoALA`: TMLR 2024 (OpenReview 1i6ZCvflQJ; the TMLR BibTeX and arXiv 2309.02427 agree on title and authors). Frames language agents by memory (working and long-term), action space and decision making; cited for memory as a module of agents.
- `Zhang2024Memory`: arXiv 2404.13501 (no journal reference on the arXiv page). A survey of memory in LLM-based agents.
- `Wang2024Workflow`: arXiv 2409.07429 (no journal reference on the arXiv page). Induces reusable workflows from past tasks and supplies them to later ones.
- `Yang2024SWEagent`: NeurIPS 2024; Crossref (10.52202/079017-1601) gives the title, the seven authors, volume 37 and pages 50528–50652. Cited for an interface (harness) that changes what a fixed model achieves.
- `OpenAI2024Memory`: OpenAI's announcement (2024-02-13; updates to 2025-06-03). The page refused automated fetches (HTTP 403); title, date and updates come from search results.
- `Anthropic2025Memory`: claude.com/blog/memory (redirected from anthropic.com/news/memory), "Bringing memory to Claude", 2025-09-11, updated 2025-10-23. It says users can view and edit memories, memory is separate per project, and memory can be exported or brought over from another AI tool — hence "what can move to another assistant is a text summary".
- `Anthropic2024MCP`: "Introducing the Model Context Protocol", 2024-11-25, fetched; defines MCP as an open standard. That Codex and Claude Code both use it is this project's own engine code (`oopc/engines.py`), not the citation.
