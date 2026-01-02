#!/usr/bin/env python3
"""
Update unified_config.json with optimized settings for preclinical cancer device leads.
"""

import json
import os

CONFIG_FILE = "unified_config.json"

# API key will be read from existing config (not overwritten if already set)
CLAUDE_API_KEY = None  # Set via unified_config.json

# All 15 good leads URLs
GOOD_LEADS_DOMAINS = ", ".join([
    "https://www.jnj.com",
    "https://usa.guerbet.com", 
    "https://abkbiomedical.com",
    "https://www.bd.com",
    "https://www.earli.com",
    "https://trisaluslifesci.com",
    "https://www.aurabiosciences.com",
    "https://betaglue.com",
    "https://www.bostonscientific.com",
    "https://mirai-medical.com",
    "https://www.pranasurgical.com",
    "https://www.stryker.com",
    "https://rakuten-med.com/us",
    "https://www.imchecktherapeutics.com",
    "https://www.engagebio.com"
])

# Optimized keyword boxes for ~2500 Serper credits (5x5x5x5x4 = 2500)
KEYWORD_BOXES = [
    # Box 1: Core offering type (5 terms)
    "medical device, interventional device, therapeutic device, ablation device, drug delivery device",
    # Box 2: Cancer focus (5 terms)
    "oncology, cancer treatment, tumor ablation, solid tumor, cancer therapy",
    # Box 3: Development stage (5 terms)
    "preclinical, pre-clinical, translational research, early stage development, R&D stage",
    # Box 4: Treatment modality (5 terms)
    "ablation, embolization, minimally invasive, catheter-based, interventional radiology",
    # Box 5: Target organs (4 terms)
    "liver tumor, lung cancer device, pancreatic cancer, kidney tumor",
    # Empty remaining boxes
    "",
    "",
    ""
]

# Optimized positive scoring factors
POSITIVE_FACTORS = [
    {"name": "US Location", "weight": 500, "sensitivity": 1, "keywords": "usa, united states, us-based, boston, san francisco, new york, california, texas, massachusetts, pennsylvania, new jersey, chicago, houston, philadelphia, austin, denver, seattle, miami, headquarters in the us, based in the us"},
    {"name": "Cancer/Oncology Focus", "weight": 300, "sensitivity": 2, "keywords": "oncology, cancer, tumor, tumour, solid tumor, malignant, carcinoma, neoplasm, metastatic, ablation therapy, cancer treatment"},
    {"name": "Target Organs", "weight": 250, "sensitivity": 2, "keywords": "liver, hepatic, lung, pulmonary, pancreas, pancreatic, kidney, renal, bladder, bile duct, biliary, brain, glioma, colorectal, colon, soft tissue, sarcoma"},
    {"name": "Medical Device", "weight": 200, "sensitivity": 2, "keywords": "medical device, device, catheter, implant, ablation, interventional, minimally invasive, endoscopic, drug delivery, microsphere, radiofrequency, rf ablation, microwave, thermal, cryoablation, embolization, electroporation"},
    {"name": "Preclinical Stage", "weight": 300, "sensitivity": 1, "keywords": "preclinical, pre-clinical, translational, early stage, r&d, research and development, proof of concept, animal study, in vivo, in vitro, laboratory research"},
    {"name": "Funding Signals", "weight": 150, "sensitivity": 2, "keywords": "series a, series b, series c, funding, raised, investment, venture, grant, nih, sbir, sttr, cprit, capital, investors"},
    {"name": "Factor 7", "weight": 100, "sensitivity": 1, "keywords": ""},
    {"name": "Factor 8", "weight": 100, "sensitivity": 1, "keywords": ""}
]

# Optimized negative scoring factors  
NEGATIVE_FACTORS = [
    {"name": "Liquid/Blood Cancers", "weight": 400, "sensitivity": 1, "keywords": "bone marrow, leukemia, lymphoma, myeloma, hematologic, liquid cancer, blood cancer"},
    {"name": "Already FDA Approved", "weight": 300, "sensitivity": 1, "keywords": "fda approved, fda-approved, fda cleared, fda-cleared, 510k cleared, commercially available, on market, market leader"},
    {"name": "Late Clinical Stage", "weight": 200, "sensitivity": 2, "keywords": "phase iii, phase 3, phase ii, phase 2, pivotal trial, registration trial, nda, pma approved"},
    {"name": "Disqualifier 4", "weight": 100, "sensitivity": 1, "keywords": ""},
    {"name": "Disqualifier 5", "weight": 100, "sensitivity": 1, "keywords": ""},
    {"name": "Disqualifier 6", "weight": 100, "sensitivity": 1, "keywords": ""},
    {"name": "Disqualifier 7", "weight": 100, "sensitivity": 1, "keywords": ""},
    {"name": "Disqualifier 8", "weight": 100, "sensitivity": 1, "keywords": ""}
]

# User's optimized scoring fields
SCORING_FIELDS = [
    {
        "enabled": True,
        "type": "score",
        "title": "US-Based",
        "min": 0,
        "max": 2,
        "prompt": "Assign a score of 0 if you are certain this business is not based in the US and has no US operations. Assign a score of 1 if you are unsure whether the business is US-based OR if the business is not US-headquartered but has confirmed US operations. Assign a score of 2 if you are confident this business is headquartered in the United States.",
        "allow_unlisted": True,
        "allow_multiple": False,
        "options": []
    },
    {
        "enabled": True,
        "type": "score",
        "title": "Funding Status",
        "min": 0,
        "max": 10,
        "prompt": "Assign a funding score from 0-10. Consider: recent funding rounds (Series A/B/C); grant awards; products already in market; partnerships with major companies; significant hiring; professional website quality. Score 0 if business appears defunct or unfunded. Score 1-3 for early-stage with minimal funding evidence. Score 4-6 for moderate funding indicators. Score 7-10 for well-funded companies with clear evidence of substantial capital.",
        "allow_unlisted": True,
        "allow_multiple": False,
        "options": []
    },
    {
        "enabled": True,
        "type": "text",
        "title": "Organs",
        "min": 0,
        "max": 10,
        "prompt": "Identify which organs or body systems this company's products/services target. Select all that apply.",
        "allow_unlisted": True,
        "allow_multiple": True,
        "options": ["Liver", "Pancreas", "Lung", "Brain/CNS", "Kidney", "Bladder", "Bile Duct", "Colorectal", "Soft Tissue", "Heart", "GI Tract", "Skin", "Bone/Musculoskeletal", "Blood/Hematology", "Other"]
    },
    {
        "enabled": True,
        "type": "score",
        "title": "Pre-Clinical Status",
        "min": 0,
        "max": 3,
        "prompt": "Assess the company's product development stage. Score 0 if no clear product is in development, or if all products are already FDA-Approved. Score 1 for clinical trials. Score 2 for early product development and R&D. Score 3 for preclinical development (ideal for large animal testing). The score should reflect the highest score of all products in development. So, if one product is phase III but another is in preclinical development, assign a score of 3.",
        "allow_unlisted": True,
        "allow_multiple": False,
        "options": []
    },
    {
        "enabled": True,
        "type": "text",
        "title": "Type of Cancer",
        "min": 0,
        "max": 10,
        "prompt": "Identify the type of cancer products from this company focus on.",
        "allow_unlisted": True,
        "allow_multiple": True,
        "options": ["Solid Tumor", "Bone Marrow/Myeloma Cancer", "Liquid/Hematologic Cancers", "Not Cancer Focused", "Other"]
    },
    {
        "enabled": True,
        "type": "text",
        "title": "Business Type",
        "min": 0,
        "max": 10,
        "prompt": "Categorize this business into one primary type based on their core offering.",
        "allow_unlisted": True,
        "allow_multiple": False,
        "options": ["Medical Device Manufacturer", "Drug/Device Combination", "Biotech/Pharma", "CRO (Contract Research Organization)", "Diagnostics", "Academic/Research Institution", "Other Healthcare"]
    },
    {
        "enabled": True,
        "type": "score",
        "title": "Overall Score",
        "min": 0,
        "max": 10,
        "prompt": "Score how well this company fits as a prospect for preclinical large animal (porcine) testing services. Consider: Are they at the right development stage (preclinical)? Do they have a medical device that would benefit from pig model testing? Are they well-funded enough to afford preclinical studies ($200-500K)? Do they treat solid tumors (not liquid cancers)? Are they US-based? Score 0-3 for poor fit; 4-6 for moderate fit; 7-10 for excellent fit.",
        "allow_unlisted": True,
        "allow_multiple": False,
        "options": []
    }
]

# Pad with empty disabled fields to reach 20
while len(SCORING_FIELDS) < 20:
    SCORING_FIELDS.append({
        "enabled": False,
        "type": "score",
        "title": "",
        "min": 0,
        "max": 10,
        "prompt": "",
        "allow_unlisted": True,
        "allow_multiple": False,
        "options": []
    })


def update_config():
    # Load existing config
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    print("Updating configuration...")
    
    # Step 1 updates
    config["step1"]["keyword_boxes"] = KEYWORD_BOXES
    config["step1"]["serper_combo_cap"] = 2500
    config["step1"]["reanalysis_period"] = 0
    print("  [OK] Step 1: Keyword boxes updated for 2500 credits")
    
    # Step 3 updates
    config["step3"]["score_threshold"] = 60
    config["step3"]["threshold_value"] = "60"
    config["step3"]["positive_factors"] = POSITIVE_FACTORS
    config["step3"]["negative_factors"] = NEGATIVE_FACTORS
    config["step3"]["positive_factor_count"] = len(POSITIVE_FACTORS)
    config["step3"]["negative_factor_count"] = len(NEGATIVE_FACTORS)
    print("  [OK] Step 3: Positive/negative factors updated with keywords")
    
    # Step 4 updates (preserve existing API key)
    # config["step4"]["api_key"] = CLAUDE_API_KEY  # Don't overwrite - keep existing key
    config["step4"]["provider_choice"] = "claude"
    config["step4"]["model"] = "claude-3-5-haiku-20241022"
    config["step4"]["model_choice"] = "model_1"
    config["step4"]["good_leads_domains"] = GOOD_LEADS_DOMAINS
    config["step4"]["scoring_fields"] = SCORING_FIELDS
    config["step4"]["scoring_field_count"] = 20
    config["step4"]["max_tokens"] = 2000
    config["step4"]["credit_limit"] = 30.0
    config["step4"]["max_content_chars"] = 10000
    config["step4"]["skip_if_processed_within_days"] = 0
    print("  [OK] Step 4: Claude API key, Haiku 3.5, scoring fields updated")
    print("  [OK] Step 4: Good leads domains added (15 URLs)")
    
    # Step 5 contact scoring titles
    config["step5"] = config.get("step5", {})
    config["step5"]["seniority_4_titles"] = "CEO, Founder, Co-Founder, Chairman, President, Owner, Chief Executive Officer, Managing Director, Principal"
    config["step5"]["seniority_3_titles"] = "CSO, CTO, CMO, COO, Chief Scientific Officer, Chief Technology Officer, Chief Medical Officer, Vice President, VP, EVP, SVP, Head of R&D, Head of Research, Head of Preclinical, Head of Development"
    config["step5"]["seniority_2_titles"] = "Director, Senior Director, Executive Director, Scientific Advisor, Senior Scientist, Principal Scientist, Lead Scientist, VP Research, Director of Research, Director of Preclinical"
    config["step5"]["seniority_1_titles"] = "Manager, Senior Manager, Scientist, Principal Investigator, Research Scientist, Project Lead, Team Lead, Associate Director"
    config["step5"]["fit_4_titles"] = "Preclinical, Translational, Discovery, In Vivo, Animal Studies, CEO, Founder, President, Chief Scientific Officer, CSO, Head of R&D"
    config["step5"]["fit_3_titles"] = "Research, R&D, Scientific, Laboratory, Device Development, Product Development, Oncology, Cancer, VP Research, Director Research"
    config["step5"]["fit_2_titles"] = "Medical Device, Device Engineering, Regulatory, Clinical Development, Medical Affairs, Biomedical, Engineering"
    config["step5"]["fit_1_titles"] = "Business Development, Operations, Project Management, Quality, Manufacturing, Sales, Marketing"
    print("  [OK] Step 5: Contact scoring titles updated for preclinical/oncology focus")
    
    # Save updated config
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)
    
    print(f"\nConfiguration saved to {CONFIG_FILE}")
    print("\n" + "="*60)
    print("CONFIGURATION SUMMARY")
    print("="*60)
    print(f"Search API: Serper.dev (existing key preserved)")
    print(f"Serper Credits: 2500 combinations")
    print(f"AI Provider: Claude")
    print(f"AI Model: Haiku 3.5 (claude-3-5-haiku-20241022)")
    print(f"Credit Limit: $30.00")
    print(f"Good Leads: 15 reference websites")
    print(f"Scoring Fields: 7 enabled fields")
    print(f"  - US-Based (0-2)")
    print(f"  - Funding Status (0-10)")
    print(f"  - Organs (multi-select)")
    print(f"  - Pre-Clinical Status (0-3)")
    print(f"  - Type of Cancer (text)")
    print(f"  - Business Type (text)")
    print(f"  - Overall Score (0-10)")
    

if __name__ == "__main__":
    update_config()
