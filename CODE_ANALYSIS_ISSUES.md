# 🔍 Code Analysis: Flaws & Inefficiencies

**Deep analysis of `unified_leadgen.py` for bugs, unused code, and performance issues**

---

## 🚨 Critical Issues

### 1. **Unused Configuration Variables (Dead Code)**

Several configuration variables are defined but never actually used in the pipeline:

| Variable | Location | Issue |
|----------|----------|-------|
| `step5.seniority_*_titles` | Lines 631-637 | These contact scoring title keywords are defined in config BUT the actual `ContactExtractor.extract_contacts()` method sends all scoring to the AI in a single call and doesn't use these local title mappings |
| `step5.fit_*_titles` | Lines 634-637 | Same issue - defined but AI does all scoring |
| `step5.contact_scoring_prompt` | Line 613-627 | The prompt is embedded in `extract_contacts()` but the `score_contact()` method (lines 4744-4856) that uses a separate prompt is **never called** in the pipeline |
| `step4.custom_explanation` | Line 508 | Defined in config but never referenced in code |
| `step1.serper_max_terms` | Line 432 | Defined but never used - combo generation doesn't limit terms |
| `step2.follow_sitemaps` | Line 452 | Config exists but sitemap parsing is **not implemented** |
| `step2.respect_robots` | Line 451 | Config exists but robots.txt checking is **not implemented** |

**Impact:** User configures these settings thinking they affect behavior, but they don't.

---

### 2. **`score_contact()` Method Never Called**

```python
# Lines 4744-4856: This entire method exists but is NEVER called
def score_contact(self, contact: Dict[str, str]) -> Dict[str, int]:
    """Score a contact based on their title using AI."""
    # ... 100+ lines of code that make a separate AI call per contact
```

The `run_contact_extraction()` method at line 4858 uses `extract_contacts()` which has AI do extraction AND scoring in one call. The `score_contact()` method is completely orphaned.

**Fix:** Delete the unused `score_contact()` method (~100 lines) or integrate it if separate scoring is desired.

---

### 3. **Redundant Database Lookups with URL Variations**

Multiple methods repeat the same URL normalization pattern:

```python
# This pattern appears 5+ times (lines 837-854, 886-899, 943-958, 988-1003, etc.)
url_variations = [
    url,
    url.replace("https://", "").replace("http://", ""),
    f"https://{url}" if not url.startswith("http") else url,
    url.replace("https://", "http://")
]
for variant in url_variations:
    cursor.execute("SELECT url FROM leads_comprehensive WHERE url = ?", (variant,))
```

**Issues:**
- 4 separate database queries per URL lookup
- Same code copied 5 times (DRY violation)
- Should normalize URLs ONCE when storing, not on every lookup

**Fix:** Create a single `normalize_url_for_db()` function and normalize on INSERT, not SELECT.

---

## ⚠️ Performance Issues

### 4. **Synchronous `time.sleep()` in Async Context**

```python
# Line 3843-3844 in analyze_website() - SYNCHRONOUS method
delay = self.rate_limiter.get_delay()
if delay > 0:
    time.sleep(delay)  # BLOCKS the entire thread!
```

This is fine for the sync version, but the same pattern appears in async code that should use `await asyncio.sleep()`:

```python
# Line 4116-4118 in analyze_website_async()
delay = self.rate_limiter.get_delay()
if delay > 0:
    await asyncio.sleep(delay)  # ✓ Correct in async version
```

The async version is correct, but `analyze_website()` (sync) is still called in the legacy fallback section (lines 4366-4399) which blocks the event loop.

---

### 5. **Repeated DataFrame Reads in Loops**

```python
# Lines 2431-2437: Inside the main discovery loop
if os.path.exists(failed_path):
    existing_df = pd.read_csv(failed_path)  # Read entire CSV
    new_df = pd.DataFrame(failed_domains_list)
    combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    combined_df.to_csv(failed_path, index=False)  # Write entire CSV
```

This reads and writes the entire failed domains CSV on **every search iteration** (up to 500 times).

**Fix:** Accumulate failed domains in memory and write once at the end, or use append mode.

---

### 6. **Fuzzy Matching Called Even When Disabled**

```python
# Lines 2982-2985
# Only do fuzzy matching if threshold < 100
if threshold < 100:
    if fuzz.partial_ratio(kw_lower, text_lower) >= threshold:
        count += 1
```

This is good - it skips fuzzy when threshold=100. BUT the `fuzz.partial_ratio()` still gets called because the check is INSIDE the conditional. The issue is the entire text is still being lowercased and processed even when only exact matching is needed.

**Optimization:** Short-circuit earlier when `threshold == 100`:

```python
if threshold == 100:
    return count  # Skip fuzzy entirely
```

---

### 7. **Global Mousewheel Binding Memory Leak**

```python
# Line 6083-6084
def _on_mousewheel(event):
    canvas.yview_scroll(int(-1*(event.delta/120)), "units")
canvas.bind_all("<MouseWheel>", _on_mousewheel)  # GLOBAL binding!
```

`bind_all()` creates a **global** binding that persists. If multiple tabs/canvases do this, the old bindings aren't cleaned up, causing:
- Multiple scroll handlers firing
- Memory leaks from closure references

**Fix:** Use `canvas.bind("<MouseWheel>", ...)` (local) or properly unbind on tab switch.

---

### 8. **Regex Compilation Inside Loops**

```python
# Lines 2946-2952: Compiled patterns are cached, but...
for kw in all_keywords:
    kw_lower = kw.lower().strip()
    if kw_lower and kw_lower not in self._compiled_patterns:
        try:
            self._compiled_patterns[kw_lower] = re.compile(rf"\b{re.escape(kw_lower)}\b", re.IGNORECASE)
```

This is good (caches patterns). BUT in `fuzzy_count()`:

```python
# Line 2980
count += len(re.findall(rf"\b{re.escape(kw_lower)}\b", text_lower))
```

If the pattern isn't in the cache, it recompiles on every call. The cache check and fallback should always use compiled patterns.

---

## 🔧 Logic Bugs

### 9. **Step 3 Score Threshold Ignored in Step 4**

```python
# Lines 4265-4270 in run_ai_analysis()
# Step 3 has already filtered the results based on the user's configuration
# (score threshold, percentage, or count). Step 4 analyzes ALL results from Step 3.
# Note: step4.score_threshold in config is not used - filtering happens in Step 3 only.
high_score_df = scoring_df  # Takes ALL from Step 3
```

This is documented but confusing. The config has `step4.score_threshold` (implied by the prompt building) but it's never used. The comment says Step 3 filters, but users might configure Step 4 threshold expecting it to work.

**Fix:** Either remove the Step 4 threshold config entirely, or implement it.

---

### 10. **Inconsistent URL Normalization Between Steps**

- **Step 1** stores domains as `example.com` (no protocol)
- **Step 2** stores URLs as `https://example.com` (with protocol)
- **Comprehensive Logger** tries to match both formats with the URL variations hack

This causes mismatches and the need for repeated URL variation lookups.

**Fix:** Standardize URL format across all steps (recommend: always store as `https://domain.com/`).

---

### 11. **`run_state_tracker` vs `stats_tracker` Confusion**

Two separate tracking systems:
- `RunStateTracker` - For resume/pause functionality (JSON file)
- `RunStatsTracker` - For GUI display (in-memory)

They track similar data but don't sync:
```python
# stats_tracker updates
self.stats_tracker.websites_scraped = count

# run_state_tracker updates (different call)
self.run_state_tracker.state['websites_scraped'] = count  # NOT DONE!
```

The `run_state_tracker` doesn't get website counts updated, only stage/batch info.

---

### 12. **Legacy Fallback Code That Never Runs**

```python
# Lines 4366-4399: "Legacy compatibility" section
legacy_processed = False
for idx, (_, row) in enumerate(high_score_df.iterrows()):
    if legacy_processed:
        break
    # ... this code processes websites one-by-one
```

`legacy_processed` starts as `False` but is never set to `True`, so the loop runs but the `break` is never triggered. However, the early check `if any(r.get('url') == url for r in results)` should skip already-processed URLs.

The real issue: this loop will try to process ALL websites again (100+ unnecessary iterations) just to check if they're already processed.

**Fix:** Remove this legacy section entirely - batch processing handles everything.

---

## 📉 Memory & Resource Issues

### 13. **Entire Website Content Loaded for Contact Extraction**

```python
# Line 4925 in run_contact_extraction()
content = self.get_website_content(url)  # Full 120,000+ chars
```

Then the content is truncated:
```python
# Line 4589
if len(content) > max_chars:
    content = content[:max_chars] + "... [truncated]"
```

**Issue:** Full content is loaded from database, stored in memory, THEN truncated. With 100 websites at 120KB each = 12MB loaded just to use 15KB.

**Fix:** Use SQL `SUBSTR()` to limit at query time:
```sql
SELECT SUBSTR(aggregated_text, 1, 15000) FROM websites WHERE root_url = ?
```

---

### 14. **Training Data Collector Always Initialized**

```python
# Lines 2003-2010
_training_collector = None

def get_training_collector() -> TrainingDataCollector:
    global _training_collector
    if _training_collector is None:
        _training_collector = TrainingDataCollector()  # Creates DB, tables
    return _training_collector
```

The collector is called in `run_pipeline()` even if the user never uses training features. It creates:
- `training_data/` directory
- SQLite database with 8 tables
- File I/O overhead

**Fix:** Make training data collection opt-in via config.

---

### 15. **Unbounded `pending_urls` List in RunStateTracker**

```python
# Lines 242-247
def add_pending_urls(self, urls: List[str]):
    for url in urls:
        if url not in self.state['pending_urls'] and url not in self.state['processed_urls']:
            self.state['pending_urls'].append(url)
    self.save_state()  # Writes to JSON every time
```

For large runs (1000+ URLs), this list grows unbounded and is serialized to JSON on every add. The `url not in list` check is O(n), making the overall operation O(n²).

**Fix:** Use sets for O(1) lookup:
```python
self.state['pending_urls_set'] = set(self.state.get('pending_urls', []))
```

---

## 🧹 Code Quality Issues

### 16. **Duplicate Code: URL Variations Pattern**

The same 4-line URL variation pattern appears in:
- `log_lead_scoring()` (lines 843-854)
- `log_lead_ai_analysis()` (lines 886-899)  
- `log_lead_contact_extraction()` (lines 943-958)
- `log_lead_contact_scoring()` (lines 988-1003)

**Fix:** Extract to single method:
```python
def _find_url_in_db(self, conn, url: str) -> Optional[str]:
    """Find URL in database, trying common variations."""
    # ... single implementation
```

---

### 17. **Magic Numbers Throughout**

```python
# Line 2679
aggregate_chunks.append(text[:20_000])  # Magic number

# Line 3411
if len(text) >= 400:  # Magic number - min chars threshold

# Line 4089
if len(content) > max_chars:  # Uses config, but...
    content = content[:max_chars] + "... [truncated]"
```

Some numbers use config, others are hardcoded. Inconsistent.

---

### 18. **Exception Swallowing**

```python
# Lines 199-200
except:
    pass  # Don't fail run if state save fails

# Lines 5783-5785  
except:
    pass  # Silently ignores JSON parse errors
```

Bare `except:` catches everything including `KeyboardInterrupt` and `SystemExit`. Should use `except Exception:` at minimum, and ideally log the error.

---

## 💰 Cost Optimization Opportunities

### 19. **Good Leads Scraped Every Run**

```python
# Lines 3597-3613 in run_scrape_and_summarize()
scraped_content = await self.scrape_good_leads()  # Scrapes websites
summary = await self.summarize_good_leads(scraped_content)  # AI call
```

If good leads domains don't change between runs, this is wasted API cost.

**Current:** Summary is cached in `good_leads_summary_cache` but only for the current run.

**Fix:** Check if domains changed since last run; if not, reuse cached summary.

---

### 20. **Full Content Sent to AI When Summary Would Suffice**

For AI analysis, the full 12,000 chars of content is sent to the API. For many use cases, a pre-summarized 2,000-char version would work just as well at 1/6 the cost.

**Suggestion:** Add option for "summarize-then-analyze" mode for cost-conscious users.

---

## 📊 Summary of Findings

| Category | Count | Severity |
|----------|-------|----------|
| Unused Code/Dead Variables | 8 | Medium |
| Performance Issues | 8 | Medium-High |
| Logic Bugs | 4 | High |
| Memory Issues | 3 | Medium |
| Code Quality | 4 | Low |
| Cost Optimization | 2 | Low |

### Priority Fixes:

1. **HIGH:** Remove or implement `step5.seniority/fit_titles` - users configure but nothing happens
2. **HIGH:** Delete unused `score_contact()` method (100 lines of dead code)
3. **HIGH:** Fix URL normalization inconsistency between steps
4. **MEDIUM:** Consolidate URL variation lookups into single function
5. **MEDIUM:** Fix repeated CSV reads in discovery loop
6. **MEDIUM:** Remove legacy fallback code in AI analysis
7. **LOW:** Use sets instead of lists for URL tracking
8. **LOW:** Add config option to disable training data collection

---

*Analysis generated: January 1, 2026*
*Target: unified_leadgen.py (~9,145 lines)*
