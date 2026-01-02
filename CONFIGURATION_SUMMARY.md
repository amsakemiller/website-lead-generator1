# Configuration Summary - Optimized for Preclinical Cancer Device Leads

**Date:** January 2, 2026  
**Optimized for:** 2,500 Serper.dev credits + Claude Haiku 3.5

---

## Cost Estimates

| Service | Cost |
|---------|------|
| **Claude Console Deposit** | **$25-30** (for ~2,500 websites) |
| Haiku 3.5 per website | ~$0.0064 |
| Total estimated AI cost | ~$16-20 |

---

## What Was Changed

### Step 1: Website Discovery
- **Keyword boxes**: Optimized for 5×5×5×5×4 = 2,500 combinations
- **serper_combo_cap**: Set to 2,500
- **reanalysis_period**: Set to 0 (process fresh)

**Keyword Boxes:**
1. Core offering: `medical device, interventional device, therapeutic device, ablation device, drug delivery device`
2. Cancer focus: `oncology, cancer treatment, tumor ablation, solid tumor, cancer therapy`
3. Development stage: `preclinical, pre-clinical, translational research, early stage development, R&D stage`
4. Treatment modality: `ablation, embolization, minimally invasive, catheter-based, interventional radiology`
5. Target organs: `liver tumor, lung cancer device, pancreatic cancer, kidney tumor`

### Step 3: Factor-Based Scoring
**Positive Factors (keywords that ADD points):**
| Factor | Weight | Keywords |
|--------|--------|----------|
| US Location | 500 | usa, united states, boston, san francisco, new york, california, texas, etc. |
| Cancer/Oncology Focus | 300 | oncology, cancer, tumor, solid tumor, malignant, carcinoma, etc. |
| Target Organs | 250 | liver, lung, pancreas, kidney, bladder, bile duct, brain, glioma, etc. |
| Medical Device | 200 | medical device, catheter, ablation, interventional, minimally invasive, etc. |
| Preclinical Stage | 300 | preclinical, translational, early stage, r&d, animal study, etc. |
| Funding Signals | 150 | series a, series b, funding, grant, nih, sbir, cprit, etc. |

**Negative Factors (keywords that SUBTRACT points):**
| Factor | Weight | Keywords |
|--------|--------|----------|
| Liquid/Blood Cancers | 400 | bone marrow, leukemia, lymphoma, myeloma, hematologic, liquid cancer |
| Already FDA Approved | 300 | fda approved, fda cleared, 510k cleared, commercially available, on market |
| Late Clinical Stage | 200 | phase iii, phase 3, phase ii, phase 2, pivotal trial |

### Step 4: AI Analysis
- **Provider**: Claude (Anthropic)
- **Model**: Haiku 3.5 (`claude-3-5-haiku-20241022`)
- **Credit Limit**: $30.00
- **Max content chars**: 10,000 (optimized for cost)

**Scoring Fields (User's Prompts):**
1. **US-Based** (0-2): Headquarters location
2. **Funding Status** (0-10): Capital availability
3. **Organs** (multi-select): Target organs including Bile Duct, Bladder, Brain/CNS, Colorectal, Kidney, Liver, Lung, Pancreas, Soft Tissue
4. **Pre-Clinical Status** (0-3): 0=FDA approved/no product, 1=clinical trials, 2=early R&D, 3=preclinical (ideal)
5. **Type of Cancer** (text): Solid Tumor, Bone Marrow/Myeloma, Liquid/Hematologic, Other
6. **Business Type** (text): Medical Device, Drug/Device Combo, Biotech/Pharma, etc.
7. **Overall Score** (0-10): Final fit assessment

**Good Leads Reference (15 URLs):**
- https://www.jnj.com
- https://usa.guerbet.com
- https://abkbiomedical.com
- https://www.bd.com
- https://www.earli.com
- https://trisaluslifesci.com
- https://www.aurabiosciences.com
- https://betaglue.com
- https://www.bostonscientific.com
- https://mirai-medical.com
- https://www.pranasurgical.com
- https://www.stryker.com
- https://rakuten-med.com/us
- https://www.imchecktherapeutics.com
- https://www.engagebio.com

### Step 5: Contact Scoring
**Optimized for preclinical/oncology research:**
- **Seniority 4**: CEO, Founder, President, Managing Director
- **Seniority 3**: CSO, CTO, CMO, VP, Head of R&D, Head of Preclinical
- **Seniority 2**: Director, Senior Scientist, VP Research
- **Seniority 1**: Manager, Scientist, Project Lead

- **Fit 4**: Preclinical, Translational, Discovery, In Vivo, Animal Studies, CEO, CSO
- **Fit 3**: Research, R&D, Scientific, Device Development, Oncology
- **Fit 2**: Medical Device, Regulatory, Clinical Development, Engineering
- **Fit 1**: Business Development, Operations, Sales, Marketing

---

## Error Handling

The code already has proper error handling:
- **10 consecutive API failures** triggers graceful stop
- **Leads saved incrementally** after each successful search batch
- If API fails after finding websites, all found websites are preserved

---

## Lead Criteria (CRITICAL - any failure = bad lead)

✅ **Must Have:**
- Medical device therapeutic for cancer
- Treats solid tumors (not liquid cancers or bone marrow)
- Target organs: Bile duct, Bladder, Brain (glioma), Colorectal, Kidney, Liver, Lung, Pancreas, Soft tissue
- Preclinical phase (not FDA approved, not in late clinical trials)
- Sufficient capital ($200-500K for studies)
- Located in US

❌ **Disqualifiers:**
- Liquid/blood cancers (leukemia, lymphoma, myeloma)
- Already FDA approved products
- Late clinical stage (Phase II/III)
- No US operations

---

## Files Modified

1. `unified_leadgen.py` - Default configuration updated
2. `unified_config.json` - Runtime configuration updated
3. `update_config.py` - Configuration update script (can be re-run)

---

## Ready to Run

The system is now configured and ready. To start:
1. Run `python unified_leadgen.py` or double-click `run_gui.bat`
2. Verify Serper API key is set (should already be in config)
3. Start the pipeline

**Expected Results:**
- ~2,500 search queries
- ~500-2,000 unique websites discovered
- AI analysis on websites passing factor scoring
- Final CSV with scored leads
