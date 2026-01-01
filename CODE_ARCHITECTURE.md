# 🏗️ Sherpa Lead Generator - Code Architecture Overview

**For Technical Developers & Non-Technical Stakeholders**

---

## 📋 Executive Summary (Non-Technical)

The Sherpa Lead Generator is a desktop application that automatically finds potential business customers by:

1. **Searching the web** for companies matching your criteria
2. **Visiting their websites** and reading their content
3. **Scoring them** based on keywords you define
4. **Having AI analyze** each company to identify the best leads
5. **Finding contact information** for key decision-makers

The entire process runs through a single graphical interface where you configure settings, start runs, and download results as spreadsheets.

---

## 🔄 High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           USER INTERFACE (GUI)                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ Step 1   │ │ Step 2   │ │ Advanced │ │  Run     │ │ Training Data    │   │
│  │ Keywords │ │ AI Setup │ │ Settings │ │ Pipeline │ │ (Developer)      │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         5-STAGE PIPELINE                                     │
│                                                                              │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐   │
│  │ STEP 1  │───▶│ STEP 2  │───▶│ STEP 3  │───▶│ STEP 4  │───▶│ STEP 5  │   │
│  │Discovery│    │ Scrape  │    │ Score   │    │AI Analyze│   │ Contacts│   │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘    └─────────┘   │
│       │              │              │              │              │         │
│       ▼              ▼              ▼              ▼              ▼         │
│  leads_raw.csv  webcrawl.db   scoring.csv   ai_analysis.csv  contacts.csv  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         OUTPUT FILES                                         │
│  • Final CSV with all lead data, scores, AI analysis, and contacts          │
│  • Comprehensive logs database (all leads ever processed)                    │
│  • Run-specific logs and debug files                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🗂️ File Structure

```
website-lead-generator1/
│
├── unified_leadgen.py          # Main application (ALL code in one file ~9,000 lines)
├── unified_config.json         # Configuration file (auto-generated)
├── requirements.txt            # Python dependencies
│
├── data/                       # Working data files
│   ├── leads_raw_*.csv         # Step 1 output: discovered websites
│   ├── webcrawl.db             # Step 2 output: SQLite database with scraped content
│   ├── scoring_results_*.csv   # Step 3 output: scored leads
│   ├── ai_analysis_*.csv       # Step 4 output: AI-analyzed leads
│   └── contacts_results_*.csv  # Step 5 output: leads with contacts
│
├── runs/                       # Individual run folders
│   └── Run X - MM-DD-YYYY/     # Each run gets its own folder
│       ├── run_state.json      # Resumable state tracker
│       └── final_results.csv   # Final output for this run
│
├── comprehensive_logs/         # Permanent database of ALL leads ever processed
│   └── comprehensive_leads.db  # SQLite database tracking all leads across runs
│
├── training_data/              # Machine learning training data collection
│   ├── training_data.db        # Database of keyword effectiveness, user feedback
│   ├── business_docs/          # Uploaded business documents
│   └── exports/                # Exported training datasets
│
├── logs/                       # Application logs
│   ├── unified_leadgen.log     # Main application log
│   └── ai_debug_*.txt          # AI prompt/response debug logs
│
└── downloads/                  # Exported CSV files for user download
```

---

## 🧩 Core Classes & Their Responsibilities

### Configuration & Utilities

| Class | Purpose | Non-Technical Explanation |
|-------|---------|---------------------------|
| `UnifiedConfig` | Manages all settings | "The settings manager" - loads/saves your configuration |
| `RunStateTracker` | Tracks run progress | "Progress bookmark" - allows resuming interrupted runs |
| `ComprehensiveLogger` | Permanent lead database | "The master record keeper" - remembers every lead ever found |
| `TrainingDataCollector` | ML training data | "Learning collector" - tracks what works for future improvements |
| `AdaptiveRateLimiter` | API speed management | "Traffic controller" - speeds up when safe, slows down on errors |

### Pipeline Steps

| Class | Step | What It Does |
|-------|------|--------------|
| `WebsiteDiscovery` | Step 1 | Uses Google search APIs to find relevant websites |
| `WebsiteScraper` | Step 2 | Visits websites and extracts their text content |
| `FactorScorer` | Step 3 | Scores websites based on keyword matches |
| `GoodLeadsScraper` | Step 4 prep | Scrapes "example good leads" for AI reference |
| `AIAnalyzer` | Step 4 | Sends website content to AI for intelligent analysis |
| `ContactExtractor` | Step 5 | Uses AI to find and score contact information |

### User Interface

| Class | Purpose |
|-------|---------|
| `InitialPopupGUI` | First popup: New Run / Continue / Download |
| `UnifiedGUI` | Main application window with all configuration tabs |
| `TrainingDataGUI` | Developer tools for viewing/exporting training data |

---

## 🔧 Step-by-Step Technical Breakdown

### Step 1: Website Discovery (`WebsiteDiscovery`)

**What it does:** Searches for websites matching your keyword criteria.

**Technical flow:**
```
1. Load keyword boxes from config (8 configurable boxes)
2. Generate keyword combinations (randomly picks one from each box)
3. For each combination:
   a. Build search query (e.g., "medical device oncology preclinical")
   b. Call Serper.dev or SerpAPI Google search
   c. Extract URLs from search results
   d. Optionally verify domains are reachable (HEAD request)
   e. Extract root domain (e.g., "example.com")
   f. Add to leads list if not already found
4. Save leads_raw_[timestamp].csv
```

**Key configuration:**
- `step1.keyword_boxes[]` - Search terms grouped by category
- `step1.api_key` - Serper.dev or SerpAPI key
- `step1.max_results` - Results per search (default: 100)
- `step1.serper_combo_cap` - Max number of searches (default: 500)

**Rate limiting:** Uses `AdaptiveRateLimiter` to automatically adjust request speed based on API responses.

---

### Step 2: Website Scraping (`WebsiteScraper`)

**What it does:** Visits each website and extracts readable text content.

**Technical flow:**
```
1. Load unscanned websites from leads CSV
2. For each website:
   a. Start at homepage
   b. Use priority queue (heap) to crawl pages in importance order
   c. Priority scoring:
      - HIGHEST: Contact/team pages (+10 points)
      - HIGH: Oncology, product, pipeline pages (+2 points)
      - LOW: Blog, news, careers pages (-3 points)
   d. Extract text using trafilatura library (or BeautifulSoup fallback)
   e. Follow links to find more pages (up to max_depth)
   f. Aggregate text from all pages (up to aggregate_char_cap)
3. Store in SQLite database (webcrawl.db)
```

**Key configuration:**
- `step2.max_pages_per_site` - Pages to crawl per site (default: 12)
- `step2.max_depth` - Link depth from homepage (default: 2)
- `step2.aggregate_char_cap` - Max text per site (default: 120,000 chars)
- `step2.contact_priority_keywords` - Keywords for page prioritization

**Database schema:**
```sql
websites(root_url, aggregated_text, num_pages, last_updated, status)
pages(root_url, page_url, status_code, text, crawled_at)
```

---

### Step 3: Factor-Based Scoring (`FactorScorer`)

**What it does:** Scores websites based on keyword matches with configurable weights.

**Technical flow:**
```
1. Load positive factors (keywords that ADD points)
2. Load negative factors (keywords that SUBTRACT points)
3. For each website's aggregated text:
   a. Count keyword matches (with optional fuzzy matching)
   b. Apply formula: (match_count / sensitivity) * weight
   c. Sum positive factor scores
   d. Subtract negative factor scores
   e. Normalize to 0-100 scale
4. Apply threshold filters (score/percentage/count)
5. Save filtered results to scoring_results_[timestamp].csv
```

**Scoring formula:**
```python
for factor in FACTORS:
    match_count = count_matches(text, factor.keywords)
    ratio = min(match_count / factor.sensitivity, 1.0)
    score += ratio * factor.weight

normalized = (score - min_possible) / (max_possible - min_possible) * 100
```

**Key configuration:**
- `step3.positive_factors[]` - List of {name, weight, sensitivity, keywords}
- `step3.negative_factors[]` - List of disqualifiers
- `step3.use_score_threshold` / `threshold_value` - Min score to pass (default: 75)
- `step3.fuzzy_match_threshold` - 85 = allow typos, 100 = exact only

---

### Step 4: AI Analysis (`AIAnalyzer`)

**What it does:** Sends website content to AI (Claude/OpenAI/Gemini) for intelligent qualification.

**Technical flow:**
```
1. Load scored websites above threshold
2. (Optional) Scrape "good leads" reference sites and summarize with AI
3. For each website:
   a. Get content from database
   b. Build dynamic prompt from scoring_fields config
   c. Send to AI API (async batch processing for speed)
   d. Parse JSON response
   e. Extract scores for each configured field
   f. Calculate is_good_lead based on overall_score >= 60
4. Save ai_analysis_results_[timestamp].csv
```

**Dynamic prompt building:**
The prompt is automatically generated from `step4.scoring_fields[]`:
- **Score fields**: Ask AI for numeric rating (e.g., 0-10 for "Funding Level")
- **Text fields**: Ask AI to select from options (e.g., "Business Type")

**Example scoring field config:**
```json
{
  "type": "score",
  "title": "Preclinical Fit",
  "min": 0,
  "max": 10,
  "prompt": "Score how well this company fits as a prospect...",
  "enabled": true
}
```

**Good Leads Reference:**
If `step4.good_leads_domains` is configured, the system:
1. Scrapes those websites
2. Summarizes them with AI in one call
3. Includes summary in all scoring prompts as examples

**Key configuration:**
- `step4.api_provider` - claude, openai, or gemini
- `step4.api_key` - API key for selected provider
- `step4.model_choice` - model_1 (cheapest) through model_4 (smartest)
- `step4.credit_limit` - Max $ to spend per run
- `step4.scoring_fields[]` - Dynamic scoring criteria

---

### Step 5: Contact Extraction (`ContactExtractor`)

**What it does:** Uses AI to find and score contact information from website content.

**Technical flow:**
```
1. Load "good leads" from AI analysis results (is_good_lead = true)
2. For each lead:
   a. Get website content from database
   b. Send to AI with contact extraction prompt
   c. AI returns:
      - company_email (general contact email)
      - contacts[] with name, position, email, phone
      - seniority_score and fit_score for each contact
   d. Sort contacts by total_score (seniority + fit)
   e. Keep top N contacts (default: 5)
3. Save contacts_results_[timestamp].csv
```

**Contact scoring (done by AI in same call):**
- **Seniority (1-4)**: CEO=4, VP=3, Director=2, Manager=1
- **Fit (1-4)**: Preclinical/Translational=4, Research=3, Oncology=2, Business=1
- **Total Score**: Seniority + Fit (max 8)

**Key configuration:**
- `step5.enabled` - Turn contact extraction on/off
- `step5.max_contacts` - Contacts per company (default: 5)
- `step5.seniority_4_titles` - Titles for highest seniority score
- `step5.fit_4_titles` - Titles for highest fit score

---

## 🎨 User Interface Architecture

### Main Window Tabs

| Tab | Purpose | Key Functions |
|-----|---------|---------------|
| **Step 1** | Keyword configuration | 8 keyword boxes, each generates search terms |
| **Step 2** | AI settings | Provider, API key, model selection, scoring fields |
| **Run Pipeline** | Execute & monitor | Start/pause runs, progress timeline, statistics |
| **Advanced** | All settings | Discovery, scraping, scoring, contact config |

### Progress Timeline

The GUI shows a proportional timeline where each step's width reflects its expected duration:
- Step 1: 15% (Search is fast)
- Step 2: 25% (Scraping takes time)
- Step 3: 10% (Scoring is fast)
- Step 4: 40% (AI analysis is slowest)
- Step 5: 10% (Contact extraction is quick)

These percentages are learned from historical runs via `HistoricalTimingLearner`.

---

## 📊 Data Persistence

### Configuration (`unified_config.json`)
- All settings stored as JSON
- Auto-saved when user changes settings
- Optional GitHub sync for version control

### Comprehensive Database (`comprehensive_logs/comprehensive_leads.db`)
Tracks ALL leads ever processed across all runs:
```sql
leads_comprehensive(
    url PRIMARY KEY,
    first_discovered, last_analyzed,
    stage,              -- 'discovered', 'scraped', 'scored', 'ai_analyzed', 'contact_scored'
    score,
    ai_analysis_result, -- JSON blob
    company_email, contacts_json, contact_count
)
```

### Run State (`runs/Run X/run_state.json`)
Enables resumable runs:
```json
{
  "current_stage": 3,
  "completed_stages": [1, 2],
  "processed_urls": ["example.com", ...],
  "pending_urls": ["pending.com", ...],
  "is_complete": false,
  "is_paused": true
}
```

---

## 🔌 External API Integrations

### Search APIs (Step 1)
| Provider | Endpoint | Purpose |
|----------|----------|---------|
| Serper.dev | `POST google.serper.dev/search` | Google search results |
| SerpAPI | `GET serpapi.com/search` | Alternative Google search |

### AI APIs (Steps 4 & 5)
| Provider | Endpoint | Models |
|----------|----------|--------|
| Anthropic (Claude) | `POST api.anthropic.com/v1/messages` | Haiku, Sonnet, Opus |
| OpenAI | `POST api.openai.com/v1/chat/completions` | GPT-4o, GPT-4o-mini |
| Google Gemini | `POST generativelanguage.googleapis.com/v1beta/...` | Flash, Pro |

---

## ⚡ Performance Optimizations

### Adaptive Rate Limiting
```python
class AdaptiveRateLimiter:
    # Starts at initial_delay (0.35s)
    # After N consecutive successes: delay *= 0.8 (faster)
    # After errors: delay *= 1.5 (slower)
    # Bounded by min_delay (0.05s) and max_delay (5s)
```

### Async Batch Processing (Step 4)
- Multiple websites analyzed in parallel
- Default batch size: 5 concurrent AI requests
- Configurable via `performance.ai_batch_size`

### Debug File Throttling
- Only writes 1 debug file per N AI calls (default: 10)
- Configurable via `performance.debug_file_interval`

### Fuzzy Matching Toggle
- Set `performance.fuzzy_match_threshold = 100` for exact matching only
- Faster than fuzzy matching (no rapidfuzz calls)

---

## 🧪 Training Data System

For future ML model training, the system collects:

### Data Collected
- **Run configs**: Snapshot of settings for each run
- **Search term stats**: Which keyword combos found the best leads
- **Lead outcomes**: Python score, AI score, user feedback for each lead
- **Keyword performance**: Effectiveness rate per keyword

### User Feedback Import
Users can import CSV with columns:
- `url` - Website URL
- `is_good_lead` - true/false feedback

The system correlates feedback with keywords to learn what works.

### Export for Training
```
training_data/exports/
├── leads_training_[timestamp].csv
├── keyword_performance_[timestamp].csv
├── search_stats_[timestamp].csv
└── training_summary_[timestamp].json
```

---

## 🛠️ Key Technical Patterns

### 1. Callback-Based Progress Updates
```python
def run_discovery(self):
    if self.progress_callback:
        self.progress_callback(f"[{i}/{total}] Searching: {keywords}")
```

### 2. Async/Await for I/O Operations
```python
async def analyze_batch_async(self, urls):
    async with aiohttp.ClientSession() as session:
        tasks = [self.analyze_website_async(session, url) for url in urls]
        results = await asyncio.gather(*tasks)
```

### 3. Priority Queue for Smart Crawling
```python
import heapq
heapq.heappush(queue, (-score, depth, url))  # Negative for max-heap behavior
```

### 4. CSV Sanitization
```python
def sanitize_for_csv(text):
    return text.replace(",", ";").replace("\n", " ")
```

---

## 🔧 Configuration Reference

For a complete list of all 100+ configuration variables, see:
- `variable_reference.csv` - Table of all settings with descriptions
- GUI tooltips - Hover over any field for explanation

---

## 📁 Dependencies

```
pandas>=1.5.0       # Data manipulation
requests>=2.28.0    # HTTP requests
aiohttp>=3.8.0      # Async HTTP
beautifulsoup4      # HTML parsing
trafilatura         # Clean text extraction
tldextract          # Domain extraction
rapidfuzz           # Fuzzy string matching
tqdm                # Progress bars (CLI)
```

---

## 🚀 Running the Application

### Standard Launch
```bash
python unified_leadgen.py
```

### Or use the batch file (Windows)
```
run_gui.bat
```

### What Happens on Launch
1. `main()` is called
2. `InitialPopupGUI` shows New Run / Continue / Download popup
3. User selects action
4. `UnifiedGUI` main window opens with selected context

---

## 📝 Summary

The Sherpa Lead Generator is a monolithic Python application (~9,000 lines) that:

1. **Discovers leads** via Google search APIs
2. **Scrapes website content** with intelligent page prioritization
3. **Scores leads** using configurable keyword factors
4. **Analyzes with AI** using dynamic, customizable prompts
5. **Extracts contacts** with seniority/fit scoring

All configuration is GUI-based, and the system maintains comprehensive logs across runs for both immediate use and future ML training.

---

*Document generated: January 1, 2026*
*Codebase version: unified_leadgen.py (single-file architecture)*
