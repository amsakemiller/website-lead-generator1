#!/usr/bin/env python3
"""
Unified Lead Generation Application
==================================

A comprehensive lead generation tool that combines all steps into a single application:
1. Website Discovery (Step 1)
2. Website Scraping (Step 2) 
3. Factor-based Scoring (Step 3)
4. AI Analysis (Step 4)

All steps run sequentially with a unified GUI for configuration.
"""

import os
import sys
import json
import asyncio
import logging
import sqlite3
import pandas as pd
import requests
import aiohttp
from aiohttp import ClientSession, ClientTimeout
import tldextract
from itertools import combinations
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin, urldefrag, parse_qs, urlunparse
from typing import List, Dict, Any, Optional, Set, Tuple
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import time
import random
import re
import csv
import hashlib
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

# Try to import optional dependencies
try:
    import trafilatura
except ImportError:
    trafilatura = None

try:
    import docx
except ImportError:
    docx = None

try:
    import PyPDF2
except ImportError:
    try:
        import pypdf as PyPDF2
    except ImportError:
        PyPDF2 = None

# ============================================================
# CONFIGURATION MANAGEMENT
# ============================================================

class UnifiedConfig:
    """Unified configuration management for all steps."""
    
    def __init__(self, config_file: str = "unified_config.json"):
        self.config_file = config_file
        self.default_config = {
            # Step 1: Website Discovery
            "step1": {
                "api_choice": "serper",
                "api_key": "",
                "region": "us",
                "max_results": 100,
                "output_path": "data/leads_raw.csv",
                "request_timeout_seconds": 15,
                "concurrency": 25,
                "keyword_boxes": [
                    "medical device",
                    "oncology, tumor, cancer",
                    "therapeutic, preclinical",
                    "ablation, interventional",
                    "drug delivery, implantable",
                    "solid tumor, localized",
                    "nanoparticle, photothermal, radiofrequency",
                    "bile duct, bladder, brain, glioma, colorectal, kidney, liver, lung, pancreas, soft tissue"
                ],
                "serper_set_keywords": "medical device",
                "serper_variable_keywords": "oncology, tumor, device, therapeutic, preclinical, ablation, interventional, drug delivery, implantable, solid tumor, localized, cancer, therapy, nanoparticle, photothermal, radiofrequency, bile duct, bladder, brain, glioma, colorectal, kidney, liver, lung, pancreas, soft tissue chemoembolization, ultrasound, translational, oncology biotech",
                "serper_combo_cap": 500,
                "serper_max_terms": 8,
                "serper_current_seed": None,
                "serper_last_seed": None
            },
            
            # Step 2: Website Scraping
            "step2": {
                "user_agent": "LeadGenBot/1.0 (+https://susclinicals.com/) Unified",
                "timeout_sec": 20,
                "read_limit_bytes": 2000000,
                "max_pages_per_site": 12,
                "max_depth": 2,
                "global_concurrency": 60,
                "per_domain_concurrency": 6,
                "robots_cache_ttl_sec": 3600,
                "min_chars_per_page": 400,
                "aggregate_char_cap": 120000,
                "respect_robots": True,
                "follow_sitemaps": True,
                "db_path": "data/webcrawl.db"
            },
            
            # Step 3: Factor-based Scoring
            "step3": {
                "score_threshold": 75,
                "output_path": "data/analysis_results.csv"
            },
            
            # Step 4: AI Analysis
            "step4": {
                "model_choice": "best",
                "api_provider": "claude",
                "api_key": "",
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 4000,
                "credit_limit": 50.0,
                "max_retries": 3,
                "log_level": "INFO",
                "batch_size": 5,
                "checkpoint_interval": 5,
                "results_file": "data/ai_analysis_results.csv",
                "custom_explanation": "",
                "examples_folder": ""
            }
        }
        self.config = self.load_config()
    
    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file or create default."""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                # Merge with defaults for any missing keys
                for step, step_config in self.default_config.items():
                    if step not in config:
                        config[step] = step_config.copy()
                    else:
                        for key, value in step_config.items():
                            if key not in config[step]:
                                config[step][key] = value
                return config
            else:
                # Create default config file
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(self.default_config, f, indent=2)
                return self.default_config.copy()
        except Exception as e:
            print(f"Error loading config: {e}")
            return self.default_config.copy()
    
    def save_config(self):
        """Save current configuration to file."""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")

# ============================================================
# LOGGING SETUP
# ============================================================

def setup_logging():
    """Setup unified logging."""
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler("logs/unified_leadgen.log", encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger("unified_leadgen")

# ============================================================
# COMPREHENSIVE LOGGING SYSTEM
# ============================================================

class ComprehensiveLogger:
    """Manages comprehensive logging for all runs."""
    
    def __init__(self):
        self.comprehensive_dir = "comprehensive_logs"
        self.runs_dir = "run_logs"
        os.makedirs(self.comprehensive_dir, exist_ok=True)
        os.makedirs(self.runs_dir, exist_ok=True)
        
        # Comprehensive database for all leads ever processed
        self.comprehensive_db = os.path.join(self.comprehensive_dir, "comprehensive_leads.db")
        self.init_comprehensive_db()
    
    def init_comprehensive_db(self):
        """Initialize comprehensive database."""
        conn = sqlite3.connect(self.comprehensive_db)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leads_comprehensive(
                url TEXT PRIMARY KEY,
                first_discovered TEXT,
                last_analyzed TEXT,
                discovery_run_id TEXT,
                last_analysis_run_id TEXT,
                stage TEXT,
                score REAL,
                ai_analysis_result TEXT,
                content_hash TEXT,
                status TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS run_logs(
                run_id TEXT PRIMARY KEY,
                start_time TEXT,
                end_time TEXT,
                status TEXT,
                step1_completed INTEGER,
                step2_completed INTEGER,
                step3_completed INTEGER,
                step4_completed INTEGER,
                total_leads INTEGER,
                analyzed_leads INTEGER
            )
        """)
        conn.commit()
        conn.close()
    
    def get_run_id(self):
        """Generate unique run ID."""
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    
    def log_lead_discovery(self, url: str, run_id: str):
        """Log a lead discovery."""
        conn = sqlite3.connect(self.comprehensive_db)
        now = datetime.now(timezone.utc).isoformat()
        
        # Check if lead already exists
        cursor = conn.cursor()
        cursor.execute("SELECT url FROM leads_comprehensive WHERE url = ?", (url,))
        exists = cursor.fetchone()
        
        if exists:
            # Update last analyzed time
            conn.execute("""
                UPDATE leads_comprehensive 
                SET last_analyzed = ?, last_analysis_run_id = ?
                WHERE url = ?
            """, (now, run_id, url))
        else:
            # Insert new lead
            conn.execute("""
                INSERT INTO leads_comprehensive 
                (url, first_discovered, last_analyzed, discovery_run_id, last_analysis_run_id, stage, status)
                VALUES (?, ?, ?, ?, ?, 'discovered', 'pending')
            """, (url, now, now, run_id, run_id))
        
        conn.commit()
        conn.close()
    
    def log_lead_scraping(self, url: str, run_id: str, success: bool):
        """Log scraping result."""
        conn = sqlite3.connect(self.comprehensive_db)
        now = datetime.now(timezone.utc).isoformat()
        
        conn.execute("""
            UPDATE leads_comprehensive 
            SET stage = ?, status = ?, last_analyzed = ?, last_analysis_run_id = ?
            WHERE url = ?
        """, ('scraped', 'success' if success else 'failed', now, run_id, url))
        
        conn.commit()
        conn.close()
    
    def log_lead_scoring(self, url: str, run_id: str, score: float):
        """Log scoring result."""
        conn = sqlite3.connect(self.comprehensive_db)
        now = datetime.now(timezone.utc).isoformat()
        
        # Try to find the lead - check with and without https:// prefix
        cursor = conn.cursor()
        
        # Try exact match first
        cursor.execute("SELECT url FROM leads_comprehensive WHERE url = ?", (url,))
        exists = cursor.fetchone()
        
        # If not found, try with/without https:// prefix variations
        if not exists:
            url_variations = [
                url,
                url.replace("https://", "").replace("http://", ""),
                f"https://{url}" if not url.startswith("http") else url,
                url.replace("https://", "http://")
            ]
            for variant in url_variations:
                cursor.execute("SELECT url FROM leads_comprehensive WHERE url = ?", (variant,))
                exists = cursor.fetchone()
                if exists:
                    url = variant  # Use the variant that exists in DB
                    break
        
        if exists:
            # Update existing lead
            conn.execute("""
                UPDATE leads_comprehensive 
                SET stage = ?, score = ?, last_analyzed = ?, last_analysis_run_id = ?
                WHERE url = ?
            """, ('scored', score, now, run_id, url))
        else:
            # Insert new lead if it doesn't exist (shouldn't happen normally, but just in case)
            conn.execute("""
                INSERT INTO leads_comprehensive 
                (url, first_discovered, last_analyzed, discovery_run_id, last_analysis_run_id, stage, score, status)
                VALUES (?, ?, ?, ?, ?, 'scored', ?, 'pending')
            """, (url, now, now, run_id, run_id, score))
        
        conn.commit()
        conn.close()
    
    def log_lead_ai_analysis(self, url: str, run_id: str, analysis_result: dict):
        """Log AI analysis result."""
        conn = sqlite3.connect(self.comprehensive_db)
        now = datetime.now(timezone.utc).isoformat()
        
        # Try to find the lead - check with and without https:// prefix (like log_lead_scoring does)
        cursor = conn.cursor()
        
        # Try exact match first
        cursor.execute("SELECT url FROM leads_comprehensive WHERE url = ?", (url,))
        exists = cursor.fetchone()
        
        # If not found, try with/without https:// prefix variations
        if not exists:
            url_variations = [
                url,
                url.replace("https://", "").replace("http://", ""),
                f"https://{url}" if not url.startswith("http") else url,
                url.replace("https://", "http://")
            ]
            for variant in url_variations:
                cursor.execute("SELECT url FROM leads_comprehensive WHERE url = ?", (variant,))
                exists = cursor.fetchone()
                if exists:
                    url = variant  # Use the variant that exists in DB
                    break
        
        if exists:
            # Update existing lead
            conn.execute("""
                UPDATE leads_comprehensive 
                SET stage = ?, ai_analysis_result = ?, last_analyzed = ?, last_analysis_run_id = ?
                WHERE url = ?
            """, ('ai_analyzed', json.dumps(analysis_result), now, run_id, url))
        else:
            # Insert new lead if it doesn't exist (shouldn't happen normally, but just in case)
            conn.execute("""
                INSERT INTO leads_comprehensive 
                (url, first_discovered, last_analyzed, discovery_run_id, last_analysis_run_id, stage, ai_analysis_result, status)
                VALUES (?, ?, ?, ?, ?, 'ai_analyzed', ?, 'pending')
            """, (url, now, now, run_id, run_id, json.dumps(analysis_result)))
        
        conn.commit()
        conn.close()
    
    def save_run_log(self, run_id: str, start_time: str, end_time: str = None, 
                    status: str = "running", step1: bool = False, step2: bool = False, 
                    step3: bool = False, step4: bool = False, total_leads: int = 0, 
                    analyzed_leads: int = 0):
        """Save run log."""
        conn = sqlite3.connect(self.comprehensive_db)
        
        conn.execute("""
            INSERT OR REPLACE INTO run_logs 
            (run_id, start_time, end_time, status, step1_completed, step2_completed, 
             step3_completed, step4_completed, total_leads, analyzed_leads)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_id, start_time, end_time, status, int(step1), int(step2), 
              int(step3), int(step4), total_leads, analyzed_leads))
        
        conn.commit()
        conn.close()
    
    def get_leads_for_reanalysis(self, days_threshold: int = 0):
        """Get leads that need re-analysis based on days threshold."""
        conn = sqlite3.connect(self.comprehensive_db)
        
        if days_threshold == 0:
            # Return all leads
            query = "SELECT url FROM leads_comprehensive"
            cursor = conn.execute(query)
        else:
            # Return leads older than threshold
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_threshold)
            query = "SELECT url FROM leads_comprehensive WHERE last_analyzed < ?"
            cursor = conn.execute(query, (cutoff_date.isoformat(),))
        
        leads = [row[0] for row in cursor.fetchall()]
        conn.close()
        return leads
    
    def get_comprehensive_data(self):
        """Get all comprehensive data for download."""
        conn = sqlite3.connect(self.comprehensive_db)
        
        query = """
            SELECT url, first_discovered, last_analyzed, stage, score, 
                   ai_analysis_result, status
            FROM leads_comprehensive 
            ORDER BY 
                CASE stage 
                    WHEN 'ai_analyzed' THEN 1 
                    WHEN 'scored' THEN 2 
                    WHEN 'scraped' THEN 3 
                    WHEN 'discovered' THEN 4 
                    ELSE 5 
                END,
                score DESC NULLS LAST
        """
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df
    
    def get_all_leads_sorted(self, python_threshold: float = 75.0):
        """Get all leads sorted by stage and score for display."""
        conn = sqlite3.connect(self.comprehensive_db)
        
        query = """
            SELECT url, stage, score, ai_analysis_result
            FROM leads_comprehensive
            ORDER BY url
        """
        
        cursor = conn.execute(query)
        rows = cursor.fetchall()
        conn.close()
        
        # Parse and categorize leads
        ai_leads = []  # AI analyzed leads with match_score
        scored_leads = []  # Python scored leads
        unscraped_leads = []  # Discovered but not scraped
        
        for row in rows:
            url, stage, score, ai_result_json = row
            
            if stage == 'ai_analyzed' and ai_result_json:
                try:
                    ai_data = json.loads(ai_result_json)
                    match_score = ai_data.get('match_score', 0)
                    ai_leads.append({
                        'url': url,
                        'stage': stage,
                        'score': match_score,
                        'ai_data': ai_data
                    })
                except:
                    pass
            elif stage == 'scored' and score is not None:
                scored_leads.append({
                    'url': url,
                    'stage': stage,
                    'score': score
                })
            elif stage == 'scraped':
                # Scraped but not scored yet
                scored_leads.append({
                    'url': url,
                    'stage': stage,
                    'score': None
                })
            elif stage == 'discovered':
                unscraped_leads.append({
                    'url': url,
                    'stage': stage,
                    'score': None
                })
        
        # Sort AI leads: highest first
        ai_leads_high = sorted([x for x in ai_leads], key=lambda x: x['score'], reverse=True)
        # Lowest AI scores
        ai_leads_low = sorted([x for x in ai_leads], key=lambda x: x['score'])
        
        # Separate scored leads from scraped-but-not-scored leads
        actually_scored = [x for x in scored_leads if x['score'] is not None]
        just_scraped = [x for x in scored_leads if x['score'] is None]
        
        # Sort scored leads: closest to threshold first
        scored_leads_close = sorted(actually_scored, key=lambda x: abs(x['score'] - python_threshold))
        # Lowest Python scores
        scored_leads_low = sorted(actually_scored, key=lambda x: x['score'])
        
        # Combine in order: highest AI, lowest AI, closest to threshold (scored), lowest scored, unscraped
        result = []
        result.extend(ai_leads_high)  # Highest AI scores
        result.extend(ai_leads_low)    # Lowest AI scores
        result.extend(scored_leads_close)  # Closest to threshold
        result.extend(scored_leads_low)    # Lowest Python scores
        result.extend(just_scraped)        # Scraped but not scored
        result.extend(unscraped_leads)     # Discovered but not scraped
        
        # Remove duplicates while preserving order
        seen = set()
        final_result = []
        for item in result:
            if item['url'] not in seen:
                seen.add(item['url'])
                final_result.append(item)
        
        return final_result

# ============================================================
# STEP 1: WEBSITE DISCOVERY
# ============================================================

class WebsiteDiscovery:
    """Step 1: Website discovery using search APIs."""
    
    def __init__(self, config: UnifiedConfig, progress_callback=None):
        self.config = config
        self.logger = setup_logging()
        self.comprehensive_logger = ComprehensiveLogger()
        self.progress_callback = progress_callback  # Callback for GUI updates
        self.last_api_error = None  # Track last API error status
    
    def _split_keywords_preserve_quotes(self, raw: str) -> List[str]:
        return [p.strip() for p in raw.split(",") if p.strip()]
    
    def generate_serper_combinations(self, keyword_boxes: List[str], cap: int = 500) -> List[List[str]]:
        """Generate combinations by taking one keyword from each non-empty box."""
        combos = []
        
        # Parse each box into a list of keywords
        box_keywords = []
        for box in keyword_boxes:
            if box.strip():
                keywords = [k.strip() for k in box.split(',') if k.strip()]
                box_keywords.append(keywords)
            else:
                box_keywords.append([])
        
        # Generate all combinations
        def generate_combos(boxes, current_combo, index):
            if index >= len(boxes):
                if current_combo:  # Only add non-empty combinations
                    combos.append(current_combo.copy())
                return
            
            if boxes[index]:  # If this box has keywords
                for keyword in boxes[index]:
                    current_combo.append(keyword)
                    generate_combos(boxes, current_combo, index + 1)
                    current_combo.pop()
            else:  # If this box is empty, skip it
                generate_combos(boxes, current_combo, index + 1)
        
        generate_combos(box_keywords, [], 0)
        
        # Shuffle and limit results
        random.shuffle(combos)
        return combos[:cap]
    
    def build_query_from_terms_as_and(self, terms: List[str]) -> str:
        return " ".join([t.strip() for t in terms if t.strip()])
    
    def format_search_key(self, terms: List[str]) -> str:
        return ", ".join([t.strip() for t in terms if t.strip()])
    
    def serper_search(self, api_key: str, query: str, max_results: int, gl: Optional[str], log_file) -> List[Dict[str, Any]]:
        url = "https://google.serper.dev/search"
        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        items = []
        per_page = 100
        pages = (max_results + per_page - 1) // per_page
        self.last_api_error = None  # Reset error flag
        for page in range(1, pages + 1):
            take = min(per_page, max_results - len(items))
            payload = {"q": query, "num": take, "gl": gl or "us", "page": page}
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=30)
                if r.status_code != 200:
                    msg = f"Serper.dev HTTP {r.status_code}: {r.text[:200]}"
                    self.logger.error(msg)
                    log_file.write(msg + "\n")
                    if r.status_code == 403 or r.status_code == 401:
                        self.last_api_error = f"HTTP {r.status_code}: Unauthorized"
                        if self.progress_callback:
                            self.progress_callback(f"  ✗ API Error: {self.last_api_error}")
                    break
                data = r.json()
                page_items = [{"title": i.get("title", ""), "snippet": i.get("snippet", ""), "link": i.get("link", "")}
                              for i in data.get("organic", [])]
                if not page_items:
                    break
                items.extend(page_items)
                self.logger.info(f"Serper.dev fetched {len(page_items)} (total {len(items)}/{max_results})")
                log_file.write(f"Fetched page {page}: {len(page_items)} results (total {len(items)})\n")
                if len(items) >= max_results:
                    break
                time.sleep(0.35)
            except Exception as e:
                msg = f"Serper.dev request failed (page {page}): {e}"
                self.logger.error(msg)
                log_file.write(msg + "\n")
                self.last_api_error = str(e)
                break
        return items[:max_results]
    
    def extract_root_domain(self, url: str) -> str:
        try:
            ext = tldextract.extract(url)
            return ext.registered_domain or ""
        except Exception:
            return ""
    
    async def verify_domains(self, urls: List[str], timeout_s: float, concurrency: int) -> Dict[str, bool]:
        timeout = ClientTimeout(total=timeout_s)
        connector = aiohttp.TCPConnector(ssl=False, limit=concurrency)
        sem = asyncio.Semaphore(concurrency)
        out: Dict[str, bool] = {}
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async def run(url: str):
                async with sem:
                    try:
                        async with session.head(url, allow_redirects=True) as resp:
                            out[url] = 200 <= resp.status < 300
                    except Exception:
                        out[url] = False
            await asyncio.gather(*(run(u) for u in urls))
        return out
    
    def load_leads_state(self, path: str) -> Dict[str, bool]:
        state: Dict[str, bool] = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    site = (row.get("Website") or "").strip()
                    scanned = (row.get("Scanned") or "").strip().lower() == "true"
                    if site: state[site] = scanned
            self.logger.info(f"Loaded {len(state)} existing websites from {path}")
        return state
    
    def save_leads_state(self, path: str, state: Dict[str, bool]) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["Website", "Scanned"])
            w.writeheader()
            for site, scanned in sorted(state.items()):
                w.writerow({"Website": site, "Scanned": "True" if scanned else "False"})
    
    async def run_discovery(self):
        """Run website discovery step."""
        self.logger.info("Starting Step 1: Website Discovery")
        if self.progress_callback:
            self.progress_callback("Starting Step 1: Website Discovery")
        
        cfg = self.config.config["step1"]
        run_start = datetime.now()
        run_id = self.comprehensive_logger.get_run_id()
        run_log = os.path.join("logs", f"discovery_{run_start.strftime('%Y%m%d_%H%M%S')}.txt")
        
        # Log run start
        self.comprehensive_logger.save_run_log(
            run_id, run_start.isoformat(), status="running", step1=True
        )
        
        try:
            with open(run_log, "w", encoding="utf-8") as log_file:
                api_choice = (cfg.get("api_choice") or "serper").lower().strip()
                api_label = "serper.dev" if api_choice.startswith("serper") else "serpapi"
                api_key = cfg.get("api_key")
                region = cfg.get("region") or "us"
                timeout_s = float(cfg.get("request_timeout_seconds", 15))
                concurrency = int(cfg.get("concurrency", 25))
                max_results = int(cfg.get("max_results", 100))
                
                # Validate API key
                if not api_key or not api_key.strip():
                    error_msg = "ERROR: API key is missing! Please configure your API key in Step 1 settings."
                    self.logger.error(error_msg)
                    if self.progress_callback:
                        self.progress_callback(error_msg)
                    return False
                
                seed = cfg.get("serper_current_seed") or random.randint(0, 999999)
                random.seed(seed)
                cfg["serper_last_seed"] = seed
                cfg["serper_current_seed"] = random.randint(0, 999999)
                
                log_file.write(f"=== LeadGen Discovery Started {run_start} ===\n")
                log_file.write(f"API: {api_label}\nRegion: {region}\nSeed: {seed}\n")
                if self.progress_callback:
                    self.progress_callback(f"Using API: {api_label}, Region: {region}")
                
                # Handle re-analysis period
                reanalysis_period = int(cfg.get("reanalysis_period", 0))
                if reanalysis_period > 0:
                    existing_leads = self.comprehensive_logger.get_leads_for_reanalysis(reanalysis_period)
                    msg = f"Re-analysis mode: Found {len(existing_leads)} leads to re-analyze"
                    self.logger.info(msg)
                    log_file.write(f"Re-analysis mode: Found {len(existing_leads)} leads to re-analyze\n")
                    if self.progress_callback:
                        self.progress_callback(msg)
                
                leads_path = f"data/leads_raw_{run_id}.csv"
                leads_state = self.load_leads_state(leads_path)
                
                # Get keyword boxes from config
                keyword_boxes = cfg.get("keyword_boxes", [])
                if not keyword_boxes:
                    # Fallback to old system for backward compatibility
                    set_terms = self._split_keywords_preserve_quotes(cfg.get("serper_set_keywords", ""))
                    var_terms = self._split_keywords_preserve_quotes(cfg.get("serper_variable_keywords", ""))
                    keyword_boxes = [", ".join(set_terms), ", ".join(var_terms)]
                
                cap = int(cfg.get("serper_combo_cap", 500))
                
                if self.progress_callback:
                    self.progress_callback(f"Generating search combinations (cap: {cap})...")
                
                combos = self.generate_serper_combinations(keyword_boxes, cap=cap)
                
                log_file.write(f"Keyword boxes: {len(keyword_boxes)}\n")
                for i, box in enumerate(keyword_boxes):
                    if box.strip():
                        log_file.write(f"  Box {i+1}: {box}\n")
                log_file.write(f"Generated {len(combos)} combos (cap={cap})\n\n")
                
                if self.progress_callback:
                    self.progress_callback(f"Generated {len(combos)} search combinations. Starting searches...")
                
                new_total = 0
                api_error_count = 0
                max_api_errors = 10  # Stop after 10 consecutive API errors
                
                for i, terms in enumerate(combos, start=1):
                    hist_key = self.format_search_key(terms)
                    query = self.build_query_from_terms_as_and(terms)
                    msg = f"Search {i}/{len(combos)}: {hist_key}"
                    self.logger.info(f"=== {msg} [{api_label}] ===")
                    log_file.write(f"=== Search {i}/{len(combos)} [{api_label}] {hist_key} ===\n")
                    
                    # Send detailed progress to GUI
                    if self.progress_callback:
                        self.progress_callback(f"[{i}/{len(combos)}] Searching: {hist_key}")
                    
                    results = self.serper_search(api_key, query, max_results, region, log_file)
                    
                    # Check for API errors
                    if self.last_api_error:
                        api_error_count += 1
                        if api_error_count >= max_api_errors:
                            error_msg = f"ERROR: Too many consecutive API errors ({api_error_count}). Last error: {self.last_api_error}. Please check your API key and account status."
                            self.logger.error(error_msg)
                            log_file.write(f"{error_msg}\n")
                            if self.progress_callback:
                                self.progress_callback(error_msg)
                            return False
                        else:
                            if self.progress_callback:
                                self.progress_callback(f"  ⚠ API error ({api_error_count}/{max_api_errors}): {self.last_api_error}")
                            log_file.write(f"API error: {self.last_api_error}\n\n")
                            continue
                    elif isinstance(results, list) and len(results) == 0:
                        # No results but no API error - might be legitimately no results
                        api_error_count = 0  # Reset counter on successful API call with no results
                        log_file.write("No search results returned.\n\n")
                        continue
                    else:
                        api_error_count = 0  # Reset counter on success
                    
                    if not results or len(results) == 0:
                        log_file.write("No search results returned.\n\n")
                        continue
                    
                    urls = [r["link"] for r in results if r.get("link")]
                    
                    if self.progress_callback:
                        self.progress_callback(f"  → Found {len(urls)} URLs, verifying domains...")
                    
                    ver_map = await self.verify_domains(urls, timeout_s, concurrency)
                    active = [u for u in urls if ver_map.get(u, False)]
                    before = len(leads_state)
                    
                    for u in active:
                        root = self.extract_root_domain(u)
                        if root and root not in leads_state:
                            leads_state[root] = False
                            # Log to comprehensive system
                            self.comprehensive_logger.log_lead_discovery(root, run_id)
                    
                    after = len(leads_state)
                    added = after - before
                    new_total += added
                    
                    status_msg = f"  → Added {added} new sites (total: {after})"
                    log_file.write(f"Added {added} new sites (total={after}).\n\n")
                    self.save_leads_state(leads_path, leads_state)
                    self.logger.info(f"Added {added} new sites (total leads now {after})")
                    
                    if self.progress_callback:
                        self.progress_callback(status_msg)
                    
                    # Save progress every 10 websites
                    if len(leads_state) % 10 == 0:
                        self.comprehensive_logger.save_run_log(
                            run_id, run_start.isoformat(), status="running", 
                            step1=True, total_leads=len(leads_state)
                        )
                
                duration = datetime.now() - run_start
                completion_msg = f"Discovery Complete! Duration: {duration}, Total leads: {len(leads_state)}"
                log_file.write(f"=== Discovery Complete {datetime.now()} ===\nDuration: {duration}\nNew total leads: {len(leads_state)}\n")
                self.logger.info(completion_msg)
                if self.progress_callback:
                    self.progress_callback(completion_msg)
            
            self.logger.info(f"Step 1 complete. Full log written to {run_log}")
            return True
            
        except Exception as e:
            error_msg = f"ERROR in Step 1: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            if self.progress_callback:
                self.progress_callback(error_msg)
            return False

# ============================================================
# STEP 2: WEBSITE SCRAPING
# ============================================================

class WebsiteScraper:
    """Step 2: Website scraping and content extraction."""
    
    def __init__(self, config: UnifiedConfig):
        self.config = config
        self.logger = setup_logging()
        self.comprehensive_logger = ComprehensiveLogger()
        
        # Heuristic keywords for page selection
        self.PRIMARY_HINTS = [
            "oncology","cancer","tumor","tumour","solid","preclinical","pipeline","technology","platform",
            "device","implant","ablation","interventional","catheter","ultrasound","radiofrequency","rf",
            "electro","photothermal","laser","microwave","nano","drug-delivery","drugdelivery","local",
            "trial","animal","mouse","murine","research","lab","products","solutions","indications",
            "bile","bladder","glioma","brain","colorectal","kidney","liver","lung","pancreas","soft-tissue",
            "about","team","company","science","mechanism","moa","publications","data",
        ]
        self.NEGATIVE_HINTS = [
            "blog","news","press","careers","jobs","privacy","terms","cookie","sitemap","login","signin",
            "contact","support","faq","events","webinar","newsletter","cart","shop","store","/tag/","/category/",
            "/author/","/page/","/wp-","javascript:","mailto:","tel:","#"
        ]
        self.SECONDARY_HINTS = ["about","company","technology","science","products","solutions","pipeline","indications","research","studies","team"]
    
    def init_db(self, db_path: str):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS websites(
                root_url TEXT PRIMARY KEY,
                aggregated_text TEXT,
                num_pages INTEGER,
                last_updated TEXT,
                status TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pages(
                root_url TEXT,
                page_url TEXT PRIMARY KEY,
                status_code INTEGER,
                text TEXT,
                crawled_at TEXT
            )
        """)
        conn.commit()
        return conn
    
    def normalize_root(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        parsed = urlparse(url)
        scheme = "https" if parsed.scheme in ("http", "https") else "https"
        netloc = parsed.netloc.lower()
        return urlunparse((scheme, netloc, "", "", "", ""))
    
    def normalize_url(self, url: str) -> str:
        u, _frag = urldefrag(url.strip())
        p = urlparse(u)
        qs = parse_qs(p.query)
        drop = {"utm_source","utm_medium","utm_campaign","utm_content","gclid","fbclid","mc_cid","mc_eid"}
        qs2 = {k:v for k,v in qs.items() if k.lower() not in drop}
        query = "&".join([f"{k}={v[0]}" for k,v in qs2.items() if v])
        return urlunparse((p.scheme, p.netloc.lower(), re.sub(r"/{2,}", "/", p.path), "", query, ""))
    
    def same_reg_domain(self, a: str, b: str) -> bool:
        ea = tldextract.extract(a)
        eb = tldextract.extract(b)
        return (ea.domain, ea.suffix) == (eb.domain, eb.suffix)
    
    def is_probably_html(self, content_type: str|None) -> bool:
        if not content_type:
            return True
        ct = content_type.split(";")[0].strip().lower()
        return ct in ("text/html", "application/xhtml+xml") or ct.startswith("text/")
    
    def extract_text(self, html: str, url: str) -> str:
        if trafilatura:
            try:
                txt = trafilatura.extract(html, url=url, include_comments=False, include_tables=False) or ""
                txt = re.sub(r"\s+", " ", txt).strip()
                return txt
            except Exception:
                pass
        soup = BeautifulSoup(html, "html.parser")
        for bad in soup(["script","style","noscript","header","footer","nav","aside"]):
            bad.decompose()
        text = soup.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text).strip()
        return text
    
    def score_candidate(self, base_root: str, page_url: str, anchor_text: str|None=None) -> float:
        score = 0.0
        if not self.same_reg_domain(base_root, page_url):
            return -1e9
        
        pu = urlparse(page_url)
        path_lower = pu.path.lower()
        s = path_lower
        
        if any(neg in s for neg in self.NEGATIVE_HINTS):
            score -= 3.0
        
        for kw in self.PRIMARY_HINTS:
            if kw in s:
                score += 2.0
        
        if anchor_text:
            at = anchor_text.lower()
            for kw in self.PRIMARY_HINTS:
                if kw in at:
                    score += 1.2
            for kw in self.SECONDARY_HINTS:
                if kw in at:
                    score += 0.6
        
        depth = s.count("/")
        score += max(0, 2.0 - 0.3 * depth)
        
        if path_lower in ("", "/"):
            score += 0.5
        
        if re.search(r"\.(pdf|png|jpg|jpeg|gif|svg|mp4|zip|rar|7z|gz|json|xml)$", s):
            score -= 10.0
        
        return score
    
    def discover_links(self, base_url: str, html: str) -> list[tuple[str,str]]:
        soup = BeautifulSoup(html, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            abs_url = urljoin(base_url, href)
            abs_url = self.normalize_url(abs_url)
            anchor_text = a.get_text(strip=True)[:200]
            links.append((abs_url, anchor_text))
        return links
    
    async def fetch(self, session: aiohttp.ClientSession, url: str, read_limit: int) -> tuple[int, str|None, str|None]:
        try:
            async with session.get(url) as resp:
                ct = resp.headers.get("Content-Type", "")
                if not self.is_probably_html(ct):
                    return resp.status, ct, None
                body = await resp.content.read(read_limit)
                html = body.decode(errors="ignore")
                return resp.status, ct, html
        except Exception as e:
            self.logger.debug(f"Fetch error {url}: {e}")
            return 0, None, None
    
    async def crawl_site(self, root_url: str, session: aiohttp.ClientSession, conn: sqlite3.Connection, cfg: dict) -> bool:
        root = self.normalize_root(root_url)
        seen = set()
        kept = []
        queue: list[tuple[float,int,str]] = []
        import heapq
        
        heapq.heappush(queue, (-self.score_candidate(root, root), 0, root))
        seen.add(root)
        
        pages = 0
        aggregate_chunks = []
        
        while queue and pages < cfg["max_pages_per_site"]:
            _negscore, depth, url = heapq.heappop(queue)
            if depth > cfg["max_depth"]:
                continue
            
            status, ct, html = await self.fetch(session, url, cfg["read_limit_bytes"])
            
            if status == 0 or html is None:
                continue
            
            text = self.extract_text(html, url)
            if len(text) >= cfg["min_chars_per_page"]:
                kept.append((url, status, text))
                if sum(len(x) for x in aggregate_chunks) < cfg["aggregate_char_cap"]:
                    aggregate_chunks.append(text[:20_000])
            
            pages += 1
            
            for abs_url, anchor in self.discover_links(url, html):
                if not self.same_reg_domain(root, abs_url):
                    continue
                if abs_url in seen:
                    continue
                seen.add(abs_url)
                s = self.score_candidate(root, abs_url, anchor)
                if s <= -5:
                    continue
                heapq.heappush(queue, (-s, depth + 1, abs_url))
        
        status = "ok" if kept else "empty"
        aggregated = " ".join(aggregate_chunks)[:cfg["aggregate_char_cap"]]
        
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            INSERT INTO websites(root_url, aggregated_text, num_pages, last_updated, status)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(root_url) DO UPDATE SET
               aggregated_text=excluded.aggregated_text,
               num_pages=excluded.num_pages,
               last_updated=excluded.last_updated,
               status=excluded.status
        """, (root, aggregated, len(kept), now, status))
        
        for url, status_code, text in kept:
            conn.execute("""
                INSERT INTO pages(root_url, page_url, status_code, text, crawled_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(page_url) DO UPDATE SET
                   status_code=excluded.status_code,
                   text=excluded.text,
                   crawled_at=excluded.crawled_at
            """, (root, url, status_code, text, now))
        
        conn.commit()
        return bool(kept)
    
    async def run_scraping(self):
        """Run website scraping step."""
        self.logger.info("Starting Step 2: Website Scraping")
        
        cfg = self.config.config["step2"]
        # Find the most recent leads file
        import glob
        leads_files = glob.glob("data/leads_raw_*.csv")
        if not leads_files:
            self.logger.error("No leads file found")
            return False
        input_csv = max(leads_files, key=os.path.getctime)
        db_path = cfg["db_path"]
        run_id = self.comprehensive_logger.get_run_id()
        
        if not os.path.exists(input_csv):
            self.logger.error(f"Input CSV not found: {input_csv}")
            return False
        
        conn = self.init_db(db_path)
        
        # Load targets from CSV
        df = pd.read_csv(input_csv, dtype=str).fillna("")
        cols = {c.lower().strip(): c for c in df.columns}
        need = {"website","scanned"}
        if not need.issubset(set(k.lower() for k in df.columns)):
            self.logger.error(f"CSV must contain columns: {need}. Got: {df.columns.tolist()}")
            return False
        
        df.columns = [c.lower().strip() for c in df.columns]
        
        tasks = []
        indices = []
        for i, row in df.iterrows():
            scanned = str(row.get("scanned","")).strip().lower()
            site = str(row.get("website","")).strip()
            if not site or scanned == "true":
                continue
            indices.append(i)
            tasks.append(site)
        
        if not tasks:
            self.logger.info("No unscanned websites found.")
            return True
        
        timeout = ClientTimeout(total=cfg["timeout_sec"])
        headers = {"User-Agent": cfg["user_agent"], "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
        
        scanned_idx = []
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for chunk_start in range(0, len(tasks), 20):
                chunk_sites = tasks[chunk_start:chunk_start+20]
                chunk_idxs = indices[chunk_start:chunk_start+20]
                
                chunk_end = min(chunk_start + 20, len(tasks))
                self.logger.info(f"Processing batch {chunk_start//20 + 1} (sites {chunk_start+1}-{chunk_end}/{len(tasks)})")
                
                results = await asyncio.gather(*[
                    self.crawl_site(site, session, conn, cfg) for site in chunk_sites
                ], return_exceptions=True)
                
                for idx, site, res in zip(chunk_idxs, chunk_sites, results):
                    scanned_idx.append(idx)
                    
                    if isinstance(res, Exception):
                        self.logger.error(f"ERROR: {site} -> {repr(res)}")
                        self.comprehensive_logger.log_lead_scraping(site, run_id, False)
                        continue
                    if res:
                        self.logger.info(f"SCRAPED: {site}")
                        self.comprehensive_logger.log_lead_scraping(site, run_id, True)
                    else:
                        self.logger.info(f"NO TEXT: {site}")
                        self.comprehensive_logger.log_lead_scraping(site, run_id, False)
                
                # Update CSV
                for i in scanned_idx:
                    df.at[i, "scanned"] = "true"
                df.to_csv(input_csv, index=False)
                
                # Save progress every 10 websites
                if len(scanned_idx) % 10 == 0:
                    self.comprehensive_logger.save_run_log(
                        run_id, datetime.now().isoformat(), status="running", 
                        step1=True, step2=True, analyzed_leads=len(scanned_idx)
                    )
                
                scanned_idx.clear()
        
        conn.close()
        self.logger.info("Step 2 complete: Website scraping finished")
        return True

# ============================================================
# STEP 3: FACTOR-BASED SCORING
# ============================================================

class FactorScorer:
    """Step 3: Factor-based website scoring."""
    
    def __init__(self, config: UnifiedConfig):
        self.config = config
        self.logger = setup_logging()
        self.comprehensive_logger = ComprehensiveLogger()
        
        # Load factors from config
        self.load_factors_from_config()
    
    def load_factors_from_config(self):
        """Load factors from configuration."""
        step3_config = self.config.config["step3"]
        
        # Load positive factors
        self.FACTORS = []
        positive_factors = step3_config.get("positive_factors", [])
        for factor in positive_factors:
            if factor.get("name") and factor.get("keywords"):
                self.FACTORS.append({
                    "name": factor["name"],
                    "sensitivity": factor.get("sensitivity", 1),
                    "weight": factor.get("weight", 100),
                    "keywords": [k.strip() for k in factor["keywords"].split(",") if k.strip()]
                })
        
        # Load negative factors
        self.DISQUALIFIERS = []
        negative_factors = step3_config.get("negative_factors", [])
        for factor in negative_factors:
            if factor.get("name") and factor.get("keywords"):
                self.DISQUALIFIERS.append({
                    "name": factor["name"],
                    "sensitivity": factor.get("sensitivity", 1),
                    "weight": factor.get("weight", 100),
                    "keywords": [k.strip() for k in factor["keywords"].split(",") if k.strip()]
                })
        
        # If no factors loaded, use defaults
        if not self.FACTORS and not self.DISQUALIFIERS:
            self.load_default_factors()
    
    def load_default_factors(self):
        """Load default factors if none configured."""
        self.FACTORS = [
            {"name": "us", "sensitivity": 1, "weight": 100, "keywords": [
                "usa", "u.s.", "united states", "boston", "chicago", "ohio",
                "new york", "california", "pennsylvania", "cincinnati"
            ]},
            {"name": "oncology", "sensitivity": 3, "weight": 500, "keywords": [
                "oncology", "cancer", "tumor", "tumour", "glioma", "solid tumor",
                "metastatic", "carcinoma", "neoplasm", "melanoma"
            ]},
            {"name": "medical_device", "sensitivity": 1, "weight": 100, "keywords": [
                "device", "implant", "catheter", "radiofrequency", "rf ablation",
                "ultrasound", "laser", "microwave", "interventional",
                "drug delivery", "microdevice", "biosensor"
            ]},
            {"name": "preclinical", "sensitivity": 1, "weight": 500, "keywords": [
                "preclinical", "animal study", "murine", "mouse model", "rat model",
                "in vivo", "in vitro", "laboratory research", "bench study", "toxicology study"
            ]},
            {"name": "organ_target", "sensitivity": 2, "weight": 100, "keywords": [
                "bile", "biliary", "bladder", "glioma", "brain", "colorectal",
                "colon", "kidney", "renal", "liver", "hepatic", "lung", "pulmonary",
                "pancreas", "pancreatic", "soft tissue", "sarcoma"
            ]},
        ]
        
        self.DISQUALIFIERS = [
            {"name": "non_us", "sensitivity": 20, "weight": 100, "keywords": [
                "germany", "france", "china", "india", "canada", "uk", "england",
                "scotland", "ireland", "japan", "korea", "australia", "israel", "italy", "spain"
            ]},
            {"name": "post_clinical", "sensitivity": 10, "weight": 500, "keywords": [
                "phase i", "phase ii", "phase iii", "clinical trial", "human trial",
                "patient study", "patients", "subjects", "first-in-human", "in human"
            ]},
        ]
    
    def fuzzy_count(self, text: str, keywords: List[str], threshold: int = 85) -> int:
        text_lower = text.lower()
        count = 0
        for kw in keywords:
            kw = kw.lower()
            count += len(re.findall(rf"\b{re.escape(kw)}\b", text_lower))
            if fuzz.partial_ratio(kw, text_lower) >= threshold:
                count += 1
        return count
    
    def score_text(self, text: str) -> Dict:
        text = text.lower()
        total_score = 0
        breakdown = []
        
        for f in self.FACTORS:
            keywords = f.get("keywords", [])
            count = self.fuzzy_count(text, keywords)
            ratio = min(count / f["sensitivity"], 1)
            contrib = ratio * f["weight"]
            total_score += contrib
            breakdown.append({
                "name": f["name"],
                "type": "factor",
                "count": count,
                "contrib": round(contrib, 2)
            })
        
        for d in self.DISQUALIFIERS:
            keywords = d.get("keywords", [])
            count = self.fuzzy_count(text, keywords)
            ratio = min(count / d["sensitivity"], 1)
            contrib = -ratio * d["weight"]
            total_score += contrib
            breakdown.append({
                "name": d["name"],
                "type": "disqualifier",
                "count": count,
                "contrib": round(contrib, 2)
            })
        
        max_score = sum(f["weight"] for f in self.FACTORS)
        min_score = -sum(d["weight"] for d in self.DISQUALIFIERS)
        normalized = (total_score - min_score) / (max_score - min_score) * 100
        normalized = round(max(0, min(normalized, 100)), 2)
        
        return {
            "total_score": round(total_score, 2),
            "normalized": normalized,
            "breakdown": breakdown
        }
    
    def run_scoring(self):
        """Run factor-based scoring step."""
        self.logger.info("Starting Step 3: Factor-based Scoring")
        
        cfg = self.config.config["step3"]
        db_path = self.config.config["step2"]["db_path"]
        
        if not os.path.exists(db_path):
            self.logger.error(f"Database not found: {db_path}")
            return False
        
        # Load websites from database
        # Score ANY website that has text, regardless of status
        conn = sqlite3.connect(db_path)
        query = "SELECT root_url AS url, aggregated_text AS text FROM websites WHERE aggregated_text IS NOT NULL AND aggregated_text != '' AND LENGTH(TRIM(aggregated_text)) > 0"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if df.empty:
            self.logger.warning("No valid websites found in database.")
            return False
        
        self.logger.info(f"Analyzing {len(df)} websites from {db_path}")
        
        results = []
        run_id = self.comprehensive_logger.get_run_id()
        processed_count = 0
        
        for _, row in df.iterrows():
            url = row["url"]
            text = row["text"]
            score_result = self.score_text(text)
            flat = {"url": url, "total_score": score_result["total_score"], "normalized": score_result["normalized"]}
            for b in score_result["breakdown"]:
                flat[f"{b['name']}_count"] = b["count"]
                flat[f"{b['name']}_score"] = b["contrib"]
            results.append(flat)
            
            # Log to comprehensive system
            self.comprehensive_logger.log_lead_scoring(url, run_id, score_result["normalized"])
            processed_count += 1
            
            # Save progress every 10 websites
            if processed_count % 10 == 0:
                self.comprehensive_logger.save_run_log(
                    run_id, datetime.now().isoformat(), status="running", 
                    step1=True, step2=True, step3=True, analyzed_leads=processed_count
                )
        
        results_df = pd.DataFrame(results)
        results_df = results_df.sort_values("normalized", ascending=False)
        
        # Apply threshold based on configuration
        threshold_type = cfg.get("threshold_type", "score")
        threshold_value = cfg.get("threshold_value", "75")
        
        if threshold_type == "score":
            threshold = float(threshold_value)
            filtered_df = results_df[results_df['normalized'] >= threshold]
        elif threshold_type == "percentage":
            percentage = float(threshold_value)
            num_to_keep = int(len(results_df) * percentage / 100)
            filtered_df = results_df.head(num_to_keep)
        elif threshold_type == "count":
            count = int(threshold_value)
            filtered_df = results_df.head(count)
        else:
            filtered_df = results_df
        
        # Save results
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"data/scoring_results_{run_id}.csv"
        os.makedirs("data", exist_ok=True)
        filtered_df.to_csv(output_path, index=False)
        
        self.logger.info(f"Step 3 complete: Scoring results saved to {output_path}")
        self.logger.info(f"Filtered to {len(filtered_df)} websites based on {threshold_type} threshold")
        if not filtered_df.empty:
            self.logger.info(f"Top 5 scores:")
            for _, row in filtered_df.head(5).iterrows():
                self.logger.info(f"  {row['url']}: {row['normalized']:.2f}")
        
        return True

# ============================================================
# ADAPTIVE RATE LIMITER
# ============================================================

class AdaptiveRateLimiter:
    """Automatically finds the fastest rate without errors."""
    
    def __init__(self, initial_delay: float = 0.1, min_delay: float = 0.01, max_delay: float = 5.0):
        self.current_delay = initial_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.consecutive_successes = 0
        self.consecutive_errors = 0
        self.success_threshold = 5  # Need 5 successes to speed up
        self.error_threshold = 2    # 2 errors to slow down
        
    def get_delay(self) -> float:
        """Get current delay between requests."""
        return self.current_delay
    
    def on_success(self):
        """Called when a request succeeds."""
        self.consecutive_successes += 1
        self.consecutive_errors = 0
        
        # Speed up if we've had enough consecutive successes
        if self.consecutive_successes >= self.success_threshold:
            self.current_delay = max(self.min_delay, self.current_delay * 0.8)
            self.consecutive_successes = 0
            self.logger.info(f"⚡ Sped up: delay now {self.current_delay:.3f}s")
    
    def on_error(self):
        """Called when a request fails."""
        self.consecutive_errors += 1
        self.consecutive_successes = 0
        
        # Slow down if we've had errors
        if self.consecutive_errors >= self.error_threshold:
            self.current_delay = min(self.max_delay, self.current_delay * 1.5)
            self.consecutive_errors = 0
            self.logger.info(f"🐌 Slowed down: delay now {self.current_delay:.3f}s")
    
    def set_logger(self, logger):
        """Set logger for rate limiter messages."""
        self.logger = logger

# ============================================================
# STEP 4: AI ANALYSIS
# ============================================================

def read_example_files(folder_path: str) -> str:
    """
    Read all relevant files from a folder and return combined text.
    Supports: .txt, .md, .html, .csv, .docx, .pdf, .rtf
    """
    if not folder_path or not os.path.exists(folder_path):
        return ""
    
    supported_extensions = {'.txt', '.md', '.html', '.htm', '.csv', '.docx', '.pdf', '.rtf'}
    combined_text = []
    
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            ext = os.path.splitext(file)[1].lower()
            
            if ext not in supported_extensions:
                continue
            
            try:
                if ext == '.txt' or ext == '.md' or ext == '.rtf':
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        combined_text.append(f"=== {file} ===\n{content}\n\n")
                
                elif ext == '.html' or ext == '.htm':
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        soup = BeautifulSoup(f.read(), 'html.parser')
                        # Remove script and style elements
                        for script in soup(["script", "style"]):
                            script.decompose()
                        content = soup.get_text(separator='\n', strip=True)
                        combined_text.append(f"=== {file} ===\n{content}\n\n")
                
                elif ext == '.csv':
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        reader = csv.reader(f)
                        rows = list(reader)
                        content = '\n'.join([', '.join(row) for row in rows])
                        combined_text.append(f"=== {file} ===\n{content}\n\n")
                
                elif ext == '.docx' and docx:
                    try:
                        doc = docx.Document(file_path)
                        paragraphs = [p.text for p in doc.paragraphs]
                        content = '\n'.join(paragraphs)
                        combined_text.append(f"=== {file} ===\n{content}\n\n")
                    except Exception as e:
                        logging.warning(f"Error reading {file_path}: {e}")
                
                elif ext == '.pdf' and PyPDF2:
                    try:
                        with open(file_path, 'rb') as f:
                            pdf_reader = PyPDF2.PdfReader(f)
                            pages_text = []
                            for page_num in range(min(len(pdf_reader.pages), 10)):  # Limit to first 10 pages
                                page = pdf_reader.pages[page_num]
                                pages_text.append(page.extract_text())
                            content = '\n'.join(pages_text)
                            combined_text.append(f"=== {file} ===\n{content}\n\n")
                    except Exception as e:
                        logging.warning(f"Error reading {file_path}: {e}")
                
            except Exception as e:
                logging.warning(f"Error reading {file_path}: {e}")
                continue
    
    return '\n'.join(combined_text)

class AIAnalyzer:
    """Step 4: AI-powered lead analysis."""
    
    def __init__(self, config: UnifiedConfig, progress_callback=None):
        self.config = config
        self.logger = setup_logging()
        self.comprehensive_logger = ComprehensiveLogger()
        self.rate_limiter = AdaptiveRateLimiter()
        self.rate_limiter.set_logger(self.logger)
        self.credit_used = 0.0
        self.credit_limit = 0.0
        self.progress_callback = progress_callback  # Callback for GUI updates
    
    def estimate_api_cost(self, content: str, model: str, provider: str = "claude") -> float:
        """Estimate API cost for a request."""
        # Estimate tokens (rough: 1 token ≈ 4 characters)
        input_tokens = len(content) / 4
        output_tokens = 1000  # Assume ~1000 tokens output
        
        if provider.lower() == "openai":
            # OpenAI pricing (as of 2024)
            if "gpt-4" in model.lower():
                input_cost = 0.03   # $30 per 1M input tokens
                output_cost = 0.06  # $60 per 1M output tokens
            elif "gpt-3.5-turbo" in model.lower():
                input_cost = 0.0015  # $1.50 per 1M input tokens
                output_cost = 0.002   # $2.00 per 1M output tokens
            else:
                input_cost = 0.0015
                output_cost = 0.002
        else:
            # Anthropic pricing
            if "haiku" in model.lower():
                input_cost = 0.00025  # $0.25 per 1M input tokens
                output_cost = 0.00125  # $1.25 per 1M output tokens
            else:  # sonnet
                input_cost = 0.003   # $3 per 1M input tokens
                output_cost = 0.015  # $15 per 1M output tokens
        
        cost = (input_tokens * input_cost / 1000) + (output_tokens * output_cost / 1000)
        return cost
    
    def get_website_content(self, url: str) -> Optional[str]:
        try:
            conn = sqlite3.connect(self.config.config["step2"]["db_path"])
            cursor = conn.cursor()
            cursor.execute(
                "SELECT aggregated_text FROM websites WHERE root_url = ?", 
                (url,)
            )
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0]:
                return result[0]
            return None
        except Exception as e:
            self.logger.error(f"Error getting content for {url}: {e}")
            return None
    
    def analyze_website(self, url: str, content: str) -> Dict[str, Any]:
        cfg = self.config.config["step4"]
        api_key = cfg.get("api_key", "")
        model = cfg.get("model", "gpt-3.5-turbo")
        provider = cfg.get("provider_choice") or cfg.get("api_provider", "claude")
        
        if not api_key:
            self.logger.error("❌ ERROR: API key not configured for AI analysis")
            return None
        
        # Check credit limit
        estimated_cost = self.estimate_api_cost(content, model, provider)
        if self.credit_used + estimated_cost > self.credit_limit:
            self.logger.warning(f"Credit limit reached: ${self.credit_used:.2f}/${self.credit_limit:.2f}")
            return None
        
        max_chars = 12000
        if len(content) > max_chars:
            content = content[:max_chars] + "... [truncated]"
        
        # Get custom prompt components from config
        custom_explanation = cfg.get("custom_explanation", "").strip()
        examples_folder = cfg.get("examples_folder", "").strip()
        
        # Read example files if folder is provided
        examples_text = ""
        if examples_folder and os.path.exists(examples_folder):
            examples_text = read_example_files(examples_folder)
            if examples_text:
                # Limit examples text to prevent token limit issues (approximately 5000 characters)
                # This is roughly 1250 tokens, leaving room for the rest of the prompt
                max_examples_chars = 5000
                if len(examples_text) > max_examples_chars:
                    examples_text = examples_text[:max_examples_chars] + f"\n\n... [truncated {len(examples_text) - max_examples_chars} more characters]"
                examples_text = f"\n\n=== EXAMPLES OF GOOD LEADS ===\n\nHere are examples of good leads for reference:\n\n{examples_text}"
        
        # Build the prompt
        if custom_explanation:
            explanation_section = f"""
{custom_explanation}
"""
        else:
            # Fallback to default explanation
            explanation_section = """
Focus on identifying companies that:
1. Are B2B service providers (CROs, consulting firms, medical device companies, etc.)
2. Serve other businesses in healthcare/pharma/medical device sectors
3. Have clear commercial offerings and business models
4. Are NOT just news sites, academic institutions, or consumer-focused companies
"""
        
        prompt = f"""
You are an expert business analyst specializing in identifying high-quality B2B leads in the healthcare, medical device, and pharmaceutical industries.

Analyze the following website and determine if it represents a good business lead.

{explanation_section}{examples_text}

Website URL: {url}
Website Content: {content}

Please provide your analysis in the following JSON format:
{{
    "match_score": <integer 0-100, how well this matches ideal lead criteria>,
    "business_type": "<brief description of what type of business this is>",
    "is_good_lead": <true/false, whether this is a qualified business lead>,
    "confidence": <integer 0-100, how confident you are in this assessment>,
    "reasoning": "<detailed explanation of your assessment>",
    "key_indicators": "<comma-separated list of positive indicators>",
    "red_flags": "<comma-separated list of any concerns or negative indicators>"
}}

Focus on identifying legitimate B2B companies that would be valuable leads for healthcare technology and services.
"""
        
        for attempt in range(cfg.get("max_retries", 3)):
            try:
                # Apply adaptive rate limiting
                delay = self.rate_limiter.get_delay()
                if delay > 0:
                    time.sleep(delay)
                
                # Determine API endpoint and headers based on provider
                if provider.lower() == "openai":
                    # OpenAI API
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    }
                    api_url = "https://api.openai.com/v1/chat/completions"
                    payload = {
                        "model": model,
                        "max_tokens": cfg.get("max_tokens", 2000),
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ]
                    }
                else:
                    # Anthropic/Claude API (default)
                    headers = {
                        "x-api-key": api_key,
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01"
                    }
                    api_url = "https://api.anthropic.com/v1/messages"
                    payload = {
                        "model": model,
                        "max_tokens": cfg.get("max_tokens", 2000),
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ]
                    }
                
                self.logger.debug(f"Making {provider.upper()} API request to {api_url}")
                
                response = requests.post(
                    api_url,
                    headers=headers,
                    json=payload,
                    timeout=30
                )
                
                if response.status_code == 200:
                    # Success - update rate limiter and credit tracking
                    self.rate_limiter.on_success()
                    self.credit_used += estimated_cost
                    
                    result = response.json()
                    
                    # Handle different response formats
                    if provider.lower() == "openai":
                        content_text = result['choices'][0]['message']['content']
                    else:
                        # Anthropic format
                        content_text = result['content'][0]['text']
                    
                    # Save prompt and response for debugging
                    self._save_ai_debug_log(url, prompt, content_text, error=None)
                    
                    try:
                        start_idx = content_text.find('{')
                        end_idx = content_text.rfind('}') + 1
                        if start_idx != -1 and end_idx > start_idx:
                            json_str = content_text[start_idx:end_idx]
                            analysis = json.loads(json_str)
                            
                            analysis['url'] = url
                            analysis['processed_at'] = datetime.now(timezone.utc).isoformat()
                            analysis['content_length'] = len(content)
                            analysis['estimated_cost'] = estimated_cost
                            
                            return analysis
                        else:
                            self.logger.warning(f"Could not extract JSON from response for {url}")
                            return None
                    except json.JSONDecodeError as e:
                        self.logger.warning(f"Could not parse JSON response for {url}: {e}")
                        return None
                elif response.status_code == 401:
                    # Authentication error - stop retrying, log clearly
                    self.rate_limiter.on_error()
                    error_msg = response.text
                    # Update debug log with error
                    self._save_ai_debug_log(url, prompt, None, error=f"401 Authentication Error: {error_msg}")
                    auth_error = f"❌ AUTHENTICATION ERROR for {url}: Invalid API key!"
                    provider_error = f"   Provider: {provider.upper()}"
                    response_error = f"   Response: {response.status_code} - {error_msg}"
                    check_key_error = f"   Please check your {provider.upper()} API key in Step 4 settings."
                    self.logger.error(auth_error)
                    self.logger.error(provider_error)
                    self.logger.error(response_error)
                    self.logger.error(check_key_error)
                    if self.progress_callback:
                        self.progress_callback(auth_error)
                        self.progress_callback(provider_error)
                        self.progress_callback(check_key_error)
                    return None
                else:
                    # Other error - update rate limiter
                    self.rate_limiter.on_error()
                    error_response = response.text
                    # Update debug log with error
                    self._save_ai_debug_log(url, prompt, None, error=f"HTTP {response.status_code}: {error_response}")
                    self.logger.warning(f"API request failed for {url}: {response.status_code} - {error_response}")
                    if attempt < cfg.get("max_retries", 3) - 1:
                        continue
                    return None
                    
            except Exception as e:
                # Error - update rate limiter
                self.rate_limiter.on_error()
                error_msg = str(e)
                # Update debug log with exception
                self._save_ai_debug_log(url, prompt, None, error=f"Exception: {error_msg}")
                self.logger.error(f"Error analyzing {url} (attempt {attempt + 1}): {e}")
                if attempt < cfg.get("max_retries", 3) - 1:
                    continue
                self.logger.error(f"❌ Failed to analyze {url} after {cfg.get('max_retries', 3)} attempts")
                return None
        
        return None
    
    def _save_ai_debug_log(self, url: str, prompt: str, response: Optional[str], error: Optional[str] = None):
        """Save AI prompt and response to a debug log file."""
        try:
            os.makedirs("logs", exist_ok=True)
            # Create a safe filename from URL
            safe_url = url.replace("https://", "").replace("http://", "").replace("/", "_").replace(":", "_")
            safe_url = re.sub(r'[<>"|?*]', '_', safe_url)[:100]  # Limit length and remove invalid chars
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            debug_file = os.path.join("logs", f"ai_debug_{safe_url}_{timestamp}.txt")
            
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(f"=== AI DEBUG LOG ===\n")
                f.write(f"URL: {url}\n")
                f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                if error:
                    f.write(f"STATUS: ERROR - {error}\n")
                else:
                    f.write(f"STATUS: SUCCESS\n")
                f.write(f"\n{'='*80}\n")
                f.write(f"PROMPT SENT TO AI:\n")
                f.write(f"{'='*80}\n\n")
                f.write(prompt)
                f.write(f"\n\n{'='*80}\n")
                if response:
                    f.write(f"RESPONSE FROM AI:\n")
                    f.write(f"{'='*80}\n\n")
                    f.write(response)
                elif error:
                    f.write(f"ERROR RESPONSE:\n")
                    f.write(f"{'='*80}\n\n")
                    f.write(error)
                else:
                    f.write(f"RESPONSE: Not yet received\n")
            
            self.logger.info(f"AI debug log saved to: {debug_file}")
        except Exception as e:
            self.logger.warning(f"Failed to save AI debug log: {e}")
    
    def run_ai_analysis(self):
        """Run AI analysis step."""
        self.logger.info("Starting Step 4: AI Analysis")
        
        cfg = self.config.config["step4"]
        self.credit_limit = cfg.get("credit_limit", 50.0)
        self.credit_used = 0.0
        
        # Validate API key configuration
        api_key = cfg.get("api_key", "")
        provider = cfg.get("provider_choice") or cfg.get("api_provider", "claude")
        
        if not api_key:
            error_msg = "❌ ERROR: API key is not configured in Step 4 settings!"
            self.logger.error(error_msg)
            self.logger.error("   Please go to Step 4 tab and enter your API key.")
            if self.progress_callback:
                self.progress_callback(error_msg)
                self.progress_callback("   Please go to Step 4 tab and enter your API key.")
            return False
        
        # Log provider and key status (hide actual key) - show in GUI too
        key_display = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
        provider_msg = f"Using API Provider: {provider.upper()}"
        key_msg = f"API Key: {key_display} ({'configured' if api_key else 'MISSING'})"
        self.logger.info(provider_msg)
        self.logger.info(key_msg)
        if self.progress_callback:
            self.progress_callback(provider_msg)
            self.progress_callback(key_msg)
        
        # Find the most recent scoring results
        import glob
        scoring_files = glob.glob("data/scoring_results_*.csv")
        if not scoring_files:
            self.logger.error("No scoring results found")
            return False
        scoring_path = max(scoring_files, key=os.path.getctime)
        
        run_id = self.comprehensive_logger.get_run_id()
        results_path = f"data/ai_analysis_results_{run_id}.csv"
        
        if not os.path.exists(scoring_path):
            self.logger.error(f"Scoring results not found: {scoring_path}")
            return False
        
        # Load scoring results (already filtered by Step 3 based on user's threshold settings)
        scoring_df = pd.read_csv(scoring_path)
        
        # Step 3 has already filtered the results based on the user's configuration
        # (score threshold, percentage, or count). Step 4 analyzes ALL results from Step 3.
        # Note: step4.score_threshold in config is not used - filtering happens in Step 3 only.
        high_score_df = scoring_df
        
        found_msg = f"Found {len(high_score_df)} websites from Step 3 results to analyze"
        self.logger.info(found_msg)
        if self.progress_callback:
            self.progress_callback(found_msg)
        
        if len(high_score_df) == 0:
            warning_msg = "No websites found in scoring results for AI analysis"
            self.logger.warning(warning_msg)
            if self.progress_callback:
                self.progress_callback(warning_msg)
            return True
        
        results = []
        run_id = self.comprehensive_logger.get_run_id()
        processed_count = 0
        
        for idx, (_, row) in enumerate(high_score_df.iterrows()):
            url = row['url']
            normalized_score = row['normalized']
            
            process_msg = f"Processing {idx + 1}/{len(high_score_df)}: {url} (score: {normalized_score:.2f})"
            self.logger.info(process_msg)
            if self.progress_callback:
                self.progress_callback(process_msg)
            
            content = self.get_website_content(url)
            if not content:
                self.logger.warning(f"No content found for {url}")
                continue
            
            analysis = self.analyze_website(url, content)
            if analysis:
                analysis['normalized_score'] = normalized_score
                results.append(analysis)
                complete_msg = f"Analysis complete: {url} - Match: {analysis.get('match_score', 'N/A')}, Good Lead: {analysis.get('is_good_lead', 'N/A')}"
                self.logger.info(complete_msg)
                if self.progress_callback:
                    self.progress_callback(complete_msg)
                
                # Log to comprehensive system
                self.comprehensive_logger.log_lead_ai_analysis(url, run_id, analysis)
            else:
                failed_msg = f"Failed to analyze {url}"
                self.logger.error(failed_msg)
                if self.progress_callback:
                    self.progress_callback(f"ERROR: {failed_msg}")
            
            processed_count += 1
            
            # Log credit usage
            self.logger.info(f"Credit used: ${self.credit_used:.2f}/${self.credit_limit:.2f}")
            
            # Save progress every 10 websites
            if processed_count % 10 == 0:
                self.comprehensive_logger.save_run_log(
                    run_id, datetime.now().isoformat(), status="running", 
                    step1=True, step2=True, step3=True, step4=True, analyzed_leads=processed_count
                )
        
        # Save results
        if results:
            results_df = pd.DataFrame(results)
            results_df.to_csv(results_path, index=False)
            self.logger.info(f"Step 4 complete: AI analysis results saved to {results_path}")
            
            good_leads = results_df[results_df['is_good_lead'] == True]
            self.logger.info(f"Summary: {len(good_leads)}/{len(results_df)} identified as good leads")
            if len(good_leads) > 0:
                self.logger.info("Top good leads:")
                for _, lead in good_leads.head(5).iterrows():
                    self.logger.info(f"  {lead['url']} - {lead['business_type']} (Match: {lead['match_score']})")
        else:
            self.logger.warning("No successful AI analyses completed")
        
        return True

# ============================================================
# INITIAL POPUP GUI
# ============================================================

class InitialPopupGUI:
    """Initial popup GUI for selecting run type."""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Lead Generation Tool")
        self.root.geometry("400x300")
        self.root.resizable(False, False)
        
        # Center the window
        self.root.eval('tk::PlaceWindow . center')
        
        self.setup_gui()
    
    def setup_gui(self):
        """Setup the initial popup interface."""
        # Title
        title_label = ttk.Label(self.root, text="Lead Generation Tool", font=('Arial', 16, 'bold'))
        title_label.pack(pady=20)
        
        # Description
        desc_label = ttk.Label(self.root, text="Choose how you'd like to proceed:", font=('Arial', 10))
        desc_label.pack(pady=10)
        
        # Buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(pady=20, padx=20, fill='x')
        
        ttk.Button(button_frame, text="New Run", command=self.new_run, style='Accent.TButton').pack(fill='x', pady=5)
        ttk.Button(button_frame, text="Continue Run", command=self.continue_run).pack(fill='x', pady=5)
        ttk.Button(button_frame, text="Download Leads", command=self.download_leads).pack(fill='x', pady=5)
        
        # Exit button
        ttk.Button(button_frame, text="Exit", command=self.root.quit).pack(fill='x', pady=(20, 5))
    
    def new_run(self):
        """Start a new run."""
        self.root.destroy()
        app = UnifiedLeadGenGUI()
        app.run()
    
    def continue_run(self):
        """Continue a previous run."""
        self.root.destroy()
        app = ContinueRunGUI()
        app.run()
    
    def download_leads(self):
        """Download leads."""
        self.root.destroy()
        app = DownloadLeadsGUI()
        app.run()
    
    def run(self):
        """Run the popup."""
        self.root.mainloop()

class ContinueRunGUI:
    """GUI for continuing previous runs."""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Continue Previous Run")
        self.root.geometry("600x400")
        
        self.setup_gui()
    
    def setup_gui(self):
        """Setup the continue run interface."""
        ttk.Label(self.root, text="Previous Runs", font=('Arial', 14, 'bold')).pack(pady=10)
        
        # List of previous runs
        self.runs_listbox = tk.Listbox(self.root, height=15)
        self.runs_listbox.pack(fill='both', expand=True, padx=20, pady=10)
        
        # Load previous runs
        self.load_previous_runs()
        
        # Buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(pady=10)
        
        ttk.Button(button_frame, text="Continue Selected Run", command=self.continue_selected).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Back", command=self.back_to_main).pack(side='left', padx=5)
    
    def load_previous_runs(self):
        """Load list of previous runs."""
        try:
            comprehensive_logger = ComprehensiveLogger()
            conn = sqlite3.connect(comprehensive_logger.comprehensive_db)
            
            query = """
                SELECT run_id, start_time, end_time, status, step1_completed, step2_completed, 
                       step3_completed, step4_completed, total_leads, analyzed_leads
                FROM run_logs 
                ORDER BY start_time DESC
            """
            
            cursor = conn.execute(query)
            runs = cursor.fetchall()
            conn.close()
            
            for run in runs:
                run_id, start_time, end_time, status, step1, step2, step3, step4, total_leads, analyzed_leads = run
                
                # Format status
                if status == "finished":
                    status_text = "Finished"
                elif step4:
                    status_text = f"Step 4: {analyzed_leads}/{total_leads} analyzed"
                elif step3:
                    status_text = f"Step 3: {analyzed_leads}/{total_leads} scored"
                elif step2:
                    status_text = f"Step 2: {analyzed_leads}/{total_leads} scraped"
                elif step1:
                    status_text = f"Step 1: {total_leads} discovered"
                else:
                    status_text = "Not started"
                
                # Format time
                try:
                    dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    time_str = start_time
                
                display_text = f"{time_str} - {status_text}"
                self.runs_listbox.insert(tk.END, display_text)
                self.runs_listbox.runs_data = runs  # Store run data for later use
                
        except Exception as e:
            self.runs_listbox.insert(0, f"Error loading runs: {str(e)}")
    
    def continue_selected(self):
        """Continue the selected run."""
        selection = self.runs_listbox.curselection()
        if selection:
            # Load the selected run configuration and continue
            self.root.destroy()
            # Implementation would load the specific run config
            app = UnifiedLeadGenGUI()
            app.run()
    
    def back_to_main(self):
        """Go back to main popup."""
        self.root.destroy()
        app = InitialPopupGUI()
        app.run()
    
    def run(self):
        """Run the continue GUI."""
        self.root.mainloop()

class DownloadLeadsGUI:
    """GUI for downloading leads."""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Download Leads")
        self.root.geometry("500x300")
        
        self.setup_gui()
    
    def setup_gui(self):
        """Setup the download leads interface."""
        ttk.Label(self.root, text="Download Leads", font=('Arial', 14, 'bold')).pack(pady=10)
        
        # Download options
        ttk.Label(self.root, text="Select data source:").pack(pady=10)
        
        self.source_var = tk.StringVar(value="comprehensive")
        ttk.Radiobutton(self.root, text="Comprehensive (All leads ever)", variable=self.source_var, value="comprehensive").pack()
        ttk.Radiobutton(self.root, text="Specific Run", variable=self.source_var, value="specific").pack()
        
        # Run selection (if specific)
        self.run_var = tk.StringVar()
        self.run_combo = ttk.Combobox(self.root, textvariable=self.run_var, state="readonly")
        self.run_combo.pack(pady=10)
        
        # Buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(pady=20)
        
        ttk.Button(button_frame, text="Download CSV", command=self.download_csv).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Back", command=self.back_to_main).pack(side='left', padx=5)
    
    def download_csv(self):
        """Download the leads as CSV."""
        try:
            comprehensive_logger = ComprehensiveLogger()
            
            if self.source_var.get() == "comprehensive":
                # Get comprehensive data
                df = comprehensive_logger.get_comprehensive_data()
                filename = f"comprehensive_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            else:
                # Get specific run data
                run_id = self.run_var.get()
                if not run_id:
                    messagebox.showerror("Error", "Please select a run")
                    return
                
                # This would need to be implemented to get specific run data
                df = comprehensive_logger.get_comprehensive_data()  # For now, use comprehensive
                filename = f"run_{run_id}_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            # Sort data according to requirements
            df = self.sort_leads_data(df)
            
            # Save to file
            filepath = os.path.join("downloads", filename)
            os.makedirs("downloads", exist_ok=True)
            df.to_csv(filepath, index=False)
            
            messagebox.showinfo("Success", f"CSV file saved to: {filepath}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to download CSV: {str(e)}")
    
    def sort_leads_data(self, df):
        """Sort leads data according to the specified requirements."""
        if df.empty:
            return df
        
        # Create a priority column for sorting
        def get_priority(row):
            stage = row.get('stage', '')
            score = row.get('score', 0)
            
            if stage == 'ai_analyzed':
                # AI analyzed leads sorted by score (highest first)
                return (1, -score)
            elif stage == 'scored':
                # Scored leads sorted by score (highest first)
                return (2, -score)
            elif stage == 'scraped':
                # Scraped leads
                return (3, 0)
            elif stage == 'discovered':
                # Discovered leads
                return (4, 0)
            else:
                # Other stages
                return (5, 0)
        
        # Add priority column
        df['priority'] = df.apply(get_priority, axis=1)
        
        # Sort by priority
        df = df.sort_values('priority')
        
        # Remove priority column
        df = df.drop('priority', axis=1)
        
        return df
    
    def back_to_main(self):
        """Go back to main popup."""
        self.root.destroy()
        app = InitialPopupGUI()
        app.run()
    
    def run(self):
        """Run the download GUI."""
        self.root.mainloop()

# ============================================================
# UNIFIED GUI
# ============================================================

class UnifiedLeadGenGUI:
    """Unified GUI for the lead generation application."""
    
    def __init__(self):
        self.config = UnifiedConfig()
        self.root = tk.Tk()
        self.root.title("Unified Lead Generation Tool")
        self.root.geometry("800x600")
        
        self.setup_gui()
    
    def setup_gui(self):
        """Setup the GUI interface."""
        # Create notebook for tabs
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Step 1 Tab
        self.setup_step1_tab(notebook)
        
        # Step 2 Tab
        self.setup_step2_tab(notebook)
        
        # Step 3 Tab
        self.setup_step3_tab(notebook)
        
        # Step 4 Tab
        self.setup_step4_tab(notebook)
        
        # Control Tab
        self.setup_control_tab(notebook)
    
    def setup_step1_tab(self, notebook):
        """Setup Step 1 configuration tab."""
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Step 1: Discovery")
        
        # API Configuration
        ttk.Label(frame, text="API Configuration", font=('Arial', 12, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 10))
        
        ttk.Label(frame, text="API Provider:").grid(row=1, column=0, sticky='w')
        self.api_choice = tk.StringVar(value=self.config.config["step1"]["api_choice"])
        ttk.Radiobutton(frame, text="Serper.dev", variable=self.api_choice, value="serper").grid(row=1, column=1, sticky='w')
        ttk.Radiobutton(frame, text="SerpAPI", variable=self.api_choice, value="serpapi").grid(row=1, column=2, sticky='w')
        
        ttk.Label(frame, text="API Key:").grid(row=2, column=0, sticky='w')
        self.api_key = tk.StringVar(value=self.config.config["step1"]["api_key"])
        ttk.Entry(frame, textvariable=self.api_key, width=60, show="•").grid(row=2, column=1, columnspan=2, sticky='ew')
        
        # Search Configuration
        ttk.Label(frame, text="Search Configuration", font=('Arial', 12, 'bold')).grid(row=3, column=0, columnspan=2, sticky='w', pady=(20, 10))
        
        ttk.Label(frame, text="Region:").grid(row=4, column=0, sticky='w')
        self.region = tk.StringVar(value=self.config.config["step1"]["region"])
        ttk.Entry(frame, textvariable=self.region).grid(row=4, column=1, sticky='w')
        
        ttk.Label(frame, text="Max Results per Search:").grid(row=5, column=0, sticky='w')
        self.max_results = tk.StringVar(value=str(self.config.config["step1"]["max_results"]))
        ttk.Entry(frame, textvariable=self.max_results).grid(row=5, column=1, sticky='w')
        ttk.Label(frame, text="(max search results per individual search query)").grid(row=5, column=2, sticky='w', padx=(5, 0))
        
        ttk.Label(frame, text="Max Number of Searches:").grid(row=6, column=0, sticky='w')
        self.combo_cap = tk.StringVar(value=str(self.config.config["step1"]["serper_combo_cap"]))
        ttk.Entry(frame, textvariable=self.combo_cap).grid(row=6, column=1, sticky='w')
        ttk.Label(frame, text="(max total search combinations to execute)").grid(row=6, column=2, sticky='w', padx=(5, 0))
        
        ttk.Label(frame, text="Re-analysis Period (days):").grid(row=7, column=0, sticky='w')
        self.reanalysis_period = tk.StringVar(value=str(self.config.config["step1"].get("reanalysis_period", 0)))
        ttk.Entry(frame, textvariable=self.reanalysis_period, width=20).grid(row=7, column=1, sticky='w')
        ttk.Label(frame, text="(0 = analyze all, >0 = re-analyze leads older than X days)").grid(row=8, column=1, sticky='w')
        
        # Keyword Boxes
        ttk.Label(frame, text="Keyword Boxes (one keyword from each box per search)", font=('Arial', 12, 'bold')).grid(row=9, column=0, columnspan=2, sticky='w', pady=(20, 10))
        
        # Create 8 keyword boxes
        self.keyword_boxes = []
        for i in range(8):
            ttk.Label(frame, text=f"Box {i+1}:").grid(row=10+i, column=0, sticky='nw', padx=(0, 10))
            box = tk.Text(frame, width=50, height=2)
            # Load existing keywords if available
            if "keyword_boxes" in self.config.config["step1"] and i < len(self.config.config["step1"]["keyword_boxes"]):
                box.insert("1.0", self.config.config["step1"]["keyword_boxes"][i])
            elif i == 0 and "serper_set_keywords" in self.config.config["step1"]:
                box.insert("1.0", self.config.config["step1"]["serper_set_keywords"])
            elif i == 1 and "serper_variable_keywords" in self.config.config["step1"]:
                box.insert("1.0", self.config.config["step1"]["serper_variable_keywords"])
            box.grid(row=10+i, column=1, columnspan=2, sticky='ew')
            self.keyword_boxes.append(box)
        
        # Advanced Settings
        ttk.Label(frame, text="Advanced Settings", font=('Arial', 12, 'bold')).grid(row=18, column=0, columnspan=2, sticky='w', pady=(20, 10))
        
        ttk.Label(frame, text="Max Terms per Search:").grid(row=19, column=0, sticky='w')
        self.max_terms = tk.StringVar(value=str(self.config.config["step1"]["serper_max_terms"]))
        ttk.Entry(frame, textvariable=self.max_terms).grid(row=19, column=1, sticky='w')
        
        frame.columnconfigure(1, weight=1)
    
    def setup_step2_tab(self, notebook):
        """Setup Step 2 configuration tab."""
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Step 2: Scraping")
        
        ttk.Label(frame, text="Scraping Configuration", font=('Arial', 12, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 10))
        
        ttk.Label(frame, text="Database Path:").grid(row=1, column=0, sticky='w')
        self.db_path = tk.StringVar(value=self.config.config["step2"]["db_path"])
        ttk.Entry(frame, textvariable=self.db_path, width=50).grid(row=1, column=1, columnspan=2, sticky='ew')
        
        ttk.Label(frame, text="Max Pages per Site:").grid(row=2, column=0, sticky='w')
        self.max_pages = tk.StringVar(value=str(self.config.config["step2"]["max_pages_per_site"]))
        ttk.Entry(frame, textvariable=self.max_pages).grid(row=2, column=1, sticky='w')
        
        ttk.Label(frame, text="Max Depth:").grid(row=3, column=0, sticky='w')
        self.max_depth = tk.StringVar(value=str(self.config.config["step2"]["max_depth"]))
        ttk.Entry(frame, textvariable=self.max_depth).grid(row=3, column=1, sticky='w')
        
        ttk.Label(frame, text="Global Concurrency:").grid(row=4, column=0, sticky='w')
        self.global_concurrency = tk.StringVar(value=str(self.config.config["step2"]["global_concurrency"]))
        ttk.Entry(frame, textvariable=self.global_concurrency).grid(row=4, column=1, sticky='w')
        
        ttk.Label(frame, text="Per-Domain Concurrency:").grid(row=5, column=0, sticky='w')
        self.per_domain_concurrency = tk.StringVar(value=str(self.config.config["step2"]["per_domain_concurrency"]))
        ttk.Entry(frame, textvariable=self.per_domain_concurrency).grid(row=5, column=1, sticky='w')
        
        ttk.Label(frame, text="Timeout (seconds):").grid(row=6, column=0, sticky='w')
        self.timeout = tk.StringVar(value=str(self.config.config["step2"]["timeout_sec"]))
        ttk.Entry(frame, textvariable=self.timeout).grid(row=6, column=1, sticky='w')
        
        frame.columnconfigure(1, weight=1)
    
    def setup_step3_tab(self, notebook):
        """Setup Step 3 configuration tab."""
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Step 3: Scoring")
        
        # Create scrollable frame
        canvas = tk.Canvas(frame)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Score threshold configuration
        ttk.Label(scrollable_frame, text="Score Threshold Configuration", font=('Arial', 12, 'bold')).grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 10))
        
        # Threshold type selection
        ttk.Label(scrollable_frame, text="Threshold Type:").grid(row=1, column=0, sticky='w')
        self.threshold_type = tk.StringVar(value=self.config.config["step3"].get("threshold_type", "score"))
        ttk.Radiobutton(scrollable_frame, text="Score Threshold", variable=self.threshold_type, value="score").grid(row=1, column=1, sticky='w')
        ttk.Radiobutton(scrollable_frame, text="% of Leads", variable=self.threshold_type, value="percentage").grid(row=1, column=2, sticky='w')
        ttk.Radiobutton(scrollable_frame, text="# of Leads", variable=self.threshold_type, value="count").grid(row=1, column=3, sticky='w')
        
        # Threshold value
        ttk.Label(scrollable_frame, text="Threshold Value:").grid(row=2, column=0, sticky='w')
        self.threshold_value = tk.StringVar(value=str(self.config.config["step3"].get("threshold_value", self.config.config["step3"].get("score_threshold", 75))))
        ttk.Entry(scrollable_frame, textvariable=self.threshold_value, width=20).grid(row=2, column=1, sticky='w')
        
        # Positive factors
        ttk.Label(scrollable_frame, text="Positive Factors", font=('Arial', 12, 'bold')).grid(row=3, column=0, columnspan=4, sticky='w', pady=(20, 10))
        
        # Headers for positive factors
        ttk.Label(scrollable_frame, text="Name").grid(row=4, column=0, sticky='w', padx=5)
        ttk.Label(scrollable_frame, text="Weight").grid(row=4, column=1, sticky='w', padx=5)
        ttk.Label(scrollable_frame, text="Sensitivity").grid(row=4, column=2, sticky='w', padx=5)
        ttk.Label(scrollable_frame, text="Keywords").grid(row=4, column=3, sticky='w', padx=5)
        
        # Create 8 positive factor fields
        self.positive_factors = []
        for i in range(8):
            factor_data = self.config.config["step3"].get("positive_factors", [])
            if i < len(factor_data):
                name = factor_data[i].get("name", f"Factor {i+1}")
                weight = factor_data[i].get("weight", 100)
                sensitivity = factor_data[i].get("sensitivity", 1)
                keywords = factor_data[i].get("keywords", "")
            else:
                name = f"Factor {i+1}"
                weight = 100
                sensitivity = 1
                keywords = ""
            
            row = 5 + i
            name_var = tk.StringVar(value=name)
            weight_var = tk.StringVar(value=str(weight))
            sensitivity_var = tk.StringVar(value=str(sensitivity))
            keywords_var = tk.StringVar(value=keywords)
            
            ttk.Entry(scrollable_frame, textvariable=name_var, width=15).grid(row=row, column=0, sticky='w', padx=5)
            ttk.Entry(scrollable_frame, textvariable=weight_var, width=10).grid(row=row, column=1, sticky='w', padx=5)
            ttk.Entry(scrollable_frame, textvariable=sensitivity_var, width=10).grid(row=row, column=2, sticky='w', padx=5)
            ttk.Entry(scrollable_frame, textvariable=keywords_var, width=40).grid(row=row, column=3, sticky='w', padx=5)
            
            self.positive_factors.append({
                "name": name_var,
                "weight": weight_var,
                "sensitivity": sensitivity_var,
                "keywords": keywords_var
            })
        
        # Negative factors
        ttk.Label(scrollable_frame, text="Negative Factors", font=('Arial', 12, 'bold')).grid(row=13, column=0, columnspan=4, sticky='w', pady=(20, 10))
        
        # Headers for negative factors
        ttk.Label(scrollable_frame, text="Name").grid(row=14, column=0, sticky='w', padx=5)
        ttk.Label(scrollable_frame, text="Weight").grid(row=14, column=1, sticky='w', padx=5)
        ttk.Label(scrollable_frame, text="Sensitivity").grid(row=14, column=2, sticky='w', padx=5)
        ttk.Label(scrollable_frame, text="Keywords").grid(row=14, column=3, sticky='w', padx=5)
        
        # Create 8 negative factor fields
        self.negative_factors = []
        for i in range(8):
            factor_data = self.config.config["step3"].get("negative_factors", [])
            if i < len(factor_data):
                name = factor_data[i].get("name", f"Disqualifier {i+1}")
                weight = factor_data[i].get("weight", 100)
                sensitivity = factor_data[i].get("sensitivity", 1)
                keywords = factor_data[i].get("keywords", "")
            else:
                name = f"Disqualifier {i+1}"
                weight = 100
                sensitivity = 1
                keywords = ""
            
            row = 15 + i
            name_var = tk.StringVar(value=name)
            weight_var = tk.StringVar(value=str(weight))
            sensitivity_var = tk.StringVar(value=str(sensitivity))
            keywords_var = tk.StringVar(value=keywords)
            
            ttk.Entry(scrollable_frame, textvariable=name_var, width=15).grid(row=row, column=0, sticky='w', padx=5)
            ttk.Entry(scrollable_frame, textvariable=weight_var, width=10).grid(row=row, column=1, sticky='w', padx=5)
            ttk.Entry(scrollable_frame, textvariable=sensitivity_var, width=10).grid(row=row, column=2, sticky='w', padx=5)
            ttk.Entry(scrollable_frame, textvariable=keywords_var, width=40).grid(row=row, column=3, sticky='w', padx=5)
            
            self.negative_factors.append({
                "name": name_var,
                "weight": weight_var,
                "sensitivity": sensitivity_var,
                "keywords": keywords_var
            })
        
        # Pack canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        frame.columnconfigure(0, weight=1)
    
    def setup_step4_tab(self, notebook):
        """Setup Step 4 configuration tab."""
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Step 4: AI Analysis")
        
        ttk.Label(frame, text="AI Analysis Configuration", font=('Arial', 12, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 10))
        
        ttk.Label(frame, text="AI Provider:").grid(row=1, column=0, sticky='w')
        self.ai_provider = tk.StringVar(value=self.config.config["step4"].get("provider_choice", "claude"))
        ttk.Radiobutton(frame, text="Claude (Anthropic)", variable=self.ai_provider, value="claude").grid(row=1, column=1, sticky='w')
        ttk.Radiobutton(frame, text="ChatGPT (OpenAI)", variable=self.ai_provider, value="openai").grid(row=1, column=2, sticky='w')
        
        ttk.Label(frame, text="AI Model:").grid(row=2, column=0, sticky='w')
        self.ai_model_choice = tk.StringVar(value=self.config.config["step4"].get("model_choice", "best"))
        self.fastest_label = ttk.Radiobutton(frame, text="Fastest", variable=self.ai_model_choice, value="fastest")
        self.fastest_label.grid(row=2, column=1, sticky='w')
        self.best_label = ttk.Radiobutton(frame, text="Best", variable=self.ai_model_choice, value="best")
        self.best_label.grid(row=2, column=2, sticky='w')
        
        ttk.Label(frame, text="API Key:").grid(row=3, column=0, sticky='w')
        self.ai_api_key = tk.StringVar(value=self.config.config["step4"]["api_key"])
        ttk.Entry(frame, textvariable=self.ai_api_key, width=60, show="•").grid(row=3, column=1, columnspan=2, sticky='ew')
        
        ttk.Label(frame, text="Credit Limit ($):").grid(row=4, column=0, sticky='w')
        self.credit_limit = tk.StringVar(value=str(self.config.config["step4"].get("credit_limit", "50")))
        ttk.Entry(frame, textvariable=self.credit_limit).grid(row=4, column=1, sticky='w')
        
        # Rate limiting info
        rate_info = ttk.Label(frame, text="⚡ Auto-adaptive rate limiting: System will find fastest speed automatically", 
                              font=('Arial', 9), foreground='blue')
        rate_info.grid(row=5, column=0, columnspan=3, sticky='w', pady=(5, 0))
        
        # Model descriptions
        self.model_info = ttk.Label(frame, text="", font=('Arial', 9), foreground='gray')
        self.model_info.grid(row=6, column=0, columnspan=3, sticky='w', pady=(10, 0))
        
        # Update model descriptions when provider changes
        self.update_model_descriptions()
        self.ai_provider.trace('w', lambda *args: self.update_model_descriptions())
        
        # Custom AI Prompt Configuration
        ttk.Label(frame, text="AI Prompt Configuration", font=('Arial', 12, 'bold')).grid(row=7, column=0, columnspan=3, sticky='w', pady=(20, 10))
        
        # Explanation text box
        ttk.Label(frame, text="Explanation of what makes a good lead:").grid(row=8, column=0, sticky='nw', padx=(0, 10))
        explanation_frame = ttk.Frame(frame)
        explanation_frame.grid(row=8, column=1, columnspan=2, sticky='ew', pady=(0, 10))
        
        self.ai_explanation = tk.Text(explanation_frame, width=60, height=6, wrap='word')
        explanation_scrollbar = ttk.Scrollbar(explanation_frame, orient="vertical", command=self.ai_explanation.yview)
        self.ai_explanation.configure(yscrollcommand=explanation_scrollbar.set)
        
        # Load existing explanation if available
        existing_explanation = self.config.config["step4"].get("custom_explanation", "")
        if existing_explanation:
            self.ai_explanation.insert("1.0", existing_explanation)
        
        self.ai_explanation.pack(side='left', fill='both', expand=True)
        explanation_scrollbar.pack(side='right', fill='y')
        
        # Examples folder upload
        examples_label_frame = ttk.Frame(frame)
        examples_label_frame.grid(row=9, column=0, columnspan=3, sticky='ew', pady=(0, 10))
        
        ttk.Label(examples_label_frame, text="Examples folder (good leads):").grid(row=0, column=0, sticky='w')
        
        self.examples_folder_path = tk.StringVar(value=self.config.config["step4"].get("examples_folder", ""))
        self.examples_folder_entry = ttk.Entry(examples_label_frame, textvariable=self.examples_folder_path, width=50)
        self.examples_folder_entry.grid(row=0, column=1, sticky='ew', padx=(10, 5))
        
        ttk.Button(examples_label_frame, text="Browse...", command=self.browse_examples_folder).grid(row=0, column=2, sticky='w')
        
        examples_label_frame.columnconfigure(1, weight=1)
        
        ttk.Label(frame, text="Supported formats: .txt, .md, .html, .csv, .docx, .pdf, .rtf", 
                 font=('Arial', 8), foreground='gray').grid(row=10, column=0, columnspan=3, sticky='w', padx=(0, 0))
        
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(8, weight=1)
    
    def update_model_descriptions(self):
        """Update model descriptions based on selected provider."""
        provider = self.ai_provider.get()
        if provider == "claude":
            self.fastest_label.config(text="Fastest (Claude Haiku)")
            self.best_label.config(text="Best (Claude Sonnet)")
            self.model_info.config(text="Fastest: Claude Haiku (faster, cheaper)\nBest: Claude Sonnet (higher quality)")
        else:  # openai
            self.fastest_label.config(text="Fastest (GPT-3.5)")
            self.best_label.config(text="Best (GPT-4)")
            self.model_info.config(text="Fastest: GPT-3.5 Turbo (faster, cheaper)\nBest: GPT-4 (higher quality)")
    
    def browse_examples_folder(self):
        """Open folder browser for examples folder."""
        folder = filedialog.askdirectory(title="Select folder containing example good leads")
        if folder:
            self.examples_folder_path.set(folder)
    
    def setup_control_tab(self, notebook):
        """Setup control tab for running the pipeline."""
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Run Pipeline")
        
        # Store reference to control frame for adding button later
        self.control_frame = frame
        
        ttk.Label(frame, text="Lead Generation Pipeline", font=('Arial', 14, 'bold')).grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        # Step selection
        ttk.Label(frame, text="Select Steps to Run:", font=('Arial', 12, 'bold')).grid(row=1, column=0, columnspan=3, sticky='w', pady=(0, 10))
        
        self.run_step1 = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="Step 1: Website Discovery", variable=self.run_step1).grid(row=2, column=0, sticky='w', padx=20)
        
        self.run_step2 = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="Step 2: Website Scraping", variable=self.run_step2).grid(row=3, column=0, sticky='w', padx=20)
        
        self.run_step3 = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="Step 3: Factor-based Scoring", variable=self.run_step3).grid(row=4, column=0, sticky='w', padx=20)
        
        self.run_step4 = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="Step 4: AI Analysis", variable=self.run_step4).grid(row=5, column=0, sticky='w', padx=20)
        
        # Control buttons
        ttk.Label(frame, text="", font=('Arial', 8)).grid(row=6, column=0)  # Spacer
        
        ttk.Button(frame, text="Save Configuration", command=self.save_config).grid(row=7, column=0, padx=10, pady=10)
        ttk.Button(frame, text="Load Configuration", command=self.load_config).grid(row=7, column=1, padx=10, pady=10)
        ttk.Button(frame, text="Run Selected Steps", command=self.run_pipeline, style='Accent.TButton').grid(row=7, column=2, padx=10, pady=10)
        
        # Progress area
        ttk.Label(frame, text="Progress:", font=('Arial', 12, 'bold')).grid(row=8, column=0, columnspan=3, sticky='w', pady=(20, 5))
        
        self.progress_text = tk.Text(frame, width=80, height=15, wrap='word')
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.progress_text.yview)
        self.progress_text.configure(yscrollcommand=scrollbar.set)
        
        self.progress_text.grid(row=9, column=0, columnspan=2, sticky='nsew', padx=(0, 5))
        scrollbar.grid(row=9, column=2, sticky='ns')
        
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(9, weight=1)
    
    def save_config(self):
        """Save current configuration."""
        # Update config with current values
        self.config.config["step1"]["api_choice"] = self.api_choice.get()
        self.config.config["step1"]["api_key"] = self.api_key.get()
        self.config.config["step1"]["region"] = self.region.get()
        self.config.config["step1"]["max_results"] = int(self.max_results.get())
        self.config.config["step1"]["reanalysis_period"] = int(self.reanalysis_period.get())
        
        # Save keyword boxes
        keyword_boxes_data = []
        for i, box in enumerate(self.keyword_boxes):
            keywords = box.get("1.0", "end").strip()
            keyword_boxes_data.append(keywords)
        self.config.config["step1"]["keyword_boxes"] = keyword_boxes_data
        
        self.config.config["step1"]["serper_combo_cap"] = int(self.combo_cap.get())
        self.config.config["step1"]["serper_max_terms"] = int(self.max_terms.get())
        
        self.config.config["step2"]["db_path"] = self.db_path.get()
        self.config.config["step2"]["max_pages_per_site"] = int(self.max_pages.get())
        self.config.config["step2"]["max_depth"] = int(self.max_depth.get())
        self.config.config["step2"]["global_concurrency"] = int(self.global_concurrency.get())
        self.config.config["step2"]["per_domain_concurrency"] = int(self.per_domain_concurrency.get())
        self.config.config["step2"]["timeout_sec"] = int(self.timeout.get())
        
        # Save threshold configuration
        self.config.config["step3"]["threshold_type"] = self.threshold_type.get()
        self.config.config["step3"]["threshold_value"] = self.threshold_value.get()
        
        # Save positive factors
        positive_factors = []
        for factor in self.positive_factors:
            if factor["name"].get().strip():
                positive_factors.append({
                    "name": factor["name"].get().strip(),
                    "weight": int(factor["weight"].get() or 0),
                    "sensitivity": int(factor["sensitivity"].get() or 1),
                    "keywords": factor["keywords"].get().strip()
                })
        self.config.config["step3"]["positive_factors"] = positive_factors
        
        # Save negative factors
        negative_factors = []
        for factor in self.negative_factors:
            if factor["name"].get().strip():
                negative_factors.append({
                    "name": factor["name"].get().strip(),
                    "weight": int(factor["weight"].get() or 0),
                    "sensitivity": int(factor["sensitivity"].get() or 1),
                    "keywords": factor["keywords"].get().strip()
                })
        self.config.config["step3"]["negative_factors"] = negative_factors
        
        self.config.config["step4"]["provider_choice"] = self.ai_provider.get()
        self.config.config["step4"]["model_choice"] = self.ai_model_choice.get()
        self.config.config["step4"]["api_key"] = self.ai_api_key.get()
        
        # Set model and provider based on choices
        provider = self.ai_provider.get()
        model_choice = self.ai_model_choice.get()
        
        if provider == "claude":
            self.config.config["step4"]["api_provider"] = "claude"
            if model_choice == "fastest":
                self.config.config["step4"]["model"] = "claude-3-haiku-20240307"
            else:  # best
                self.config.config["step4"]["model"] = "claude-3-5-sonnet-20241022"
        else:  # openai
            self.config.config["step4"]["api_provider"] = "openai"
            if model_choice == "fastest":
                self.config.config["step4"]["model"] = "gpt-3.5-turbo"
            else:  # best
                self.config.config["step4"]["model"] = "gpt-4"
        
        # Set max_tokens based on model choice
        if self.ai_model_choice.get() == "fastest":
            self.config.config["step4"]["max_tokens"] = 2000  # Haiku works well with shorter responses
        else:  # best
            self.config.config["step4"]["max_tokens"] = 4000  # Sonnet can handle longer responses
        
        self.config.config["step4"]["credit_limit"] = float(self.credit_limit.get())
        
        # Save custom explanation and examples folder
        self.config.config["step4"]["custom_explanation"] = self.ai_explanation.get("1.0", tk.END).strip()
        self.config.config["step4"]["examples_folder"] = self.examples_folder_path.get().strip()
        
        self.config.save_config()
        messagebox.showinfo("Success", "Configuration saved successfully!")
    
    def load_config(self):
        """Load configuration from file."""
        self.config = UnifiedConfig()
        messagebox.showinfo("Success", "Configuration loaded successfully!")
        # Refresh GUI with loaded values
        self.root.destroy()
        self.__init__()
    
    def log_progress(self, message):
        """Log progress to the text area."""
        self.progress_text.insert(tk.END, f"{datetime.now().strftime('%H:%M:%S')} - {message}\n")
        self.progress_text.see(tk.END)
        self.root.update()
    
    def run_pipeline(self):
        """Run the selected pipeline steps."""
        self.save_config()  # Save current configuration
        
        # Clear progress area
        self.progress_text.delete(1.0, tk.END)
        
        # Track output files
        output_files = []
        import glob
        
        try:
            if self.run_step1.get():
                discovery = WebsiteDiscovery(self.config, progress_callback=self.log_progress)
                success = asyncio.run(discovery.run_discovery())
                if not success:
                    self.log_progress("ERROR: Step 1 failed")
                    messagebox.showerror("Error", "Step 1 (Website Discovery) failed. Check the log for details.")
                    return
                self.log_progress("✓ Step 1 completed successfully")
                # Find most recent Step 1 output file
                step1_files = glob.glob("data/leads_raw_*.csv")
                if step1_files:
                    step1_file = max(step1_files, key=os.path.getmtime)
                    output_files.append(f"Step 1: {step1_file}")
            
            if self.run_step2.get():
                self.log_progress("Starting Step 2: Website Scraping")
                scraper = WebsiteScraper(self.config)
                success = asyncio.run(scraper.run_scraping())
                if not success:
                    self.log_progress("ERROR: Step 2 failed")
                    return
                self.log_progress("Step 2 completed successfully")
                # Step 2 saves to: data/webcrawl.db
                step2_file = self.config.config["step2"]["db_path"]
                if os.path.exists(step2_file):
                    output_files.append(f"Step 2: {step2_file}")
            
            if self.run_step3.get():
                self.log_progress("Starting Step 3: Factor-based Scoring")
                scorer = FactorScorer(self.config)
                success = scorer.run_scoring()
                if not success:
                    self.log_progress("ERROR: Step 3 failed")
                    return
                self.log_progress("Step 3 completed successfully")
                # Find most recent Step 3 output file
                step3_files = glob.glob("data/scoring_results_*.csv")
                if step3_files:
                    step3_file = max(step3_files, key=os.path.getmtime)
                    output_files.append(f"Step 3: {step3_file}")
            
            if self.run_step4.get():
                self.log_progress("Starting Step 4: AI Analysis")
                analyzer = AIAnalyzer(self.config, progress_callback=self.log_progress)
                success = analyzer.run_ai_analysis()
                if not success:
                    self.log_progress("ERROR: Step 4 failed")
                    return
                self.log_progress("Step 4 completed successfully")
                # Find most recent Step 4 output file
                step4_files = glob.glob("data/ai_analysis_results_*.csv")
                if step4_files:
                    step4_file = max(step4_files, key=os.path.getmtime)
                    output_files.append(f"Step 4: {step4_file}")
            
            self.log_progress("🎉 All selected steps completed successfully!")
            
            # Display output files
            if output_files:
                output_text = "Output saved to:\n" + "\n".join(output_files)
                # Add or update output text field
                if hasattr(self, 'output_label'):
                    self.output_label.config(text=output_text)
                else:
                    self.output_label = ttk.Label(self.control_frame, text=output_text, font=('Arial', 10), foreground='green')
                    self.output_label.grid(row=10, column=0, columnspan=3, pady=10, padx=10, sticky='w')
            
            # Add button to view output (only if not already added)
            if not hasattr(self, 'view_leads_button'):
                self.view_leads_button = ttk.Button(self.control_frame, text="View All Leads", command=self.view_all_leads, style='Accent.TButton')
                self.view_leads_button.grid(row=11, column=0, columnspan=3, pady=10)
            
        except Exception as e:
            self.log_progress(f"ERROR: {str(e)}")
            messagebox.showerror("Error", f"Pipeline failed: {str(e)}")
    
    def view_all_leads(self):
        """Open a window showing all leads sorted by stage and score."""
        logger = ComprehensiveLogger()
        python_threshold = self.config.config.get("step3", {}).get("score_threshold", 75.0)
        
        leads = logger.get_all_leads_sorted(python_threshold)
        
        # Create new window
        view_window = tk.Toplevel(self.root)
        view_window.title("All Leads - Sorted by Stage and Score")
        view_window.geometry("1000x700")
        
        # Create frame with scrollbar
        main_frame = ttk.Frame(view_window)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Header
        header_label = ttk.Label(main_frame, text=f"Total Leads: {len(leads)}", font=('Arial', 12, 'bold'))
        header_label.pack(pady=(0, 10))
        
        # Create treeview with scrollbar
        tree_frame = ttk.Frame(main_frame)
        tree_frame.pack(fill='both', expand=True)
        
        columns = ('Stage', 'Python Score', 'AI Score', 'Good Lead', 'URL', 'Notes')
        tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=25)
        
        # Define column widths and headings
        tree.heading('Stage', text='Stage')
        tree.heading('Python Score', text='Python Score')
        tree.heading('AI Score', text='AI Score')
        tree.heading('Good Lead', text='Good Lead')
        tree.heading('URL', text='URL')
        tree.heading('Notes', text='Notes')
        
        tree.column('Stage', width=100)
        tree.column('Python Score', width=100)
        tree.column('AI Score', width=100)
        tree.column('Good Lead', width=90)
        tree.column('URL', width=300)
        tree.column('Notes', width=300)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        # Pack tree and scrollbar
        tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # Populate tree
        # First, load all data from database in one query for efficiency
        conn = sqlite3.connect(logger.comprehensive_db)
        cursor = conn.execute("SELECT url, score, ai_analysis_result FROM leads_comprehensive")
        db_data = {}
        for row in cursor.fetchall():
            url_key, python_score, ai_result_json = row
            db_data[url_key] = {
                'python_score': python_score,
                'ai_result': ai_result_json
            }
        conn.close()
        
        for lead in leads:
            stage = lead.get('stage', 'unknown')
            url = lead.get('url', '')
            
            # Try to find data using URL variations (like the logging functions do)
            python_score_str = "N/A"
            ai_score_str = "N/A"
            good_lead_str = "N/A"
            notes = ""
            
            # Try exact match first, then variations
            url_variations = [
                url,
                url.replace("https://", "").replace("http://", ""),
                f"https://{url}" if not url.startswith("http") else url,
                url.replace("https://", "http://")
            ]
            
            db_record = None
            for variant in url_variations:
                if variant in db_data:
                    db_record = db_data[variant]
                    break
            
            if db_record:
                # Extract Python score (from Step 3)
                if db_record['python_score'] is not None:
                    python_score_str = f"{db_record['python_score']:.2f}"
                
                # Extract AI score and good_lead status from AI analysis result
                if db_record['ai_result']:
                    try:
                        ai_data = json.loads(db_record['ai_result'])
                        match_score = ai_data.get('match_score', None)
                        if match_score is not None:
                            ai_score_str = f"{match_score:.1f}"
                        is_good = ai_data.get('is_good_lead', None)
                        if is_good is not None:
                            good_lead_str = "Yes" if is_good else "No"
                        
                        # Build notes with AI analysis details
                        business_type = ai_data.get('business_type', 'N/A')
                        confidence = ai_data.get('confidence', 'N/A')
                        reasoning = ai_data.get('reasoning', '')
                        notes_parts = [f"Type: {business_type}", f"Confidence: {confidence}"]
                        if reasoning:
                            # Truncate reasoning if too long
                            reasoning_short = reasoning[:150] + "..." if len(reasoning) > 150 else reasoning
                            notes_parts.append(f"Reasoning: {reasoning_short}")
                        notes = " | ".join(notes_parts)
                    except Exception as e:
                        pass
            
            # If no AI data but has Python score, set notes
            if not notes:
                if stage == 'scored':
                    notes = f"Python factor-based scoring"
                elif stage == 'scraped':
                    notes = "Scraped but not yet scored"
                elif stage == 'discovered':
                    notes = "Discovered but not yet scraped"
                else:
                    notes = stage
            
            tree.insert('', 'end', values=(stage, python_score_str, ai_score_str, good_lead_str, url, notes))
        
        # Pack tree frame
        tree_frame.pack(fill='both', expand=True)
        
        # Store tree and leads data for CSV export
        view_window.tree = tree
        view_window.leads_data = leads
        view_window.db_data = db_data
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=10)
        
        # Download CSV button
        download_btn = ttk.Button(button_frame, text="Download as CSV", command=lambda: self.export_leads_to_csv(view_window))
        download_btn.pack(side='left', padx=5)
        
        # Close button
        close_btn = ttk.Button(button_frame, text="Close", command=view_window.destroy)
        close_btn.pack(side='left', padx=5)
    
    def export_leads_to_csv(self, view_window):
        """Export the current leads view to CSV."""
        try:
            # Ask user for save location
            filename = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                title="Save Leads as CSV"
            )
            
            if not filename:
                return
            
            # Get all data from tree
            leads_data = []
            for item in view_window.tree.get_children():
                values = view_window.tree.item(item, 'values')
                leads_data.append({
                    'Stage': values[0],
                    'Python Score': values[1],
                    'AI Score': values[2],
                    'Good Lead': values[3],
                    'URL': values[4],
                    'Notes': values[5]
                })
            
            # Write to CSV
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                if leads_data:
                    writer = csv.DictWriter(f, fieldnames=leads_data[0].keys())
                    writer.writeheader()
                    writer.writerows(leads_data)
            
            messagebox.showinfo("Success", f"Leads exported to {filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export CSV: {str(e)}")
    
    def run(self):
        """Run the GUI application."""
        self.root.mainloop()

# ============================================================
# MAIN ENTRY POINT
# ============================================================

def main():
    """Main entry point for the unified application."""
    print("Unified Lead Generation Tool")
    print("=" * 40)
    print("Starting GUI application...")
    
    try:
        app = InitialPopupGUI()
        app.run()
    except Exception as e:
        print(f"Error starting application: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
