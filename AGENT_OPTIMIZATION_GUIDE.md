# Lead Generation Agent Optimization Guide

## Purpose

This document serves two goals:
1. **Training Data Foundation**: Structured information for training a future optimization agent
2. **AI Engineer Reference**: Starting point for designing optimal search strategies

---

## User Input System

User inputs are collected via the Setup tab (see `user_input_config.json` for field definitions).

### Input Fields Summary

| Field | Required | Config Key | Maps To |
|-------|----------|------------|---------|
| Business Name | ✓ | `user_inputs.business_name` | Prompt context |
| Website URL | ✓ | `user_inputs.website_url` | Auto-scrape for context |
| Product Description | ✓ | `user_inputs.product_description` | Keyword boxes 1-2 |
| Ideal Customer | ✓ | `user_inputs.ideal_customer` | Keyword boxes, scoring prompts |
| Price Range | | `user_inputs.price_min/max` | Funding score calibration |
| Company Size | | `user_inputs.company_size` | Positive factors |
| Geography | | `user_inputs.geography` | Region, positive factors |
| Seniority Levels | | `user_inputs.seniority_levels` | `step5.seniority_*_titles` |
| Departments | | `user_inputs.departments` | `step5.fit_*_titles` |
| Exclusions | | `user_inputs.exclusions` | Negative factors |
| Good Leads | | `user_inputs.good_leads` | `step4.good_leads_domains` |
| Search Keywords | | `user_inputs.search_keywords` | `step1.keyword_boxes[]` |
| Other Context | | `user_inputs.other_context` | Buying signals → factors |
| Extract Contacts | | `user_inputs.extract_contacts` | `step5.enabled` |

---

## Variables Requiring Per-Run Optimization

### Category 1: Discovery Keywords (`step1.keyword_boxes[]`)

One keyword is randomly selected from each non-empty box and combined into a search query.

**Box Strategy**:

| Box | Purpose | Source |
|-----|---------|--------|
| 1 | Industry/Vertical | `product_description` industry terms |
| 2 | Product/Problem | `product_description` product terms |
| 3 | Company Stage/Size | `company_size`, `other_context` |
| 4 | Technology/Tools | `search_keywords` or inferred |
| 5 | Activity/Behavior | `other_context` buying signals |

**Decision Tree**:
```
IF user provides search_keywords organized by category:
    Use their categories directly
ELSE IF narrow ICP (one industry + one product):
    Use 2-3 boxes, combo_cap = 50-100
ELSE IF broad ICP (multiple segments):
    Use 5-7 boxes, combo_cap = 300-500
ELSE (exploratory):
    Use 3-4 boxes, combo_cap = 100-200
    Enable percentage_threshold = 30%
```

---

### Category 2: AI Scoring Fields (`step4.scoring_fields[]`)

**Core Fields (Always Enable)**:

| Field | Type | Purpose |
|-------|------|---------|
| Geographic Fit | score (0-2) | Based on `geography` input |
| Funding/Viability | score (0-10) | Calibrate to `price_min/max` |
| Business Type | text | Categories from `product_description` |
| Overall Match | score (0-100) | Uses full ICP context |

**Prompt Optimization**:
- Reference user's business: "for a company selling [product_description]"
- Be specific: "score 7-10 if [specific criteria from ideal_customer]"
- System auto-appends good leads summary when available

---

### Category 3: Factor-Based Scoring (`step3.positive/negative_factors[]`)

**Build Positive Factors From**:

| User Input | Factor Name | Weight |
|------------|-------------|--------|
| `ideal_customer` industry terms | Industry Match | 200 |
| `company_size` indicators | Size Fit | 150 |
| `geography` terms | Geographic | 100 |
| `other_context` buying signals | Buying Signals | 100 |

**Build Negative Factors From**:

| User Input | Factor Name | Weight |
|------------|-------------|--------|
| `exclusions` industries | Wrong Industry | 200 |
| `exclusions` competitors | Competitors | 300 |
| `exclusions` company types | Disqualified Type | 150 |

---

### Category 4: Threshold Settings

| Scenario | Setting |
|----------|---------|
| First run / Exploratory | `percentage_threshold = 30%` |
| Known good keywords | `score_threshold = 70` |
| Fixed AI budget | `count_threshold = budget / cost_per_lead` |

---

## Data Schema for Training

```json
{
  "run_id": "uuid",
  "user_inputs": {
    "business_name": "string",
    "product_description": "string",
    "ideal_customer": "string",
    "company_size": "string",
    "geography": "string",
    "seniority_levels": "string",
    "departments": "string",
    "exclusions": "string",
    "good_leads": "string",
    "search_keywords": "string"
  },
  "agent_decisions": {
    "keyword_boxes": ["box1", "box2"],
    "positive_factors": [{"name": "x", "weight": 100, "keywords": "y"}],
    "negative_factors": [{"name": "x", "weight": 100, "keywords": "y"}],
    "threshold_type": "percentage",
    "threshold_value": 30,
    "model_choice": "model_2"
  },
  "outcomes": {
    "leads_discovered": 500,
    "leads_ai_analyzed": 125,
    "leads_marked_good": 45,
    "user_confirmed_good": 12,
    "precision": 0.706
  }
}
```

---

## Key Metrics

| Metric | Formula | Target |
|--------|---------|--------|
| Precision | confirmed_good / ai_marked_good | > 0.70 |
| Discovery Efficiency | ai_marked_good / leads_discovered | > 0.15 |
| Cost Efficiency | confirmed_good / total_ai_cost | Maximize |

---

## Files Reference

| File | Purpose |
|------|---------|
| `user_input_config.json` | Field definitions for Setup tab |
| `USER_INPUT_TEMPLATE.md` | Human-readable input form |
| `AGENT_PROCESSING_RULES.md` | How inputs map to config |
| `unified_config.json` | All runtime configuration |
| `variable_reference.csv` | Complete variable documentation |
