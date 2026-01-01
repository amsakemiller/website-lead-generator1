# Agent Processing Rules

How the optimization agent interprets user inputs and maps them to system configuration.

---

## Input → Config Mapping

### 1. Parse User Inputs

| User Input | Extracts To | Config Target |
|------------|-------------|---------------|
| `product_description` | Industry keywords, product terms | `step1.keyword_boxes[0-1]` |
| `ideal_customer` | Size signals, activity terms, qualifiers | `step1.keyword_boxes[2-3]`, `step3.positive_factors` |
| `company_size` | Size thresholds, stage keywords | `step3.positive_factors`, scoring field prompts |
| `geography` | Region code, geographic keywords | `step1.region`, `step3.positive_factors` (geographic) |
| `seniority_levels` | Title level keywords | `step5.seniority_*_titles` |
| `departments` | Function keywords | `step5.fit_*_titles` |
| `exclusions` | Negative keywords, competitors | `step3.negative_factors` |
| `good_leads` | Domain list | `step4.good_leads_domains` |
| `search_keywords` | Pre-organized keyword boxes | `step1.keyword_boxes[]` (direct if user organized) |
| `other_context` | Buying signals, timing | `step3.positive_factors`, scoring prompts |
| `extract_contacts` | Boolean | `step5.enabled` |
| `price_min/max` | Budget indicators | Scoring prompts (funding assessment) |

---

### 2. Keyword Box Construction

The agent should organize keywords into 5-7 boxes following this structure:

| Box | Purpose | Source from User Input |
|-----|---------|------------------------|
| **1** | Industry/Vertical | `product_description` → extract industry |
| **2** | Product/Service Type | `product_description` → extract product category |
| **3** | Problem/Need | `ideal_customer` → extract pain points |
| **4** | Company Stage/Size | `company_size` + `other_context` → stage signals |
| **5** | Technology/Tools | `search_keywords` or infer from industry |
| **6** | Activity/Behavior | `other_context` → buying signals |
| **7** | Geographic (optional) | `geography` if region-specific terms help |

**If user provides `search_keywords` pre-organized:** Use their categories directly.

**Combo cap calculation:**
```
total_combinations = keywords_box1 × keywords_box2 × ... × keywords_boxN
Set serper_combo_cap = min(total_combinations, 500)
```

---

### 3. Scoring Field Configuration

Map user inputs to AI scoring prompts:

| User Input | Scoring Field | Prompt Customization |
|------------|---------------|---------------------|
| `geography` | "Geographic Fit" (score 0-2) | Include specific countries/regions |
| `company_size` | "Company Size Fit" (score 0-10) | Reference their size requirements |
| `ideal_customer` | "Overall Match" (score 0-100) | Embed full ICP description |
| `price_min/max` | "Funding/Budget" (score 0-10) | Calibrate to their deal size |
| `exclusions` | Built into all prompts | "Exclude if: [exclusions]" |

---

### 4. Factor Construction

**Positive Factors** (from `ideal_customer`, `company_size`, `other_context`):

| Factor Name | Weight | Source |
|-------------|--------|--------|
| Industry Match | 200 | Keywords from `ideal_customer` industry mentions |
| Size Fit | 150 | Keywords from `company_size` |
| Geographic | 100 | Keywords from `geography` |
| Buying Signals | 100 | Keywords from `other_context` |

**Negative Factors** (from `exclusions`):

| Factor Name | Weight | Source |
|-------------|--------|--------|
| Wrong Industry | 200 | Industries listed in exclusions |
| Competitors | 300 | Company names in exclusions |
| Wrong Size | 100 | Size exclusions mentioned |
| Academic/Non-profit | 100 | If mentioned in exclusions |

---

### 5. Contact Title Configuration

Map `seniority_levels` and `departments` to step5 title lists:

**Seniority mapping:**
- User says "CEO, VP, Director" → populate `seniority_4_titles`, `seniority_3_titles`, `seniority_2_titles`
- Weight higher seniority levels more heavily

**Department mapping:**
- User says "IT, Operations" → populate `fit_3_titles`, `fit_4_titles` with those + related terms
- Cross-reference with seniority for combined scoring

---

### 6. Threshold Selection

Based on run context:

| Scenario | Threshold Config |
|----------|------------------|
| First run / Exploratory | `use_percentage_threshold = True, percentage_value = 30` |
| Known ICP, high confidence | `use_score_threshold = True, threshold_value = 70` |
| Fixed budget | `use_count_threshold = True, count_value = budget / cost_per_lead` |
| Maximum coverage | All thresholds OFF |

---

## Single Prompt Mode Processing

When user provides free-form text instead of structured inputs:

1. **Extract structured data using AI:**
   - Business name and website
   - Product/service description
   - ICP characteristics
   - Exclusions
   - Example URLs
   - Title preferences

2. **Map to structured fields** (same as above)

3. **Validate completeness:**
   - Required: business_name, website_url, product_description, ideal_customer
   - Warn if missing: geography, good_leads, exclusions

---

## Feedback Loop Integration

After each run, log to `leadgen_feedback.db`:

```json
{
  "run_id": "uuid",
  "user_inputs": { /* all user inputs */ },
  "agent_decisions": {
    "keyword_boxes": ["box1", "box2"],
    "scoring_fields": ["field1", "field2"],
    "positive_factors": [{"name": "x", "keywords": "y"}],
    "negative_factors": [{"name": "x", "keywords": "y"}]
  },
  "outcomes": {
    "leads_discovered": 500,
    "leads_ai_marked_good": 45,
    "user_confirmed_good": 12
  }
}
```

Use historical data to:
- Identify high-performing keywords
- Adjust factor weights based on predictiveness
- Recommend threshold values based on past precision
