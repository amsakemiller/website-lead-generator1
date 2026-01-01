#!/usr/bin/env python3
"""
Sherpa Lead Generator
=====================

A comprehensive lead generation tool that combines all steps into a single application:
1. Website Discovery (Step 1)
2. Website Scraping (Step 2) 
3. Factor-based Scoring (Step 3)
4. AI Analysis (Step 4)
5. Contact Extraction (Step 5)

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
from datetime import datetime, timezone, timedelta
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
import glob
import subprocess
import shutil

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
# GLOBAL UTILITIES
# ============================================================

def get_next_run_number() -> int:
    """Get the next run number by checking existing run folders."""
    runs_dir = "runs"
    if not os.path.exists(runs_dir):
        return 1
    
    max_num = 0
    for folder in os.listdir(runs_dir):
        if folder.startswith("Run "):
            try:
                # Extract number from "Run X - ..."
                num_str = folder.split(" - ")[0].replace("Run ", "")
                num = int(num_str)
                max_num = max(max_num, num)
            except (ValueError, IndexError):
                pass
    return max_num + 1


def create_run_folder(run_number: int = None) -> Tuple[str, int]:
    """Create a new run folder with unique name.
    Returns: (folder_path, run_number)
    """
    runs_dir = "runs"
    os.makedirs(runs_dir, exist_ok=True)
    
    if run_number is None:
        run_number = get_next_run_number()
    
    # Format: Run # - M/D/YYYY HH:MM:SS
    now = datetime.now()
    date_str = now.strftime("%m-%d-%Y %H-%M-%S")
    folder_name = f"Run {run_number} - {date_str}"
    folder_path = os.path.join(runs_dir, folder_name)
    
    os.makedirs(folder_path, exist_ok=True)
    return folder_path, run_number


def get_all_run_folders() -> List[Dict[str, Any]]:
    """Get all run folders sorted by recency (newest first).
    Returns list of dicts with: folder_path, run_number, date, csv_path, website_count
    """
    runs_dir = "runs"
    if not os.path.exists(runs_dir):
        return []
    
    runs = []
    for folder in os.listdir(runs_dir):
        if not folder.startswith("Run "):
            continue
        
        folder_path = os.path.join(runs_dir, folder)
        if not os.path.isdir(folder_path):
            continue
        
        try:
            # Parse run info
            parts = folder.split(" - ", 1)
            run_number = int(parts[0].replace("Run ", ""))
            date_str = parts[1] if len(parts) > 1 else ""
            
            # Find CSV file
            csv_files = glob.glob(os.path.join(folder_path, "*.csv"))
            csv_path = csv_files[0] if csv_files else None
            
            # Count websites if CSV exists
            website_count = 0
            if csv_path and os.path.exists(csv_path):
                try:
                    df = pd.read_csv(csv_path)
                    website_count = len(df)
                except:
                    pass
            
            # Get folder modification time for sorting
            mtime = os.path.getmtime(folder_path)
            
            runs.append({
                'folder_path': folder_path,
                'folder_name': folder,
                'run_number': run_number,
                'date_str': date_str,
                'csv_path': csv_path,
                'website_count': website_count,
                'mtime': mtime
            })
        except (ValueError, IndexError):
            pass
    
    # Sort by modification time (newest first)
    runs.sort(key=lambda x: x['mtime'], reverse=True)
    return runs


class RunStateTracker:
    """Lightweight tracker for run state that can be serialized/resumed.
    Writes state to a JSON file for minimal overhead.
    """
    
    def __init__(self, run_folder: str):
        self.run_folder = run_folder
        self.state_file = os.path.join(run_folder, "run_state.json")
        self.state = {
            'run_number': 0,
            'start_time': None,
            'last_update': None,
            'current_stage': 0,
            'stage_name': '',
            'completed_stages': [],
            'websites_discovered': 0,
            'websites_scraped': 0,
            'websites_scored': 0,
            'websites_analyzed': 0,
            'websites_with_contacts': 0,
            'current_batch': 0,
            'total_batches': 0,
            'processed_urls': [],  # URLs that have been fully processed
            'pending_urls': [],    # URLs waiting to be processed
            'errors': [],
            'is_complete': False,
            'is_paused': False
        }
        self._load_state()
    
    def _load_state(self):
        """Load state from file if exists."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    saved_state = json.load(f)
                    self.state.update(saved_state)
            except:
                pass
    
    def save_state(self):
        """Save current state to file (lightweight operation)."""
        self.state['last_update'] = datetime.now().isoformat()
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2)
        except:
            pass  # Don't fail run if state save fails
    
    def start_run(self, run_number: int):
        """Initialize a new run."""
        self.state['run_number'] = run_number
        self.state['start_time'] = datetime.now().isoformat()
        self.state['is_complete'] = False
        self.state['is_paused'] = False
        self.save_state()
    
    def update_stage(self, stage: int, name: str, batch: int = 0, total: int = 0):
        """Update current stage progress."""
        self.state['current_stage'] = stage
        self.state['stage_name'] = name
        self.state['current_batch'] = batch
        self.state['total_batches'] = total
        # Save periodically (every 10 batches) to reduce I/O
        if batch % 10 == 0:
            self.save_state()
    
    def complete_stage(self, stage: int):
        """Mark a stage as complete."""
        if stage not in self.state['completed_stages']:
            self.state['completed_stages'].append(stage)
        self.save_state()
    
    def add_processed_url(self, url: str):
        """Mark a URL as fully processed."""
        if url not in self.state['processed_urls']:
            self.state['processed_urls'].append(url)
        if url in self.state['pending_urls']:
            self.state['pending_urls'].remove(url)
    
    def add_pending_urls(self, urls: List[str]):
        """Add URLs to pending list."""
        for url in urls:
            if url not in self.state['pending_urls'] and url not in self.state['processed_urls']:
                self.state['pending_urls'].append(url)
        self.save_state()
    
    def mark_complete(self):
        """Mark the run as complete."""
        self.state['is_complete'] = True
        self.state['is_paused'] = False
        self.save_state()
    
    def pause_run(self):
        """Mark the run as paused."""
        self.state['is_paused'] = True
        self.save_state()
    
    def get_resume_info(self) -> Dict[str, Any]:
        """Get info needed to resume a run."""
        return {
            'current_stage': self.state['current_stage'],
            'pending_urls': self.state['pending_urls'],
            'processed_urls': self.state['processed_urls'],
            'completed_stages': self.state['completed_stages']
        }


def git_commit_config(config_file: str) -> Tuple[bool, str]:
    """Commit config changes to git and push to GitHub.
    Returns: (success: bool, message: str)
    """
    try:
        # Check if git is available and this is a git repo
        result = subprocess.run(['git', 'status'], capture_output=True, text=True, cwd=os.path.dirname(config_file) or '.')
        if result.returncode != 0:
            return False, "Not a git repository"
        
        # Check if there are changes to commit
        result = subprocess.run(['git', 'diff', '--quiet', config_file], capture_output=True, cwd=os.path.dirname(config_file) or '.')
        if result.returncode == 0:
            # No changes to commit
            return True, "No config changes to commit"
        
        # Add the config file
        subprocess.run(['git', 'add', config_file], capture_output=True, cwd=os.path.dirname(config_file) or '.')
        
        # Commit with timestamp
        commit_msg = f"Auto-save config: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        result = subprocess.run(['git', 'commit', '-m', commit_msg], capture_output=True, text=True, cwd=os.path.dirname(config_file) or '.')
        
        if result.returncode != 0:
            return False, f"Commit failed: {result.stderr}"
        
        # Try to push (may fail if no remote configured)
        result = subprocess.run(['git', 'push'], capture_output=True, text=True, cwd=os.path.dirname(config_file) or '.')
        if result.returncode != 0:
            return True, f"Committed locally but push failed: {result.stderr}"
        
        return True, "Config committed and pushed to GitHub"
    except FileNotFoundError:
        return False, "Git not found on system"
    except Exception as e:
        return False, f"Git error: {str(e)}"


def git_pull_updates() -> Tuple[bool, str]:
    """Pull latest updates from GitHub.
    Returns: (success: bool, message: str)
    """
    try:
        # Check if this is a git repo
        result = subprocess.run(['git', 'status'], capture_output=True, text=True)
        if result.returncode != 0:
            return False, "Not a git repository"
        
        # Stash any local changes to config
        subprocess.run(['git', 'stash'], capture_output=True)
        
        # Pull from remote
        result = subprocess.run(['git', 'pull'], capture_output=True, text=True)
        
        # Try to restore stashed changes
        subprocess.run(['git', 'stash', 'pop'], capture_output=True)
        
        if result.returncode != 0:
            return False, f"Pull failed: {result.stderr}"
        
        return True, result.stdout.strip() or "Already up to date"
    except FileNotFoundError:
        return False, "Git not found on system"
    except Exception as e:
        return False, f"Git error: {str(e)}"


def sanitize_for_csv(text: str, separator: str = ";") -> str:
    """
    Global utility to sanitize text for CSV output.
    Replaces commas with semicolons (or custom separator) to prevent CSV parsing issues.
    Also cleans up whitespace.
    """
    if text is None:
        return ""
    text = str(text)
    # Replace commas with separator
    text = text.replace(",", separator)
    # Clean up excessive whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove any remaining problematic characters
    text = text.replace('"', "'").replace('\n', ' ').replace('\r', '')
    return text

# ============================================================
# CONFIGURATION MANAGEMENT
# ============================================================

class UnifiedConfig:
    """Unified configuration management for all steps."""
    
    def __init__(self, config_file: str = "unified_config.json"):
        self.config_file = config_file
        self.default_config = {
            # Master CSV path - single source of truth
            "master_csv_path": "data/leads_master.csv",
            
            # User Inputs - collected during onboarding
            "user_inputs": {
                "business_name": "",
                "website_url": "",
                "product_description": "",
                "price_min": "",
                "price_max": "",
                "ideal_customer": "",
                "company_size": "",
                "geography": "",
                "seniority_levels": "",
                "departments": "",
                "exclusions": "",
                "good_leads": "",
                "search_keywords": "",
                "other_context": "",
                "extract_contacts": True,
                "single_prompt_response": ""  # For single prompt mode
            },
            
            # AI Input Optimization Agent Settings
            "ai_optimization_agent": {
                "enabled": True,
                "prompt": """You are an expert B2B lead generation strategist and data engineer. Your task is to analyze user inputs about their business and ideal customers, then generate the OPTIMAL, COMPLETE search and scoring configuration to find the highest-quality leads.

## YOUR MISSION
Transform the user's business description and ideal customer profile into a precise, actionable lead generation configuration. Every decision should maximize the quality of leads found while minimizing wasted effort on poor matches.

## KEYWORD BOX STRATEGY
The search system works by randomly selecting ONE keyword from each non-empty box and combining them into a search query. Design your boxes strategically:

- **Box 1 (Industry/Vertical)**: Core industry terms (e.g., "e-commerce, DTC brand, online retail")
- **Box 2 (Product/Service)**: What the target companies sell or do (e.g., "software, SaaS, platform")
- **Box 3 (Problem/Need)**: Pain points or challenges (e.g., "scaling challenges, manual processes")  
- **Box 4 (Company Stage/Size)**: Growth signals (e.g., "Series A, Series B, growing, scaling")
- **Box 5 (Technology/Tools)**: Tech stack indicators (e.g., "Salesforce, Shopify, AWS")
- **Box 6 (Activity/Behavior)**: Buying signals (e.g., "hiring, expanding, raised funding")
- **Box 7 (Geographic)**: Location terms if relevant (e.g., "US headquarters, Bay Area")

Create 5-8 boxes with 3-10 keywords each. More keywords per box = more search variety.

## SCORING FACTORS
Create weighted factors that score leads based on keyword matches in their website content:

**Positive Factors** (add points when found):
- Weight 100-300: Higher = more important
- Sensitivity 1-5: How many matches needed for full credit (1=one match gives full points)

**Negative Factors** (subtract points when found):
- Use for competitors, wrong industries, disqualifiers
- Weight 100-300: Higher = stronger exclusion signal
- Sensitivity 1-3: Usually 1 (any match is bad)

## AI SCORING FIELDS
Create 4-8 scoring fields that the AI will evaluate for each lead:

1. **Geographic Fit** (score 0-2): Does the company match geographic requirements?
2. **Funding/Viability** (score 0-10): Is the company well-funded/viable enough to buy?
3. **Business Type** (text): Categorize the company type with options
4. **ICP Match** (score 0-100): Overall match to ideal customer profile

Tailor scoring field prompts to reference the user's specific business and criteria.

## OUTPUT FORMAT
Return ONLY a valid JSON object with this structure:

{
    "keyword_boxes": [
        "keyword1, keyword2, keyword3, keyword4, keyword5",
        "keyword6, keyword7, keyword8",
        "...(5-8 boxes total)"
    ],
    "keyword_box_count": 6,
    "region": "us",
    "max_results_per_search": 100,
    "combo_cap": 300,
    "positive_factors": [
        {"name": "Industry Match", "weight": 200, "sensitivity": 2, "keywords": "industry1, industry2, industry3"},
        {"name": "Size Fit", "weight": 150, "sensitivity": 2, "keywords": "size indicator1, size indicator2"},
        {"name": "Buying Signals", "weight": 100, "sensitivity": 1, "keywords": "signal1, signal2, signal3"}
    ],
    "negative_factors": [
        {"name": "Wrong Industry", "weight": 200, "sensitivity": 1, "keywords": "exclude1, exclude2"},
        {"name": "Competitors", "weight": 300, "sensitivity": 1, "keywords": "competitor1, competitor2"},
        {"name": "Too Small/Wrong Type", "weight": 150, "sensitivity": 1, "keywords": "agency, freelance, consulting"}
    ],
    "scoring_threshold": 70,
    "scoring_fields": [
        {
            "type": "score",
            "title": "Geographic Fit",
            "min": 0,
            "max": 2,
            "prompt": "Score 0 if outside target geography, 1 if uncertain, 2 if clearly within target region.",
            "enabled": true
        },
        {
            "type": "score",
            "title": "Funding/Viability",
            "min": 0,
            "max": 10,
            "prompt": "Score the company's funding level and viability. 0-3 = early/unfunded, 4-6 = moderate funding, 7-10 = well-funded.",
            "enabled": true
        },
        {
            "type": "text",
            "title": "Business Type",
            "allow_unlisted": true,
            "allow_multiple": false,
            "prompt": "Categorize this company's primary business type.",
            "options": ["Option1", "Option2", "Option3", "Other"],
            "enabled": true
        },
        {
            "type": "score",
            "title": "Overall ICP Match",
            "min": 0,
            "max": 100,
            "prompt": "Overall match score for [USER'S SPECIFIC CRITERIA]. Score 80-100 for ideal leads, 60-79 for strong leads, 40-59 for moderate leads, below 40 for poor matches.",
            "enabled": true
        }
    ],
    "seniority_4_titles": "CEO, Founder, Co-Founder, President, Owner, Managing Director",
    "seniority_3_titles": "VP, Vice President, CTO, CMO, CSO, CFO, COO, CBO, Head of, Global Head, Division Head",
    "seniority_2_titles": "Director, Senior Director, Executive Director, Principal, Lead",
    "seniority_1_titles": "Manager, Senior Manager, Coordinator, Analyst, Specialist",
    "fit_4_titles": "titles most relevant to user's sale (customize based on user's target department)",
    "fit_3_titles": "titles with good relevance",
    "fit_2_titles": "titles with moderate relevance",
    "fit_1_titles": "titles with lower relevance",
    "good_leads_domains": "",
    "reasoning": "Brief explanation of your strategic choices and why this configuration will find the best leads for this business"
}

## CRITICAL RULES
1. Output ONLY valid JSON - no markdown, no explanations outside the JSON
2. All keyword strings should be comma-separated within quotes
3. Tailor EVERY scoring field prompt to reference the user's specific business
4. If user provides example customer URLs, extract the domains and put in good_leads_domains
5. Region should be 2-letter country code (us, gb, de, etc.) based on user's geographic requirements
6. combo_cap should be: narrow ICP = 50-150, moderate ICP = 150-350, broad ICP = 350-500
7. scoring_threshold: exploratory = 50-60, targeted = 70-80, very specific = 85+

Be specific, strategic, and thorough. Your configuration directly determines lead quality."""
            },
            
            # Global Performance Settings
            "performance": {
                "ai_batch_size": 5,  # Number of companies to analyze in parallel
                "rate_limiter_success_threshold": 5,  # Consecutive successes before speeding up
                "logging_level": "moderate",  # none, limited, moderate, detailed
                "debug_file_interval": 10,  # Write 1 debug file per N AI calls
                "always_write_debug_files": False,  # Override to write every debug file
                "fuzzy_match_threshold": 85,  # 0-100, set to 100 for exact matching only
            },
            
            # CSV Output Configuration  
            "csv_output": {
                "sanitize_commas": True,  # Replace commas with semicolons in content
                "delimiter": ";",  # Delimiter for separating multiple values in one cell
                "include_failed_domains": True,  # Include failed domains at bottom of CSV
                "include_debug_columns": True,  # Add debug info as rightmost columns
                # Column order configuration (0 = don't include, 1+ = position)
                "column_order": {
                    "url": 1,
                    "company_name": 2,
                    "score": 3,
                    "ai_match_score": 4,
                    "is_good_lead": 5,
                    "business_type": 6,
                    "company_description": 7,
                    "company_email": 8,
                    "contact_1_name": 9,
                    "contact_1_position": 10,
                    "contact_1_email": 11,
                    "contact_1_score": 12,
                    "subdomains_visited": 13,
                    "processing_date": 14,
                    "error_message": 0,  # 0 = don't show (still in debug columns)
                    "pages_crawled": 0,
                    "content_length": 0,
                }
            },
            
            # Step 1: Website Discovery
            "step1": {
                "api_choice": "serper",
                "api_key": "",
                "region": "us",
                "max_results": 100,
                "output_path": "data/leads_raw.csv",
                "request_timeout_seconds": 15,
                "concurrency": 25,
                "verify_domains": True,  # Can be disabled to skip domain verification
                "record_failed_domains": True,  # Record failed domain verifications
                "rate_limit_initial": 0.35,
                "rate_limit_min": 0.05,
                "rate_limit_max": 2.0,
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
                "max_chars_per_page": 50000,
                "max_chars_per_scrape": 200000,
                "respect_robots": True,
                "follow_sitemaps": True,
                "db_path": "data/webcrawl.db",
                # Contact-related keywords get highest priority
                "contact_priority_keywords": "contact, team, about, leadership, management, executives, staff, people, our-team, meet-the-team, who-we-are, about-us, contact-us"
            },
            
            # Step 3: Factor-based Scoring
            "step3": {
                "score_threshold": 75,
                "output_path": "data/analysis_results.csv",
                "threshold_type": "score",  # score, percentage, count
                "threshold_value": "75",
                # Multi-select thresholds (OR logic) - if any is met, lead passes
                "use_score_threshold": True,
                "use_percentage_threshold": False,
                "use_count_threshold": False,
                "percentage_value": 20,
                "count_value": 100,
                "fuzzy_match_threshold": 85,
                # Positive scoring factors (keywords that add points)
                "positive_factors": [
                    {"name": "Industry Match", "weight": 200, "sensitivity": 2, "keywords": ""},
                    {"name": "Size Fit", "weight": 150, "sensitivity": 2, "keywords": ""},
                    {"name": "Buying Signals", "weight": 100, "sensitivity": 1, "keywords": ""}
                ],
                "positive_factor_count": 3,
                # Negative scoring factors (keywords that subtract points)
                "negative_factors": [
                    {"name": "Wrong Industry", "weight": 200, "sensitivity": 1, "keywords": ""},
                    {"name": "Competitors", "weight": 300, "sensitivity": 1, "keywords": ""}
                ],
                "negative_factor_count": 2
            },
            
            # Step 4: AI Analysis
            "step4": {
                "model_choice": "model_1",  # model_1, model_2, model_3, model_4
                "api_provider": "claude",   # claude, openai, gemini
                "api_key": "",
                "gemini_api_key": "",  # Separate key for Gemini
                "model": "claude-sonnet-4-20250514",
                # Claude models (4 options) - cost_per_1k = estimated $ per 1,000 leads analyzed
                "claude_models": [
                    {"name": "Haiku 3.5", "api_id": "claude-3-5-haiku-20241022", "cost_per_1k": 8.40},
                    {"name": "Sonnet 4", "api_id": "claude-sonnet-4-20250514", "cost_per_1k": 31.50},
                    {"name": "Sonnet 3.7", "api_id": "claude-3-7-sonnet-20250219", "cost_per_1k": 31.50},
                    {"name": "Opus 4", "api_id": "claude-opus-4-20250514", "cost_per_1k": 157.50}
                ],
                # OpenAI models (4 options)
                "openai_models": [
                    {"name": "GPT-4o-mini", "api_id": "gpt-4o-mini", "cost_per_1k": 1.40},
                    {"name": "GPT-4o", "api_id": "gpt-4o", "cost_per_1k": 22.50},
                    {"name": "GPT-4.1", "api_id": "gpt-4.1", "cost_per_1k": 30.00},
                    {"name": "GPT-4.1-mini", "api_id": "gpt-4.1-mini", "cost_per_1k": 7.00}
                ],
                # Gemini models (4 options)
                "gemini_models": [
                    {"name": "Flash 2.5 Lite", "api_id": "gemini-2.5-flash-preview-05-20", "cost_per_1k": 0.70},
                    {"name": "Flash 2.5", "api_id": "gemini-2.5-flash-preview-04-17", "cost_per_1k": 1.40},
                    {"name": "Pro 2.5", "api_id": "gemini-2.5-pro-preview-05-06", "cost_per_1k": 25.00},
                    {"name": "Pro 1.5", "api_id": "gemini-1.5-pro", "cost_per_1k": 17.50}
                ],
                "max_tokens": 4000,
                "credit_limit": 50.0,
                "max_retries": 3,
                "log_level": "INFO",
                "batch_size": 5,
                "checkpoint_interval": 5,
                "results_file": "data/ai_analysis_results.csv",
                "custom_explanation": "",
                "company_description_prompt": "",
                # Good leads reference configuration
                "good_leads_domains": "",  # Comma-separated list of domains to scrape as good examples
                "good_leads_max_pages_per_site": 12,  # Max pages to crawl per good lead site
                "good_leads_max_depth": 2,  # Max crawl depth for good lead sites
                "good_leads_max_chars_per_page": 50000,  # Max chars per page for good leads
                "good_leads_aggregate_char_cap": 120000,  # Max total chars per good lead site
                "good_leads_summarization_prompt": "Analyze these websites of ideal customer companies. For each, summarize: what type of business they are, their main products/services, their location/headquarters, their company size/funding stage, and what makes them an ideal customer. Remove marketing fluff and focus on concrete facts. This summary will be used as reference examples for identifying similar good leads.",
                "good_leads_max_summary_chars": 8000,  # Max chars for total good leads summary
                "good_leads_summary_cache": "",  # Cached summary from last run
                # Performance settings
                "async_batch_size": 5,  # Number of parallel AI requests
                "max_content_chars": 12000,  # Max chars to send to AI per company
                "skip_if_processed_within_days": 30,  # Skip reprocessing if done within N days (0=always process)
                "scoring_field_count": 20,  # Number of scoring fields to show
                # Multi-score fields (configurable count)
                # Each field is either "score" type or "text" type
                # Score: {type: "score", title: str, min: int, max: int, prompt: str, enabled: bool}
                # Text: {type: "text", title: str, allow_unlisted: bool, allow_multiple: bool, prompt: str, options: [str], enabled: bool}
                "scoring_fields": [
                    {
                        "type": "score",
                        "title": "US-Based",
                        "min": 0,
                        "max": 2,
                        "prompt": "Assign a score of 0 if you are certain this business is not based in the US and has no US operations. Assign a score of 1 if you are unsure whether the business is US-based OR if the business is not US-headquartered but has confirmed US operations. Assign a score of 2 if you are confident this business is headquartered in the United States.",
                        "enabled": True
                    },
                    {
                        "type": "score",
                        "title": "Well-Funded",
                        "min": 0,
                        "max": 10,
                        "prompt": "Assign a funding score from 0-10. Consider: recent funding rounds (Series A/B/C); grant awards; products already in market; partnerships with major companies; significant hiring; professional website quality. Score 0 if business appears defunct or unfunded. Score 1-3 for early-stage with minimal funding evidence. Score 4-6 for moderate funding indicators. Score 7-10 for well-funded companies with clear evidence of substantial capital.",
                        "enabled": True
                    },
                    {
                        "type": "text",
                        "title": "Business Type",
                        "allow_unlisted": True,
                        "allow_multiple": False,
                        "prompt": "Categorize this business into one primary type based on their core offering.",
                        "options": ["Medical Device Manufacturer", "CRO (Contract Research Organization)", "Biotech/Pharma", "Consulting/Services", "Academic/Research Institution", "Software/Digital Health", "Diagnostics", "Other Healthcare"],
                        "enabled": True
                    },
                    {
                        "type": "text",
                        "title": "Target Organ/System",
                        "allow_unlisted": True,
                        "allow_multiple": True,
                        "prompt": "Identify which organs or body systems this company's products/services target. Select all that apply.",
                        "options": ["Liver", "Pancreas", "Heart", "Lung", "Brain/CNS", "Kidney", "GI Tract", "Skin", "Bone/Musculoskeletal", "Blood/Hematology"],
                        "enabled": True
                    },
                    {
                        "type": "score",
                        "title": "Development Stage",
                        "min": 0,
                        "max": 5,
                        "prompt": "Assess the company's product development stage. Score 0 if no clear product in development. Score 1 for concept/early R&D stage. Score 2 for preclinical development (ideal for large animal testing). Score 3 for early clinical trials (Phase I/II). Score 4 for late clinical trials (Phase III). Score 5 for products already FDA-cleared/approved and on market.",
                        "enabled": True
                    },
                    {
                        "type": "text",
                        "title": "Therapeutic Focus",
                        "allow_unlisted": True,
                        "allow_multiple": True,
                        "prompt": "Identify the therapeutic areas this company focuses on.",
                        "options": ["Oncology/Cancer", "Cardiovascular", "Immunology", "Infectious Disease", "Neurology", "Metabolic/Diabetes", "Rare Disease", "Regenerative Medicine"],
                        "enabled": True
                    },
                    {
                        "type": "score",
                        "title": "Preclinical Fit",
                        "min": 0,
                        "max": 10,
                        "prompt": "Score how well this company fits as a prospect for preclinical large animal (porcine) testing services. Consider: Are they at the right development stage (preclinical)? Do they have a medical device that would benefit from pig model testing? Are they well-funded enough to afford preclinical studies? Score 0-3 for poor fit; 4-6 for moderate fit; 7-10 for excellent fit.",
                        "enabled": True
                    },
                    {
                        "type": "score",
                        "title": "Overall Score",
                        "min": 0,
                        "max": 100,
                        "prompt": "Provide an overall lead quality score from 0-100. This should reflect the total assessment of this company as a potential customer for preclinical medical device testing services. Consider all factors: US presence; funding level; appropriate development stage (preclinical ideal); oncology/cancer focus; medical device vs pharma. Score 80-100 for ideal leads; 60-79 for strong leads; 40-59 for moderate leads; 20-39 for weak leads; 0-19 for non-fits.",
                        "enabled": True
                    }
                ],
            },
            
            # Step 5: Contact Extraction
            "step5": {
                "enabled": True,
                "contact_extraction_prompt": """Extract contact information from this website content. Look for:
1. A general company contact email (like info@, contact@, hello@, sales@)
2. Individual team members/employees with their contact details

For each person found, extract:
- Full name
- Position/Title  
- Email address
- Phone number (if available)

Focus on finding decision-makers, executives, and key personnel.""",
                "contact_scoring_prompt": """Score this contact based on their title/position for B2B sales outreach in the healthcare/medical device/preclinical research industry.

SENIORITY SCORE (1-4):
- 4 = Highest: CEO, Founder, Co-Founder, Chairman, President, Owner (top decision-makers)
- 3 = High: Chief Officers (CSO, CTO, CMO, COO), Vice President, EVP, SVP, Global Head, Head of Department
- 2 = Medium: Director, Senior Director, Executive Director, Scientific Advisor, Senior Scientist
- 1 = Lower: Associate Director, Manager, Scientist, Principal Investigator, Group Leader, Data Scientist

FIT SCORE (1-4) - How relevant is this person for preclinical/translational research sales:
- 4 = Excellent fit: Title contains "Preclinical", "Translational", "Discovery" combined with seniority, OR is a Founder/CEO/President (they oversee preclinical teams)
- 3 = Good fit: Scientific/Research leadership roles (CSO, CTO, VP Research, Head of R&D), titles mentioning "Scientific", "Research", "In Vivo", "In Vitro"
- 2 = Moderate fit: General scientific roles with oncology/cancer/immunology focus, Drug Development, Medical Affairs, Pharmacology
- 1 = Lower fit: Business Development, Operations, Economic, Project Management, pure administrative roles, general Director/Manager without scientific context

NOTE: Most senior people (CEO, Founder, etc.) automatically get highest "fit" score since preclinical teams report to them.""",
                "max_contacts": 5,
                # Configurable title keywords for scoring (with synonyms)
                "seniority_4_titles": "CEO, Founder, Co-Founder, Chairman, President, Owner, Chief Executive Officer, Managing Director, Principal, Proprietor",
                "seniority_3_titles": "CSO, CTO, CMO, COO, CFO, CBO, Chief Scientific Officer, Chief Technology Officer, Chief Medical Officer, Chief Operating Officer, Vice President, VP, EVP, SVP, Executive Vice President, Senior Vice President, Global Head, Head of, Division Head, Department Head",
                "seniority_2_titles": "Director, Senior Director, Executive Director, Scientific Advisor, Senior Scientist, Associate Vice President, AVP, Group Director, Regional Director, Lead Scientist, Principal Scientist, Staff Scientist",
                "seniority_1_titles": "Associate Director, Manager, Senior Manager, Scientist, Principal Investigator, PI, Group Leader, Data Scientist, Research Scientist, Project Lead, Team Lead, Coordinator, Analyst, Specialist, Associate",
                "fit_4_titles": "Preclinical, Translational, Discovery, CEO, Founder, President, Chief Executive, Principal, Owner, Co-Founder, Chairman",
                "fit_3_titles": "Scientific, Research, R&D, In Vivo, In Vitro, Laboratory, Lab Director, CSO, CTO, VP Research, Head of Research, Research Director, Science, Innovation",
                "fit_2_titles": "Oncology, Cancer, Immunology, Drug Development, Medical Affairs, Pharmacology, Clinical Development, Therapeutics, Biopharmaceutical, Life Sciences, Biotech, Healthcare",
                "fit_1_titles": "Business Development, Operations, Economic, Project Management, Administrative, Finance, Legal, HR, Human Resources, Marketing, Sales, Communications, IT, Information Technology"
            }
        }
        self.config = self.load_config()
    
    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file or create default."""
        import copy
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                # Merge with defaults for any missing keys (deep merge)
                for step, step_config in self.default_config.items():
                    if step not in config:
                        config[step] = copy.deepcopy(step_config)
                    elif isinstance(step_config, dict):
                        for key, value in step_config.items():
                            if key not in config[step]:
                                config[step][key] = copy.deepcopy(value)
                return config
            else:
                # Create default config file
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(self.default_config, f, indent=2)
                return copy.deepcopy(self.default_config)
        except Exception as e:
            print(f"Error loading config: {e}")
            return copy.deepcopy(self.default_config)
    
    def save_config(self, sync_to_github: bool = True) -> bool:
        """Save current configuration to file and optionally sync to GitHub.
        Returns True on success, False on failure."""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
                f.flush()  # Ensure data is written to buffer
            # Force OS to write to disk (Windows especially needs this)
            import os as os_module
            os_module.sync() if hasattr(os_module, 'sync') else None
            
            # Sync to GitHub if enabled
            if sync_to_github:
                success, git_message = git_commit_config(self.config_file)
                if success:
                    print(f"GitHub sync: {git_message}")
                else:
                    print(f"GitHub sync warning: {git_message}")
                    # Don't fail the save if git sync fails
            
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

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
        """Initialize comprehensive database with all stages including contact extraction."""
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
                status TEXT,
                company_email TEXT,
                contacts_json TEXT,
                contact_count INTEGER DEFAULT 0
            )
        """)
        # Add new columns if they don't exist (for existing databases)
        try:
            conn.execute("ALTER TABLE leads_comprehensive ADD COLUMN company_email TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            conn.execute("ALTER TABLE leads_comprehensive ADD COLUMN contacts_json TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE leads_comprehensive ADD COLUMN contact_count INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        
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
                step5_completed INTEGER DEFAULT 0,
                total_leads INTEGER,
                analyzed_leads INTEGER
            )
        """)
        # Add step5_completed column if it doesn't exist
        try:
            conn.execute("ALTER TABLE run_logs ADD COLUMN step5_completed INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
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
                    step3: bool = False, step4: bool = False, step5: bool = False,
                    total_leads: int = 0, analyzed_leads: int = 0):
        """Save run log."""
        conn = sqlite3.connect(self.comprehensive_db)
        
        conn.execute("""
            INSERT OR REPLACE INTO run_logs 
            (run_id, start_time, end_time, status, step1_completed, step2_completed, 
             step3_completed, step4_completed, step5_completed, total_leads, analyzed_leads)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_id, start_time, end_time, status, int(step1), int(step2), 
              int(step3), int(step4), int(step5), total_leads, analyzed_leads))
        
        conn.commit()
        conn.close()
    
    def log_lead_contact_extraction(self, url: str, run_id: str, company_email: str, contacts: list):
        """Log contact extraction result. Stage: contact_scraped."""
        conn = sqlite3.connect(self.comprehensive_db)
        now = datetime.now(timezone.utc).isoformat()
        
        # Try to find the lead
        cursor = conn.cursor()
        cursor.execute("SELECT url FROM leads_comprehensive WHERE url = ?", (url,))
        exists = cursor.fetchone()
        
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
                    url = variant
                    break
        
        contacts_json = json.dumps(contacts) if contacts else "[]"
        contact_count = len(contacts) if contacts else 0
        
        if exists:
            conn.execute("""
                UPDATE leads_comprehensive 
                SET stage = ?, company_email = ?, contacts_json = ?, contact_count = ?,
                    last_analyzed = ?, last_analysis_run_id = ?
                WHERE url = ?
            """, ('contact_scraped', company_email or '', contacts_json, contact_count, now, run_id, url))
        else:
            conn.execute("""
                INSERT INTO leads_comprehensive 
                (url, first_discovered, last_analyzed, discovery_run_id, last_analysis_run_id, 
                 stage, company_email, contacts_json, contact_count, status)
                VALUES (?, ?, ?, ?, ?, 'contact_scraped', ?, ?, ?, 'pending')
            """, (url, now, now, run_id, run_id, company_email or '', contacts_json, contact_count))
        
        conn.commit()
        conn.close()
    
    def log_lead_contact_scoring(self, url: str, run_id: str, scored_contacts: list):
        """Log contact scoring result. Stage: contact_scored."""
        conn = sqlite3.connect(self.comprehensive_db)
        now = datetime.now(timezone.utc).isoformat()
        
        cursor = conn.cursor()
        cursor.execute("SELECT url FROM leads_comprehensive WHERE url = ?", (url,))
        exists = cursor.fetchone()
        
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
                    url = variant
                    break
        
        contacts_json = json.dumps(scored_contacts) if scored_contacts else "[]"
        
        if exists:
            conn.execute("""
                UPDATE leads_comprehensive 
                SET stage = ?, contacts_json = ?, last_analyzed = ?, last_analysis_run_id = ?
                WHERE url = ?
            """, ('contact_scored', contacts_json, now, run_id, url))
        
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
    
    def get_comprehensive_data(self, include_failed: bool = True):
        """Get all comprehensive data for download, sorted by stage with highest scores first."""
        conn = sqlite3.connect(self.comprehensive_db)
        
        query = """
            SELECT url, first_discovered, last_analyzed, stage, score, 
                   ai_analysis_result, status, company_email, contacts_json, contact_count
            FROM leads_comprehensive 
            ORDER BY 
                CASE stage 
                    WHEN 'contact_scored' THEN 1
                    WHEN 'contact_scraped' THEN 2
                    WHEN 'ai_analyzed' THEN 3 
                    WHEN 'scored' THEN 4 
                    WHEN 'scraped' THEN 5 
                    WHEN 'discovered' THEN 6 
                    WHEN 'failed' THEN 8
                    ELSE 7 
                END,
                score DESC NULLS LAST
        """
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        # Rename last_analyzed to processing_date for clarity
        if 'last_analyzed' in df.columns:
            df = df.rename(columns={'last_analyzed': 'processing_date'})
        
        # Sanitize text columns
        text_columns = ['url', 'ai_analysis_result', 'company_email', 'contacts_json', 'status']
        for col in text_columns:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: sanitize_for_csv(x) if x else '')
        
        # Add failed domains from separate file if they exist and include_failed is True
        if include_failed:
            import glob
            failed_files = glob.glob("data/failed_*.csv")
            if failed_files:
                failed_dfs = []
                for f in failed_files:
                    try:
                        fdf = pd.read_csv(f)
                        fdf['stage'] = 'failed'
                        fdf['status'] = 'failed'
                        failed_dfs.append(fdf)
                    except:
                        pass
                
                if failed_dfs:
                    all_failed = pd.concat(failed_dfs, ignore_index=True)
                    all_failed = all_failed.drop_duplicates(subset=['url'], keep='first')
                    
                    # Ensure same columns exist
                    for col in df.columns:
                        if col not in all_failed.columns:
                            all_failed[col] = ''
                    for col in all_failed.columns:
                        if col not in df.columns:
                            df[col] = ''
                    
                    # Append failed to bottom
                    df = pd.concat([df, all_failed], ignore_index=True)
        
        return df
    
    def get_all_leads_sorted(self, python_threshold: float = 75.0):
        """Get all leads sorted by stage and score for display. Includes new contact stages."""
        conn = sqlite3.connect(self.comprehensive_db)
        
        query = """
            SELECT url, stage, score, ai_analysis_result, company_email, contacts_json, contact_count
            FROM leads_comprehensive
            ORDER BY url
        """
        
        cursor = conn.execute(query)
        rows = cursor.fetchall()
        conn.close()
        
        # Parse and categorize leads
        contact_scored_leads = []  # Fully processed with contact scores
        contact_scraped_leads = []  # Contacts extracted but not scored
        ai_leads = []  # AI analyzed leads with match_score
        scored_leads = []  # Python scored leads
        unscraped_leads = []  # Discovered but not scraped
        
        for row in rows:
            url, stage, score, ai_result_json, company_email, contacts_json, contact_count = row
            
            if stage == 'contact_scored':
                contact_scored_leads.append({
                    'url': url,
                    'stage': stage,
                    'score': score,
                    'company_email': company_email,
                    'contact_count': contact_count
                })
            elif stage == 'contact_scraped':
                contact_scraped_leads.append({
                    'url': url,
                    'stage': stage,
                    'score': score,
                    'company_email': company_email,
                    'contact_count': contact_count
                })
            elif stage == 'ai_analyzed' and ai_result_json:
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
        
        # Sort contact scored leads by score (highest first)
        contact_scored_sorted = sorted(contact_scored_leads, key=lambda x: x.get('score', 0) or 0, reverse=True)
        contact_scraped_sorted = sorted(contact_scraped_leads, key=lambda x: x.get('score', 0) or 0, reverse=True)
        
        # Sort AI leads: highest first
        ai_leads_high = sorted(ai_leads, key=lambda x: x['score'], reverse=True)
        
        # Separate scored leads from scraped-but-not-scored leads
        actually_scored = [x for x in scored_leads if x['score'] is not None]
        just_scraped = [x for x in scored_leads if x['score'] is None]
        
        # Sort scored leads: highest first (changed from closest to threshold)
        scored_leads_sorted = sorted(actually_scored, key=lambda x: x['score'], reverse=True)
        
        # Combine in order: contact_scored, contact_scraped, AI analyzed, scored, scraped, discovered
        result = []
        result.extend(contact_scored_sorted)  # Fully processed leads (highest priority)
        result.extend(contact_scraped_sorted)  # Contacts extracted
        result.extend(ai_leads_high)  # AI analyzed
        result.extend(scored_leads_sorted)  # Python scored
        result.extend(just_scraped)  # Scraped but not scored
        result.extend(unscraped_leads)  # Discovered but not scraped
        
        # Remove duplicates while preserving order
        seen = set()
        final_result = []
        for item in result:
            if item['url'] not in seen:
                seen.add(item['url'])
                final_result.append(item)
        
        return final_result

# ============================================================
# TRAINING DATA COLLECTION SYSTEM
# ============================================================

class TrainingDataCollector:
    """
    Collects and manages training data for future AI model training.
    Tracks correlations between search terms, configurations, and lead quality.
    Operates independently from the main pipeline to avoid any performance impact.
    """
    
    def __init__(self):
        self.training_dir = "training_data"
        self.docs_dir = os.path.join(self.training_dir, "business_docs")
        self.feedback_dir = os.path.join(self.training_dir, "user_feedback")
        self.exports_dir = os.path.join(self.training_dir, "exports")
        
        os.makedirs(self.training_dir, exist_ok=True)
        os.makedirs(self.docs_dir, exist_ok=True)
        os.makedirs(self.feedback_dir, exist_ok=True)
        os.makedirs(self.exports_dir, exist_ok=True)
        
        self.db_path = os.path.join(self.training_dir, "training_data.db")
        self.init_database()
    
    def init_database(self):
        """Initialize the training data database with comprehensive schema."""
        conn = sqlite3.connect(self.db_path)
        
        # Run configurations - snapshot of config at time of run
        conn.execute("""
            CREATE TABLE IF NOT EXISTS run_configs (
                run_id TEXT PRIMARY KEY,
                run_timestamp TEXT,
                config_json TEXT,
                keyword_boxes_json TEXT,
                positive_factors_json TEXT,
                negative_factors_json TEXT,
                ai_prompts_json TEXT,
                region TEXT,
                max_results INTEGER,
                notes TEXT
            )
        """)
        
        # Search term effectiveness - maps search queries to lead outcomes
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_term_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                search_query TEXT,
                keyword_combo_json TEXT,
                total_results INTEGER,
                leads_discovered INTEGER,
                leads_scraped INTEGER,
                leads_scored INTEGER,
                leads_ai_analyzed INTEGER,
                avg_python_score REAL,
                avg_ai_score REAL,
                good_leads_count INTEGER,
                user_confirmed_good INTEGER DEFAULT 0,
                user_confirmed_bad INTEGER DEFAULT 0,
                effectiveness_score REAL,
                created_at TEXT,
                FOREIGN KEY (run_id) REFERENCES run_configs(run_id)
            )
        """)
        
        # Individual lead outcomes with full tracking
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lead_outcomes (
                url TEXT PRIMARY KEY,
                first_run_id TEXT,
                last_run_id TEXT,
                discovery_search_query TEXT,
                keyword_combo_used TEXT,
                python_score REAL,
                ai_score REAL,
                ai_is_good_lead INTEGER,
                ai_analysis_json TEXT,
                user_feedback TEXT,
                user_is_good_lead INTEGER,
                user_feedback_timestamp TEXT,
                company_name TEXT,
                business_type TEXT,
                notes TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        
        # User feedback imports from CSV
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback_imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_timestamp TEXT,
                source_file TEXT,
                total_rows INTEGER,
                matched_urls INTEGER,
                good_leads_count INTEGER,
                bad_leads_count INTEGER,
                notes TEXT
            )
        """)
        
        # Business documentation storage
        conn.execute("""
            CREATE TABLE IF NOT EXISTS business_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_type TEXT,
                filename TEXT,
                content TEXT,
                summary TEXT,
                keywords_extracted TEXT,
                upload_timestamp TEXT,
                notes TEXT
            )
        """)
        
        # Keyword performance tracking
        conn.execute("""
            CREATE TABLE IF NOT EXISTS keyword_performance (
                keyword TEXT PRIMARY KEY,
                times_used INTEGER DEFAULT 0,
                leads_generated INTEGER DEFAULT 0,
                good_leads_generated INTEGER DEFAULT 0,
                avg_score_when_used REAL,
                user_confirmed_effective INTEGER DEFAULT 0,
                last_used TEXT,
                notes TEXT
            )
        """)
        
        # Factor performance tracking (positive/negative factors)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS factor_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_type TEXT,
                factor_name TEXT,
                keywords TEXT,
                weight INTEGER,
                times_triggered INTEGER DEFAULT 0,
                avg_score_impact REAL,
                good_lead_correlation REAL,
                last_updated TEXT
            )
        """)
        
        # AI model configuration history
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_model_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                provider TEXT,
                model TEXT,
                total_leads_analyzed INTEGER,
                good_leads_identified INTEGER,
                avg_confidence REAL,
                total_cost REAL,
                user_agreement_rate REAL,
                notes TEXT,
                timestamp TEXT
            )
        """)
        
        # Export/sync history
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sync_type TEXT,
                direction TEXT,
                timestamp TEXT,
                files_synced TEXT,
                records_count INTEGER,
                status TEXT,
                error_message TEXT
            )
        """)
        
        conn.commit()
        conn.close()
    
    def log_run_config(self, run_id: str, config: dict):
        """Save a snapshot of the configuration used for a run."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc).isoformat()
        
        # Extract key components
        step1 = config.get('step1', {})
        step3 = config.get('step3', {})
        step4 = config.get('step4', {})
        
        conn.execute("""
            INSERT OR REPLACE INTO run_configs 
            (run_id, run_timestamp, config_json, keyword_boxes_json, 
             positive_factors_json, negative_factors_json, ai_prompts_json, 
             region, max_results, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            now,
            json.dumps(config),
            json.dumps(step1.get('keyword_boxes', [])),
            json.dumps(step3.get('positive_factors', [])),
            json.dumps(step3.get('negative_factors', [])),
            json.dumps({
                'custom_explanation': step4.get('custom_explanation', ''),
                'company_description_prompt': step4.get('company_description_prompt', ''),
            }),
            step1.get('region', 'us'),
            step1.get('max_results', 100),
            ''
        ))
        
        conn.commit()
        conn.close()
    
    def log_search_query(self, run_id: str, search_query: str, keyword_combo: list, results_count: int):
        """Log a search query and its immediate results."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc).isoformat()
        
        conn.execute("""
            INSERT INTO search_term_stats 
            (run_id, search_query, keyword_combo_json, total_results, 
             leads_discovered, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            search_query,
            json.dumps(keyword_combo),
            results_count,
            results_count,
            now
        ))
        
        # Update keyword performance
        for keyword in keyword_combo:
            if keyword.strip():
                conn.execute("""
                    INSERT INTO keyword_performance (keyword, times_used, leads_generated, last_used)
                    VALUES (?, 1, ?, ?)
                    ON CONFLICT(keyword) DO UPDATE SET
                        times_used = times_used + 1,
                        leads_generated = leads_generated + ?,
                        last_used = ?
                """, (keyword.strip(), results_count, now, results_count, now))
        
        conn.commit()
        conn.close()
    
    def log_lead_outcome(self, url: str, run_id: str, search_query: str = None,
                         keyword_combo: list = None, python_score: float = None,
                         ai_score: float = None, ai_is_good: bool = None,
                         ai_analysis: dict = None, company_name: str = None,
                         business_type: str = None):
        """Log or update a lead's outcome data."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc).isoformat()
        
        # Check if lead exists
        cursor = conn.execute("SELECT url FROM lead_outcomes WHERE url = ?", (url,))
        exists = cursor.fetchone()
        
        if exists:
            # Update existing record
            updates = []
            params = []
            
            if python_score is not None:
                updates.append("python_score = ?")
                params.append(python_score)
            if ai_score is not None:
                updates.append("ai_score = ?")
                params.append(ai_score)
            if ai_is_good is not None:
                updates.append("ai_is_good_lead = ?")
                params.append(1 if ai_is_good else 0)
            if ai_analysis:
                updates.append("ai_analysis_json = ?")
                params.append(json.dumps(ai_analysis))
            if company_name:
                updates.append("company_name = ?")
                params.append(company_name)
            if business_type:
                updates.append("business_type = ?")
                params.append(business_type)
            
            updates.append("last_run_id = ?")
            params.append(run_id)
            updates.append("updated_at = ?")
            params.append(now)
            
            params.append(url)
            
            if updates:
                conn.execute(f"""
                    UPDATE lead_outcomes SET {', '.join(updates)} WHERE url = ?
                """, params)
        else:
            # Insert new record
            conn.execute("""
                INSERT INTO lead_outcomes 
                (url, first_run_id, last_run_id, discovery_search_query, 
                 keyword_combo_used, python_score, ai_score, ai_is_good_lead,
                 ai_analysis_json, company_name, business_type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                url, run_id, run_id, search_query,
                json.dumps(keyword_combo) if keyword_combo else None,
                python_score, ai_score,
                1 if ai_is_good else (0 if ai_is_good is not None else None),
                json.dumps(ai_analysis) if ai_analysis else None,
                company_name, business_type, now, now
            ))
        
        conn.commit()
        conn.close()
    
    def import_user_feedback_csv(self, csv_path: str) -> dict:
        """
        Import user feedback from CSV. Expected columns: url, is_good_lead (or good_lead, feedback)
        Returns stats about the import.
        """
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc).isoformat()
        
        try:
            df = pd.read_csv(csv_path)
            
            # Normalize column names
            df.columns = [c.lower().strip() for c in df.columns]
            
            # Find URL column
            url_col = None
            for col in ['url', 'website', 'domain', 'link']:
                if col in df.columns:
                    url_col = col
                    break
            
            if not url_col:
                return {'success': False, 'error': 'No URL column found'}
            
            # Find feedback column
            feedback_col = None
            for col in ['is_good_lead', 'good_lead', 'feedback', 'is_good', 'good', 'quality']:
                if col in df.columns:
                    feedback_col = col
                    break
            
            if not feedback_col:
                return {'success': False, 'error': 'No feedback column found'}
            
            matched = 0
            good_count = 0
            bad_count = 0
            
            for _, row in df.iterrows():
                url = str(row[url_col]).strip()
                feedback_raw = str(row[feedback_col]).strip().lower()
                
                # Interpret feedback
                is_good = feedback_raw in ['1', 'true', 'yes', 'good', 'y', 'positive']
                
                if is_good:
                    good_count += 1
                else:
                    bad_count += 1
                
                # Update lead_outcomes
                cursor = conn.execute("SELECT url FROM lead_outcomes WHERE url = ?", (url,))
                if cursor.fetchone():
                    conn.execute("""
                        UPDATE lead_outcomes 
                        SET user_feedback = ?, user_is_good_lead = ?, user_feedback_timestamp = ?
                        WHERE url = ?
                    """, (feedback_raw, 1 if is_good else 0, now, url))
                    matched += 1
                else:
                    # Insert even if we don't have prior data
                    conn.execute("""
                        INSERT INTO lead_outcomes 
                        (url, user_feedback, user_is_good_lead, user_feedback_timestamp, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (url, feedback_raw, 1 if is_good else 0, now, now, now))
            
            # Log the import
            conn.execute("""
                INSERT INTO feedback_imports 
                (import_timestamp, source_file, total_rows, matched_urls, good_leads_count, bad_leads_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (now, os.path.basename(csv_path), len(df), matched, good_count, bad_count))
            
            conn.commit()
            
            # Update keyword performance based on feedback
            self._update_keyword_performance_from_feedback(conn)
            
            conn.close()
            
            return {
                'success': True,
                'total_rows': len(df),
                'matched_urls': matched,
                'good_leads': good_count,
                'bad_leads': bad_count
            }
            
        except Exception as e:
            conn.close()
            return {'success': False, 'error': str(e)}
    
    def _update_keyword_performance_from_feedback(self, conn):
        """Update keyword effectiveness based on user feedback."""
        # Get all leads with user feedback and their keyword combos
        cursor = conn.execute("""
            SELECT keyword_combo_used, user_is_good_lead 
            FROM lead_outcomes 
            WHERE user_is_good_lead IS NOT NULL AND keyword_combo_used IS NOT NULL
        """)
        
        keyword_stats = {}
        for row in cursor.fetchall():
            try:
                keywords = json.loads(row[0])
                is_good = row[1]
                
                for kw in keywords:
                    if kw.strip():
                        kw = kw.strip()
                        if kw not in keyword_stats:
                            keyword_stats[kw] = {'good': 0, 'total': 0}
                        keyword_stats[kw]['total'] += 1
                        if is_good:
                            keyword_stats[kw]['good'] += 1
            except:
                pass
        
        # Update keyword_performance table
        for kw, stats in keyword_stats.items():
            effectiveness = stats['good'] / stats['total'] if stats['total'] > 0 else 0
            conn.execute("""
                UPDATE keyword_performance 
                SET good_leads_generated = ?, user_confirmed_effective = ?
                WHERE keyword = ?
            """, (stats['good'], 1 if effectiveness > 0.5 else 0, kw))
        
        conn.commit()
    
    def add_business_doc(self, filepath: str, doc_type: str = 'general', notes: str = '') -> dict:
        """Add a business document (txt, meeting notes, overview, etc.)."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc).isoformat()
        
        try:
            # Read file content
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            filename = os.path.basename(filepath)
            
            # Copy to docs directory
            dest_path = os.path.join(self.docs_dir, f"{now.replace(':', '-')}_{filename}")
            shutil.copy(filepath, dest_path)
            
            # Extract simple keywords (words that appear frequently)
            words = re.findall(r'\b[a-zA-Z]{4,}\b', content.lower())
            word_counts = {}
            for w in words:
                word_counts[w] = word_counts.get(w, 0) + 1
            top_keywords = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:50]
            keywords_str = ', '.join([w[0] for w in top_keywords])
            
            conn.execute("""
                INSERT INTO business_docs 
                (doc_type, filename, content, keywords_extracted, upload_timestamp, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (doc_type, filename, content, keywords_str, now, notes))
            
            conn.commit()
            conn.close()
            
            return {'success': True, 'filename': filename, 'keywords_count': len(top_keywords)}
            
        except Exception as e:
            conn.close()
            return {'success': False, 'error': str(e)}
    
    def get_training_stats(self) -> dict:
        """Get comprehensive statistics about collected training data."""
        conn = sqlite3.connect(self.db_path)
        
        stats = {}
        
        # Total runs
        cursor = conn.execute("SELECT COUNT(*) FROM run_configs")
        stats['total_runs'] = cursor.fetchone()[0]
        
        # Total leads tracked
        cursor = conn.execute("SELECT COUNT(*) FROM lead_outcomes")
        stats['total_leads'] = cursor.fetchone()[0]
        
        # Leads with user feedback
        cursor = conn.execute("SELECT COUNT(*) FROM lead_outcomes WHERE user_is_good_lead IS NOT NULL")
        stats['leads_with_feedback'] = cursor.fetchone()[0]
        
        # User confirmed good leads
        cursor = conn.execute("SELECT COUNT(*) FROM lead_outcomes WHERE user_is_good_lead = 1")
        stats['user_confirmed_good'] = cursor.fetchone()[0]
        
        # User confirmed bad leads
        cursor = conn.execute("SELECT COUNT(*) FROM lead_outcomes WHERE user_is_good_lead = 0")
        stats['user_confirmed_bad'] = cursor.fetchone()[0]
        
        # Total unique keywords tracked
        cursor = conn.execute("SELECT COUNT(*) FROM keyword_performance")
        stats['unique_keywords'] = cursor.fetchone()[0]
        
        # Top performing keywords
        cursor = conn.execute("""
            SELECT keyword, good_leads_generated, leads_generated,
                   CASE WHEN leads_generated > 0 
                        THEN CAST(good_leads_generated AS REAL) / leads_generated 
                        ELSE 0 END as effectiveness
            FROM keyword_performance 
            WHERE leads_generated > 5
            ORDER BY effectiveness DESC
            LIMIT 10
        """)
        stats['top_keywords'] = [{'keyword': r[0], 'good': r[1], 'total': r[2], 'rate': r[3]} 
                                  for r in cursor.fetchall()]
        
        # Business docs count
        cursor = conn.execute("SELECT COUNT(*) FROM business_docs")
        stats['business_docs'] = cursor.fetchone()[0]
        
        # Feedback imports
        cursor = conn.execute("SELECT COUNT(*) FROM feedback_imports")
        stats['feedback_imports'] = cursor.fetchone()[0]
        
        # Last sync
        cursor = conn.execute("""
            SELECT timestamp, sync_type, direction, status 
            FROM sync_history 
            ORDER BY timestamp DESC LIMIT 1
        """)
        last_sync = cursor.fetchone()
        stats['last_sync'] = {
            'timestamp': last_sync[0] if last_sync else None,
            'type': last_sync[1] if last_sync else None,
            'direction': last_sync[2] if last_sync else None,
            'status': last_sync[3] if last_sync else None
        }
        
        conn.close()
        return stats
    
    def export_for_training(self, output_dir: str = None) -> dict:
        """Export all training data in formats suitable for ML training."""
        if output_dir is None:
            output_dir = self.exports_dir
        
        os.makedirs(output_dir, exist_ok=True)
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        conn = sqlite3.connect(self.db_path)
        
        exported_files = []
        
        try:
            # Export lead outcomes with all data
            df = pd.read_sql_query("""
                SELECT * FROM lead_outcomes 
                ORDER BY updated_at DESC
            """, conn)
            leads_file = os.path.join(output_dir, f"leads_training_{now}.csv")
            df.to_csv(leads_file, index=False)
            exported_files.append(leads_file)
            
            # Export keyword performance
            df = pd.read_sql_query("SELECT * FROM keyword_performance ORDER BY leads_generated DESC", conn)
            kw_file = os.path.join(output_dir, f"keyword_performance_{now}.csv")
            df.to_csv(kw_file, index=False)
            exported_files.append(kw_file)
            
            # Export search term stats
            df = pd.read_sql_query("SELECT * FROM search_term_stats ORDER BY created_at DESC", conn)
            search_file = os.path.join(output_dir, f"search_stats_{now}.csv")
            df.to_csv(search_file, index=False)
            exported_files.append(search_file)
            
            # Export run configs
            df = pd.read_sql_query("SELECT * FROM run_configs ORDER BY run_timestamp DESC", conn)
            config_file = os.path.join(output_dir, f"run_configs_{now}.csv")
            df.to_csv(config_file, index=False)
            exported_files.append(config_file)
            
            # Export business docs
            df = pd.read_sql_query("SELECT * FROM business_docs ORDER BY upload_timestamp DESC", conn)
            docs_file = os.path.join(output_dir, f"business_docs_{now}.csv")
            df.to_csv(docs_file, index=False)
            exported_files.append(docs_file)
            
            # Create a summary JSON
            stats = self.get_training_stats()
            summary_file = os.path.join(output_dir, f"training_summary_{now}.json")
            with open(summary_file, 'w') as f:
                json.dump(stats, f, indent=2)
            exported_files.append(summary_file)
            
            conn.close()
            
            return {'success': True, 'files': exported_files}
            
        except Exception as e:
            conn.close()
            return {'success': False, 'error': str(e)}
    
    def log_sync(self, sync_type: str, direction: str, files: list, 
                 records_count: int, status: str, error: str = None):
        """Log a sync operation."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc).isoformat()
        
        conn.execute("""
            INSERT INTO sync_history 
            (sync_type, direction, timestamp, files_synced, records_count, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (sync_type, direction, now, json.dumps(files), records_count, status, error))
        
        conn.commit()
        conn.close()
    
    def get_keyword_effectiveness_report(self) -> pd.DataFrame:
        """Generate a detailed keyword effectiveness report."""
        conn = sqlite3.connect(self.db_path)
        
        df = pd.read_sql_query("""
            SELECT 
                keyword,
                times_used,
                leads_generated,
                good_leads_generated,
                CASE WHEN leads_generated > 0 
                     THEN ROUND(CAST(good_leads_generated AS REAL) / leads_generated * 100, 2)
                     ELSE 0 END as effectiveness_pct,
                avg_score_when_used,
                last_used
            FROM keyword_performance
            WHERE times_used > 0
            ORDER BY effectiveness_pct DESC, leads_generated DESC
        """, conn)
        
        conn.close()
        return df
    
    def calculate_search_term_correlations(self) -> dict:
        """Calculate correlations between search terms and lead quality."""
        conn = sqlite3.connect(self.db_path)
        
        # Get all leads with scores and their keyword combos
        cursor = conn.execute("""
            SELECT keyword_combo_used, python_score, ai_score, user_is_good_lead
            FROM lead_outcomes
            WHERE keyword_combo_used IS NOT NULL
        """)
        
        keyword_scores = {}
        
        for row in cursor.fetchall():
            try:
                keywords = json.loads(row[0])
                python_score = row[1]
                ai_score = row[2]
                user_good = row[3]
                
                for kw in keywords:
                    kw = kw.strip()
                    if not kw:
                        continue
                    
                    if kw not in keyword_scores:
                        keyword_scores[kw] = {
                            'python_scores': [],
                            'ai_scores': [],
                            'user_good': 0,
                            'user_bad': 0,
                            'total': 0
                        }
                    
                    keyword_scores[kw]['total'] += 1
                    
                    if python_score is not None:
                        keyword_scores[kw]['python_scores'].append(python_score)
                    if ai_score is not None:
                        keyword_scores[kw]['ai_scores'].append(ai_score)
                    if user_good == 1:
                        keyword_scores[kw]['user_good'] += 1
                    elif user_good == 0:
                        keyword_scores[kw]['user_bad'] += 1
            except:
                pass
        
        conn.close()
        
        # Calculate correlations
        results = []
        for kw, data in keyword_scores.items():
            result = {
                'keyword': kw,
                'total_leads': data['total'],
                'avg_python_score': sum(data['python_scores']) / len(data['python_scores']) if data['python_scores'] else None,
                'avg_ai_score': sum(data['ai_scores']) / len(data['ai_scores']) if data['ai_scores'] else None,
                'user_good_rate': data['user_good'] / (data['user_good'] + data['user_bad']) if (data['user_good'] + data['user_bad']) > 0 else None,
                'user_feedback_count': data['user_good'] + data['user_bad']
            }
            results.append(result)
        
        # Sort by effectiveness
        results.sort(key=lambda x: (x['user_good_rate'] or 0, x['avg_ai_score'] or 0), reverse=True)
        
        return {
            'correlations': results,
            'total_keywords_analyzed': len(results),
            'keywords_with_feedback': sum(1 for r in results if r['user_feedback_count'] > 0)
        }


def git_push_training_data() -> Tuple[bool, str]:
    """Push training data to GitHub.
    Returns: (success: bool, message: str)
    """
    try:
        training_dir = "training_data"
        
        # Check if git is available
        result = subprocess.run(['git', 'status'], capture_output=True, text=True)
        if result.returncode != 0:
            return False, "Not a git repository"
        
        # Add training data directory
        result = subprocess.run(['git', 'add', training_dir], capture_output=True, text=True)
        
        # Check if there are changes
        result = subprocess.run(['git', 'diff', '--cached', '--quiet'], capture_output=True)
        if result.returncode == 0:
            return True, "No training data changes to push"
        
        # Commit with timestamp
        commit_msg = f"Training data update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        result = subprocess.run(['git', 'commit', '-m', commit_msg], capture_output=True, text=True)
        
        if result.returncode != 0:
            return False, f"Commit failed: {result.stderr}"
        
        # Push
        result = subprocess.run(['git', 'push'], capture_output=True, text=True)
        if result.returncode != 0:
            return True, f"Committed locally but push failed: {result.stderr}"
        
        return True, "Training data pushed to GitHub successfully"
    except FileNotFoundError:
        return False, "Git not found on system"
    except Exception as e:
        return False, f"Git error: {str(e)}"


def git_pull_training_data() -> Tuple[bool, str]:
    """Pull latest training data from GitHub.
    Returns: (success: bool, message: str)
    """
    try:
        result = subprocess.run(['git', 'status'], capture_output=True, text=True)
        if result.returncode != 0:
            return False, "Not a git repository"
        
        # Stash local training data changes
        subprocess.run(['git', 'stash', 'push', '-m', 'training_data_backup', 'training_data/'], 
                      capture_output=True)
        
        # Pull
        result = subprocess.run(['git', 'pull'], capture_output=True, text=True)
        
        # Try to restore stashed changes (merge with pulled data)
        subprocess.run(['git', 'stash', 'pop'], capture_output=True)
        
        if result.returncode != 0:
            return False, f"Pull failed: {result.stderr}"
        
        return True, result.stdout.strip() or "Already up to date"
    except FileNotFoundError:
        return False, "Git not found on system"
    except Exception as e:
        return False, f"Git error: {str(e)}"


# Global training data collector instance (lazy initialized)
_training_collector = None

def get_training_collector() -> TrainingDataCollector:
    """Get or create the global training data collector."""
    global _training_collector
    if _training_collector is None:
        _training_collector = TrainingDataCollector()
    return _training_collector


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
        
        # Adaptive rate limiter for Step 1
        cfg = config.config.get("step1", {})
        self.rate_limiter = AdaptiveRateLimiter(
            initial_delay=cfg.get("rate_limit_initial", 0.35),
            min_delay=cfg.get("rate_limit_min", 0.05),
            max_delay=cfg.get("rate_limit_max", 2.0)
        )
        self.rate_limiter.set_logger(self.logger)
    
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
                # Use adaptive rate limiting
                delay = self.rate_limiter.get_delay()
                if delay > 0 and page > 1:
                    time.sleep(delay)
                
                r = requests.post(url, json=payload, headers=headers, timeout=30)
                if r.status_code != 200:
                    msg = f"Serper.dev HTTP {r.status_code}: {r.text[:200]}"
                    self.logger.error(msg)
                    log_file.write(msg + "\n")
                    self.rate_limiter.on_error()
                    if r.status_code == 403 or r.status_code == 401:
                        self.last_api_error = f"HTTP {r.status_code}: Unauthorized"
                        if self.progress_callback:
                            self.progress_callback(f"  ✗ API Error: {self.last_api_error}")
                    elif r.status_code == 429:
                        self.last_api_error = "Rate limited - slowing down"
                        if self.progress_callback:
                            self.progress_callback(f"  ⚠ Rate limited, new delay: {self.rate_limiter.get_delay():.2f}s")
                        continue  # Retry with slower rate
                    break
                
                # Success - speed up if possible
                self.rate_limiter.on_success()
                
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
            except Exception as e:
                msg = f"Serper.dev request failed (page {page}): {e}"
                self.logger.error(msg)
                log_file.write(msg + "\n")
                self.last_api_error = str(e)
                self.rate_limiter.on_error()
                break
        return items[:max_results]
    
    def serpapi_search(self, api_key: str, query: str, max_results: int, gl: Optional[str], log_file) -> List[Dict[str, Any]]:
        """Search using SerpAPI (Google Search API)."""
        base_url = "https://serpapi.com/search"
        items = []
        per_page = 100
        self.last_api_error = None
        
        start = 0
        while len(items) < max_results:
            params = {
                "api_key": api_key,
                "q": query,
                "num": min(per_page, max_results - len(items)),
                "start": start,
                "gl": gl or "us",
                "engine": "google"
            }
            
            try:
                # Use adaptive rate limiting
                delay = self.rate_limiter.get_delay()
                if delay > 0 and start > 0:
                    time.sleep(delay)
                
                r = requests.get(base_url, params=params, timeout=30)
                if r.status_code != 200:
                    msg = f"SerpAPI HTTP {r.status_code}: {r.text[:200]}"
                    self.logger.error(msg)
                    log_file.write(msg + "\n")
                    self.rate_limiter.on_error()
                    if r.status_code == 401:
                        self.last_api_error = f"HTTP {r.status_code}: Unauthorized"
                        if self.progress_callback:
                            self.progress_callback(f"  ✗ API Error: {self.last_api_error}")
                    elif r.status_code == 429:
                        self.last_api_error = "Rate limited - slowing down"
                        if self.progress_callback:
                            self.progress_callback(f"  ⚠ Rate limited, new delay: {self.rate_limiter.get_delay():.2f}s")
                        continue
                    break
                
                # Success - speed up if possible
                self.rate_limiter.on_success()
                
                data = r.json()
                
                # Check for API errors in response
                if "error" in data:
                    msg = f"SerpAPI error: {data['error']}"
                    self.logger.error(msg)
                    log_file.write(msg + "\n")
                    self.last_api_error = data['error']
                    break
                
                organic_results = data.get("organic_results", [])
                page_items = [{"title": i.get("title", ""), "snippet": i.get("snippet", ""), "link": i.get("link", "")}
                              for i in organic_results]
                
                if not page_items:
                    break
                    
                items.extend(page_items)
                self.logger.info(f"SerpAPI fetched {len(page_items)} (total {len(items)}/{max_results})")
                log_file.write(f"Fetched from position {start}: {len(page_items)} results (total {len(items)})\n")
                
                start += len(page_items)
                
                if len(items) >= max_results:
                    break
                    
            except Exception as e:
                msg = f"SerpAPI request failed: {e}"
                self.logger.error(msg)
                log_file.write(msg + "\n")
                self.last_api_error = str(e)
                self.rate_limiter.on_error()
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
                    
                    # Use correct API based on choice
                    if api_choice == "serpapi":
                        results = self.serpapi_search(api_key, query, max_results, region, log_file)
                    else:
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
                    
                    # Domain verification is optional
                    verify_domains = cfg.get("verify_domains", True)
                    record_failed = cfg.get("record_failed_domains", True)
                    failed_domains_list = []
                    
                    if verify_domains:
                        if self.progress_callback:
                            self.progress_callback(f"  → Found {len(urls)} URLs, verifying domains...")
                        
                        ver_map = await self.verify_domains(urls, timeout_s, concurrency)
                        active = [u for u in urls if ver_map.get(u, False)]
                        
                        # Track failed domains if configured
                        if record_failed:
                            for u in urls:
                                if not ver_map.get(u, False):
                                    root = self.extract_root_domain(u)
                                    if root:
                                        failed_domains_list.append({
                                            "url": root,
                                            "error": "Domain verification failed (unreachable)",
                                            "processing_date": datetime.now(timezone.utc).isoformat()
                                        })
                    else:
                        if self.progress_callback:
                            self.progress_callback(f"  → Found {len(urls)} URLs (verification skipped)")
                        active = urls  # Accept all URLs without verification
                    
                    before = len(leads_state)
                    
                    for u in active:
                        root = self.extract_root_domain(u)
                        if root and root not in leads_state:
                            leads_state[root] = False
                            # Log to comprehensive system
                            self.comprehensive_logger.log_lead_discovery(root, run_id)
                    
                    # Save failed domains to a separate file
                    if failed_domains_list:
                        failed_path = f"data/failed_domains_{run_id}.csv"
                        os.makedirs("data", exist_ok=True)
                        # Append to existing file or create new
                        if os.path.exists(failed_path):
                            existing_df = pd.read_csv(failed_path)
                            new_df = pd.DataFrame(failed_domains_list)
                            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
                            combined_df.drop_duplicates(subset=['url'], keep='first', inplace=True)
                            combined_df.to_csv(failed_path, index=False)
                        else:
                            pd.DataFrame(failed_domains_list).to_csv(failed_path, index=False)
                    
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
    
    def __init__(self, config: UnifiedConfig, progress_callback=None):
        self.config = config
        self.logger = setup_logging()
        self.comprehensive_logger = ComprehensiveLogger()
        self.progress_callback = progress_callback
        
        # Load contact priority keywords from config (highest priority - we NEED contact pages)
        contact_keywords_str = config.config.get("step2", {}).get(
            "contact_priority_keywords", 
            "contact, team, about, leadership, management, executives, staff, people, our-team, meet-the-team, who-we-are, about-us, contact-us"
        )
        self.CONTACT_PRIORITY_HINTS = [k.strip().lower() for k in contact_keywords_str.split(",") if k.strip()]
        
        # Heuristic keywords for page selection
        self.PRIMARY_HINTS = [
            "oncology","cancer","tumor","tumour","solid","preclinical","pipeline","technology","platform",
            "device","implant","ablation","interventional","catheter","ultrasound","radiofrequency","rf",
            "electro","photothermal","laser","microwave","nano","drug-delivery","drugdelivery","local",
            "trial","animal","mouse","murine","research","lab","products","solutions","indications",
            "bile","bladder","glioma","brain","colorectal","kidney","liver","lung","pancreas","soft-tissue",
            "about","team","company","science","mechanism","moa","publications","data",
        ]
        # Note: "contact" REMOVED from negative - it's now highest priority in CONTACT_PRIORITY_HINTS
        self.NEGATIVE_HINTS = [
            "blog","news","press","careers","jobs","privacy","terms","cookie","sitemap","login","signin",
            "support","faq","events","webinar","newsletter","cart","shop","store","/tag/","/category/",
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
        
        # HIGHEST PRIORITY: Contact-related pages (we need these for contact extraction)
        for kw in self.CONTACT_PRIORITY_HINTS:
            if kw in s:
                score += 10.0  # Highest priority - ensures contact pages are crawled
        
        if anchor_text:
            at = anchor_text.lower()
            for kw in self.CONTACT_PRIORITY_HINTS:
                if kw in at:
                    score += 8.0  # High priority for anchor text matches
        
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
                batch_msg = f"[{chunk_end}/{len(tasks)}] Scraping: batch {chunk_start//20 + 1}"
                self.logger.info(f"Processing batch {chunk_start//20 + 1} (sites {chunk_start+1}-{chunk_end}/{len(tasks)})")
                if self.progress_callback:
                    self.progress_callback(batch_msg)
                
                results = await asyncio.gather(*[
                    self.crawl_site(site, session, conn, cfg) for site in chunk_sites
                ], return_exceptions=True)
                
                failed_scrapes = []
                for idx, site, res in zip(chunk_idxs, chunk_sites, results):
                    scanned_idx.append(idx)
                    
                    if isinstance(res, Exception):
                        self.logger.error(f"ERROR: {site} -> {repr(res)}")
                        self.comprehensive_logger.log_lead_scraping(site, run_id, False)
                        failed_scrapes.append({
                            "url": site,
                            "error": f"Exception: {repr(res)}"[:200].replace(",", ";"),
                            "processing_date": datetime.now(timezone.utc).isoformat()
                        })
                        continue
                    if res:
                        self.logger.info(f"SCRAPED: {site}")
                        self.comprehensive_logger.log_lead_scraping(site, run_id, True)
                    else:
                        self.logger.info(f"NO TEXT: {site}")
                        self.comprehensive_logger.log_lead_scraping(site, run_id, False)
                        failed_scrapes.append({
                            "url": site,
                            "error": "No text content extracted",
                            "processing_date": datetime.now(timezone.utc).isoformat()
                        })
                
                # Save failed scrapes
                if failed_scrapes:
                    failed_path = f"data/failed_scrapes_{run_id}.csv"
                    os.makedirs("data", exist_ok=True)
                    if os.path.exists(failed_path):
                        existing_df = pd.read_csv(failed_path)
                        new_df = pd.DataFrame(failed_scrapes)
                        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
                        combined_df.to_csv(failed_path, index=False)
                    else:
                        pd.DataFrame(failed_scrapes).to_csv(failed_path, index=False)
                
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
    
    def __init__(self, config: UnifiedConfig, progress_callback=None):
        self.config = config
        self.logger = setup_logging()
        self.comprehensive_logger = ComprehensiveLogger()
        self.progress_callback = progress_callback
        
        # Get fuzzy match threshold from config (100 = exact matching only)
        perf_config = config.config.get("performance", {})
        self.fuzzy_threshold = perf_config.get("fuzzy_match_threshold", 85)
        
        # Get logging level
        self.logging_level = perf_config.get("logging_level", "moderate")
        
        # Load factors from config
        self.load_factors_from_config()
        
        # Pre-compile regex patterns for performance
        self._compile_keyword_patterns()
    
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
    
    def _compile_keyword_patterns(self):
        """Pre-compile regex patterns for all keywords (performance optimization)."""
        self._compiled_patterns = {}
        all_keywords = []
        for f in self.FACTORS:
            all_keywords.extend(f.get("keywords", []))
        for d in self.DISQUALIFIERS:
            all_keywords.extend(d.get("keywords", []))
        
        for kw in all_keywords:
            kw_lower = kw.lower().strip()
            if kw_lower and kw_lower not in self._compiled_patterns:
                try:
                    self._compiled_patterns[kw_lower] = re.compile(rf"\b{re.escape(kw_lower)}\b", re.IGNORECASE)
                except re.error:
                    # Fallback for problematic patterns
                    self._compiled_patterns[kw_lower] = None
    
    def fuzzy_count(self, text: str, keywords: List[str], threshold: int = None) -> int:
        """Count keyword matches with optional fuzzy matching.
        
        Args:
            text: Text to search in
            keywords: List of keywords to find
            threshold: Fuzzy match threshold (0-100). If 100, skip fuzzy matching entirely.
                      If None, use config value.
        """
        if threshold is None:
            threshold = self.fuzzy_threshold
        
        text_lower = text.lower()
        count = 0
        
        for kw in keywords:
            kw_lower = kw.lower().strip()
            if not kw_lower:
                continue
            
            # Use pre-compiled pattern if available
            if hasattr(self, '_compiled_patterns') and kw_lower in self._compiled_patterns:
                pattern = self._compiled_patterns[kw_lower]
                if pattern:
                    count += len(pattern.findall(text_lower))
            else:
                count += len(re.findall(rf"\b{re.escape(kw_lower)}\b", text_lower))
            
            # Only do fuzzy matching if threshold < 100
            if threshold < 100:
                if fuzz.partial_ratio(kw_lower, text_lower) >= threshold:
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
            flat = {
                "url": url, 
                "total_score": score_result["total_score"], 
                "normalized": score_result["normalized"],
                "processing_date": datetime.now(timezone.utc).isoformat()
            }
            for b in score_result["breakdown"]:
                flat[f"{b['name']}_count"] = b["count"]
                flat[f"{b['name']}_score"] = b["contrib"]
            results.append(flat)
            
            # Log to comprehensive system
            self.comprehensive_logger.log_lead_scoring(url, run_id, score_result["normalized"])
            processed_count += 1
            
            # Report progress every 10 websites
            if processed_count % 10 == 0 and self.progress_callback:
                self.progress_callback(f"[{processed_count}/{len(df)}] Scoring websites...")
            
            # Save progress every 10 websites
            if processed_count % 10 == 0:
                self.comprehensive_logger.save_run_log(
                    run_id, datetime.now().isoformat(), status="running", 
                    step1=True, step2=True, step3=True, analyzed_leads=processed_count
                )
        
        results_df = pd.DataFrame(results)
        results_df = results_df.sort_values("normalized", ascending=False)
        
        # Apply multi-select thresholds with OR logic
        # If any threshold is enabled and met, the lead passes
        use_score = cfg.get("use_score_threshold", True)
        use_percentage = cfg.get("use_percentage_threshold", False)
        use_count = cfg.get("use_count_threshold", False)
        
        # If no threshold is selected, use score threshold by default
        if not use_score and not use_percentage and not use_count:
            use_score = True
        
        # Build mask for OR logic
        mask = pd.Series([False] * len(results_df), index=results_df.index)
        threshold_descriptions = []
        
        if use_score:
            score_threshold = float(cfg.get("threshold_value", 75))
            score_mask = results_df['normalized'] >= score_threshold
            mask = mask | score_mask
            threshold_descriptions.append(f"score >= {score_threshold}")
        
        if use_percentage:
            percentage = float(cfg.get("percentage_value", 20))
            num_to_keep = max(1, int(len(results_df) * percentage / 100))
            # Get indices of top percentage
            top_indices = results_df.head(num_to_keep).index
            percentage_mask = results_df.index.isin(top_indices)
            mask = mask | percentage_mask
            threshold_descriptions.append(f"top {percentage}%")
        
        if use_count:
            count = int(cfg.get("count_value", 100))
            # Get indices of top count
            top_indices = results_df.head(count).index
            count_mask = results_df.index.isin(top_indices)
            mask = mask | count_mask
            threshold_descriptions.append(f"top {count}")
        
        filtered_df = results_df[mask]
        threshold_description = " OR ".join(threshold_descriptions)
        
        # Save results
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"data/scoring_results_{run_id}.csv"
        os.makedirs("data", exist_ok=True)
        filtered_df.to_csv(output_path, index=False)
        
        self.logger.info(f"Step 3 complete: Scoring results saved to {output_path}")
        self.logger.info(f"Filtered to {len(filtered_df)} websites based on: {threshold_description}")
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
    
    def __init__(self, initial_delay: float = 0.1, min_delay: float = 0.01, max_delay: float = 5.0, 
                 success_threshold: int = 5, error_threshold: int = 2):
        self.current_delay = initial_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.consecutive_successes = 0
        self.consecutive_errors = 0
        self.success_threshold = success_threshold  # Configurable: successes needed to speed up
        self.error_threshold = error_threshold      # Configurable: errors to slow down
        self.logger = None
        self.logging_level = "moderate"  # none, limited, moderate, detailed
        
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
            if self.logger and self.logging_level in ("moderate", "detailed"):
                self.logger.info(f"⚡ Sped up: delay now {self.current_delay:.3f}s")
    
    def on_error(self):
        """Called when a request fails."""
        self.consecutive_errors += 1
        self.consecutive_successes = 0
        
        # Slow down if we've had errors
        if self.consecutive_errors >= self.error_threshold:
            self.current_delay = min(self.max_delay, self.current_delay * 1.5)
            self.consecutive_errors = 0
            if self.logger and self.logging_level != "none":
                self.logger.info(f"🐌 Slowed down: delay now {self.current_delay:.3f}s")
    
    def record_success(self):
        """Alias for on_success for backward compatibility."""
        self.on_success()
    
    def record_rate_limit(self):
        """Called when rate limited - more aggressive slowdown."""
        self.consecutive_errors += 2
        self.consecutive_successes = 0
        self.current_delay = min(self.max_delay, self.current_delay * 2.0)
        if self.logger and self.logging_level != "none":
            self.logger.warning(f"⚠️ Rate limited: delay now {self.current_delay:.3f}s")
    
    def set_logger(self, logger, logging_level: str = "moderate"):
        """Set logger for rate limiter messages."""
        self.logger = logger
        self.logging_level = logging_level

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


class GoodLeadsScraper:
    """Scrapes and summarizes good leads reference websites."""
    
    def __init__(self, config: UnifiedConfig, progress_callback=None):
        self.config = config
        self.logger = setup_logging()
        self.progress_callback = progress_callback
        
    def normalize_url(self, u: str) -> str:
        """Normalize URL for consistency."""
        p = urlparse(u)
        # Force https, lowercase host, remove trailing slash
        scheme = "https"
        netloc = p.netloc.lower().lstrip("www.")
        path = p.path.rstrip("/") or "/"
        return urlunparse((scheme, netloc, path, "", "", ""))
    
    def normalize_root(self, raw: str) -> str:
        """Normalize a root URL."""
        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw
        return self.normalize_url(raw.split("/")[0] + "//" + urlparse(raw).netloc)
    
    def extract_text(self, html: str, url: str) -> str:
        """Extract readable text from HTML."""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Basic cleaning
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        return "\n".join(lines)
    
    def score_candidate(self, root: str, url: str, anchor: str = "") -> float:
        """Score a URL for crawl priority."""
        score = 0.0
        path_lower = urlparse(url).path.lower()
        
        # Priority keywords
        priority_terms = ["about", "product", "service", "solution", "team", "company", "overview"]
        for term in priority_terms:
            if term in path_lower or term in anchor.lower():
                score += 2.0
        
        # Penalize deep paths
        depth = path_lower.count("/")
        score += max(0, 2.0 - 0.3 * depth)
        
        # Homepage bonus
        if path_lower in ("", "/"):
            score += 0.5
        
        # Penalize file downloads
        if re.search(r"\.(pdf|png|jpg|jpeg|gif|svg|mp4|zip|rar|7z|gz|json|xml)$", path_lower):
            score -= 10.0
        
        return score
    
    def same_reg_domain(self, root: str, url: str) -> bool:
        """Check if URL is same registered domain as root."""
        try:
            from tld import get_tld
            root_tld = get_tld(root, as_object=True)
            url_tld = get_tld(url, as_object=True)
            return root_tld.fld == url_tld.fld
        except:
            # Fallback: compare netlocs
            return urlparse(root).netloc == urlparse(url).netloc
    
    def discover_links(self, base_url: str, html: str) -> list:
        """Discover links from HTML."""
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
    
    async def fetch(self, session: aiohttp.ClientSession, url: str, read_limit: int) -> tuple:
        """Fetch a URL and return status, content-type, and HTML."""
        try:
            async with session.get(url) as resp:
                ct = resp.headers.get("Content-Type", "")
                if "text/html" not in ct.lower():
                    return resp.status, ct, None
                body = await resp.content.read(read_limit)
                html = body.decode(errors="ignore")
                return resp.status, ct, html
        except Exception as e:
            self.logger.debug(f"Fetch error {url}: {e}")
            return 0, None, None
    
    async def crawl_good_lead_site(self, root_url: str, session: aiohttp.ClientSession, cfg: dict) -> str:
        """Crawl a single good lead website and return extracted text."""
        root = self.normalize_root(root_url)
        seen = set()
        kept = []
        queue = []
        import heapq
        
        heapq.heappush(queue, (-self.score_candidate(root, root), 0, root))
        seen.add(root)
        
        pages = 0
        aggregate_chunks = []
        max_pages = cfg.get("good_leads_max_pages_per_site", 12)
        max_depth = cfg.get("good_leads_max_depth", 2)
        max_chars_per_page = cfg.get("good_leads_max_chars_per_page", 50000)
        aggregate_cap = cfg.get("good_leads_aggregate_char_cap", 120000)
        
        while queue and pages < max_pages:
            _negscore, depth, url = heapq.heappop(queue)
            if depth > max_depth:
                continue
            
            status, ct, html = await self.fetch(session, url, 2000000)
            
            if status == 0 or html is None:
                continue
            
            text = self.extract_text(html, url)
            if len(text) >= 400:  # Min chars threshold
                text_trimmed = text[:max_chars_per_page]
                kept.append((url, text_trimmed))
                if sum(len(x[1]) for x in kept) < aggregate_cap:
                    aggregate_chunks.append(text_trimmed[:20000])
            
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
        
        aggregated = "\n\n".join(aggregate_chunks)[:aggregate_cap]
        return aggregated
    
    async def scrape_good_leads(self) -> dict:
        """
        Scrape all good leads domains and return a dict with domain -> content mapping.
        """
        cfg = self.config.config.get("step4", {})
        domains_str = cfg.get("good_leads_domains", "").strip()
        
        if not domains_str:
            return {}
        
        # Parse comma-separated domains
        domains = [d.strip() for d in domains_str.split(",") if d.strip()]
        if not domains:
            return {}
        
        self.logger.info(f"Scraping {len(domains)} good leads reference websites...")
        if self.progress_callback:
            self.progress_callback(f"Scraping {len(domains)} good leads reference sites...")
        
        results = {}
        timeout = ClientTimeout(total=20)
        headers = {
            "User-Agent": self.config.config.get("step2", {}).get("user_agent", "LeadGenBot/1.0"),
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
        }
        
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for i, domain in enumerate(domains):
                try:
                    if self.progress_callback:
                        self.progress_callback(f"[{i+1}/{len(domains)}] Scraping good lead: {domain}")
                    
                    content = await self.crawl_good_lead_site(domain, session, cfg)
                    if content:
                        results[domain] = content
                        self.logger.info(f"Scraped good lead: {domain} ({len(content)} chars)")
                    else:
                        self.logger.warning(f"No content from good lead: {domain}")
                except Exception as e:
                    self.logger.error(f"Error scraping good lead {domain}: {e}")
        
        return results
    
    async def summarize_good_leads(self, scraped_content: dict) -> str:
        """
        Summarize all good leads content with a single AI API call.
        Returns the summary text.
        """
        if not scraped_content:
            return ""
        
        cfg = self.config.config.get("step4", {})
        max_summary_chars = cfg.get("good_leads_max_summary_chars", 8000)
        summarization_prompt = cfg.get("good_leads_summarization_prompt", "").strip()
        
        if not summarization_prompt:
            summarization_prompt = "Analyze these websites of ideal customer companies. For each, summarize: what type of business they are, their main products/services, their location/headquarters, their company size/funding stage, and what makes them an ideal customer. Remove marketing fluff and focus on concrete facts."
        
        # Build content for summarization
        combined_content = []
        for domain, content in scraped_content.items():
            # Limit each domain's content to avoid overwhelming the AI
            content_limit = min(len(content), 15000)
            combined_content.append(f"=== {domain} ===\n{content[:content_limit]}\n")
        
        all_content = "\n".join(combined_content)
        
        # Limit total content to reasonable size for AI
        if len(all_content) > 50000:
            all_content = all_content[:50000] + "\n\n[Content truncated...]"
        
        full_prompt = f"""{summarization_prompt}

Here are the websites to analyze:

{all_content}

Please provide a clear, structured summary that highlights what makes these companies good examples of ideal customers. Keep the summary concise but informative (aim for {max_summary_chars} characters or less)."""

        # Make API call based on provider
        provider = cfg.get("api_provider", "claude")
        api_key = cfg.get("api_key", "")
        
        if provider == "gemini":
            api_key = cfg.get("gemini_api_key", "") or api_key
        
        if not api_key:
            self.logger.warning("No API key configured for good leads summarization")
            return ""
        
        try:
            if self.progress_callback:
                self.progress_callback("Summarizing good leads with AI...")
            
            if provider == "claude":
                summary = await self._call_claude(api_key, full_prompt, cfg)
            elif provider == "openai":
                summary = await self._call_openai(api_key, full_prompt, cfg)
            elif provider == "gemini":
                summary = await self._call_gemini(api_key, full_prompt, cfg)
            else:
                self.logger.error(f"Unknown API provider: {provider}")
                return ""
            
            # Truncate if needed
            if len(summary) > max_summary_chars:
                summary = summary[:max_summary_chars] + "..."
            
            self.logger.info(f"Good leads summary generated: {len(summary)} chars")
            return summary
            
        except Exception as e:
            self.logger.error(f"Error summarizing good leads: {e}")
            return ""
    
    async def _call_claude(self, api_key: str, prompt: str, cfg: dict) -> str:
        """Call Claude API for summarization."""
        import anthropic
        
        # Get model from config
        model_choice = cfg.get("model_choice", "model_1")
        models = cfg.get("claude_models", [])
        model_idx = int(model_choice.replace("model_", "")) - 1 if model_choice.startswith("model_") else 0
        model_id = models[model_idx]["api_id"] if model_idx < len(models) else "claude-3-5-haiku-20241022"
        
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model_id,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    
    async def _call_openai(self, api_key: str, prompt: str, cfg: dict) -> str:
        """Call OpenAI API for summarization."""
        import openai
        
        model_choice = cfg.get("model_choice", "model_1")
        models = cfg.get("openai_models", [])
        model_idx = int(model_choice.replace("model_", "")) - 1 if model_choice.startswith("model_") else 0
        model_id = models[model_idx]["api_id"] if model_idx < len(models) else "gpt-4o-mini"
        
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model_id,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    
    async def _call_gemini(self, api_key: str, prompt: str, cfg: dict) -> str:
        """Call Gemini API for summarization."""
        import google.generativeai as genai
        
        model_choice = cfg.get("model_choice", "model_1")
        models = cfg.get("gemini_models", [])
        model_idx = int(model_choice.replace("model_", "")) - 1 if model_choice.startswith("model_") else 0
        model_id = models[model_idx]["api_id"] if model_idx < len(models) else "gemini-2.5-flash-preview-05-20"
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_id)
        response = model.generate_content(prompt)
        return response.text
    
    async def run_scrape_and_summarize(self) -> str:
        """
        Main entry point: scrape good leads domains and summarize them.
        Returns the summary text to be used in scoring prompts.
        """
        scraped_content = await self.scrape_good_leads()
        
        if not scraped_content:
            self.logger.info("No good leads domains configured or scraped")
            return ""
        
        summary = await self.summarize_good_leads(scraped_content)
        
        # Cache the summary in config for future reference
        self.config.config["step4"]["good_leads_summary_cache"] = summary
        
        return summary


# ============================================================
# AI INPUT OPTIMIZATION AGENT
# ============================================================

class AIInputOptimizationAgent:
    """
    AI agent that analyzes user inputs and generates optimal search configuration.
    This agent reads the user's business description and ideal customer profile,
    then uses AI to select the best search parameters for finding high-quality leads.
    """
    
    def __init__(self, config: UnifiedConfig, progress_callback=None):
        self.config = config
        self.progress_callback = progress_callback
        self.logger = setup_logging()
    
    def _log(self, message: str):
        """Log a message and optionally call progress callback."""
        self.logger.info(message)
        if self.progress_callback:
            self.progress_callback(message)
    
    def _build_user_context(self) -> str:
        """Build the user context string from all user inputs."""
        user_inputs = self.config.config.get("user_inputs", {})
        
        context_parts = []
        
        # Business identity
        if user_inputs.get("business_name"):
            context_parts.append(f"Business Name: {user_inputs['business_name']}")
        if user_inputs.get("website_url"):
            context_parts.append(f"Website: {user_inputs['website_url']}")
        
        # What they sell
        if user_inputs.get("product_description"):
            context_parts.append(f"Product/Service: {user_inputs['product_description']}")
        if user_inputs.get("price_min") or user_inputs.get("price_max"):
            price_range = f"${user_inputs.get('price_min', '?')} - ${user_inputs.get('price_max', '?')}"
            context_parts.append(f"Price Range: {price_range}")
        
        # Ideal customer
        if user_inputs.get("ideal_customer"):
            context_parts.append(f"Ideal Customer Description: {user_inputs['ideal_customer']}")
        if user_inputs.get("company_size"):
            context_parts.append(f"Target Company Size: {user_inputs['company_size']}")
        if user_inputs.get("geography"):
            context_parts.append(f"Geographic Requirements: {user_inputs['geography']}")
        
        # Decision makers
        if user_inputs.get("seniority_levels"):
            context_parts.append(f"Target Seniority Levels: {user_inputs['seniority_levels']}")
        if user_inputs.get("departments"):
            context_parts.append(f"Target Departments: {user_inputs['departments']}")
        
        # Exclusions
        if user_inputs.get("exclusions"):
            context_parts.append(f"Exclusions (do NOT target): {user_inputs['exclusions']}")
        
        # Examples and context
        if user_inputs.get("good_leads"):
            context_parts.append(f"Example Good Customers (URLs): {user_inputs['good_leads']}")
        if user_inputs.get("search_keywords"):
            context_parts.append(f"User-Suggested Search Keywords: {user_inputs['search_keywords']}")
        if user_inputs.get("other_context"):
            context_parts.append(f"Additional Context: {user_inputs['other_context']}")
        
        # Single prompt mode response (comprehensive)
        if user_inputs.get("single_prompt_response"):
            context_parts.append(f"Comprehensive Business Description:\n{user_inputs['single_prompt_response']}")
        
        # Preferences
        extract_contacts = user_inputs.get("extract_contacts", True)
        context_parts.append(f"Extract Individual Contacts: {'Yes' if extract_contacts else 'No'}")
        
        return "\n\n".join(context_parts)
    
    async def _call_ai(self, prompt: str) -> str:
        """Call the AI API with the optimization prompt."""
        cfg = self.config.config.get("step4", {})
        provider = cfg.get("provider_choice", cfg.get("api_provider", "claude"))
        api_key = cfg.get("api_key", "")
        gemini_key = cfg.get("gemini_api_key", "")
        
        if provider == "gemini":
            api_key = gemini_key
        
        if not api_key:
            raise ValueError(f"No API key configured for {provider}")
        
        self._log(f"Calling {provider} API for input optimization...")
        
        if provider == "claude":
            return await self._call_claude(api_key, prompt, cfg)
        elif provider == "openai":
            return await self._call_openai(api_key, prompt, cfg)
        elif provider == "gemini":
            return await self._call_gemini(api_key, prompt, cfg)
        else:
            raise ValueError(f"Unknown provider: {provider}")
    
    async def _call_claude(self, api_key: str, prompt: str, cfg: dict) -> str:
        """Call Claude API."""
        import anthropic
        
        model_choice = cfg.get("model_choice", "model_1")
        models = cfg.get("claude_models", [])
        model_idx = int(model_choice.replace("model_", "")) - 1 if model_choice.startswith("model_") else 0
        model_id = models[model_idx]["api_id"] if model_idx < len(models) else "claude-3-5-haiku-20241022"
        
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model_id,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    
    async def _call_openai(self, api_key: str, prompt: str, cfg: dict) -> str:
        """Call OpenAI API."""
        import openai
        
        model_choice = cfg.get("model_choice", "model_1")
        models = cfg.get("openai_models", [])
        model_idx = int(model_choice.replace("model_", "")) - 1 if model_choice.startswith("model_") else 0
        model_id = models[model_idx]["api_id"] if model_idx < len(models) else "gpt-4o-mini"
        
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model_id,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    
    async def _call_gemini(self, api_key: str, prompt: str, cfg: dict) -> str:
        """Call Gemini API."""
        import google.generativeai as genai
        
        model_choice = cfg.get("model_choice", "model_1")
        models = cfg.get("gemini_models", [])
        model_idx = int(model_choice.replace("model_", "")) - 1 if model_choice.startswith("model_") else 0
        model_id = models[model_idx]["api_id"] if model_idx < len(models) else "gemini-2.5-flash-preview-05-20"
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_id)
        response = model.generate_content(prompt)
        return response.text
    
    def _parse_ai_response(self, response: str) -> Dict[str, Any]:
        """Parse the AI response JSON."""
        # Try to extract JSON from response
        try:
            # First try direct parse
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        
        # Try to find JSON block in response
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        
        # If all else fails, return empty dict
        self._log("Warning: Could not parse AI response as JSON")
        return {}
    
    def _apply_ai_config(self, ai_config: Dict[str, Any]):
        """Apply the AI-generated configuration to the config object.
        
        This applies all 'Updated Every Run' variables from variable_reference.csv:
        - step1: keyword_boxes, keyword_box_count, region, max_results, serper_combo_cap
        - step3: positive_factors, negative_factors, threshold settings
        - step4: scoring_fields, good_leads_domains
        - step5: seniority and fit title configurations
        """
        # ============================================================
        # STEP 1: DISCOVERY CONFIGURATION
        # ============================================================
        
        # Apply keyword boxes
        if "keyword_boxes" in ai_config:
            keyword_boxes = ai_config["keyword_boxes"]
            # Ensure it's a list and clean up
            if isinstance(keyword_boxes, list):
                self.config.config["step1"]["keyword_boxes"] = keyword_boxes
                self.config.config["step1"]["keyword_box_count"] = len(keyword_boxes)
                self._log(f"Applied {len(keyword_boxes)} keyword boxes")
        
        # Apply keyword_box_count if explicitly provided
        if "keyword_box_count" in ai_config:
            self.config.config["step1"]["keyword_box_count"] = ai_config["keyword_box_count"]
        
        # Apply region (2-letter country code)
        if "region" in ai_config:
            region = ai_config["region"].lower().strip()
            if len(region) == 2:
                self.config.config["step1"]["region"] = region
                self._log(f"Applied region: {region}")
        
        # Apply search settings
        if "max_results_per_search" in ai_config:
            try:
                max_results = int(ai_config["max_results_per_search"])
                if 10 <= max_results <= 200:
                    self.config.config["step1"]["max_results"] = max_results
            except (ValueError, TypeError):
                pass
        
        if "combo_cap" in ai_config:
            try:
                combo_cap = int(ai_config["combo_cap"])
                if 10 <= combo_cap <= 1000:
                    self.config.config["step1"]["serper_combo_cap"] = combo_cap
                    self._log(f"Applied combo cap: {combo_cap}")
            except (ValueError, TypeError):
                pass
        
        # ============================================================
        # STEP 3: FACTOR-BASED SCORING CONFIGURATION
        # ============================================================
        
        # Apply positive factors
        if "positive_factors" in ai_config:
            factors = ai_config["positive_factors"]
            if isinstance(factors, list) and len(factors) > 0:
                # Validate and clean factor structure
                cleaned_factors = []
                for factor in factors:
                    if isinstance(factor, dict) and "name" in factor and "keywords" in factor:
                        cleaned_factors.append({
                            "name": str(factor.get("name", "Factor")),
                            "weight": int(factor.get("weight", 100)),
                            "sensitivity": int(factor.get("sensitivity", 2)),
                            "keywords": str(factor.get("keywords", ""))
                        })
                if cleaned_factors:
                    self.config.config["step3"]["positive_factors"] = cleaned_factors
                    self.config.config["step3"]["positive_factor_count"] = len(cleaned_factors)
                    self._log(f"Applied {len(cleaned_factors)} positive scoring factors")
        
        # Apply negative factors
        if "negative_factors" in ai_config:
            factors = ai_config["negative_factors"]
            if isinstance(factors, list) and len(factors) > 0:
                cleaned_factors = []
                for factor in factors:
                    if isinstance(factor, dict) and "name" in factor and "keywords" in factor:
                        cleaned_factors.append({
                            "name": str(factor.get("name", "Exclusion")),
                            "weight": int(factor.get("weight", 100)),
                            "sensitivity": int(factor.get("sensitivity", 1)),
                            "keywords": str(factor.get("keywords", ""))
                        })
                if cleaned_factors:
                    self.config.config["step3"]["negative_factors"] = cleaned_factors
                    self.config.config["step3"]["negative_factor_count"] = len(cleaned_factors)
                    self._log(f"Applied {len(cleaned_factors)} negative scoring factors")
        
        # Apply scoring threshold
        if "scoring_threshold" in ai_config:
            try:
                threshold = int(ai_config["scoring_threshold"])
                if 0 <= threshold <= 100:
                    self.config.config["step3"]["threshold_value"] = str(threshold)
                    self.config.config["step3"]["use_score_threshold"] = True
                    self._log(f"Applied scoring threshold: {threshold}")
            except (ValueError, TypeError):
                pass
        
        # ============================================================
        # STEP 4: AI SCORING FIELDS CONFIGURATION
        # ============================================================
        
        # Apply AI scoring fields (Updated Every Run)
        if "scoring_fields" in ai_config:
            fields = ai_config["scoring_fields"]
            if isinstance(fields, list) and len(fields) > 0:
                cleaned_fields = []
                for field in fields:
                    if isinstance(field, dict) and "type" in field and "title" in field:
                        field_type = field.get("type", "score")
                        cleaned_field = {
                            "type": field_type,
                            "title": str(field.get("title", "Field")),
                            "prompt": str(field.get("prompt", "")),
                            "enabled": bool(field.get("enabled", True))
                        }
                        if field_type == "score":
                            cleaned_field["min"] = int(field.get("min", 0))
                            cleaned_field["max"] = int(field.get("max", 10))
                        elif field_type == "text":
                            cleaned_field["allow_unlisted"] = bool(field.get("allow_unlisted", True))
                            cleaned_field["allow_multiple"] = bool(field.get("allow_multiple", False))
                            cleaned_field["options"] = field.get("options", [])
                        cleaned_fields.append(cleaned_field)
                
                if cleaned_fields:
                    # Merge with existing fields - replace matching titles, add new ones
                    existing_fields = self.config.config.get("step4", {}).get("scoring_fields", [])
                    existing_titles = {f.get("title"): i for i, f in enumerate(existing_fields)}
                    
                    for new_field in cleaned_fields:
                        title = new_field.get("title")
                        if title in existing_titles:
                            # Replace existing field
                            existing_fields[existing_titles[title]] = new_field
                        else:
                            # Add as new field
                            existing_fields.append(new_field)
                    
                    self.config.config["step4"]["scoring_fields"] = existing_fields
                    self.config.config["step4"]["scoring_field_count"] = len(existing_fields)
                    self._log(f"Applied {len(cleaned_fields)} AI scoring fields")
        
        # Apply good leads domains
        if "good_leads_domains" in ai_config:
            domains = ai_config["good_leads_domains"]
            if domains and isinstance(domains, str):
                self.config.config["step4"]["good_leads_domains"] = domains.strip()
                self._log(f"Applied good leads domains: {domains[:50]}...")
        
        # ============================================================
        # STEP 5: CONTACT EXTRACTION CONFIGURATION
        # ============================================================
        
        if "step5" not in self.config.config:
            self.config.config["step5"] = {}
        
        # Apply seniority title configurations
        for key in ["seniority_4_titles", "seniority_3_titles", "seniority_2_titles", "seniority_1_titles"]:
            if key in ai_config:
                value = ai_config[key]
                if isinstance(value, str) and value.strip():
                    self.config.config["step5"][key] = value.strip()
        
        # Apply fit title configurations
        for key in ["fit_4_titles", "fit_3_titles", "fit_2_titles", "fit_1_titles"]:
            if key in ai_config:
                value = ai_config[key]
                if isinstance(value, str) and value.strip():
                    self.config.config["step5"][key] = value.strip()
        
        # Log completion
        self._log("AI configuration applied successfully")
    
    def _save_run_file(self, user_inputs: Dict, ai_prompt: str, ai_response: str, ai_config: Dict) -> str:
        """Save run file with all inputs and AI selections."""
        # Create runs directory if it doesn't exist
        runs_dir = "runs"
        os.makedirs(runs_dir, exist_ok=True)
        
        # Generate run folder name
        run_number = get_next_run_number()
        now = datetime.now()
        date_str = now.strftime("%m-%d-%Y %H-%M-%S")
        folder_name = f"Run {run_number} - {date_str}"
        folder_path = os.path.join(runs_dir, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        
        # Create the run data
        run_data = {
            "run_number": run_number,
            "created_at": now.isoformat(),
            "user_inputs": user_inputs,
            "ai_optimization": {
                "prompt": ai_prompt,
                "raw_response": ai_response,
                "parsed_config": ai_config
            },
            "final_config": {
                "step1": self.config.config.get("step1", {}),
                "step3": self.config.config.get("step3", {}),
                "step5": self.config.config.get("step5", {})
            }
        }
        
        # Save to JSON file
        run_file_path = os.path.join(folder_path, "ai_optimization_run.json")
        with open(run_file_path, 'w', encoding='utf-8') as f:
            json.dump(run_data, f, indent=2, default=str)
        
        self._log(f"Run file saved: {run_file_path}")
        return folder_path
    
    async def optimize_inputs(self) -> Tuple[bool, Dict[str, Any], str]:
        """
        Main entry point: analyze user inputs and generate optimal configuration.
        
        Returns:
            Tuple of (success, ai_config_dict, run_folder_path)
        """
        try:
            # Get agent settings
            agent_settings = self.config.config.get("ai_optimization_agent", {})
            agent_prompt = agent_settings.get("prompt", "")
            
            if not agent_prompt:
                self._log("Error: No AI optimization prompt configured")
                return False, {}, ""
            
            # Build user context
            self._log("Building user context from inputs...")
            user_context = self._build_user_context()
            
            if not user_context.strip():
                self._log("Error: No user inputs provided")
                return False, {}, ""
            
            # Build full prompt
            full_prompt = f"""{agent_prompt}

=== USER'S BUSINESS AND IDEAL CUSTOMER INFORMATION ===

{user_context}

=== END OF USER INFORMATION ===

Now analyze this information and generate the optimal search configuration as a JSON object.
Remember to return ONLY valid JSON."""
            
            # Call AI
            self._log("Calling AI to optimize search configuration...")
            ai_response = await self._call_ai(full_prompt)
            
            # Parse response
            self._log("Parsing AI response...")
            ai_config = self._parse_ai_response(ai_response)
            
            if not ai_config:
                self._log("Error: Failed to parse AI response")
                return False, {}, ""
            
            # Log reasoning if provided
            if "reasoning" in ai_config:
                self._log(f"AI Reasoning: {ai_config['reasoning']}")
            
            # Apply configuration
            self._log("Applying AI-generated configuration...")
            self._apply_ai_config(ai_config)
            
            # Save run file
            user_inputs = self.config.config.get("user_inputs", {})
            run_folder = self._save_run_file(user_inputs, agent_prompt, ai_response, ai_config)
            
            self._log("AI optimization complete!")
            return True, ai_config, run_folder
            
        except Exception as e:
            self._log(f"Error during AI optimization: {str(e)}")
            self.logger.exception("AI optimization failed")
            return False, {}, ""


class AIAnalyzer:
    """Step 4: AI-powered lead analysis with async batch processing."""
    
    def __init__(self, config: UnifiedConfig, progress_callback=None):
        self.config = config
        self.logger = setup_logging()
        self.comprehensive_logger = ComprehensiveLogger()
        
        # Get performance settings
        perf_config = config.config.get("performance", {})
        self.logging_level = perf_config.get("logging_level", "moderate")
        self.debug_file_interval = perf_config.get("debug_file_interval", 10)
        self.always_write_debug = perf_config.get("always_write_debug_files", False)
        self.batch_size = config.config.get("step4", {}).get("async_batch_size", 5)
        success_threshold = perf_config.get("rate_limiter_success_threshold", 5)
        
        self.rate_limiter = AdaptiveRateLimiter(success_threshold=success_threshold)
        self.rate_limiter.set_logger(self.logger, self.logging_level)
        self.credit_used = 0.0
        self.credit_limit = 0.0
        self.progress_callback = progress_callback
        self.ai_call_count = 0  # Track calls for debug file throttling
        
        # CSV output settings
        self.csv_config = config.config.get("csv_output", {})
        self.sanitize_commas = self.csv_config.get("sanitize_commas", True)
    
    def estimate_api_cost(self, content: str, model: str, provider: str = "claude") -> float:
        """Estimate API cost for a request using configured costs or fallback pricing."""
        # Try to get cost from config first
        cfg = self.config.config.get("step4", {})
        models_key = f"{provider.lower()}_models"
        if models_key in cfg:
            for m in cfg[models_key]:
                if m.get("api_id") == model:
                    # Return cost per website - check for cost_per_1k first, then cost_per_100
                    if "cost_per_1k" in m:
                        return m.get("cost_per_1k", 1.0) / 1000
                    elif "cost_per_100" in m:
                        return m.get("cost_per_100", 0.1) / 100
                    else:
                        return 1.0 / 1000
        
        # Fallback: estimate based on tokens
        input_tokens = len(content) / 4
        output_tokens = 1000
        
        if provider.lower() == "openai":
            if "gpt-4o-mini" in model.lower() or "gpt-4.1-mini" in model.lower():
                input_cost, output_cost = 0.00015, 0.0006
            elif "gpt-4o" in model.lower() or "gpt-4.1" in model.lower():
                input_cost, output_cost = 0.0025, 0.01
            else:
                input_cost, output_cost = 0.0025, 0.01
        elif provider.lower() == "gemini":
            if "flash" in model.lower() and "lite" in model.lower():
                input_cost, output_cost = 0.000075, 0.0003
            elif "flash" in model.lower():
                input_cost, output_cost = 0.0001, 0.0004
            elif "pro" in model.lower():
                input_cost, output_cost = 0.00125, 0.005
            else:
                input_cost, output_cost = 0.0001, 0.0004
        else:  # claude
            if "haiku" in model.lower():
                input_cost, output_cost = 0.0008, 0.004
            elif "opus" in model.lower():
                input_cost, output_cost = 0.015, 0.075
            else:  # sonnet
                input_cost, output_cost = 0.003, 0.015
        
        return (input_tokens * input_cost / 1000) + (output_tokens * output_cost / 1000)
    
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
    
    def _build_scoring_prompt(self, url: str, content: str) -> Tuple[str, List[Dict]]:
        """Build the AI prompt dynamically from configured scoring fields.
        
        Returns:
            Tuple of (prompt_string, list_of_enabled_fields)
        """
        cfg = self.config.config["step4"]
        scoring_fields = cfg.get("scoring_fields", [])
        company_description_prompt = cfg.get("company_description_prompt", "").strip()
        
        # Get delimiter for multi-value fields
        csv_config = self.config.config.get("csv_output", {})
        delimiter = csv_config.get("delimiter", ";")
        
        # Use cached good leads summary if available (generated during pipeline run)
        examples_text = ""
        good_leads_summary = cfg.get("good_leads_summary_cache", "").strip()
        if good_leads_summary:
            max_summary_chars = cfg.get("good_leads_max_summary_chars", 8000)
            if len(good_leads_summary) > max_summary_chars:
                good_leads_summary = good_leads_summary[:max_summary_chars] + "\n\n... [truncated]"
            examples_text = f"\n\n=== EXAMPLES OF GOOD LEADS (SUMMARIZED) ===\n\n{good_leads_summary}"
        
        # Filter to only enabled fields
        enabled_fields = [f for f in scoring_fields if f.get("enabled", False) and f.get("title", "").strip()]
        
        # Build field instructions
        field_instructions = []
        json_fields = []
        
        for i, field in enumerate(enabled_fields):
            field_type = field.get("type", "score")
            title = field.get("title", f"Field {i+1}").strip()
            prompt = field.get("prompt", "").strip()
            
            # Create safe key name (lowercase, underscores)
            key = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')
            field['_key'] = key  # Store for later use
            
            if field_type == "score":
                min_val = field.get("min", 0)
                max_val = field.get("max", 10)
                field_instructions.append(f"""
=== {title} (Score: {min_val}-{max_val}) ===
{prompt}
""")
                json_fields.append(f'    "{key}": <integer {min_val}-{max_val}>')
                
            elif field_type == "text":
                options = field.get("options", [])
                allow_unlisted = field.get("allow_unlisted", True)
                allow_multiple = field.get("allow_multiple", False)
                
                options_text = ""
                if options:
                    options_text = f"\nAvailable options: {', '.join(options)}"
                    if allow_unlisted:
                        options_text += "\nYou may also provide unlisted options if none of the above fit."
                    if allow_multiple:
                        options_text += f"\nMultiple selections allowed - separate with '{delimiter}' (e.g., Option1{delimiter} Option2)"
                        options_text += f"\nIMPORTANT: List options in order (listed options first by their number, then unlisted options last)"
                
                field_instructions.append(f"""
=== {title} (Text Selection) ===
{prompt}{options_text}
""")
                
                if allow_multiple:
                    json_fields.append(f'    "{key}": "<selected option(s) separated by {delimiter}>"')
                else:
                    json_fields.append(f'    "{key}": "<selected option>"')
        
        # Build the full prompt
        prompt = f"""You are an expert business analyst specializing in identifying high-quality B2B leads in the healthcare, medical device, and pharmaceutical industries.

Analyze the following website and provide scores/classifications for each field below.
{examples_text}

{"".join(field_instructions)}

=== Additional Instructions ===
- For all text responses, use '{delimiter}' instead of commas to separate multiple values
- Be consistent and precise in your scoring
- Base all assessments on the website content provided

Website URL: {url}
Website Content: {content}

Please provide your analysis in the following JSON format:
{{
{chr(10).join(json_fields)},
    "company_description": "<brief company description>",
    "reasoning": "<detailed explanation of your overall assessment>",
    "key_indicators": "<{delimiter}-separated list of positive indicators>",
    "red_flags": "<{delimiter}-separated list of any concerns>"
}}

IMPORTANT: Use '{delimiter}' instead of commas in all text fields to separate multiple items.
"""
        
        return prompt, enabled_fields
    
    def _sanitize_ai_response(self, text: str) -> str:
        """Convert commas in AI response to the configured delimiter."""
        if not text:
            return ""
        csv_config = self.config.config.get("csv_output", {})
        delimiter = csv_config.get("delimiter", ";")
        # Replace commas with delimiter
        text = str(text).replace(",", delimiter)
        # Clean up excessive whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
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
        
        max_chars = cfg.get("max_content_chars", 12000)
        if len(content) > max_chars:
            content = content[:max_chars] + "... [truncated]"
        
        # Build the dynamic prompt from scoring fields
        prompt, enabled_fields = self._build_scoring_prompt(url, content)
        
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
                elif provider.lower() == "gemini":
                    # Google Gemini API
                    gemini_key = cfg.get("gemini_api_key", api_key)
                    headers = {
                        "Content-Type": "application/json"
                    }
                    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
                    payload = {
                        "contents": [
                            {
                                "parts": [{"text": prompt}]
                            }
                        ],
                        "generationConfig": {
                            "maxOutputTokens": cfg.get("max_tokens", 2000)
                        }
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
                    elif provider.lower() == "gemini":
                        # Gemini format
                        content_text = result['candidates'][0]['content']['parts'][0]['text']
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
                            
                            # Sanitize all text fields (replace commas with delimiter)
                            for key, value in analysis.items():
                                if isinstance(value, str):
                                    analysis[key] = self._sanitize_ai_response(value)
                            
                            # Add metadata
                            analysis['url'] = url
                            analysis['processed_at'] = datetime.now(timezone.utc).isoformat()
                            analysis['content_length'] = len(content)
                            analysis['estimated_cost'] = estimated_cost
                            
                            # Add backwards-compatible fields if overall_score exists
                            if 'overall_score' in analysis:
                                analysis['match_score'] = analysis['overall_score']
                                # Determine if good lead based on overall score (>= 60)
                                try:
                                    analysis['is_good_lead'] = int(analysis['overall_score']) >= 60
                                except (ValueError, TypeError):
                                    analysis['is_good_lead'] = False
                            
                            # Store enabled field info for CSV column generation
                            analysis['_scoring_fields'] = [f.get('_key', f.get('title', '')) for f in enabled_fields]
                            
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
    
    def _sanitize_for_csv(self, text: str) -> str:
        """Remove commas from text and replace with semicolons for CSV safety."""
        if not text or not self.sanitize_commas:
            return text or ""
        # Replace commas with semicolons
        text = str(text).replace(",", ";")
        # Also clean up excessive whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def _should_write_debug_file(self) -> bool:
        """Determine if we should write a debug file based on throttling settings."""
        if self.always_write_debug:
            return True
        # Write every N calls
        return (self.ai_call_count % self.debug_file_interval) == 0
    
    def _save_ai_debug_log(self, url: str, prompt: str, response: Optional[str], error: Optional[str] = None):
        """Save AI prompt and response to a debug log file (with throttling)."""
        self.ai_call_count += 1
        
        # Check if we should write this debug file
        if not self._should_write_debug_file():
            return
        
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
                f.write(f"Call Number: {self.ai_call_count}\n")
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
            
            if self.logging_level == "detailed":
                self.logger.info(f"AI debug log saved to: {debug_file}")
        except Exception as e:
            if self.logging_level != "none":
                self.logger.warning(f"Failed to save AI debug log: {e}")
    
    async def analyze_website_async(self, session: aiohttp.ClientSession, url: str, content: str) -> Dict[str, Any]:
        """Async version of analyze_website for batch processing."""
        cfg = self.config.config["step4"]
        api_key = cfg.get("api_key", "")
        model = cfg.get("model", "claude-3-5-sonnet-20241022")
        provider = cfg.get("provider_choice") or cfg.get("api_provider", "claude")
        
        if not api_key:
            return {"url": url, "error": "API key not configured"}
        
        # Check credit limit
        estimated_cost = self.estimate_api_cost(content, model, provider)
        if self.credit_used + estimated_cost > self.credit_limit:
            return {"url": url, "error": "Credit limit reached"}
        
        max_chars = cfg.get("max_content_chars", 12000)
        if len(content) > max_chars:
            content = content[:max_chars] + "... [truncated]"
        
        # Build the dynamic prompt from scoring fields (same as sync version)
        prompt, enabled_fields = self._build_scoring_prompt(url, content)
        
        # Set up API request
        if provider.lower() == "openai":
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            api_url = "https://api.openai.com/v1/chat/completions"
            payload = {"model": model, "max_tokens": cfg.get("max_tokens", 2000),
                      "messages": [{"role": "user", "content": prompt}]}
        elif provider.lower() == "gemini":
            gemini_key = cfg.get("gemini_api_key", api_key)
            headers = {"Content-Type": "application/json"}
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"maxOutputTokens": cfg.get("max_tokens", 2000)}}
        else:
            headers = {"x-api-key": api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01"}
            api_url = "https://api.anthropic.com/v1/messages"
            payload = {"model": model, "max_tokens": cfg.get("max_tokens", 2000),
                      "messages": [{"role": "user", "content": prompt}]}
        
        for attempt in range(cfg.get("max_retries", 3)):
            try:
                delay = self.rate_limiter.get_delay()
                if delay > 0:
                    await asyncio.sleep(delay)
                
                async with session.post(api_url, headers=headers, json=payload, timeout=60) as response:
                    if response.status == 200:
                        self.rate_limiter.on_success()
                        self.credit_used += estimated_cost
                        
                        result = await response.json()
                        
                        if provider.lower() == "openai":
                            content_text = result['choices'][0]['message']['content']
                        elif provider.lower() == "gemini":
                            content_text = result['candidates'][0]['content']['parts'][0]['text']
                        else:
                            content_text = result['content'][0]['text']
                        
                        self._save_ai_debug_log(url, prompt, content_text, error=None)
                        
                        # Parse JSON response
                        start_idx = content_text.find('{')
                        end_idx = content_text.rfind('}') + 1
                        if start_idx != -1 and end_idx > start_idx:
                            json_str = content_text[start_idx:end_idx]
                            analysis = json.loads(json_str)
                            
                            # Sanitize all text fields (replace commas with delimiter)
                            for key, value in analysis.items():
                                if isinstance(value, str):
                                    analysis[key] = self._sanitize_ai_response(value)
                            
                            # Add metadata
                            analysis['url'] = url
                            analysis['processed_at'] = datetime.now(timezone.utc).isoformat()
                            analysis['content_length'] = len(content)
                            analysis['estimated_cost'] = estimated_cost
                            
                            # Add backwards-compatible fields if overall_score exists
                            if 'overall_score' in analysis:
                                analysis['match_score'] = analysis['overall_score']
                                try:
                                    analysis['is_good_lead'] = int(analysis['overall_score']) >= 60
                                except (ValueError, TypeError):
                                    analysis['is_good_lead'] = False
                            
                            # Store enabled field info for CSV column generation
                            analysis['_scoring_fields'] = [f.get('_key', f.get('title', '')) for f in enabled_fields]
                            
                            return analysis
                        
                        return {"url": url, "error": "Could not parse JSON from response"}
                    
                    elif response.status == 429:
                        self.rate_limiter.record_rate_limit()
                        continue
                    elif response.status == 401:
                        self.rate_limiter.on_error()
                        return {"url": url, "error": f"Authentication error (401)"}
                    else:
                        self.rate_limiter.on_error()
                        error_text = await response.text()
                        self._save_ai_debug_log(url, prompt, None, error=f"HTTP {response.status}: {error_text}")
                        if attempt < cfg.get("max_retries", 3) - 1:
                            continue
                        return {"url": url, "error": f"HTTP {response.status}"}
                        
            except asyncio.TimeoutError:
                self.rate_limiter.on_error()
                if attempt < cfg.get("max_retries", 3) - 1:
                    continue
                return {"url": url, "error": "Request timeout"}
            except Exception as e:
                self.rate_limiter.on_error()
                self._save_ai_debug_log(url, prompt, None, error=str(e))
                if attempt < cfg.get("max_retries", 3) - 1:
                    continue
                return {"url": url, "error": str(e)}
        
        return {"url": url, "error": "Max retries exceeded"}
    
    async def analyze_batch_async(self, urls_and_contents: List[Tuple[str, str, float]]) -> List[Dict[str, Any]]:
        """Process a batch of websites in parallel using async."""
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = [
                self.analyze_website_async(session, url, content) 
                for url, content, _ in urls_and_contents
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Convert exceptions to error dicts
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    url = urls_and_contents[i][0]
                    processed_results.append({"url": url, "error": str(result)})
                else:
                    processed_results.append(result)
            
            return processed_results
    
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
        failed_domains = []  # Track failed domains for CSV
        run_id = self.comprehensive_logger.get_run_id()
        processed_count = 0
        
        # Collect all URLs and content for batch processing
        urls_to_process = []
        for _, row in high_score_df.iterrows():
            url = row['url']
            normalized_score = row['normalized']
            content = self.get_website_content(url)
            if content:
                urls_to_process.append((url, content, normalized_score))
            else:
                failed_domains.append({
                    "url": url,
                    "error": "No content found in database",
                    "normalized_score": normalized_score,
                    "processing_date": datetime.now(timezone.utc).isoformat()
                })
        
        if self.logging_level in ("moderate", "detailed"):
            self.logger.info(f"Prepared {len(urls_to_process)} websites for analysis, {len(failed_domains)} skipped (no content)")
        
        # Process in batches using async
        batch_size = self.batch_size
        total_batches = (len(urls_to_process) + batch_size - 1) // batch_size
        
        for batch_idx in range(total_batches):
            batch_start = batch_idx * batch_size
            batch_end = min(batch_start + batch_size, len(urls_to_process))
            batch = urls_to_process[batch_start:batch_end]
            
            batch_msg = f"Processing batch {batch_idx + 1}/{total_batches} ({len(batch)} companies in parallel)"
            if self.logging_level != "none":
                self.logger.info(batch_msg)
            if self.progress_callback:
                self.progress_callback(batch_msg)
            
            # Run async batch
            batch_results = asyncio.run(self.analyze_batch_async(batch))
            
            for result, (url, content, normalized_score) in zip(batch_results, batch):
                processed_count += 1
                
                if result and "error" not in result:
                    result['normalized_score'] = normalized_score
                    # Sanitize text fields for CSV
                    for key in ['reasoning', 'business_type', 'company_description', 'key_indicators', 'red_flags']:
                        if key in result:
                            result[key] = self._sanitize_for_csv(result.get(key, ""))
                    results.append(result)
                    
                    if self.logging_level in ("moderate", "detailed"):
                        self.logger.info(f"✓ {url}: Match={result.get('match_score', 'N/A')}")
                    
                    # Log to comprehensive system
                    self.comprehensive_logger.log_lead_ai_analysis(url, run_id, result)
                else:
                    error_msg = result.get("error", "Unknown error") if result else "No result"
                    failed_domains.append({
                        "url": url,
                        "error": self._sanitize_for_csv(error_msg),
                        "normalized_score": normalized_score,
                        "processing_date": datetime.now(timezone.utc).isoformat()
                    })
                    if self.logging_level != "none":
                        self.logger.warning(f"✗ {url}: {error_msg}")
            
            # Progress update
            if self.progress_callback:
                self.progress_callback(f"Completed {processed_count}/{len(urls_to_process)} | Credit: ${self.credit_used:.2f}/${self.credit_limit:.2f}")
            
            # Check credit limit
            if self.credit_used >= self.credit_limit:
                if self.logging_level != "none":
                    self.logger.warning("Credit limit reached, stopping analysis")
                if self.progress_callback:
                    self.progress_callback("⚠️ Credit limit reached")
                break
        
        # Legacy compatibility: also run sync for any remaining (shouldn't happen normally)
        # This section is kept for backward compatibility but batch processing should handle all
        legacy_processed = False
        for idx, (_, row) in enumerate(high_score_df.iterrows()):
            if legacy_processed:
                break
            url = row['url']
            # Skip if already processed in batch
            if any(r.get('url') == url for r in results) or any(f.get('url') == url for f in failed_domains):
                continue
            normalized_score = row['normalized']
            
            content = self.get_website_content(url)
            if not content:
                if self.logging_level != "none":
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
        
        # Save results with failed domains at bottom
        if results or failed_domains:
            # Add processing_date to all successful results
            for r in results:
                if 'processing_date' not in r:
                    r['processing_date'] = datetime.now(timezone.utc).isoformat()
                # Sanitize all text fields
                for key in list(r.keys()):
                    if isinstance(r[key], str):
                        r[key] = self._sanitize_for_csv(r[key])
                # Remove internal fields that shouldn't be in CSV
                r.pop('_scoring_fields', None)
            
            # Create results DataFrame
            results_df = pd.DataFrame(results) if results else pd.DataFrame()
            
            # Sort by match_score descending (best leads first)
            if not results_df.empty and 'match_score' in results_df.columns:
                results_df = results_df.sort_values('match_score', ascending=False)
            
            # Add failed domains at the bottom if configured
            csv_config = self.config.config.get("csv_output", {})
            if csv_config.get("include_failed_domains", True) and failed_domains:
                # Create failed domains DataFrame with same columns
                failed_df = pd.DataFrame(failed_domains)
                failed_df['match_score'] = -1  # Mark as failed
                failed_df['is_good_lead'] = False
                failed_df['business_type'] = 'FAILED'
                failed_df['confidence'] = 0
                failed_df['reasoning'] = failed_df['error']
                
                # Combine: successful leads first, then failed at bottom
                if not results_df.empty:
                    # Ensure same columns
                    for col in results_df.columns:
                        if col not in failed_df.columns:
                            failed_df[col] = ''
                    for col in failed_df.columns:
                        if col not in results_df.columns:
                            results_df[col] = ''
                    results_df = pd.concat([results_df, failed_df], ignore_index=True)
                else:
                    results_df = failed_df
            
            results_df.to_csv(results_path, index=False)
            self.logger.info(f"Step 4 complete: AI analysis results saved to {results_path}")
            
            successful_count = len([r for r in results if r.get('is_good_lead')])
            self.logger.info(f"Summary: {successful_count}/{len(results)} identified as good leads, {len(failed_domains)} failed")
            
            if results:
                good_leads = [r for r in results if r.get('is_good_lead')]
                if good_leads:
                    self.logger.info("Top good leads:")
                    for lead in good_leads[:5]:
                        self.logger.info(f"  {lead.get('url', 'N/A')} - {lead.get('business_type', 'N/A')} (Match: {lead.get('match_score', 'N/A')})")
        else:
            self.logger.warning("No AI analyses completed (no results or failures)")
        
        return True

# ============================================================
# CONTACT EXTRACTION (Step 5)
# ============================================================

class ContactExtractor:
    """Step 5: AI-powered contact extraction and scoring (combined in single call)."""
    
    def __init__(self, config: UnifiedConfig, progress_callback=None):
        self.config = config
        self.logger = setup_logging()
        self.comprehensive_logger = ComprehensiveLogger()
        
        # Get performance settings
        perf_config = config.config.get("performance", {})
        self.logging_level = perf_config.get("logging_level", "moderate")
        self.batch_size = config.config.get("step4", {}).get("async_batch_size", 5)
        success_threshold = perf_config.get("rate_limiter_success_threshold", 5)
        
        self.rate_limiter = AdaptiveRateLimiter(success_threshold=success_threshold)
        self.rate_limiter.set_logger(self.logger, self.logging_level)
        self.credit_used = 0.0
        self.credit_limit = 0.0
        self.progress_callback = progress_callback
        
        # CSV output settings
        csv_config = config.config.get("csv_output", {})
        self.sanitize_commas = csv_config.get("sanitize_commas", True)
    
    def _sanitize_for_csv(self, text: str) -> str:
        """Remove commas from text and replace with semicolons for CSV safety."""
        if not text or not self.sanitize_commas:
            return text or ""
        text = str(text).replace(",", ";")
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def estimate_api_cost(self, content: str, model: str, provider: str = "claude") -> float:
        """Estimate API cost for a request using configured costs or fallback pricing."""
        # Try to get cost from config first
        cfg = self.config.config.get("step4", {})
        models_key = f"{provider.lower()}_models"
        if models_key in cfg:
            for m in cfg[models_key]:
                if m.get("api_id") == model:
                    # Return cost per website, multiply by 1.5 for contact extraction
                    # Check for cost_per_1k first, then cost_per_100
                    if "cost_per_1k" in m:
                        return (m.get("cost_per_1k", 1.0) / 1000) * 1.5
                    elif "cost_per_100" in m:
                        return (m.get("cost_per_100", 0.1) / 100) * 1.5
                    else:
                        return (1.0 / 1000) * 1.5
        
        # Fallback: estimate based on tokens
        input_tokens = len(content) / 4
        output_tokens = 2000  # Contact extraction needs more output tokens
        
        if provider.lower() == "openai":
            if "gpt-4o-mini" in model.lower() or "gpt-4.1-mini" in model.lower():
                input_cost, output_cost = 0.00015, 0.0006
            elif "gpt-4o" in model.lower() or "gpt-4.1" in model.lower():
                input_cost, output_cost = 0.0025, 0.01
            else:
                input_cost, output_cost = 0.0025, 0.01
        elif provider.lower() == "gemini":
            if "flash" in model.lower() and "lite" in model.lower():
                input_cost, output_cost = 0.000075, 0.0003
            elif "flash" in model.lower():
                input_cost, output_cost = 0.0001, 0.0004
            elif "pro" in model.lower():
                input_cost, output_cost = 0.00125, 0.005
            else:
                input_cost, output_cost = 0.0001, 0.0004
        else:  # claude
            if "haiku" in model.lower():
                input_cost, output_cost = 0.0008, 0.004
            elif "opus" in model.lower():
                input_cost, output_cost = 0.015, 0.075
            else:  # sonnet
                input_cost, output_cost = 0.003, 0.015
        
        return (input_tokens * input_cost / 1000) + (output_tokens * output_cost / 1000)
    
    def get_website_content(self, url: str) -> Optional[str]:
        """Get scraped content for a website."""
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
    
    def extract_contacts(self, url: str, content: str) -> Dict[str, Any]:
        """Extract contacts from website content using AI."""
        cfg_step4 = self.config.config["step4"]
        cfg_step5 = self.config.config.get("step5", {})
        
        api_key = cfg_step4.get("api_key", "")
        model = cfg_step4.get("model", "claude-3-5-sonnet-20241022")
        provider = cfg_step4.get("provider_choice") or cfg_step4.get("api_provider", "claude")
        
        if not api_key:
            self.logger.error("❌ ERROR: API key not configured for contact extraction")
            return None
        
        # Check credit limit
        estimated_cost = self.estimate_api_cost(content, model, provider)
        if self.credit_used + estimated_cost > self.credit_limit:
            self.logger.warning(f"Credit limit reached: ${self.credit_used:.2f}/${self.credit_limit:.2f}")
            return None
        
        max_chars = 15000
        if len(content) > max_chars:
            content = content[:max_chars] + "... [truncated]"
        
        # Get custom prompt from config
        extraction_prompt = cfg_step5.get("contact_extraction_prompt", "").strip()
        if not extraction_prompt:
            extraction_prompt = """Extract contact information from this website content. Look for:
1. A general company contact email (like info@, contact@, hello@, sales@)
2. Individual team members/employees with their contact details

For each person found, extract:
- Full name
- Position/Title  
- Email address
- Phone number (if available)

Focus on finding decision-makers, executives, and key personnel."""
        
        # Extract domain for email detection
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace('www.', '')
        
        # Get scoring criteria from config
        scoring_prompt = cfg_step5.get("contact_scoring_prompt", "").strip()
        if not scoring_prompt:
            scoring_prompt = """SENIORITY SCORE (1-4):
- 4 = Highest: CEO, Founder, Co-Founder, Chairman, President, Owner
- 3 = High: Chief Officers (CSO, CTO, CMO, COO), Vice President, EVP, SVP, Global Head
- 2 = Medium: Director, Senior Director, Executive Director, Scientific Advisor
- 1 = Lower: Associate Director, Manager, Scientist, Principal Investigator

FIT SCORE (1-4) for preclinical/translational research sales:
- 4 = Excellent fit: Preclinical, Translational, Discovery roles, or Founders/CEOs
- 3 = Good fit: Scientific/Research leadership, R&D, In Vivo/In Vitro
- 2 = Moderate fit: Oncology/cancer focus, Drug Development, Pharmacology
- 1 = Lower fit: Business Development, Operations, administrative roles"""
        
        prompt = f"""You are an expert at extracting and scoring contact information from website content.

{extraction_prompt}

SCORING CRITERIA:
{scoring_prompt}

Website URL: {url}
Domain: {domain}

Website Content:
{content}

Please extract all contacts found AND score each one. Return in the following JSON format:
{{
    "company_email": "<general company contact email like info@domain.com or null if not found>",
    "contacts": [
        {{
            "full_name": "<person's full name>",
            "position": "<job title/position>",
            "email": "<email address or null>",
            "phone": "<phone number or null>",
            "seniority_score": <integer 1-4>,
            "fit_score": <integer 1-4>,
            "total_score": <sum of seniority + fit, integer 2-8>
        }}
    ]
}}

Important:
- Only include contacts that appear to be employees/team members of this company
- Prioritize executives, leadership, and decision-makers
- Score each contact based on their title using the criteria above
- Return up to 10 contacts maximum, sorted by total_score (highest first)
- If no contacts are found, return an empty contacts array
- Only include real contact information found in the content, do not make up data
"""
        
        for attempt in range(cfg_step4.get("max_retries", 3)):
            try:
                delay = self.rate_limiter.get_delay()
                if delay > 0:
                    time.sleep(delay)
                
                if provider.lower() == "openai":
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    }
                    api_url = "https://api.openai.com/v1/chat/completions"
                    payload = {
                        "model": model,
                        "max_tokens": cfg_step4.get("max_tokens", 4000),
                        "messages": [{"role": "user", "content": prompt}]
                    }
                elif provider.lower() == "gemini":
                    gemini_key = cfg_step4.get("gemini_api_key", api_key)
                    headers = {"Content-Type": "application/json"}
                    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
                    payload = {
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"maxOutputTokens": cfg_step4.get("max_tokens", 4000)}
                    }
                else:
                    headers = {
                        "x-api-key": api_key,
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01"
                    }
                    api_url = "https://api.anthropic.com/v1/messages"
                    payload = {
                        "model": model,
                        "max_tokens": cfg_step4.get("max_tokens", 4000),
                        "messages": [{"role": "user", "content": prompt}]
                    }
                
                response = requests.post(api_url, headers=headers, json=payload, timeout=60)
                
                if response.status_code == 200:
                    self.rate_limiter.record_success()
                    result = response.json()
                    
                    if provider.lower() == "openai":
                        response_text = result["choices"][0]["message"]["content"]
                    elif provider.lower() == "gemini":
                        response_text = result["candidates"][0]["content"]["parts"][0]["text"]
                    else:
                        response_text = result["content"][0]["text"]
                    
                    # Update credit usage
                    self.credit_used += estimated_cost
                    
                    # Parse JSON response
                    json_match = re.search(r'\{[\s\S]*\}', response_text)
                    if json_match:
                        try:
                            contacts_data = json.loads(json_match.group())
                            return contacts_data
                        except json.JSONDecodeError:
                            self.logger.warning(f"Failed to parse contact JSON for {url}")
                            return None
                    return None
                    
                elif response.status_code == 429:
                    self.rate_limiter.record_rate_limit()
                    continue
                else:
                    self.logger.error(f"API error for {url}: {response.status_code}")
                    if response.status_code == 401:
                        return None
                    
            except Exception as e:
                self.logger.error(f"Error extracting contacts for {url}: {e}")
                if attempt < cfg_step4.get("max_retries", 3) - 1:
                    time.sleep(2 ** attempt)
        
        return None
    
    def score_contact(self, contact: Dict[str, str]) -> Dict[str, int]:
        """Score a contact based on their title using AI."""
        cfg_step4 = self.config.config["step4"]
        cfg_step5 = self.config.config.get("step5", {})
        
        api_key = cfg_step4.get("api_key", "")
        model = cfg_step4.get("model", "claude-3-5-sonnet-20241022")
        provider = cfg_step4.get("provider_choice") or cfg_step4.get("api_provider", "claude")
        
        if not api_key or not contact.get("position"):
            return {"seniority": 1, "fit": 1, "total_score": 2}
        
        scoring_prompt = cfg_step5.get("contact_scoring_prompt", "").strip()
        if not scoring_prompt:
            scoring_prompt = """Score this contact based on their title/position for B2B sales outreach in the healthcare/medical device/preclinical research industry.

SENIORITY SCORE (1-4):
- 4 = Highest: CEO, Founder, Co-Founder, Chairman, President, Owner
- 3 = High: Chief Officers (CSO, CTO, CMO, COO), Vice President, EVP, SVP, Global Head
- 2 = Medium: Director, Senior Director, Executive Director, Scientific Advisor
- 1 = Lower: Associate Director, Manager, Scientist, Principal Investigator

FIT SCORE (1-4):
- 4 = Excellent fit: Preclinical, Translational, Discovery roles, or Founders/CEOs
- 3 = Good fit: Scientific/Research leadership, R&D, In Vivo/In Vitro
- 2 = Moderate fit: Oncology/cancer focus, Drug Development, Pharmacology
- 1 = Lower fit: Business Development, Operations, administrative roles"""
        
        prompt = f"""{scoring_prompt}

Contact Information:
- Name: {contact.get('full_name', 'Unknown')}
- Position/Title: {contact.get('position', 'Unknown')}

Please score this contact and return ONLY a JSON object:
{{
    "seniority": <integer 1-4>,
    "fit": <integer 1-4>,
    "reasoning": "<brief explanation>"
}}"""
        
        try:
            delay = self.rate_limiter.get_delay()
            if delay > 0:
                time.sleep(delay)
            
            if provider.lower() == "openai":
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                api_url = "https://api.openai.com/v1/chat/completions"
                payload = {
                    "model": model,
                    "max_tokens": 500,
                    "messages": [{"role": "user", "content": prompt}]
                }
            elif provider.lower() == "gemini":
                gemini_key = cfg_step4.get("gemini_api_key", api_key)
                headers = {"Content-Type": "application/json"}
                api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 500}
                }
            else:
                headers = {
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01"
                }
                api_url = "https://api.anthropic.com/v1/messages"
                payload = {
                    "model": model,
                    "max_tokens": 500,
                    "messages": [{"role": "user", "content": prompt}]
                }
            
            response = requests.post(api_url, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                self.rate_limiter.record_success()
                result = response.json()
                
                if provider.lower() == "openai":
                    response_text = result["choices"][0]["message"]["content"]
                elif provider.lower() == "gemini":
                    response_text = result["candidates"][0]["content"]["parts"][0]["text"]
                else:
                    response_text = result["content"][0]["text"]
                
                # Parse JSON response
                json_match = re.search(r'\{[\s\S]*?\}', response_text)
                if json_match:
                    try:
                        score_data = json.loads(json_match.group())
                        seniority = int(score_data.get("seniority", 1))
                        fit = int(score_data.get("fit", 1))
                        # Clamp values to 1-4
                        seniority = max(1, min(4, seniority))
                        fit = max(1, min(4, fit))
                        return {
                            "seniority": seniority,
                            "fit": fit,
                            "total_score": seniority + fit
                        }
                    except (json.JSONDecodeError, ValueError):
                        pass
            
        except Exception as e:
            self.logger.debug(f"Error scoring contact: {e}")
        
        return {"seniority": 1, "fit": 1, "total_score": 2}
    
    def run_contact_extraction(self) -> bool:
        """Run contact extraction on AI analysis results."""
        cfg_step5 = self.config.config.get("step5", {})
        
        if not cfg_step5.get("enabled", True):
            self.logger.info("Contact extraction is disabled")
            return True
        
        cfg_step4 = self.config.config["step4"]
        self.credit_limit = cfg_step4.get("credit_limit", 50.0)
        
        api_key = cfg_step4.get("api_key", "")
        if not api_key:
            error_msg = "❌ ERROR: API key is not configured!"
            self.logger.error(error_msg)
            if self.progress_callback:
                self.progress_callback(error_msg)
            return False
        
        # Find the most recent AI analysis results
        import glob
        ai_files = glob.glob("data/ai_analysis_results_*.csv")
        if not ai_files:
            self.logger.error("No AI analysis results found")
            return False
        ai_results_path = max(ai_files, key=os.path.getctime)
        
        run_id = self.comprehensive_logger.get_run_id()
        contacts_path = f"data/contacts_results_{run_id}.csv"
        
        if not os.path.exists(ai_results_path):
            self.logger.error(f"AI results not found: {ai_results_path}")
            return False
        
        # Load AI analysis results
        ai_df = pd.read_csv(ai_results_path)
        
        # Filter to good leads only
        if 'is_good_lead' in ai_df.columns:
            leads_df = ai_df[ai_df['is_good_lead'] == True].copy()
        else:
            leads_df = ai_df.copy()
        
        if len(leads_df) == 0:
            self.logger.info("No good leads to extract contacts from")
            return True
        
        self.logger.info(f"Extracting contacts for {len(leads_df)} leads")
        if self.progress_callback:
            self.progress_callback(f"Starting contact extraction for {len(leads_df)} leads...")
        
        max_contacts = cfg_step5.get("max_contacts", 5)
        results = []
        processed_count = 0
        
        for idx, row in leads_df.iterrows():
            url = row.get('url', '')
            if not url:
                continue
            
            processed_count += 1
            progress_msg = f"[{processed_count}/{len(leads_df)}] Extracting contacts: {url}"
            if self.logging_level in ("moderate", "detailed"):
                self.logger.info(progress_msg)
            if self.progress_callback:
                self.progress_callback(progress_msg)
            
            content = self.get_website_content(url)
            if not content:
                if self.logging_level != "none":
                    self.logger.warning(f"No content for {url}")
                # Add row with empty contact fields
                result_row = row.to_dict()
                result_row['company_email'] = ''
                for i in range(1, max_contacts + 1):
                    result_row[f'contact_{i}_name'] = ''
                    result_row[f'contact_{i}_position'] = ''
                    result_row[f'contact_{i}_email'] = ''
                    result_row[f'contact_{i}_phone'] = ''
                    result_row[f'contact_{i}_score'] = ''
                results.append(result_row)
                continue
            
            # Extract contacts
            contacts_data = self.extract_contacts(url, content)
            
            result_row = row.to_dict()
            result_row['company_email'] = ''
            
            if contacts_data:
                result_row['company_email'] = self._sanitize_for_csv(contacts_data.get('company_email', '') or '')
                
                contacts = contacts_data.get('contacts', [])
                
                # Contacts are already scored by AI in the same call - no separate API calls needed!
                # Just sort by total_score (already provided by AI)
                scored_contacts = sorted(
                    contacts[:10], 
                    key=lambda x: x.get('total_score', 0), 
                    reverse=True
                )
                
                # Log to comprehensive system
                self.comprehensive_logger.log_lead_contact_extraction(
                    url, run_id, 
                    contacts_data.get('company_email', ''), 
                    contacts
                )
                self.comprehensive_logger.log_lead_contact_scoring(url, run_id, scored_contacts)
                
                # Add top contacts to result
                for i in range(1, max_contacts + 1):
                    if i <= len(scored_contacts):
                        c = scored_contacts[i-1]
                        result_row[f'contact_{i}_name'] = self._sanitize_for_csv(c.get('full_name', '') or '')
                        result_row[f'contact_{i}_position'] = self._sanitize_for_csv(c.get('position', '') or '')
                        result_row[f'contact_{i}_email'] = self._sanitize_for_csv(c.get('email', '') or '')
                        result_row[f'contact_{i}_phone'] = self._sanitize_for_csv(c.get('phone', '') or '')
                        # Score format: "seniority/fit (total)" - scores come from AI now
                        seniority = c.get('seniority_score', 1)
                        fit = c.get('fit_score', 1)
                        total = c.get('total_score', seniority + fit)
                        result_row[f'contact_{i}_score'] = f"{seniority}/{fit} ({total})"
                    else:
                        result_row[f'contact_{i}_name'] = ''
                        result_row[f'contact_{i}_position'] = ''
                        result_row[f'contact_{i}_email'] = ''
                        result_row[f'contact_{i}_phone'] = ''
                        result_row[f'contact_{i}_score'] = ''
            else:
                # No contacts found
                for i in range(1, max_contacts + 1):
                    result_row[f'contact_{i}_name'] = ''
                    result_row[f'contact_{i}_position'] = ''
                    result_row[f'contact_{i}_email'] = ''
                    result_row[f'contact_{i}_phone'] = ''
                    result_row[f'contact_{i}_score'] = ''
            
            results.append(result_row)
            
            # Log credit usage
            self.logger.info(f"Credit used: ${self.credit_used:.2f}/${self.credit_limit:.2f}")
            
            # Check credit limit
            if self.credit_used >= self.credit_limit:
                self.logger.warning("Credit limit reached, stopping contact extraction")
                if self.progress_callback:
                    self.progress_callback("⚠️ Credit limit reached")
                break
        
        # Save results with processing dates
        if results:
            # Add processing_date to all results
            for r in results:
                if 'processing_date' not in r:
                    r['processing_date'] = datetime.now(timezone.utc).isoformat()
                # Sanitize all string fields
                for key in list(r.keys()):
                    if isinstance(r[key], str):
                        r[key] = self._sanitize_for_csv(r[key])
            
            results_df = pd.DataFrame(results)
            results_df.to_csv(contacts_path, index=False)
            self.logger.info(f"Step 5 complete: Contact extraction results saved to {contacts_path}")
            
            # Count contacts found
            contacts_found = sum(1 for r in results if r.get('contact_1_name'))
            emails_found = sum(1 for r in results if r.get('company_email'))
            self.logger.info(f"Summary: Found contacts for {contacts_found}/{len(results)} leads, {emails_found} company emails")
            
            if self.progress_callback:
                self.progress_callback(f"✓ Contact extraction complete: {contacts_found} leads with contacts, {emails_found} company emails")
        else:
            self.logger.warning("No contact extraction results")
        
        return True


# ============================================================
# HISTORICAL TIMING LEARNER (Lightweight)
# ============================================================

class HistoricalTimingLearner:
    """Learns stage timing from historical runs to improve ETA estimates.
    
    Stores minimal data: just stage durations and item counts.
    Uses rolling averages (last 10 runs) to avoid unbounded growth.
    All operations are O(1) - no expensive computations.
    """
    
    HISTORY_FILE = "timing_history.json"
    MAX_HISTORY = 10  # Keep last 10 runs (rolling window)
    
    # Default weights (percentages) - used when no history available
    DEFAULT_WEIGHTS = {1: 15, 2: 25, 3: 10, 4: 40, 5: 10}
    
    def __init__(self):
        self.history = self._load_history()
    
    def _load_history(self) -> dict:
        """Load history from file. O(1) operation."""
        if os.path.exists(self.HISTORY_FILE):
            try:
                with open(self.HISTORY_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {"runs": [], "avg_weights": self.DEFAULT_WEIGHTS.copy()}
    
    def _save_history(self):
        """Save history to file. Called only on run completion."""
        try:
            with open(self.HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, indent=2)
        except:
            pass  # Don't fail if can't save
    
    def record_run(self, stage_durations: Dict[int, float], item_counts: Dict[int, int]):
        """Record timing data from a completed run.
        
        Args:
            stage_durations: {stage_num: seconds_elapsed}
            item_counts: {stage_num: items_processed}
        
        Called once per run completion - very lightweight.
        """
        if not stage_durations:
            return
        
        # Calculate relative weights from this run
        total_duration = sum(stage_durations.values())
        if total_duration < 1:
            return  # Run too short to learn from
        
        run_data = {
            "timestamp": datetime.now().isoformat(),
            "total_seconds": total_duration,
            "stages": {}
        }
        
        for stage, duration in stage_durations.items():
            weight = (duration / total_duration) * 100
            items = item_counts.get(stage, 0)
            run_data["stages"][str(stage)] = {
                "weight": round(weight, 1),
                "seconds": round(duration, 1),
                "items": items,
                "sec_per_item": round(duration / items, 3) if items > 0 else 0
            }
        
        # Add to history (rolling window)
        self.history["runs"].append(run_data)
        if len(self.history["runs"]) > self.MAX_HISTORY:
            self.history["runs"] = self.history["runs"][-self.MAX_HISTORY:]
        
        # Update average weights
        self._recalculate_averages()
        self._save_history()
    
    def _recalculate_averages(self):
        """Recalculate average weights from history. O(n) where n=MAX_HISTORY=10."""
        if not self.history["runs"]:
            self.history["avg_weights"] = self.DEFAULT_WEIGHTS.copy()
            return
        
        # Simple average across all recorded runs
        weight_sums = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        
        for run in self.history["runs"]:
            for stage_str, data in run.get("stages", {}).items():
                stage = int(stage_str)
                if stage in weight_sums:
                    weight_sums[stage] += data.get("weight", 0)
                    counts[stage] += 1
        
        # Calculate averages, fall back to defaults
        avg_weights = {}
        for stage in range(1, 6):
            if counts[stage] > 0:
                avg_weights[stage] = round(weight_sums[stage] / counts[stage], 1)
            else:
                avg_weights[stage] = self.DEFAULT_WEIGHTS[stage]
        
        # Normalize to 100%
        total = sum(avg_weights.values())
        if total > 0:
            for stage in avg_weights:
                avg_weights[stage] = round((avg_weights[stage] / total) * 100, 1)
        
        self.history["avg_weights"] = avg_weights
    
    def get_learned_weights(self) -> Dict[int, float]:
        """Get the learned stage weights. O(1) operation."""
        return self.history.get("avg_weights", self.DEFAULT_WEIGHTS.copy())
    
    def get_estimated_duration(self, stage: int, item_count: int) -> float:
        """Estimate duration for a stage based on historical per-item rates.
        
        Returns estimated seconds, or 0 if no data available.
        """
        if not self.history["runs"]:
            return 0
        
        # Get average seconds per item from recent runs
        total_rate = 0
        count = 0
        
        for run in self.history["runs"][-5:]:  # Last 5 runs only
            stage_data = run.get("stages", {}).get(str(stage), {})
            rate = stage_data.get("sec_per_item", 0)
            if rate > 0:
                total_rate += rate
                count += 1
        
        if count > 0:
            avg_rate = total_rate / count
            return avg_rate * item_count
        
        return 0
    
    def get_confidence_level(self) -> str:
        """Get confidence level based on amount of historical data."""
        num_runs = len(self.history.get("runs", []))
        if num_runs == 0:
            return "No history (using defaults)"
        elif num_runs < 3:
            return f"Low ({num_runs} runs)"
        elif num_runs < 7:
            return f"Medium ({num_runs} runs)"
        else:
            return f"High ({num_runs} runs)"


# Global timing learner instance (singleton)
_timing_learner = None

def get_timing_learner() -> HistoricalTimingLearner:
    """Get the global timing learner instance."""
    global _timing_learner
    if _timing_learner is None:
        _timing_learner = HistoricalTimingLearner()
    return _timing_learner


# ============================================================
# RUN STATS TRACKER (Lightweight Progress Tracking)
# ============================================================

class RunStatsTracker:
    """Lightweight tracker for pipeline run statistics."""
    
    # Stage definitions - weights loaded from history
    STAGE_NAMES = {
        1: {"name": "Discovery", "description": "Finding websites via search API"},
        2: {"name": "Scraping", "description": "Extracting content from websites"},
        3: {"name": "Scoring", "description": "Evaluating websites with factors"},
        4: {"name": "AI Analysis", "description": "AI-powered lead qualification"},
        5: {"name": "Contacts", "description": "Extracting contact information"},
    }
    
    # Default weights (overridden by learned weights)
    DEFAULT_WEIGHTS = {1: 15, 2: 25, 3: 10, 4: 40, 5: 10}
    
    def __init__(self):
        # Load learned weights from history
        learner = get_timing_learner()
        self.stage_weights = learner.get_learned_weights()
        self.confidence = learner.get_confidence_level()
        
        # Build STAGES dict with learned weights
        self.STAGES = {}
        for stage, info in self.STAGE_NAMES.items():
            self.STAGES[stage] = {
                "name": info["name"],
                "description": info["description"],
                "weight": self.stage_weights.get(stage, self.DEFAULT_WEIGHTS[stage])
            }
        
        self.reset()
    
    def reset(self):
        """Reset all tracking state."""
        self.start_time = None
        self.current_stage = 0
        self.current_batch = 0
        self.total_batches = 0
        self.stage_description = "Initializing..."
        
        # Website counts
        self.total_websites_to_visit = 0
        self.websites_discovered = 0
        self.websites_scraped = 0
        self.websites_scored = 0
        self.websites_analyzed = 0
        self.websites_with_contacts = 0
        
        # Search stats
        self.total_search_combinations = 0
        self.searches_completed = 0
        
        # Timing for ETA calculation
        self.stage_start_times = {}
        self.stage_end_times = {}
        self.batch_times = []  # Rolling window for ETA
        
        # Estimated total websites (statistical)
        self.estimated_total_websites = 0
        
    def start_run(self):
        """Mark the start of a pipeline run."""
        self.reset()
        self.start_time = time.time()
        
    def start_stage(self, stage: int, total_batches: int = 0, description: str = None):
        """Start a new pipeline stage."""
        self.current_stage = stage
        self.current_batch = 0
        self.total_batches = total_batches
        self.stage_start_times[stage] = time.time()
        if description:
            self.stage_description = description
        elif stage in self.STAGES:
            self.stage_description = self.STAGES[stage]["description"]
        self.batch_times = []  # Reset batch timing for new stage
        
    def update_batch(self, batch: int, total: int = None, description: str = None):
        """Update current batch progress within a stage."""
        if self.current_batch > 0 and len(self.batch_times) < 20:
            # Track time per batch for ETA (keep last 20)
            self.batch_times.append(time.time())
        self.current_batch = batch
        if total is not None:
            self.total_batches = total
        if description:
            self.stage_description = description
            
    def complete_stage(self, stage: int):
        """Mark a stage as complete."""
        self.stage_end_times[stage] = time.time()
        
    def set_search_combinations(self, total: int):
        """Set total search combinations for Stage 1."""
        self.total_search_combinations = total
        self.total_batches = total
        # Estimate: each search returns ~10-30 unique websites
        self.estimated_total_websites = total * 15  # Conservative average
        
    def set_websites_discovered(self, count: int):
        """Set count of websites discovered."""
        self.websites_discovered = count
        self.total_websites_to_visit = count
        # Update estimate now that we have real data
        self.estimated_total_websites = count
        
    def set_websites_to_scrape(self, count: int):
        """Set count of websites to scrape."""
        self.total_websites_to_visit = count
        
    def get_elapsed_time(self) -> float:
        """Get elapsed time in seconds."""
        if not self.start_time:
            return 0
        return time.time() - self.start_time
    
    def get_elapsed_formatted(self) -> str:
        """Get formatted elapsed time string."""
        elapsed = self.get_elapsed_time()
        hours, remainder = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"
    
    def get_percent_complete(self) -> float:
        """Calculate overall completion percentage."""
        if self.current_stage == 0:
            return 0.0
            
        # Calculate based on stage weights and batch progress
        completed_weight = sum(
            self.STAGES[s]["weight"] 
            for s in range(1, self.current_stage) 
            if s in self.STAGES
        )
        
        # Add partial weight for current stage
        if self.current_stage in self.STAGES:
            stage_weight = self.STAGES[self.current_stage]["weight"]
            if self.total_batches > 0:
                stage_progress = self.current_batch / self.total_batches
            else:
                stage_progress = 0.5  # Assume halfway if no batches
            completed_weight += stage_weight * stage_progress
        
        total_weight = sum(s["weight"] for s in self.STAGES.values())
        return min(100.0, (completed_weight / total_weight) * 100)
    
    def get_eta_formatted(self) -> str:
        """Estimate remaining time based on progress rate."""
        elapsed = self.get_elapsed_time()
        percent = self.get_percent_complete()
        
        if percent <= 1 or elapsed < 10:
            return "Calculating..."
        
        # Simple linear projection
        total_estimated = elapsed / (percent / 100)
        remaining = total_estimated - elapsed
        
        if remaining < 0:
            return "Almost done..."
        
        hours, remainder = divmod(int(remaining), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            return f"~{hours}h {minutes}m"
        elif minutes > 0:
            return f"~{minutes}m {seconds}s"
        else:
            return f"~{seconds}s"
    
    def get_stage_name(self) -> str:
        """Get current stage name."""
        if self.current_stage in self.STAGES:
            return f"Stage {self.current_stage}: {self.STAGES[self.current_stage]['name']}"
        return "Initializing"
    
    def get_batch_info(self) -> str:
        """Get batch info string."""
        if self.total_batches > 0:
            return f"{self.current_batch} / {self.total_batches}"
        return "—"
    
    def record_completed_run(self):
        """Record timing data from this completed run to improve future estimates.
        
        Called once when run completes - very lightweight operation.
        """
        if not self.stage_start_times:
            return  # Nothing to record
        
        # Calculate stage durations
        stage_durations = {}
        for stage in range(1, 6):
            start = self.stage_start_times.get(stage)
            end = self.stage_end_times.get(stage)
            if start and end:
                stage_durations[stage] = end - start
        
        # Get item counts for each stage
        item_counts = {
            1: self.total_search_combinations,
            2: self.websites_scraped or self.websites_discovered,
            3: self.websites_scored or self.websites_scraped,
            4: self.websites_analyzed,
            5: self.websites_with_contacts
        }
        
        # Record to learner
        learner = get_timing_learner()
        learner.record_run(stage_durations, item_counts)
    
    def get_confidence_info(self) -> str:
        """Get confidence level info for display."""
        return self.confidence


# ============================================================
# AI-ASSISTED SETUP GUI
# ============================================================

class AIAssistedSetupGUI:
    """GUI for AI-assisted lead generation setup."""
    
    def __init__(self):
        self.config = UnifiedConfig()
        self.root = tk.Tk()
        self.root.title("AI-Assisted Setup - Sherpa Lead Generator")
        self.root.geometry("600x550")
        self.root.resizable(True, True)
        
        # Make maximized (windowed fullscreen - keeps title bar and close button)
        self.root.state('zoomed')
        
        # Show selection screen first
        self.setup_selection_screen()
    
    def setup_selection_screen(self):
        """Show the initial selection screen (Option A vs B)."""
        # Clear any existing widgets
        for widget in self.root.winfo_children():
            widget.destroy()
        
        main_frame = ttk.Frame(self.root, padding=30)
        main_frame.pack(fill='both', expand=True)
        
        # Title
        ttk.Label(main_frame, text="AI-Assisted Setup", 
                  font=('Arial', 18, 'bold')).pack(pady=(0, 5))
        ttk.Label(main_frame, text="Choose how you'd like to describe your business", 
                  font=('Arial', 10), foreground='gray').pack(pady=(0, 30))
        
        # ============================================================
        # AI CONFIGURATION (shown on selection screen)
        # ============================================================
        ai_frame = ttk.LabelFrame(main_frame, text="AI Configuration", padding=10)
        ai_frame.pack(fill='x', pady=(0, 20))
        
        self._setup_ai_config(ai_frame)
        
        # ============================================================
        # OPTION BUTTONS
        # ============================================================
        options_frame = ttk.Frame(main_frame)
        options_frame.pack(fill='both', expand=True, pady=10)
        
        # Option A: Single Prompt
        option_a_frame = ttk.LabelFrame(options_frame, text="Option A: Single Prompt", padding=15)
        option_a_frame.pack(fill='x', pady=10)
        
        ttk.Label(option_a_frame, 
                  text="Describe everything in one text box. Best for AI-generated responses\nor if you prefer free-form writing.",
                  wraplength=500, justify='left').pack(anchor='w')
        ttk.Button(option_a_frame, text="Use Single Prompt →", 
                   command=lambda: self.show_input_screen("single")).pack(anchor='e', pady=(10, 0))
        
        # Option B: Guided Questions
        option_b_frame = ttk.LabelFrame(options_frame, text="Option B: Guided Questions", padding=15)
        option_b_frame.pack(fill='x', pady=10)
        
        ttk.Label(option_b_frame, 
                  text="Answer individual questions step by step. Best if you prefer\nstructured inputs with examples for each field.",
                  wraplength=500, justify='left').pack(anchor='w')
        ttk.Button(option_b_frame, text="Use Guided Questions →", 
                   command=lambda: self.show_input_screen("guided")).pack(anchor='e', pady=(10, 0))
        
        # Back button
        ttk.Button(main_frame, text="← Back", command=self._go_back).pack(anchor='w', pady=(20, 0))
    
    def _setup_ai_config(self, parent_frame):
        """Setup AI configuration widgets."""
        # Load current config
        step4 = self.config.config.get("step4", {})
        step1 = self.config.config.get("step1", {})
        current_provider = step4.get("api_provider", "claude")
        current_model_choice = step4.get("model_choice", "model_1")
        current_api_key = step4.get("api_key", "")
        current_gemini_key = step4.get("gemini_api_key", "")
        
        # Load search API config
        current_search_api = step1.get("api_choice", "serper")
        current_search_api_key = step1.get("api_key", "")
        
        # Load selection model config (if exists)
        selection_provider = step4.get("selection_api_provider", current_provider)
        selection_model_choice = step4.get("selection_model_choice", current_model_choice)
        selection_api_key = step4.get("selection_api_key", "")
        selection_gemini_key = step4.get("selection_gemini_key", "")
        use_same_model = step4.get("use_same_model_for_selection", True)
        num_websites = step4.get("num_websites", 100)
        
        # Build model list from all providers
        self.all_models = []
        for provider in ["claude", "openai", "gemini"]:
            models_key = f"{provider}_models"
            models = step4.get(models_key, [])
            for i, model in enumerate(models):
                model_name = model.get("name", f"Model {i+1}")
                model_id = model.get("api_id", "")
                
                # Check for cost_per_1k first, then cost_per_100 (convert to per 1k)
                if "cost_per_1k" in model:
                    cost = float(model.get("cost_per_1k", 0))
                elif "cost_per_100" in model:
                    # Convert cost_per_100 to cost_per_1k (multiply by 10)
                    cost = float(model.get("cost_per_100", 0)) * 10
                else:
                    cost = 0
                
                self.all_models.append({
                    "display": f"{provider.title()}: {model_name} (${cost:.2f}/1K)",
                    "provider": provider,
                    "model_index": i,
                    "api_id": model_id,
                    "name": model_name,
                    "cost_per_1k": cost
                })
        
        # Number of Websites
        num_websites_row = ttk.Frame(parent_frame)
        num_websites_row.pack(fill='x', pady=5)
        ttk.Label(num_websites_row, text="Max Number of Unique Websites Searched:").pack(side='left')
        
        self.num_websites_var = tk.StringVar(value=str(num_websites))
        num_websites_entry = ttk.Entry(num_websites_row, textvariable=self.num_websites_var, width=15)
        num_websites_entry.pack(side='left', padx=10)
        num_websites_entry.bind('<KeyRelease>', lambda e: self._update_cost_estimate())
        
        # Estimated Cost Display
        self.cost_estimate_label = ttk.Label(num_websites_row, text="", foreground='blue')
        self.cost_estimate_label.pack(side='left', padx=10)
        
        # Separator
        ttk.Separator(parent_frame, orient='horizontal').pack(fill='x', pady=10)
        
        # ============================================================
        # SEARCH MODEL (for actual search/analysis)
        # ============================================================
        search_label = ttk.Label(parent_frame, text="Search Model (for website analysis):", 
                                 font=('Arial', 10, 'bold'))
        search_label.pack(anchor='w', pady=(5, 5))
        
        # Model selection
        model_row = ttk.Frame(parent_frame)
        model_row.pack(fill='x', pady=5)
        ttk.Label(model_row, text="AI Model:").pack(side='left')
        
        self.model_var = tk.StringVar()
        model_display_list = [m["display"] for m in self.all_models]
        self.model_combo = ttk.Combobox(model_row, textvariable=self.model_var, 
                                         values=model_display_list, width=40, state='readonly')
        self.model_combo.pack(side='left', padx=10)
        
        # Set current selection based on config
        try:
            model_idx = int(current_model_choice.replace("model_", "")) - 1
            for i, m in enumerate(self.all_models):
                if m["provider"] == current_provider and m["model_index"] == model_idx:
                    self.model_combo.current(i)
                    break
        except:
            if self.all_models:
                self.model_combo.current(0)
        
        # Bind model change to update API key field and cost estimate
        self.model_combo.bind("<<ComboboxSelected>>", lambda e: (self._on_model_change(e), self._update_cost_estimate()))
        
        # API Key
        key_row = ttk.Frame(parent_frame)
        key_row.pack(fill='x', pady=5)
        ttk.Label(key_row, text="API Key:").pack(side='left')
        
        self.api_key_var = tk.StringVar()
        # Set initial key based on provider
        if current_provider == "gemini":
            self.api_key_var.set(current_gemini_key)
        else:
            self.api_key_var.set(current_api_key)
        
        self.api_key_entry = ttk.Entry(key_row, textvariable=self.api_key_var, width=45, show='*')
        self.api_key_entry.pack(side='left', padx=10)
        
        # Show/hide key button
        self.show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(key_row, text="Show", variable=self.show_key, 
                        command=self._toggle_key_visibility).pack(side='left')
        
        # Separator
        ttk.Separator(parent_frame, orient='horizontal').pack(fill='x', pady=10)
        
        # ============================================================
        # SELECTION MODEL (for selecting search inputs)
        # ============================================================
        selection_label = ttk.Label(parent_frame, text="Selection Model (for selecting search inputs):", 
                                    font=('Arial', 10, 'bold'))
        selection_label.pack(anchor='w', pady=(5, 5))
        
        # Use Same Model checkbox
        self.use_same_model_var = tk.BooleanVar(value=use_same_model)
        use_same_check = ttk.Checkbutton(parent_frame, text="Use Same Model", 
                                         variable=self.use_same_model_var,
                                         command=self._toggle_selection_model_fields)
        use_same_check.pack(anchor='w', pady=5)
        
        # Selection Model selection frame
        self.selection_model_frame = ttk.Frame(parent_frame)
        self.selection_model_frame.pack(fill='x', pady=5)
        
        # Model selection
        selection_model_row = ttk.Frame(self.selection_model_frame)
        selection_model_row.pack(fill='x', pady=5)
        ttk.Label(selection_model_row, text="AI Model:").pack(side='left')
        
        self.selection_model_var = tk.StringVar()
        self.selection_model_combo = ttk.Combobox(selection_model_row, textvariable=self.selection_model_var, 
                                                   values=model_display_list, width=40, state='readonly')
        self.selection_model_combo.pack(side='left', padx=10)
        
        # Set current selection based on config
        try:
            selection_model_idx = int(selection_model_choice.replace("model_", "")) - 1
            for i, m in enumerate(self.all_models):
                if m["provider"] == selection_provider and m["model_index"] == selection_model_idx:
                    self.selection_model_combo.current(i)
                    break
        except:
            if self.all_models:
                self.selection_model_combo.current(0)
        
        # Bind model change to update cost estimate
        self.selection_model_combo.bind("<<ComboboxSelected>>", lambda e: self._update_cost_estimate())
        
        # Selection API Key
        selection_key_row = ttk.Frame(self.selection_model_frame)
        selection_key_row.pack(fill='x', pady=5)
        ttk.Label(selection_key_row, text="API Key:").pack(side='left')
        
        self.selection_api_key_var = tk.StringVar()
        # Set initial key based on provider
        if selection_provider == "gemini":
            self.selection_api_key_var.set(selection_gemini_key if selection_gemini_key else current_gemini_key)
        else:
            self.selection_api_key_var.set(selection_api_key if selection_api_key else current_api_key)
        
        self.selection_api_key_entry = ttk.Entry(selection_key_row, textvariable=self.selection_api_key_var, width=45, show='*')
        self.selection_api_key_entry.pack(side='left', padx=10)
        
        # Show/hide key button
        self.selection_show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(selection_key_row, text="Show", variable=self.selection_show_key, 
                        command=self._toggle_selection_key_visibility).pack(side='left')
        
        # Initially hide if using same model
        if use_same_model:
            self.selection_model_frame.pack_forget()
        
        # Add custom model button
        ttk.Button(parent_frame, text="+ Add Custom Model", 
                   command=self._add_custom_model).pack(anchor='w', pady=(10, 0))
        
        # Initial cost estimate
        self._update_cost_estimate()
    
    def show_input_screen(self, mode):
        """Show the input screen based on selected mode."""
        # Clear existing widgets
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # Resize window for input screen and maximize
        self.root.geometry("750x800")
        self.root.state('zoomed')  # Windowed fullscreen
        
        # Create scrollable canvas
        canvas = tk.Canvas(self.root, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        def _on_mousewheel(event):
            # Handle both mouse wheel and touchpad - ensure at least 1 unit scroll
            if event.delta == 0:
                return
            direction = -1 if event.delta > 0 else 1
            units = max(1, abs(event.delta) // 120)
            canvas.yview_scroll(direction * units, "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        # Pack scrollbar FIRST so it gets space before canvas expands
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        main_frame = ttk.Frame(scrollable_frame, padding=20)
        main_frame.pack(fill='both', expand=True)
        
        if mode == "single":
            self._build_single_prompt_screen(main_frame)
        else:
            self._build_guided_screen(main_frame)
    
    def _build_single_prompt_screen(self, parent):
        """Build the single prompt input screen."""
        self.guided_mode = False  # Track that we're in single prompt mode
        
        ttk.Label(parent, text="Single Prompt Mode", 
                  font=('Arial', 16, 'bold')).pack(pady=(0, 5))
        ttk.Label(parent, text="Describe everything about your business and ideal customers", 
                  font=('Arial', 10), foreground='gray').pack(pady=(0, 15))
        
        # Comprehensive description for AI context
        self.single_prompt_description = self._get_single_prompt_description()
        
        # Create scrollable frame for description
        desc_frame = ttk.Frame(parent)
        desc_frame.pack(fill='x', pady=(0, 10))
        
        desc_text = tk.Text(desc_frame, width=85, height=20, wrap='word', 
                           foreground='#555555', background='#f8f8f8', 
                           relief='flat', padx=10, pady=10)
        desc_text.insert("1.0", self.single_prompt_description)
        desc_text.config(state='disabled')  # Make read-only
        desc_text.pack(side='left', fill='x', expand=True)
        
        # Scrollbar for description
        desc_scrollbar = ttk.Scrollbar(desc_frame, orient='vertical', command=desc_text.yview)
        desc_scrollbar.pack(side='right', fill='y')
        desc_text.config(yscrollcommand=desc_scrollbar.set)
        
        # Copy button
        copy_btn = ttk.Button(parent, text="📋 Copy Description to Clipboard", 
                              command=lambda: self._copy_to_clipboard(self.single_prompt_description))
        copy_btn.pack(anchor='w', pady=(0, 15))
        
        # Text input
        self.prompt_text = tk.Text(parent, width=85, height=15, wrap='word')
        self.prompt_text.pack(fill='both', expand=True, pady=5)
        
        # Load saved response
        user_inputs = self.config.config.get("user_inputs", {})
        saved = user_inputs.get("single_prompt_response", "")
        if saved:
            self.prompt_text.insert("1.0", saved)
        
        # Buttons
        self._add_bottom_buttons(parent)
    
    def _get_single_prompt_description(self):
        """Return the comprehensive description for single prompt mode."""
        return """═══════════════════════════════════════════════════════════════════════════════
                           SINGLE PROMPT MODE - COMPREHENSIVE GUIDE
═══════════════════════════════════════════════════════════════════════════════

This tool uses AI to find leads that match your ideal customer profile. The more context you 
provide, the better the AI can identify and score potential leads. Copy this description to 
paste into ChatGPT/Claude to help generate your response.

───────────────────────────────────────────────────────────────────────────────
WHAT TO INCLUDE (in any format you prefer):
───────────────────────────────────────────────────────────────────────────────

1. YOUR BUSINESS IDENTITY
   • Company name and website URL (required for exclusion from results)
   • What you sell (product/service type, B2B vs B2C)
   • Price range/deal size (helps filter by company size)
   • Your value proposition (what problem you solve)

2. IDEAL CUSTOMER PROFILE (ICP)
   • Company size: revenue range, employee count
   • Industry/vertical: specific sectors you target
   • Geography: countries, regions, or "anywhere"
   • Company stage: startup, growth, enterprise, etc.
   • Current situation: what tools/processes they use now
   
3. BUYING SIGNALS (what indicates they're ready to buy)
   • Pain points they're experiencing
   • Trigger events: funding raised, new hires, expansion, tech changes
   • Job titles that indicate need
   • Technologies in their stack that suggest fit
   
4. WHO TO CONTACT (Decision Makers)
   • Target job titles/roles (VP of X, Director of Y, Founder)
   • Department (Sales, Marketing, Operations, IT, etc.)
   • Seniority level (C-suite, VP, Director, Manager)
   
5. EXCLUSION CRITERIA (Who NOT to target)
   • Competitors and their customers
   • Companies too small or too large
   • Industries that don't fit
   • Geographies you can't serve
   • Companies using competitor products
   
6. EXISTING CUSTOMERS (examples to find similar companies)
   • List 3-5 current customer websites
   • These help the AI understand your ideal profile
   
7. SEARCH KEYWORDS (terms to find prospects)
   • Industry terms: "e-commerce", "SaaS", "manufacturing"
   • Problem terms: "scaling challenges", "manual processes"
   • Technology terms: "Salesforce user", "AWS", "Shopify"
   • Stage terms: "Series A", "hiring", "growing fast"

───────────────────────────────────────────────────────────────────────────────
WHY THIS MATTERS FOR AI LEAD SCORING:
───────────────────────────────────────────────────────────────────────────────

The AI will score each discovered website on multiple factors:
• Industry/vertical match
• Company size fit
• Technology stack alignment
• Content relevance to your solution
• Presence of target job titles
• Buying signal indicators

More specific details = more accurate scoring = better leads.

───────────────────────────────────────────────────────────────────────────────
EXAMPLE OF A GREAT RESPONSE:
───────────────────────────────────────────────────────────────────────────────

BoxFlow (boxflow.io) sells warehouse management software to mid-size e-commerce 
companies in the US. Our deals range $30K-$150K/year.

IDEAL CUSTOMER:
• Revenue: $5M-$100M annually
• Employees: 50-500 people
• Operations: Ships 1000+ orders/day
• Current state: Using spreadsheets or outdated WMS
• Strong signals: Recently raised funding, opened new warehouse, hiring ops staff

DECISION MAKERS:
• Primary: VP/Director of Operations, Logistics, or Supply Chain
• Secondary: COO at smaller companies (under 100 employees)
• Avoid: IT-only contacts (they're not the budget holder)

DO NOT TARGET:
• 3PLs (they're competitors' customers)
• Companies already on SAP/Oracle WMS
• Companies under $3M revenue (too small)
• Companies outside the US (we can't support internationally yet)
• Amazon FBA-only sellers (don't need our solution)

CURRENT CUSTOMERS (find similar):
• acme-shipping.com
• fastfulfill.io  
• boxbrand.com

SEARCH TERMS BY CATEGORY:
• Industry: e-commerce, DTC brand, online retail, Shopify seller, BigCommerce
• Problem: fulfillment challenges, warehouse inefficiency, inventory management
• Stage: Series A, Series B, growing, scaling, hiring warehouse staff
• Tech: WMS, 3PL alternative, ShipStation, fulfillment software, Shopify Plus

═══════════════════════════════════════════════════════════════════════════════
TIP: You can paste this entire guide into ChatGPT/Claude with your business 
info and ask it to generate a response in this format!
═══════════════════════════════════════════════════════════════════════════════"""

    def _copy_to_clipboard(self, text):
        """Copy text to system clipboard."""
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()  # Required for clipboard to persist
        # Show brief confirmation
        messagebox.showinfo("Copied!", "Description copied to clipboard.\n\nPaste into ChatGPT or Claude to help generate your response.")
    
    def _add_field_help(self, parent, help_text, padx_left=165):
        """Add help text below a field."""
        help_label = ttk.Label(parent, text=help_text, 
                              foreground='#666666', font=('Arial', 9),
                              wraplength=600, justify='left')
        help_label.pack(anchor='w', padx=(padx_left, 0), pady=(2, 8))
    
    def _build_guided_screen(self, parent):
        """Build the guided questions input screen."""
        ttk.Label(parent, text="Guided Questions Mode", 
                  font=('Arial', 16, 'bold')).pack(pady=(0, 5))
        ttk.Label(parent, text="Answer each question to describe your ideal customers. The AI agent uses these inputs to automatically configure search keywords, scoring factors, and contact extraction.", 
                  font=('Arial', 10), foreground='gray', wraplength=700, justify='left').pack(pady=(0, 15))
        
        user_inputs = self.config.config.get("user_inputs", {})
        
        # Business Identity
        ttk.Label(parent, text="Business Identity", font=('Arial', 11, 'bold')).pack(anchor='w', pady=(10, 5))
        
        row1 = ttk.Frame(parent)
        row1.pack(fill='x', pady=2)
        ttk.Label(row1, text="Business Name *", width=20).pack(side='left')
        self.input_business_name = ttk.Entry(row1, width=50)
        self.input_business_name.insert(0, user_inputs.get("business_name", ""))
        self.input_business_name.pack(side='left', padx=5)
        self._add_field_help(parent, 
            "REQUIRED: Your company name. The AI uses this to automatically exclude your own company from search results. "
            "Example: 'BoxFlow' or 'Acme Corporation'")
        
        row2 = ttk.Frame(parent)
        row2.pack(fill='x', pady=2)
        ttk.Label(row2, text="Website URL *", width=20).pack(side='left')
        self.input_website_url = ttk.Entry(row2, width=50)
        self.input_website_url.insert(0, user_inputs.get("website_url", ""))
        self.input_website_url.pack(side='left', padx=5)
        self._add_field_help(parent,
            "REQUIRED: Your company website URL (e.g., https://boxflow.io). The AI agent automatically scrapes your website "
            "to understand your business, messaging, and value proposition. This content helps the AI generate better search "
            "keywords and scoring factors. Your domain is also automatically excluded from search results.")
        
        # What You Sell
        ttk.Label(parent, text="What You Sell", font=('Arial', 11, 'bold')).pack(anchor='w', pady=(15, 5))
        
        row3 = ttk.Frame(parent)
        row3.pack(fill='x', pady=2)
        ttk.Label(row3, text="Product/Service *", width=20).pack(side='left')
        self.input_product = ttk.Entry(row3, width=50)
        self.input_product.insert(0, user_inputs.get("product_description", ""))
        self.input_product.pack(side='left', padx=5)
        self._add_field_help(parent,
            "REQUIRED: Describe what you sell in 1-2 sentences. Be specific about product type, B2B vs B2C, and target market. "
            "The AI uses this to generate industry-specific search keywords (keyword boxes 1-2) and understand your business model. "
            "Examples: 'B2B SaaS for warehouse management', 'Executive recruiting for tech companies', 'Industrial equipment maintenance services'. "
            "AVOID: Generic terms like 'software' or 'services' - be specific about what you do.")
        
        row4 = ttk.Frame(parent)
        row4.pack(fill='x', pady=2)
        ttk.Label(row4, text="Price Range", width=20).pack(side='left')
        self.input_price_min = ttk.Entry(row4, width=12)
        self.input_price_min.insert(0, user_inputs.get("price_min", ""))
        self.input_price_min.pack(side='left', padx=2)
        ttk.Label(row4, text="to $").pack(side='left')
        self.input_price_max = ttk.Entry(row4, width=12)
        self.input_price_max.insert(0, user_inputs.get("price_max", ""))
        self.input_price_max.pack(side='left', padx=2)
        self._add_field_help(parent,
            "OPTIONAL: Your typical deal size range (e.g., Min: 30000, Max: 150000). The AI uses this to calibrate company size "
            "scoring - if you sell $30K-$150K deals, the AI knows to target mid-market companies, not Fortune 500 or tiny startups. "
            "This helps the AI generate appropriate 'Funding/Viability' scores in AI analysis. Leave blank if deal sizes vary widely.")
        
        # Ideal Customer
        ttk.Label(parent, text="Ideal Customer", font=('Arial', 11, 'bold')).pack(anchor='w', pady=(15, 5))
        
        row5 = ttk.Frame(parent)
        row5.pack(fill='x', pady=2)
        ttk.Label(row5, text="Ideal Customer *", width=20).pack(side='left', anchor='n')
        self.input_ideal = tk.Text(row5, width=50, height=4)
        self.input_ideal.insert("1.0", user_inputs.get("ideal_customer", ""))
        self.input_ideal.pack(side='left', padx=5)
        self._add_field_help(parent,
            "REQUIRED: Describe your ideal customer in detail. Include: industry/vertical, company stage, current situation, "
            "operational metrics, and buying signals. The AI uses this to generate keyword boxes (3-4), create positive scoring "
            "factors, and write AI analysis prompts. BE SPECIFIC: 'Mid-size e-commerce companies ($5M-$100M revenue, 50-500 employees) "
            "struggling with warehouse efficiency, shipping 1000+ orders/day, using spreadsheets or outdated WMS. Strong signals: "
            "recently raised funding, opened new warehouse, hiring ops staff.' The more detail, the better the AI configuration.")
        
        row6 = ttk.Frame(parent)
        row6.pack(fill='x', pady=2)
        ttk.Label(row6, text="Company Size", width=20).pack(side='left')
        self.input_size = ttk.Entry(row6, width=50)
        self.input_size.insert(0, user_inputs.get("company_size", ""))
        self.input_size.pack(side='left', padx=5)
        self._add_field_help(parent,
            "OPTIONAL: Target company size requirements. Include employee count, revenue range, funding stage, or other size indicators. "
            "The AI uses this to create 'Size Fit' positive scoring factors (weight 150) and generate stage/size keywords. "
            "Examples: '50-500 employees, $5M-$100M revenue, Series A+', 'Fortune 500 only', '10-50 employees, seed to Series A'. "
            "If you already included this in 'Ideal Customer', you can leave blank or add more specific details here.")
        
        row7 = ttk.Frame(parent)
        row7.pack(fill='x', pady=2)
        ttk.Label(row7, text="Geography", width=20).pack(side='left')
        self.input_geo = ttk.Entry(row7, width=50)
        self.input_geo.insert(0, user_inputs.get("geography", ""))
        self.input_geo.pack(side='left', padx=5)
        self._add_field_help(parent,
            "OPTIONAL: Geographic requirements for your customers. The AI uses this to set the search region and create 'Geographic' "
            "positive scoring factors (weight 100). Be specific: 'US only', 'English-speaking countries', 'Must have EU operations', "
            "'No restrictions'. If blank, the AI will search globally. This helps filter results and improve lead quality.")
        
        # Decision Makers
        ttk.Label(parent, text="Decision Makers", font=('Arial', 11, 'bold')).pack(anchor='w', pady=(15, 5))
        
        row8 = ttk.Frame(parent)
        row8.pack(fill='x', pady=2)
        ttk.Label(row8, text="Seniority Levels", width=20).pack(side='left')
        self.input_seniority = ttk.Entry(row8, width=50)
        self.input_seniority.insert(0, user_inputs.get("seniority_levels", ""))
        self.input_seniority.pack(side='left', padx=5)
        self._add_field_help(parent,
            "OPTIONAL: What seniority levels have budget authority to buy your solution? The AI uses this to configure contact "
            "extraction titles (seniority_4_titles, seniority_3_titles, etc.). List specific levels: 'CEO, VP, Director, Manager' "
            "or 'C-suite, VP, Director'. The AI maps these to: Level 4 (C-suite), Level 3 (VP/Head), Level 2 (Director), "
            "Level 1 (Manager). If blank, the AI will infer from your other inputs or use defaults.")
        
        row9 = ttk.Frame(parent)
        row9.pack(fill='x', pady=2)
        ttk.Label(row9, text="Departments", width=20).pack(side='left')
        self.input_depts = ttk.Entry(row9, width=50)
        self.input_depts.insert(0, user_inputs.get("departments", ""))
        self.input_depts.pack(side='left', padx=5)
        self._add_field_help(parent,
            "OPTIONAL: Which departments or functions make purchasing decisions for your solution? The AI uses this to configure "
            "fit-based contact extraction titles (fit_4_titles, fit_3_titles, etc.). List departments: 'Operations, Logistics, Supply Chain' "
            "or 'IT, Engineering, CTO'. The AI prioritizes finding contacts in these departments. Examples: 'Sales, Marketing' for "
            "sales tools, 'Operations, Logistics' for operations software, 'IT, Engineering' for developer tools. If blank, the AI "
            "will infer from your product description.")
        
        # Exclusions & Examples
        ttk.Label(parent, text="Exclusions & Examples", font=('Arial', 11, 'bold')).pack(anchor='w', pady=(15, 5))
        
        row10 = ttk.Frame(parent)
        row10.pack(fill='x', pady=2)
        ttk.Label(row10, text="Exclusions", width=20).pack(side='left', anchor='n')
        self.input_exclusions = tk.Text(row10, width=50, height=3)
        self.input_exclusions.insert("1.0", user_inputs.get("exclusions", ""))
        self.input_exclusions.pack(side='left', padx=5)
        self._add_field_help(parent,
            "OPTIONAL: Who should be excluded from results? The AI uses this to create negative scoring factors (exclusions) that "
            "automatically filter out or down-score these companies. Include: competitors and their customers, wrong company sizes, "
            "industries that don't fit, geographies you can't serve, companies using competitor products. Examples: '3PLs (competitors' "
            "customers), companies using SAP/Oracle, under $3M revenue, outside US, agencies'. Each exclusion becomes a negative factor "
            "with weight 150-300. This saves time and API costs by avoiding analysis of companies you know won't buy.")
        
        row11 = ttk.Frame(parent)
        row11.pack(fill='x', pady=2)
        ttk.Label(row11, text="Good Lead URLs", width=20).pack(side='left', anchor='n')
        self.input_leads = tk.Text(row11, width=50, height=3)
        self.input_leads.insert("1.0", user_inputs.get("good_leads", ""))
        self.input_leads.pack(side='left', padx=5)
        self._add_field_help(parent,
            "OPTIONAL: List 3-10 URLs of ideal customers (current customers, past customers, or companies you wish were customers). "
            "Format: one URL per line or comma-separated (e.g., 'acme-shipping.com, fastfulfill.io, boxbrand.com'). The AI automatically "
            "scrapes these websites to understand what good leads look like, uses their content to identify similar companies, and creates "
            "positive factors based on patterns found. This is one of the most powerful inputs - the AI learns from your best customers "
            "to find similar companies. Include the domain only (no https:// needed).")
        
        row12 = ttk.Frame(parent)
        row12.pack(fill='x', pady=2)
        ttk.Label(row12, text="Search Keywords", width=20).pack(side='left', anchor='n')
        self.input_keywords = tk.Text(row12, width=50, height=4)
        self.input_keywords.insert("1.0", user_inputs.get("search_keywords", ""))
        self.input_keywords.pack(side='left', padx=5)
        self._add_field_help(parent,
            "OPTIONAL: Search terms organized by category. The AI uses these to create keyword boxes (5-8 boxes). One term from each "
            "non-empty box is randomly selected and combined into search queries. Organize by category: Industry terms (e-commerce, "
            "SaaS, manufacturing), Problem terms (scaling challenges, manual processes), Stage/size terms (Series A, growing, "
            "enterprise), Technology terms (Salesforce, AWS, Shopify), Activity terms (hiring, expanding, raised funding). "
            "Example format: 'Industry: e-commerce, DTC brand, online retail | Problem: fulfillment challenges, warehouse inefficiency | "
            "Stage: Series A, growing, scaling | Tech: WMS, ShipStation, Shopify Plus'. If you provide organized keywords, the AI uses "
            "them directly. If blank, the AI generates keywords from your other inputs.")
        
        row13 = ttk.Frame(parent)
        row13.pack(fill='x', pady=2)
        ttk.Label(row13, text="Other Context", width=20).pack(side='left', anchor='n')
        self.input_other = tk.Text(row13, width=50, height=3)
        self.input_other.insert("1.0", user_inputs.get("other_context", ""))
        self.input_other.pack(side='left', padx=5)
        self._add_field_help(parent,
            "OPTIONAL: Any additional context that helps identify good leads. The AI uses this to create 'Buying Signals' positive "
            "factors (weight 100) and enhance scoring prompts. Include: buying signals (recently raised funding = strong signal, hiring "
            "for X role = good timing), timing indicators (when companies are most likely to buy), trigger events (expansion, tech changes, "
            "new initiatives), or other helpful context. Examples: 'Recently raised funding = strong signal', 'Hiring VP of Operations = "
            "good timing for WMS', 'Companies expanding to new markets need our solution', 'Digital transformation initiatives indicate "
            "readiness'. This helps the AI prioritize leads that are actively looking for solutions.")
        
        # Track that we're in guided mode
        self.guided_mode = True
        
        # Buttons
        self._add_bottom_buttons(parent)
    
    def _add_bottom_buttons(self, parent):
        """Add bottom buttons to input screen."""
        button_frame = ttk.Frame(parent)
        button_frame.pack(fill='x', pady=(20, 30))
        
        ttk.Button(button_frame, text="← Back", command=self.setup_selection_screen).pack(side='left', padx=(10, 0))
        
        ttk.Button(button_frame, text="Start AI-Assisted Run →", 
                   command=self._start_run).pack(side='right')
        
        ttk.Button(button_frame, text="Save & Configure Manually", 
                   command=self._save_and_manual).pack(side='right', padx=10)
    
    def _on_model_change(self, event=None):
        """Handle model selection change."""
        # Get selected model
        idx = self.model_combo.current()
        if idx >= 0 and idx < len(self.all_models):
            selected = self.all_models[idx]
            provider = selected["provider"]
            
            # Load the appropriate API key
            step4 = self.config.config.get("step4", {})
            if provider == "gemini":
                key = step4.get("gemini_api_key", "")
            else:
                key = step4.get("api_key", "")
            self.api_key_var.set(key)
    
    def _toggle_key_visibility(self):
        """Toggle API key visibility."""
        if self.show_key.get():
            self.api_key_entry.config(show='')
        else:
            self.api_key_entry.config(show='*')
    
    def _toggle_selection_key_visibility(self):
        """Toggle selection API key visibility."""
        if self.selection_show_key.get():
            self.selection_api_key_entry.config(show='')
        else:
            self.selection_api_key_entry.config(show='*')
    
    def _toggle_selection_model_fields(self):
        """Show/hide selection model fields based on 'use same model' checkbox."""
        use_same = self.use_same_model_var.get()
        
        if use_same:
            # Hide the entire selection model frame
            self.selection_model_frame.pack_forget()
        else:
            # Show the selection model frame
            self.selection_model_frame.pack(fill='x', pady=5)
        
        # Update cost estimate when toggling
        self._update_cost_estimate()
    
    def _update_cost_estimate(self):
        """Calculate and display estimated cost based on models and number of websites."""
        try:
            # Get number of websites
            num_websites = int(self.num_websites_var.get())
            if num_websites <= 0:
                self.cost_estimate_label.config(text="", foreground='blue')
                return
        except (ValueError, AttributeError):
            self.cost_estimate_label.config(text="", foreground='blue')
            return
        
        # Get search model cost
        search_cost_per_1k = 0
        try:
            idx = self.model_combo.current()
            if idx >= 0 and idx < len(self.all_models):
                selected_model = self.all_models[idx]
                # Try to get cost from the model dict (already converted to cost_per_1k)
                cost_value = selected_model.get("cost_per_1k")
                if cost_value is None or cost_value == 0:
                    # If not in dict, try to get from config
                    step4 = self.config.config.get("step4", {})
                    provider = selected_model.get("provider")
                    model_idx = selected_model.get("model_index")
                    if provider and model_idx is not None:
                        models_key = f"{provider}_models"
                        models = step4.get(models_key, [])
                        if model_idx < len(models):
                            model_config = models[model_idx]
                            # Check for cost_per_1k first, then cost_per_100
                            if "cost_per_1k" in model_config:
                                cost_value = model_config.get("cost_per_1k", 0)
                            elif "cost_per_100" in model_config:
                                cost_value = model_config.get("cost_per_100", 0) * 10
                search_cost_per_1k = float(cost_value) if cost_value is not None else 0.0
        except (ValueError, AttributeError, IndexError, TypeError) as e:
            search_cost_per_1k = 0
        
        # Get selection model cost
        selection_cost_per_1k = 0
        use_same = self.use_same_model_var.get() if hasattr(self, 'use_same_model_var') else True
        
        if use_same:
            # Use same model for selection - use search model cost
            selection_cost_per_1k = search_cost_per_1k
        else:
            try:
                selection_idx = self.selection_model_combo.current()
                if selection_idx >= 0 and selection_idx < len(self.all_models):
                    selected_selection_model = self.all_models[selection_idx]
                    # Try to get cost from the model dict (already converted to cost_per_1k)
                    cost_value = selected_selection_model.get("cost_per_1k")
                    if cost_value is None or cost_value == 0:
                        # If not in dict, try to get from config
                        step4 = self.config.config.get("step4", {})
                        provider = selected_selection_model.get("provider")
                        model_idx = selected_selection_model.get("model_index")
                        if provider and model_idx is not None:
                            models_key = f"{provider}_models"
                            models = step4.get(models_key, [])
                            if model_idx < len(models):
                                model_config = models[model_idx]
                                # Check for cost_per_1k first, then cost_per_100
                                if "cost_per_1k" in model_config:
                                    cost_value = model_config.get("cost_per_1k", 0)
                                elif "cost_per_100" in model_config:
                                    cost_value = model_config.get("cost_per_100", 0) * 10
                    selection_cost_per_1k = float(cost_value) if cost_value is not None else 0.0
            except (ValueError, AttributeError, IndexError, TypeError):
                selection_cost_per_1k = 0
        
        # Calculate costs
        # Search model: cost per website = cost_per_1k / 1000
        # Selection model: typically one call per run (estimate as 0.1% of search cost for simplicity)
        search_cost_per_site = search_cost_per_1k / 1000
        selection_cost_per_run = (selection_cost_per_1k / 1000) * 0.1  # Estimate: one selection call
        
        total_search_cost = search_cost_per_site * num_websites
        total_selection_cost = selection_cost_per_run
        
        # Add some variance (80-120% of base cost) for range estimate
        min_total = (total_search_cost + total_selection_cost) * 0.8
        max_total = (total_search_cost + total_selection_cost) * 1.2
        
        # Format display
        if min_total < 0.01:
            estimate_text = "Estimated cost: < $0.01"
        else:
            estimate_text = f"Estimated cost: ${min_total:.2f} - ${max_total:.2f}"
        
        self.cost_estimate_label.config(text=estimate_text, foreground='blue')
    
    def _add_custom_model(self):
        """Add a custom model configuration."""
        # Create popup for custom model
        popup = tk.Toplevel(self.root)
        popup.title("Add Custom Model")
        popup.geometry("450x300")
        popup.transient(self.root)
        popup.grab_set()
        
        frame = ttk.Frame(popup, padding=20)
        frame.pack(fill='both', expand=True)
        
        ttk.Label(frame, text="Add Custom AI Model", font=('Arial', 12, 'bold')).pack(pady=(0, 15))
        
        # Provider selection
        prov_row = ttk.Frame(frame)
        prov_row.pack(fill='x', pady=5)
        ttk.Label(prov_row, text="Provider:", width=15).pack(side='left')
        provider_var = tk.StringVar(value="claude")
        ttk.Combobox(prov_row, textvariable=provider_var, 
                     values=["claude", "openai", "gemini"], width=20, state='readonly').pack(side='left')
        
        # Model name
        name_row = ttk.Frame(frame)
        name_row.pack(fill='x', pady=5)
        ttk.Label(name_row, text="Display Name:", width=15).pack(side='left')
        name_var = tk.StringVar()
        ttk.Entry(name_row, textvariable=name_var, width=25).pack(side='left')
        
        # API ID
        id_row = ttk.Frame(frame)
        id_row.pack(fill='x', pady=5)
        ttk.Label(id_row, text="API Model ID:", width=15).pack(side='left')
        id_var = tk.StringVar()
        ttk.Entry(id_row, textvariable=id_var, width=35).pack(side='left')
        ttk.Label(frame, text="e.g., claude-3-5-sonnet-20241022, gpt-4o, gemini-1.5-pro", 
                  foreground='gray').pack(anchor='w', padx=(120, 0))
        
        # Cost
        cost_row = ttk.Frame(frame)
        cost_row.pack(fill='x', pady=5)
        ttk.Label(cost_row, text="Cost per 1K:", width=15).pack(side='left')
        cost_var = tk.StringVar(value="1.00")
        ttk.Entry(cost_row, textvariable=cost_var, width=10).pack(side='left')
        ttk.Label(cost_row, text="$ (for cost tracking)").pack(side='left', padx=5)
        
        def save_model():
            provider = provider_var.get()
            name = name_var.get().strip()
            api_id = id_var.get().strip()
            try:
                cost = float(cost_var.get())
            except:
                cost = 1.0
            
            if not name or not api_id:
                messagebox.showerror("Error", "Please fill in Display Name and API Model ID")
                return
            
            # Add to config
            models_key = f"{provider}_models"
            if models_key not in self.config.config["step4"]:
                self.config.config["step4"][models_key] = []
            
            self.config.config["step4"][models_key].append({
                "name": name,
                "api_id": api_id,
                "cost_per_1k": cost
            })
            
            # Add to dropdown
            new_model = {
                "display": f"{provider.title()}: {name} (${cost:.2f}/1K)",
                "provider": provider,
                "model_index": len(self.config.config["step4"][models_key]) - 1,
                "api_id": api_id,
                "name": name,
                "cost_per_1k": cost
            }
            self.all_models.append(new_model)
            
            # Update comboboxes
            model_display_list = [m["display"] for m in self.all_models]
            self.model_combo['values'] = model_display_list
            self.model_combo.current(len(self.all_models) - 1)
            
            # Also update selection model combo if it exists
            if hasattr(self, 'selection_model_combo'):
                self.selection_model_combo['values'] = model_display_list
            
            # Update cost estimate
            if hasattr(self, '_update_cost_estimate'):
                self._update_cost_estimate()
            
            # Save config
            self.config.save_config()
            
            popup.destroy()
            messagebox.showinfo("Success", f"Added model: {name}")
        
        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill='x', pady=20)
        ttk.Button(btn_frame, text="Cancel", command=popup.destroy).pack(side='left')
        ttk.Button(btn_frame, text="Add Model", command=save_model).pack(side='right')
    
    def _save_config(self):
        """Save current selections to config."""
        # Get selected model (saved from selection screen)
        if hasattr(self, 'model_combo') and hasattr(self, 'all_models'):
            idx = self.model_combo.current()
            if idx >= 0 and idx < len(self.all_models):
                selected = self.all_models[idx]
                self.config.config["step4"]["api_provider"] = selected["provider"]
                self.config.config["step4"]["model_choice"] = f"model_{selected['model_index'] + 1}"
                
                # Save API key to appropriate field
                if hasattr(self, 'api_key_var'):
                    key = self.api_key_var.get()
                    if selected["provider"] == "gemini":
                        self.config.config["step4"]["gemini_api_key"] = key
                    else:
                        self.config.config["step4"]["api_key"] = key
        
        # Save number of websites
        if hasattr(self, 'num_websites_var'):
            try:
                num_websites = int(self.num_websites_var.get())
                if num_websites > 0:
                    self.config.config["step4"]["num_websites"] = num_websites
            except (ValueError, AttributeError):
                pass
        
        # Save search API settings (Serper/SerpAPI)
        if hasattr(self, 'search_api_var'):
            self.config.config["step1"]["api_choice"] = self.search_api_var.get()
        if hasattr(self, 'search_api_key_var'):
            self.config.config["step1"]["api_key"] = self.search_api_key_var.get()
        
        # Save selection model settings
        if hasattr(self, 'use_same_model_var'):
            use_same = self.use_same_model_var.get()
            self.config.config["step4"]["use_same_model_for_selection"] = use_same
            
            if use_same:
                # If using same model, use search model settings for selection
                if hasattr(self, 'model_combo') and hasattr(self, 'all_models'):
                    idx = self.model_combo.current()
                    if idx >= 0 and idx < len(self.all_models):
                        selected = self.all_models[idx]
                        self.config.config["step4"]["selection_api_provider"] = selected["provider"]
                        self.config.config["step4"]["selection_model_choice"] = f"model_{selected['model_index'] + 1}"
                        
                        # Use same API key as search model
                        if hasattr(self, 'api_key_var'):
                            key = self.api_key_var.get()
                            if selected["provider"] == "gemini":
                                self.config.config["step4"]["selection_gemini_api_key"] = key
                                self.config.config["step4"].pop("selection_api_key", None)
                            else:
                                self.config.config["step4"]["selection_api_key"] = key
                                self.config.config["step4"].pop("selection_gemini_api_key", None)
            else:
                # Using different model for selection
                if hasattr(self, 'selection_model_combo') and hasattr(self, 'all_models'):
                    selection_idx = self.selection_model_combo.current()
                    if selection_idx >= 0 and selection_idx < len(self.all_models):
                        selection_selected = self.all_models[selection_idx]
                        self.config.config["step4"]["selection_api_provider"] = selection_selected["provider"]
                        self.config.config["step4"]["selection_model_choice"] = f"model_{selection_selected['model_index'] + 1}"
                        
                        # Save selection API key
                        if hasattr(self, 'selection_api_key_var'):
                            selection_key = self.selection_api_key_var.get()
                            if selection_selected["provider"] == "gemini":
                                self.config.config["step4"]["selection_gemini_api_key"] = selection_key
                                self.config.config["step4"].pop("selection_api_key", None)
                            else:
                                self.config.config["step4"]["selection_api_key"] = selection_key
                                self.config.config["step4"].pop("selection_gemini_api_key", None)
        
        if "user_inputs" not in self.config.config:
            self.config.config["user_inputs"] = {}
        
        # Check which mode we're in and save appropriately
        if hasattr(self, 'guided_mode') and self.guided_mode:
            # Guided mode - save individual fields
            if hasattr(self, 'input_business_name'):
                self.config.config["user_inputs"]["business_name"] = self.input_business_name.get()
            if hasattr(self, 'input_website_url'):
                self.config.config["user_inputs"]["website_url"] = self.input_website_url.get()
            if hasattr(self, 'input_product'):
                self.config.config["user_inputs"]["product_description"] = self.input_product.get()
            if hasattr(self, 'input_price_min'):
                self.config.config["user_inputs"]["price_min"] = self.input_price_min.get()
            if hasattr(self, 'input_price_max'):
                self.config.config["user_inputs"]["price_max"] = self.input_price_max.get()
            if hasattr(self, 'input_ideal'):
                self.config.config["user_inputs"]["ideal_customer"] = self.input_ideal.get("1.0", "end").strip()
            if hasattr(self, 'input_size'):
                self.config.config["user_inputs"]["company_size"] = self.input_size.get()
            if hasattr(self, 'input_geo'):
                self.config.config["user_inputs"]["geography"] = self.input_geo.get()
            if hasattr(self, 'input_seniority'):
                self.config.config["user_inputs"]["seniority_levels"] = self.input_seniority.get()
            if hasattr(self, 'input_depts'):
                self.config.config["user_inputs"]["departments"] = self.input_depts.get()
            if hasattr(self, 'input_exclusions'):
                self.config.config["user_inputs"]["exclusions"] = self.input_exclusions.get("1.0", "end").strip()
            if hasattr(self, 'input_leads'):
                self.config.config["user_inputs"]["good_leads"] = self.input_leads.get("1.0", "end").strip()
            if hasattr(self, 'input_keywords'):
                self.config.config["user_inputs"]["search_keywords"] = self.input_keywords.get("1.0", "end").strip()
            if hasattr(self, 'input_other'):
                self.config.config["user_inputs"]["other_context"] = self.input_other.get("1.0", "end").strip()
        else:
            # Single prompt mode
            if hasattr(self, 'prompt_text'):
                self.config.config["user_inputs"]["single_prompt_response"] = self.prompt_text.get("1.0", "end").strip()
        
        # Sync good_leads to step4.good_leads_domains
        good_leads_raw = self.config.config["user_inputs"].get("good_leads", "")
        if good_leads_raw:
            good_leads_urls = [url.strip() for url in good_leads_raw.replace('\n', ',').replace(' ', ',').split(',') if url.strip()]
            good_leads_domains = []
            for url in good_leads_urls:
                if url:
                    domain = url.replace('https://', '').replace('http://', '').replace('www.', '')
                    domain = domain.split('/')[0]
                    if domain:
                        good_leads_domains.append(domain)
            self.config.config["step4"]["good_leads_domains"] = ", ".join(good_leads_domains)
        
        self.config.save_config()
    
    def _go_back(self):
        """Go back to main popup."""
        self.root.destroy()
        app = InitialPopupGUI()
        app.run()
    
    def _save_and_manual(self):
        """Save and open manual configuration."""
        self._save_config()
        self.root.destroy()
        app = UnifiedLeadGenGUI()
        app.run()
    
    def _start_run(self):
        """Start the AI-assisted run."""
        # Validate inputs based on mode
        if hasattr(self, 'guided_mode') and self.guided_mode:
            # Guided mode validation
            if hasattr(self, 'input_product') and not self.input_product.get().strip():
                messagebox.showerror("Error", "Please fill in the Product/Service field")
                return
            if hasattr(self, 'input_ideal') and not self.input_ideal.get("1.0", "end").strip():
                messagebox.showerror("Error", "Please describe your ideal customer")
                return
        else:
            # Single prompt mode validation
            if hasattr(self, 'prompt_text'):
                prompt = self.prompt_text.get("1.0", "end").strip()
                if not prompt:
                    messagebox.showerror("Error", "Please describe your business and ideal customers")
                    return
        
        # Validate AI API key
        if hasattr(self, 'api_key_var'):
            ai_api_key = self.api_key_var.get().strip()
            if not ai_api_key:
                messagebox.showerror("Error", 
                    "Please enter your AI API key.\n\n"
                    "Get a key from:\n"
                    "• Claude: console.anthropic.com\n"
                    "• OpenAI: platform.openai.com\n"
                    "• Gemini: aistudio.google.com")
                return
        
        # Validate Search API key
        if hasattr(self, 'search_api_key_var'):
            search_api_key = self.search_api_key_var.get().strip()
            if not search_api_key:
                messagebox.showerror("Error", 
                    "Please enter your Search API key.\n\n"
                    "Get a key from:\n"
                    "• Serper: serper.dev\n"
                    "• SerpAPI: serpapi.com")
                return
        
        # Save config
        self._save_config()
        
        # Show loading screen and run AI optimization
        self._show_loading_screen()
    
    def _show_loading_screen(self):
        """Show loading screen while AI agent processes inputs."""
        # Clear existing widgets
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # Create loading frame
        loading_frame = ttk.Frame(self.root, padding=50)
        loading_frame.pack(fill='both', expand=True)
        
        # Title
        ttk.Label(loading_frame, text="🤖 AI Optimization in Progress", 
                  font=('Arial', 18, 'bold')).pack(pady=(50, 20))
        
        # Status message
        self.loading_status = tk.StringVar(value="Initializing AI agent...")
        status_label = ttk.Label(loading_frame, textvariable=self.loading_status, 
                                  font=('Arial', 11))
        status_label.pack(pady=10)
        
        # Progress indicator (indeterminate)
        self.progress_bar = ttk.Progressbar(loading_frame, mode='indeterminate', length=400)
        self.progress_bar.pack(pady=20)
        self.progress_bar.start(10)
        
        # Log display
        ttk.Label(loading_frame, text="Activity Log:", font=('Arial', 10, 'bold')).pack(anchor='w', pady=(20, 5))
        
        self.loading_log = tk.Text(loading_frame, width=80, height=10, wrap='word', state='disabled',
                                    background='#f8f8f8', foreground='#333333')
        self.loading_log.pack(fill='x', pady=5)
        
        # Cancel button
        self.cancel_btn = ttk.Button(loading_frame, text="Cancel", command=self._cancel_optimization)
        self.cancel_btn.pack(pady=20)
        
        # Track if cancelled
        self.optimization_cancelled = False
        
        # Start AI optimization in background thread
        import threading
        self.optimization_thread = threading.Thread(target=self._run_ai_optimization, daemon=True)
        self.optimization_thread.start()
        
        # Poll for completion
        self._check_optimization_status()
    
    def _log_to_loading(self, message: str):
        """Log a message to the loading screen."""
        def update():
            self.loading_status.set(message)
            self.loading_log.config(state='normal')
            self.loading_log.insert('end', f"{datetime.now().strftime('%H:%M:%S')} - {message}\n")
            self.loading_log.see('end')
            self.loading_log.config(state='disabled')
        
        # Schedule update on main thread
        self.root.after(0, update)
    
    def _run_ai_optimization(self):
        """Run AI optimization in background thread."""
        try:
            # Create agent
            agent = AIInputOptimizationAgent(self.config, progress_callback=self._log_to_loading)
            
            # Run optimization (use asyncio.run for the async method)
            success, ai_config, run_folder = asyncio.run(agent.optimize_inputs())
            
            # Store results for later use
            self.optimization_success = success
            self.optimization_config = ai_config
            self.optimization_run_folder = run_folder
            self.optimization_complete = True
            
        except Exception as e:
            self._log_to_loading(f"Error: {str(e)}")
            self.optimization_success = False
            self.optimization_config = {}
            self.optimization_run_folder = ""
            self.optimization_complete = True
    
    def _check_optimization_status(self):
        """Poll for optimization completion."""
        if self.optimization_cancelled:
            return
        
        if hasattr(self, 'optimization_complete') and self.optimization_complete:
            # Stop progress bar
            self.progress_bar.stop()
            
            if self.optimization_success:
                # Show review screen
                self._show_review_screen()
            else:
                # Show error
                messagebox.showerror("Optimization Failed", 
                    "AI optimization failed. Please check the log for details.\n\n"
                    "You can try again or proceed with manual configuration.")
                self._go_back()
        else:
            # Check again in 100ms
            self.root.after(100, self._check_optimization_status)
    
    def _cancel_optimization(self):
        """Cancel the optimization process."""
        self.optimization_cancelled = True
        self._go_back()
    
    def _show_review_screen(self):
        """Show review screen with AI-selected inputs and options to review or start."""
        # Clear existing widgets
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # Create scrollable canvas
        canvas = tk.Canvas(self.root, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        def _on_mousewheel(event):
            if event.delta == 0:
                return
            direction = -1 if event.delta > 0 else 1
            units = max(1, abs(event.delta) // 120)
            canvas.yview_scroll(direction * units, "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        main_frame = ttk.Frame(scrollable_frame, padding=20)
        main_frame.pack(fill='both', expand=True)
        
        # Title
        ttk.Label(main_frame, text="✅ AI Optimization Complete", 
                  font=('Arial', 18, 'bold')).pack(pady=(0, 10))
        ttk.Label(main_frame, text="Review the AI-selected configuration below", 
                  font=('Arial', 10), foreground='gray').pack(pady=(0, 20))
        
        # AI Reasoning (if available)
        if self.optimization_config.get("reasoning"):
            reasoning_frame = ttk.LabelFrame(main_frame, text="AI Reasoning", padding=10)
            reasoning_frame.pack(fill='x', pady=10)
            ttk.Label(reasoning_frame, text=self.optimization_config["reasoning"], 
                      wraplength=700, justify='left').pack(anchor='w')
        
        # Keyword Boxes
        if self.optimization_config.get("keyword_boxes"):
            keywords_frame = ttk.LabelFrame(main_frame, text="Search Keywords (Keyword Boxes)", padding=10)
            keywords_frame.pack(fill='x', pady=10)
            
            for i, box in enumerate(self.optimization_config["keyword_boxes"]):
                ttk.Label(keywords_frame, text=f"Box {i+1}: {box}", 
                          wraplength=700).pack(anchor='w', pady=2)
        
        # Search Settings
        settings_frame = ttk.LabelFrame(main_frame, text="Search Settings", padding=10)
        settings_frame.pack(fill='x', pady=10)
        
        settings_text = []
        
        # Add search API info from config
        step1 = self.config.config.get("step1", {})
        search_api = step1.get("api_choice", "serper")
        settings_text.append(f"Search API: {search_api.title()}")
        
        if self.optimization_config.get("region"):
            settings_text.append(f"Region: {self.optimization_config['region'].upper()}")
        if self.optimization_config.get("max_results_per_search"):
            settings_text.append(f"Max Results per Search: {self.optimization_config['max_results_per_search']}")
        if self.optimization_config.get("combo_cap"):
            settings_text.append(f"Search Combination Cap: {self.optimization_config['combo_cap']}")
        if self.optimization_config.get("scoring_threshold"):
            settings_text.append(f"Scoring Threshold: {self.optimization_config['scoring_threshold']}")
        
        # Add number of websites from config
        step4 = self.config.config.get("step4", {})
        num_websites = step4.get("num_websites", 100)
        settings_text.append(f"Max Websites to Search: {num_websites}")
        
        for text in settings_text:
            ttk.Label(settings_frame, text=text).pack(anchor='w', pady=2)
        
        # AI Scoring Fields
        if self.optimization_config.get("scoring_fields"):
            scoring_frame = ttk.LabelFrame(main_frame, text="AI Scoring Fields", padding=10)
            scoring_frame.pack(fill='x', pady=10)
            
            for field in self.optimization_config["scoring_fields"]:
                field_type = field.get("type", "score")
                title = field.get("title", "Field")
                if field_type == "score":
                    min_val = field.get("min", 0)
                    max_val = field.get("max", 10)
                    ttk.Label(scoring_frame, 
                              text=f"• {title} (score {min_val}-{max_val})",
                              wraplength=700).pack(anchor='w', pady=1)
                else:
                    options = ", ".join(field.get("options", [])[:3])
                    if len(field.get("options", [])) > 3:
                        options += "..."
                    ttk.Label(scoring_frame, 
                              text=f"• {title} (text: {options})",
                              wraplength=700).pack(anchor='w', pady=1)
        
        # Positive Factors
        if self.optimization_config.get("positive_factors"):
            pos_frame = ttk.LabelFrame(main_frame, text="Positive Scoring Factors (Good Leads)", padding=10)
            pos_frame.pack(fill='x', pady=10)
            
            for factor in self.optimization_config["positive_factors"]:
                ttk.Label(pos_frame, 
                          text=f"• {factor.get('name', 'Factor')} (weight: {factor.get('weight', 100)}) - Keywords: {factor.get('keywords', '')}",
                          wraplength=700).pack(anchor='w', pady=2)
        
        # Negative Factors
        if self.optimization_config.get("negative_factors"):
            neg_frame = ttk.LabelFrame(main_frame, text="Negative Scoring Factors (Exclusions)", padding=10)
            neg_frame.pack(fill='x', pady=10)
            
            for factor in self.optimization_config["negative_factors"]:
                ttk.Label(neg_frame, 
                          text=f"• {factor.get('name', 'Factor')} (weight: {factor.get('weight', 100)}) - Keywords: {factor.get('keywords', '')}",
                          wraplength=700).pack(anchor='w', pady=2)
        
        # Contact Titles
        titles_frame = ttk.LabelFrame(main_frame, text="Contact Scoring Titles", padding=10)
        titles_frame.pack(fill='x', pady=10)
        
        for key in ["seniority_4_titles", "seniority_3_titles", "fit_4_titles", "fit_3_titles"]:
            if self.optimization_config.get(key):
                display_key = key.replace("_", " ").title()
                ttk.Label(titles_frame, text=f"{display_key}: {self.optimization_config[key]}",
                          wraplength=700).pack(anchor='w', pady=2)
        
        # Run folder info
        if self.optimization_run_folder:
            folder_frame = ttk.Frame(main_frame)
            folder_frame.pack(fill='x', pady=10)
            ttk.Label(folder_frame, text=f"📁 Run folder: {self.optimization_run_folder}", 
                      foreground='gray').pack(anchor='w')
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill='x', pady=30)
        
        # Back button
        ttk.Button(button_frame, text="← Back", command=self._go_back).pack(side='left')
        
        # Start button (primary action)
        start_btn = ttk.Button(button_frame, text="▶ Start Lead Generation", 
                               command=self._start_lead_generation)
        start_btn.pack(side='right', padx=5)
        
        # Review Inputs button
        review_btn = ttk.Button(button_frame, text="📝 Review & Edit Inputs", 
                                command=self._review_and_edit)
        review_btn.pack(side='right', padx=5)
    
    def _review_and_edit(self):
        """Open the main GUI to review and edit inputs before starting."""
        self.root.destroy()
        app = UnifiedLeadGenGUI(resume_run_folder=self.optimization_run_folder if hasattr(self, 'optimization_run_folder') else None)
        app.run()
    
    def _start_lead_generation(self):
        """Start the lead generation pipeline with AI-optimized settings."""
        self.root.destroy()
        app = UnifiedLeadGenGUI(resume_run_folder=self.optimization_run_folder if hasattr(self, 'optimization_run_folder') else None)
        # Automatically start the pipeline
        app.root.after(100, app.run_pipeline)
        app.run()
    
    def run(self):
        """Run the GUI."""
        self.root.mainloop()


# ============================================================
# INITIAL POPUP GUI
# ============================================================

class InitialPopupGUI:
    """Initial popup GUI for selecting run type."""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Sherpa Lead Generator")
        self.root.geometry("400x400")
        self.root.resizable(True, True)
        
        # Make maximized (windowed fullscreen - keeps title bar and close button)
        self.root.state('zoomed')
        
        self.setup_gui()
    
    def setup_gui(self):
        """Setup the initial popup interface."""
        # Title
        title_label = ttk.Label(self.root, text="Sherpa Lead Generator", font=('Arial', 16, 'bold'))
        title_label.pack(pady=20)
        
        # Description
        desc_label = ttk.Label(self.root, text="Choose how you'd like to proceed:", font=('Arial', 10))
        desc_label.pack(pady=10)
        
        # Buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(pady=20, padx=20, fill='x')
        
        # New Run buttons - side by side
        new_run_frame = ttk.Frame(button_frame)
        new_run_frame.pack(fill='x', pady=5)
        
        # Manual run button (left half)
        manual_btn = ttk.Button(new_run_frame, text="New Run\n(Manual)", command=self.new_run_manual)
        manual_btn.pack(side='left', fill='x', expand=True, padx=(0, 2))
        
        # AI-assisted run button (right half)
        ai_btn = ttk.Button(new_run_frame, text="New Run\n(AI Setup)", command=self.new_run_ai_assisted)
        ai_btn.pack(side='right', fill='x', expand=True, padx=(2, 0))
        
        ttk.Button(button_frame, text="Continue Run", command=self.continue_run).pack(fill='x', pady=5)
        ttk.Button(button_frame, text="Download Results", command=self.download_leads).pack(fill='x', pady=5)
        
        # Update from GitHub button
        ttk.Button(button_frame, text="Update from GitHub", command=self.update_from_github).pack(fill='x', pady=5)
        
        # Developer Options button
        ttk.Button(button_frame, text="🔧 Developer Options", command=self.developer_options).pack(fill='x', pady=5)
        
        # Exit button
        ttk.Button(button_frame, text="Exit", command=self.root.quit).pack(fill='x', pady=(20, 5))
    
    def new_run_manual(self):
        """Start a new run with manual configuration."""
        self.root.destroy()
        app = UnifiedLeadGenGUI()
        app.run()
    
    def new_run_ai_assisted(self):
        """Start a new run with AI-assisted setup."""
        self.root.destroy()
        app = AIAssistedSetupGUI()
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
    
    def developer_options(self):
        """Open developer options."""
        self.root.destroy()
        app = DeveloperOptionsGUI()
        app.run()
    
    def update_from_github(self):
        """Pull latest updates from GitHub."""
        # Show a confirmation dialog first
        result = messagebox.askyesno(
            "Update from GitHub",
            "This will download the latest version from GitHub.\n\n"
            "Your local configuration (unified_config.json) will be preserved.\n\n"
            "Do you want to continue?"
        )
        if not result:
            return
        
        # Show a progress indicator
        self.root.config(cursor="wait")
        self.root.update()
        
        try:
            success, message = git_pull_updates()
            
            if success:
                if "Already up to date" in message:
                    messagebox.showinfo("No Updates", message)
                else:
                    messagebox.showinfo("Update Complete", message)
                    # Ask if user wants to restart
                    if messagebox.askyesno("Restart Required", "Would you like to close the application now?\n\nYou'll need to restart it to use the new version."):
                        self.root.quit()
            else:
                messagebox.showerror("Update Failed", f"Failed to update:\n\n{message}")
        finally:
            self.root.config(cursor="")
    
    def run(self):
        """Run the popup."""
        print("Starting GUI main loop...")
        self.root.mainloop()
        print("GUI main loop ended.")

class ContinueRunGUI:
    """GUI for continuing previous runs by browsing run folders."""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Continue Previous Run - Sherpa Lead Generator")
        self.root.geometry("800x500")
        self.root.resizable(True, True)
        
        # Make maximized (windowed fullscreen - keeps title bar and close button)
        self.root.state('zoomed')
        
        self.selected_run = None
        
        self.setup_gui()
    
    def setup_gui(self):
        """Setup the continue run interface."""
        ttk.Label(self.root, text="Select a Run to Continue", font=('Arial', 14, 'bold')).pack(pady=10)
        
        ttk.Label(self.root, text="Choose a previous run folder to resume:", font=('Arial', 10)).pack(pady=5)
        
        # Create treeview for run list
        tree_frame = ttk.Frame(self.root)
        tree_frame.pack(fill='both', expand=True, padx=20, pady=10)
        
        columns = ('Run #', 'Date/Time', 'Websites', 'Status', 'Folder')
        self.runs_tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=15)
        
        self.runs_tree.heading('Run #', text='Run #')
        self.runs_tree.heading('Date/Time', text='Date/Time')
        self.runs_tree.heading('Websites', text='Websites')
        self.runs_tree.heading('Status', text='Status')
        self.runs_tree.heading('Folder', text='Folder')
        
        self.runs_tree.column('Run #', width=60)
        self.runs_tree.column('Date/Time', width=150)
        self.runs_tree.column('Websites', width=80)
        self.runs_tree.column('Status', width=100)
        self.runs_tree.column('Folder', width=300)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.runs_tree.yview)
        self.runs_tree.configure(yscrollcommand=scrollbar.set)
        
        self.runs_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # Load previous runs
        self.load_previous_runs()
        
        # Buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(pady=15)
        
        ttk.Button(button_frame, text="📂 Browse for Run Folder...", command=self.browse_for_folder).pack(side='left', padx=5)
        ttk.Button(button_frame, text="▶ Continue Selected Run", command=self.continue_selected).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Back", command=self.back_to_main).pack(side='left', padx=5)
    
    def load_previous_runs(self):
        """Load list of previous runs from run folders."""
        runs = get_all_run_folders()
        
        if not runs:
            self.runs_tree.insert('', 'end', values=('—', 'No previous runs found', '—', '—', 'Create a new run first'))
            return
        
        for run in runs:
            # Determine status from state file
            state_file = os.path.join(run['folder_path'], 'run_state.json')
            status = "Unknown"
            if os.path.exists(state_file):
                try:
                    with open(state_file, 'r') as f:
                        state = json.load(f)
                        if state.get('is_complete'):
                            status = "✓ Complete"
                        elif state.get('is_paused'):
                            status = "⏸ Paused"
                        else:
                            stage = state.get('current_stage', 0)
                            status = f"Stage {stage}" if stage > 0 else "Ready"
                except:
                    status = "Unknown"
            elif run['csv_path']:
                status = "✓ Has Results"
            else:
                status = "No data"
            
            self.runs_tree.insert('', 'end', values=(
                run['run_number'],
                run['date_str'],
                run['website_count'],
                status,
                run['folder_name']
            ), tags=(run['folder_path'],))
    
    def browse_for_folder(self):
        """Open folder browser to select a run folder."""
        runs_dir = os.path.abspath("runs")
        if not os.path.exists(runs_dir):
            runs_dir = os.getcwd()
        
        folder = filedialog.askdirectory(
            title="Select Run Folder",
            initialdir=runs_dir
        )
        
        if folder:
            # Check if it's a valid run folder
            state_file = os.path.join(folder, 'run_state.json')
            config_file = os.path.join(folder, 'config.json')
            
            if os.path.exists(state_file) or os.path.exists(config_file):
                self.selected_run = folder
                self.root.destroy()
                app = UnifiedLeadGenGUI(resume_run_folder=folder)
                app.run()
            else:
                messagebox.showwarning("Invalid Folder", 
                    "This doesn't appear to be a valid run folder.\n\n"
                    "Please select a folder created by Sherpa Lead Generator.")
    
    def continue_selected(self):
        """Continue the selected run from the tree."""
        selection = self.runs_tree.selection()
        if not selection:
            messagebox.showinfo("Select a Run", "Please select a run from the list or browse for a folder.")
            return
        
        item = self.runs_tree.item(selection[0])
        folder_name = item['values'][4]  # Folder column
        
        if folder_name == 'Create a new run first':
            self.back_to_main()
            return
        
        # Get full folder path
        folder_path = os.path.join("runs", folder_name)
        
        if os.path.exists(folder_path):
            self.root.destroy()
            app = UnifiedLeadGenGUI(resume_run_folder=folder_path)
            app.run()
        else:
            messagebox.showerror("Folder Not Found", f"Run folder not found: {folder_path}")
    
    def back_to_main(self):
        """Go back to main popup."""
        self.root.destroy()
        app = InitialPopupGUI()
        app.run()
    
    def run(self):
        """Run the continue GUI."""
        self.root.mainloop()

class DownloadLeadsGUI:
    """GUI for downloading leads from previous runs."""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Download Results - Sherpa Lead Generator")
        self.root.geometry("900x550")
        self.root.resizable(True, True)
        
        # Make maximized (windowed fullscreen - keeps title bar and close button)
        self.root.state('zoomed')
        
        self.setup_gui()
    
    def setup_gui(self):
        """Setup the download leads interface."""
        ttk.Label(self.root, text="Download Results", font=('Arial', 14, 'bold')).pack(pady=10)
        
        ttk.Label(self.root, text="Select a run to download its results (sorted by most recent):", 
                  font=('Arial', 10)).pack(pady=5)
        
        # Create treeview for run list
        tree_frame = ttk.Frame(self.root)
        tree_frame.pack(fill='both', expand=True, padx=20, pady=10)
        
        columns = ('Run #', 'Date/Time', 'Websites Processed', 'Status', 'CSV File')
        self.runs_tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=15)
        
        self.runs_tree.heading('Run #', text='Run #')
        self.runs_tree.heading('Date/Time', text='Date/Time')
        self.runs_tree.heading('Websites Processed', text='Websites Processed')
        self.runs_tree.heading('Status', text='Status')
        self.runs_tree.heading('CSV File', text='CSV File')
        
        self.runs_tree.column('Run #', width=60)
        self.runs_tree.column('Date/Time', width=150)
        self.runs_tree.column('Websites Processed', width=130)
        self.runs_tree.column('Status', width=100)
        self.runs_tree.column('CSV File', width=350)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.runs_tree.yview)
        self.runs_tree.configure(yscrollcommand=scrollbar.set)
        
        self.runs_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # Double-click to download
        self.runs_tree.bind('<Double-1>', lambda e: self.download_selected())
        
        # Load runs
        self.load_runs()
        
        # Buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(pady=15)
        
        ttk.Button(button_frame, text="📥 Download Selected", command=self.download_selected).pack(side='left', padx=5)
        ttk.Button(button_frame, text="📥 Download All (Comprehensive)", command=self.download_comprehensive).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Back", command=self.back_to_main).pack(side='left', padx=5)
    
    def load_runs(self):
        """Load all runs from run folders, sorted by recency."""
        runs = get_all_run_folders()
        
        if not runs:
            self.runs_tree.insert('', 'end', values=('—', 'No runs found', '0', '—', 'Create a new run first'))
            return
        
        for run in runs:
            # Determine status from state file
            state_file = os.path.join(run['folder_path'], 'run_state.json')
            status = "Unknown"
            if os.path.exists(state_file):
                try:
                    with open(state_file, 'r') as f:
                        state = json.load(f)
                        if state.get('is_complete'):
                            status = "✓ Complete"
                        elif state.get('is_paused'):
                            status = "⏸ Paused"
                        else:
                            stage = state.get('current_stage', 0)
                            status = f"Stage {stage}" if stage > 0 else "In Progress"
                except:
                    pass
            elif run['csv_path']:
                status = "✓ Has Results"
            
            csv_name = os.path.basename(run['csv_path']) if run['csv_path'] else "No CSV found"
            
            self.runs_tree.insert('', 'end', values=(
                run['run_number'],
                run['date_str'],
                run['website_count'],
                status,
                csv_name
            ), tags=(run['folder_path'], run['csv_path'] or ''))
    
    def download_selected(self):
        """Download CSV for the selected run."""
        selection = self.runs_tree.selection()
        if not selection:
            messagebox.showinfo("Select a Run", "Please select a run from the list to download.")
            return
        
        item = self.runs_tree.item(selection[0])
        values = item['values']
        
        if values[0] == '—':
            messagebox.showinfo("No Runs", "No runs available to download.")
            return
        
        run_number = values[0]
        folder_path = item['tags'][0] if item['tags'] else None
        original_csv = item['tags'][1] if len(item['tags']) > 1 else None
        
        if not original_csv or not os.path.exists(original_csv):
            messagebox.showwarning("No CSV", f"No CSV file found for Run {run_number}.")
            return
        
        # Ask where to save
        default_name = f"Run_{run_number}_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=default_name,
            title="Save Results CSV"
        )
        
        if not filepath:
            return
        
        try:
            # Copy the CSV to the new location
            shutil.copy2(original_csv, filepath)
            
            messagebox.showinfo("Success", f"Results saved to:\n{filepath}\n\n{values[2]} websites included.")
            
            # Return to initial screen
            self.back_to_main()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save CSV: {str(e)}")
    
    def download_comprehensive(self):
        """Download all leads from comprehensive database."""
        try:
            comprehensive_logger = ComprehensiveLogger()
            df = comprehensive_logger.get_comprehensive_data()
            
            if df.empty:
                messagebox.showinfo("No Data", "No leads found in the comprehensive database.")
                return
            
            # Sort data
            df = self.sort_leads_data(df)
            
            # Ask where to save
            default_name = f"comprehensive_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            filepath = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                initialfile=default_name,
                title="Save Comprehensive Results"
            )
            
            if not filepath:
                return
            
            df.to_csv(filepath, index=False)
            messagebox.showinfo("Success", f"Comprehensive results saved to:\n{filepath}\n\n{len(df)} leads included.")
            
            # Return to initial screen
            self.back_to_main()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to download CSV: {str(e)}")
    
    def sort_leads_data(self, df):
        """Sort leads data according to the specified requirements."""
        if df.empty:
            return df
        
        # Create a priority column for sorting
        def get_priority(row):
            stage = row.get('stage', '')
            score = row.get('score', 0) or 0
            
            if stage == 'contact_scored':
                return (0, -score)
            elif stage == 'contact_scraped':
                return (1, -score)
            elif stage == 'ai_analyzed':
                return (2, -score)
            elif stage == 'scored':
                return (3, -score)
            elif stage == 'scraped':
                return (4, 0)
            elif stage == 'discovered':
                return (5, 0)
            else:
                return (6, 0)
        
        df['priority'] = df.apply(get_priority, axis=1)
        df = df.sort_values('priority')
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
    
    def __init__(self, resume_run_folder: str = None):
        self.config = UnifiedConfig()
        self.root = tk.Tk()
        self.root.title("Sherpa Lead Generator")
        
        # Make maximized (limited fullscreen - keeps title bar and close button)
        self.root.state('zoomed')  # Windows maximized mode
        
        self.is_running = False  # Track if bot is actively running
        self.current_run_folder = None  # Current run folder path
        self.run_state_tracker = None  # State tracker for current run
        self.resume_run_folder = resume_run_folder  # Folder to resume from (if any)
        
        # Handle window close (X button) - prompt to save
        self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)
        
        self.setup_gui()
    
    def setup_gui(self):
        """Setup the GUI interface."""
        # Create main container
        main_container = ttk.Frame(self.root)
        main_container.pack(fill='both', expand=True, padx=10, pady=(10, 0))
        
        # Store references to scrollable canvases for mousewheel handling
        self._scrollable_canvases = []
        
        # Create notebook for tabs
        notebook = ttk.Notebook(main_container)
        notebook.pack(fill='both', expand=True)
        self._notebook = notebook
        
        # Onboarding Tab (first tab)
        self.setup_onboarding_tab(notebook)
        
        # Step 1 Tab
        self.setup_step1_tab(notebook)
        
        # Step 2 Tab: AI Analysis (formerly Step 4)
        self.setup_step2_tab(notebook)
        
        # Step 3 Tab: Run (formerly Control/Run Pipeline)
        self.setup_step3_tab(notebook)
        
        # Advanced Settings Tab
        self.setup_advanced_tab(notebook)
        
        # Bottom ribbon with progress bar and Save and Exit button
        self.setup_bottom_ribbon()
        
        # Setup unified mousewheel scrolling handler
        self._setup_mousewheel_handler()
    
    def _setup_mousewheel_handler(self):
        """Setup smart mousewheel scrolling that handles Text widgets and page scrolling."""
        def _calc_scroll_amount(delta):
            """Calculate scroll amount - works with both mouse wheel and touchpad.
            
            Mouse wheels typically send delta in multiples of 120.
            Touchpads may send smaller deltas. Ensure at least 1 unit scroll.
            """
            if delta == 0:
                return 0
            # Determine direction
            direction = -1 if delta > 0 else 1
            # Calculate units (at least 1)
            units = max(1, abs(delta) // 120)
            return direction * units
        
        def _on_mousewheel(event):
            # Get the widget under the mouse cursor
            widget = event.widget.winfo_containing(event.x_root, event.y_root)
            
            if widget is None:
                return
            
            scroll_amount = _calc_scroll_amount(event.delta)
            if scroll_amount == 0:
                return
            
            # Check if the widget or any of its parents is a Text widget
            current = widget
            text_widget = None
            while current:
                if isinstance(current, tk.Text):
                    text_widget = current
                    break
                try:
                    current = current.master
                except:
                    break
            
            if text_widget:
                # Check if the Text widget has more content than visible (needs scrolling)
                try:
                    # Check if content exceeds visible area
                    bbox = text_widget.bbox("end-1c")
                    if bbox:
                        # Content fits in view, check if there's content above visible area
                        first_visible = text_widget.index("@0,0")
                        if first_visible != "1.0":
                            # There's content above, allow scrolling
                            text_widget.yview_scroll(scroll_amount, "units")
                            return "break"
                        # Content fits and we're at top - fall through to scroll page
                    else:
                        # bbox is None means end is not visible, content exceeds view
                        text_widget.yview_scroll(scroll_amount, "units")
                        return "break"
                except:
                    pass
            
            # Otherwise, scroll the canvas (page) - find it in widget hierarchy
            try:
                current = widget
                while current:
                    if isinstance(current, tk.Canvas) and current in self._scrollable_canvases:
                        current.yview_scroll(scroll_amount, "units")
                        return "break"
                    try:
                        current = current.master
                    except:
                        break
                
                # If no canvas found in direct hierarchy, find canvas in current tab frame
                current_tab = self._notebook.select()
                if current_tab:
                    tab_frame = self._notebook.nametowidget(current_tab)
                    # Search for a canvas child in the tab frame
                    for canvas in self._scrollable_canvases:
                        try:
                            if str(canvas.master) == str(tab_frame):
                                canvas.yview_scroll(scroll_amount, "units")
                                return "break"
                        except:
                            pass
            except:
                pass
        
        # Bind to the root window to catch all mousewheel events
        self.root.bind_all("<MouseWheel>", _on_mousewheel)
    
    def setup_onboarding_tab(self, notebook):
        """Setup the onboarding/user input tab."""
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Setup")
        
        # Create scrollable canvas
        canvas = tk.Canvas(frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Bind canvas width to scrollable_frame width so it expands properly
        def configure_scrollable_frame(event):
            canvas_width = event.width
            canvas.itemconfig(canvas_window, width=canvas_width)
        canvas.bind('<Configure>', configure_scrollable_frame)
        
        # Store canvas reference for mousewheel handling
        self._scrollable_canvases.append(canvas)
        
        # Pack scrollbar FIRST so it gets space before canvas expands
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        row = 0
        user_inputs = self.config.config.get("user_inputs", {})
        
        # Load field config from JSON
        try:
            config_path = os.path.join(os.path.dirname(__file__), "user_input_config.json")
            with open(config_path, 'r', encoding='utf-8') as f:
                input_config = json.load(f)
        except:
            input_config = None
        
        # === SINGLE PROMPT MODE BUTTON ===
        single_prompt_frame = ttk.LabelFrame(scrollable_frame, text="Quick Setup", padding=10)
        single_prompt_frame.grid(row=row, column=0, columnspan=3, sticky='ew', padx=10, pady=5)
        row += 1
        
        ttk.Button(single_prompt_frame, text="Answer One Prompt Instead", 
                   command=self._toggle_single_prompt_mode).pack(side='left')
        ttk.Label(single_prompt_frame, text="  Describe everything in one text box (for AI-generated or detailed responses)", 
                  foreground='gray').pack(side='left')
        
        # Single prompt text area (hidden by default)
        self.single_prompt_container = ttk.Frame(scrollable_frame)
        self.single_prompt_container.grid(row=row, column=0, columnspan=3, sticky='ew', padx=10, pady=5)
        self.single_prompt_visible = False
        row += 1
        
        # Build single prompt UI (initially hidden)
        self._build_single_prompt_ui()
        
        # === GUIDED MODE FIELDS ===
        self.guided_fields_container = ttk.Frame(scrollable_frame)
        self.guided_fields_container.grid(row=row, column=0, columnspan=3, sticky='ew', padx=10, pady=5)
        row += 1
        
        gf_row = 0
        
        # --- Business Identity ---
        ttk.Label(self.guided_fields_container, text="Business Identity", font=('Arial', 11, 'bold')).grid(
            row=gf_row, column=0, sticky='w', pady=(10, 5))
        gf_row += 1
        
        # Business Name *required*
        ttk.Label(self.guided_fields_container, text="Business Name *required*").grid(row=gf_row, column=0, sticky='w')
        entry_frame_bn = ttk.Frame(self.guided_fields_container)
        entry_frame_bn.grid(row=gf_row, column=1, sticky='ew', padx=5)
        self.input_business_name = ttk.Entry(entry_frame_bn, width=50)
        self.input_business_name.insert(0, user_inputs.get("business_name", ""))
        self.input_business_name.pack(fill='x', expand=True)
        gf_row += 1
        
        # Website URL *required*
        ttk.Label(self.guided_fields_container, text="Website URL *required*").grid(row=gf_row, column=0, sticky='w')
        entry_frame_wu = ttk.Frame(self.guided_fields_container)
        entry_frame_wu.grid(row=gf_row, column=1, sticky='ew', padx=5)
        self.input_website_url = ttk.Entry(entry_frame_wu, width=50)
        self.input_website_url.insert(0, user_inputs.get("website_url", ""))
        self.input_website_url.pack(fill='x', expand=True)
        ttk.Label(self.guided_fields_container, text="We'll scrape this for context", foreground='gray').grid(
            row=gf_row, column=2, sticky='w')
        gf_row += 1
        
        # --- What You Sell ---
        ttk.Label(self.guided_fields_container, text="What You Sell", font=('Arial', 11, 'bold')).grid(
            row=gf_row, column=0, sticky='w', pady=(15, 5))
        gf_row += 1
        
        # Product Description *required*
        ttk.Label(self.guided_fields_container, text="What do you sell? *required*").grid(row=gf_row, column=0, sticky='w')
        entry_frame_prod = ttk.Frame(self.guided_fields_container)
        entry_frame_prod.grid(row=gf_row, column=1, sticky='ew', padx=5)
        self.input_product_description = ttk.Entry(entry_frame_prod, width=60)
        self.input_product_description.insert(0, user_inputs.get("product_description", ""))
        self.input_product_description.pack(fill='x', expand=True)
        gf_row += 1
        ttk.Label(self.guided_fields_container, text="e.g., \"B2B SaaS for inventory\", \"Executive recruiting\", \"Equipment maintenance\"", 
                  foreground='gray').grid(row=gf_row, column=1, sticky='w', padx=5)
        gf_row += 1
        
        # Price Range
        price_frame = ttk.Frame(self.guided_fields_container)
        price_frame.grid(row=gf_row, column=0, columnspan=2, sticky='w', pady=5)
        ttk.Label(price_frame, text="Price range per deal").pack(side='left')
        ttk.Label(price_frame, text="  Min $").pack(side='left')
        self.input_price_min = ttk.Entry(price_frame, width=12)
        self.input_price_min.insert(0, user_inputs.get("price_min", ""))
        self.input_price_min.pack(side='left')
        ttk.Label(price_frame, text=" to Max $").pack(side='left')
        self.input_price_max = ttk.Entry(price_frame, width=12)
        self.input_price_max.insert(0, user_inputs.get("price_max", ""))
        self.input_price_max.pack(side='left')
        ttk.Label(price_frame, text="  (leave blank if variable)", foreground='gray').pack(side='left')
        gf_row += 1
        
        # --- Ideal Customer ---
        ttk.Label(self.guided_fields_container, text="Ideal Customer", font=('Arial', 11, 'bold')).grid(
            row=gf_row, column=0, sticky='w', pady=(15, 5))
        gf_row += 1
        
        # Ideal Customer *required*
        ttk.Label(self.guided_fields_container, text="Describe ideal customer *required*").grid(row=gf_row, column=0, sticky='nw')
        self.input_ideal_customer = tk.Text(self.guided_fields_container, width=60, height=3)
        self.input_ideal_customer.insert("1.0", user_inputs.get("ideal_customer", ""))
        self.input_ideal_customer.grid(row=gf_row, column=1, sticky='ew', padx=5)
        gf_row += 1
        ttk.Label(self.guided_fields_container, text="e.g., \"Mid-size e-commerce companies struggling with fulfillment\"", 
                  foreground='gray').grid(row=gf_row, column=1, sticky='w', padx=5)
        gf_row += 1
        
        # Company Size
        ttk.Label(self.guided_fields_container, text="Target company size").grid(row=gf_row, column=0, sticky='w')
        entry_frame_cs = ttk.Frame(self.guided_fields_container)
        entry_frame_cs.grid(row=gf_row, column=1, sticky='ew', padx=5)
        self.input_company_size = ttk.Entry(entry_frame_cs, width=60)
        self.input_company_size.insert(0, user_inputs.get("company_size", ""))
        self.input_company_size.pack(fill='x', expand=True)
        gf_row += 1
        ttk.Label(self.guided_fields_container, text="e.g., 50-500 employees, $5M-$100M revenue, Series A+", 
                  foreground='gray').grid(row=gf_row, column=1, sticky='w', padx=5)
        gf_row += 1
        
        # Geography
        ttk.Label(self.guided_fields_container, text="Geographic requirements").grid(row=gf_row, column=0, sticky='w')
        self.input_geography = ttk.Entry(self.guided_fields_container, width=60)
        self.input_geography.insert(0, user_inputs.get("geography", ""))
        self.input_geography.grid(row=gf_row, column=1, sticky='ew', padx=5)
        gf_row += 1
        ttk.Label(self.guided_fields_container, text="e.g., \"US only\", \"English-speaking\", \"No restrictions\"", 
                  foreground='gray').grid(row=gf_row, column=1, sticky='w', padx=5)
        gf_row += 1
        
        # --- Decision Makers ---
        ttk.Label(self.guided_fields_container, text="Decision Makers", font=('Arial', 11, 'bold')).grid(
            row=gf_row, column=0, sticky='w', pady=(15, 5))
        gf_row += 1
        
        # Seniority Levels
        ttk.Label(self.guided_fields_container, text="Seniority levels that buy").grid(row=gf_row, column=0, sticky='w')
        entry_frame_sl = ttk.Frame(self.guided_fields_container)
        entry_frame_sl.grid(row=gf_row, column=1, sticky='ew', padx=5)
        self.input_seniority_levels = ttk.Entry(entry_frame_sl, width=60)
        self.input_seniority_levels.insert(0, user_inputs.get("seniority_levels", ""))
        self.input_seniority_levels.pack(fill='x', expand=True)
        gf_row += 1
        ttk.Label(self.guided_fields_container, text="e.g., CEO, VP, Director, Manager, Head of", 
                  foreground='gray').grid(row=gf_row, column=1, sticky='w', padx=5)
        gf_row += 1
        
        # Departments
        ttk.Label(self.guided_fields_container, text="Departments you sell to").grid(row=gf_row, column=0, sticky='w')
        self.input_departments = ttk.Entry(self.guided_fields_container, width=60)
        self.input_departments.insert(0, user_inputs.get("departments", ""))
        self.input_departments.grid(row=gf_row, column=1, sticky='ew', padx=5)
        gf_row += 1
        ttk.Label(self.guided_fields_container, text="e.g., IT, Marketing, Operations, Finance, HR, Engineering", 
                  foreground='gray').grid(row=gf_row, column=1, sticky='w', padx=5)
        gf_row += 1
        
        # --- Exclusions ---
        ttk.Label(self.guided_fields_container, text="Exclusions", font=('Arial', 11, 'bold')).grid(
            row=gf_row, column=0, sticky='w', pady=(15, 5))
        gf_row += 1
        
        ttk.Label(self.guided_fields_container, text="Who should we exclude?").grid(row=gf_row, column=0, sticky='nw')
        self.input_exclusions = tk.Text(self.guided_fields_container, width=60, height=2)
        self.input_exclusions.insert("1.0", user_inputs.get("exclusions", ""))
        self.input_exclusions.grid(row=gf_row, column=1, sticky='ew', padx=5)
        gf_row += 1
        ttk.Label(self.guided_fields_container, text="Industries, company types, competitors. e.g., \"Agencies, Government, Acme Corp\"", 
                  foreground='gray').grid(row=gf_row, column=1, sticky='w', padx=5)
        gf_row += 1
        
        # --- Examples & Context ---
        ttk.Label(self.guided_fields_container, text="Examples & Context", font=('Arial', 11, 'bold')).grid(
            row=gf_row, column=0, sticky='w', pady=(15, 5))
        gf_row += 1
        
        # Good Leads URLs
        ttk.Label(self.guided_fields_container, text="Example customers (URLs)").grid(row=gf_row, column=0, sticky='nw')
        self.input_good_leads = tk.Text(self.guided_fields_container, width=60, height=2)
        self.input_good_leads.insert("1.0", user_inputs.get("good_leads", ""))
        self.input_good_leads.grid(row=gf_row, column=1, sticky='ew', padx=5)
        gf_row += 1
        ttk.Label(self.guided_fields_container, text="3-10 URLs separated by commas or new lines", 
                  foreground='gray').grid(row=gf_row, column=1, sticky='w', padx=5)
        gf_row += 1
        
        # Search Keywords
        ttk.Label(self.guided_fields_container, text="Search terms that work").grid(row=gf_row, column=0, sticky='nw')
        self.input_search_keywords = tk.Text(self.guided_fields_container, width=60, height=3)
        self.input_search_keywords.insert("1.0", user_inputs.get("search_keywords", ""))
        self.input_search_keywords.grid(row=gf_row, column=1, sticky='ew', padx=5)
        gf_row += 1
        ttk.Label(self.guided_fields_container, text="Group by: Industry, Problem, Stage, Tech. One from each combines into searches.", 
                  foreground='gray').grid(row=gf_row, column=1, sticky='w', padx=5)
        gf_row += 1
        
        # Other Context
        ttk.Label(self.guided_fields_container, text="Anything else?").grid(row=gf_row, column=0, sticky='nw')
        self.input_other_context = tk.Text(self.guided_fields_container, width=60, height=2)
        self.input_other_context.insert("1.0", user_inputs.get("other_context", ""))
        self.input_other_context.grid(row=gf_row, column=1, sticky='ew', padx=5)
        gf_row += 1
        ttk.Label(self.guided_fields_container, text="Buying signals, timing. e.g., \"Raised funding = strong signal\"", 
                  foreground='gray').grid(row=gf_row, column=1, sticky='w', padx=5)
        gf_row += 1
        
        # --- Preferences ---
        ttk.Label(self.guided_fields_container, text="Preferences", font=('Arial', 11, 'bold')).grid(
            row=gf_row, column=0, sticky='w', pady=(15, 5))
        gf_row += 1
        
        # Extract Contacts
        self.input_extract_contacts = tk.BooleanVar(value=user_inputs.get("extract_contacts", True))
        contacts_frame = ttk.Frame(self.guided_fields_container)
        contacts_frame.grid(row=gf_row, column=0, columnspan=2, sticky='w')
        ttk.Checkbutton(contacts_frame, text="Extract individual contacts", 
                        variable=self.input_extract_contacts).pack(side='left')
        ttk.Label(contacts_frame, text="  Find names, titles, and emails at each company", 
                  foreground='gray').pack(side='left')
        gf_row += 1
        
        # Configure column weights
        self.guided_fields_container.columnconfigure(1, weight=1)
        scrollable_frame.columnconfigure(0, weight=1)
    
    def _build_single_prompt_ui(self):
        """Build the single prompt mode UI (hidden by default)."""
        # Get comprehensive description
        description = self._get_single_prompt_description()
        
        # Create frame for description with scrollable text
        self.single_prompt_desc_frame = ttk.Frame(self.single_prompt_container)
        
        desc_text = tk.Text(self.single_prompt_desc_frame, width=100, height=18, wrap='word',
                           foreground='#555555', background='#f8f8f8',
                           relief='flat', padx=10, pady=10)
        desc_text.insert("1.0", description)
        desc_text.config(state='disabled')  # Make read-only
        desc_text.pack(side='left', fill='x', expand=True)
        
        desc_scrollbar = ttk.Scrollbar(self.single_prompt_desc_frame, orient='vertical', command=desc_text.yview)
        desc_scrollbar.pack(side='right', fill='y')
        desc_text.config(yscrollcommand=desc_scrollbar.set)
        
        # Copy button
        self.single_prompt_copy_btn = ttk.Button(self.single_prompt_container, 
                                                  text="📋 Copy Description to Clipboard",
                                                  command=lambda: self._copy_to_clipboard(description))
        
        # Store reference for toggling
        self.single_prompt_example = self.single_prompt_desc_frame
        
        self.single_prompt_text = tk.Text(self.single_prompt_container, width=100, height=15)
        self.single_prompt_text.insert("1.0", self.config.config.get("user_inputs", {}).get("single_prompt_response", ""))
    
    def _toggle_single_prompt_mode(self):
        """Toggle between single prompt and guided mode."""
        if self.single_prompt_visible:
            # Hide single prompt, show guided
            self.single_prompt_example.pack_forget()
            self.single_prompt_copy_btn.pack_forget()
            self.single_prompt_text.pack_forget()
            self.guided_fields_container.grid()
            self.single_prompt_visible = False
        else:
            # Show single prompt, hide guided
            self.guided_fields_container.grid_remove()
            self.single_prompt_example.pack(anchor='w', pady=5, fill='x')
            self.single_prompt_copy_btn.pack(anchor='w', pady=(0, 10))
            self.single_prompt_text.pack(fill='x', pady=5)
            self.single_prompt_visible = True
    
    def setup_step1_tab(self, notebook):
        """Setup Step 1 configuration tab."""
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Step 1: Discovery")
        
        # Create scrollable canvas for the tab
        canvas = tk.Canvas(frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        self.step1_scrollable_frame = ttk.Frame(canvas)
        
        self.step1_scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.step1_scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Store canvas reference for mousewheel handling
        self._scrollable_canvases.append(canvas)
        
        # Pack scrollbar FIRST so it gets space before canvas expands
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        # Header with count control
        header_frame = ttk.Frame(self.step1_scrollable_frame)
        header_frame.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 10))
        
        ttk.Label(header_frame, text="Keywords: One Keyword is Randomly Selected From Each Box. Leave Box Empty to Skip.", 
                  font=('Arial', 12, 'bold')).pack(side='left')
        ttk.Label(header_frame, text="  Put related terms in same box, separated by commas.", 
                  font=('Arial', 9), foreground='gray').pack(side='left')
        
        ttk.Label(header_frame, text="   Number of boxes:").pack(side='left', padx=(20, 5))
        self.keyword_box_count = tk.StringVar(value=str(self.config.config["step1"].get("keyword_box_count", 8)))
        count_entry = ttk.Entry(header_frame, textvariable=self.keyword_box_count, width=5)
        count_entry.pack(side='left')
        ttk.Button(header_frame, text="Update", command=self._rebuild_keyword_boxes).pack(side='left', padx=5)
        
        # Container for keyword boxes (will be rebuilt dynamically)
        self.keyword_boxes_container = ttk.Frame(self.step1_scrollable_frame)
        self.keyword_boxes_container.grid(row=1, column=0, columnspan=3, sticky='ew')
        
        # Build initial keyword boxes
        self.keyword_boxes = []
        self._rebuild_keyword_boxes()
        
        self.step1_scrollable_frame.columnconfigure(1, weight=1)
    
    def _rebuild_keyword_boxes(self):
        """Rebuild keyword boxes based on current count."""
        # Save current values before destroying
        current_values = []
        for box in self.keyword_boxes:
            try:
                current_values.append(box.get("1.0", "end").strip())
            except:
                current_values.append("")
        
        # Destroy existing widgets
        for widget in self.keyword_boxes_container.winfo_children():
            widget.destroy()
        
        # Get count
        try:
            count = int(self.keyword_box_count.get())
            count = max(1, min(50, count))  # Clamp between 1 and 50
        except ValueError:
            count = 8
        
        # Update config
        self.config.config["step1"]["keyword_box_count"] = count
        
        # Create new keyword boxes
        self.keyword_boxes = []
        existing_keywords = self.config.config["step1"].get("keyword_boxes", [])
        
        for i in range(count):
            ttk.Label(self.keyword_boxes_container, text=f"Box {i+1}:").grid(row=i, column=0, sticky='nw', padx=(0, 10))
            box = tk.Text(self.keyword_boxes_container, width=50, height=2)
            
            # Restore value: first from current values, then from config, then from old format
            if i < len(current_values) and current_values[i]:
                box.insert("1.0", current_values[i])
            elif i < len(existing_keywords):
                box.insert("1.0", existing_keywords[i])
            elif i == 0 and "serper_set_keywords" in self.config.config["step1"]:
                box.insert("1.0", self.config.config["step1"]["serper_set_keywords"])
            elif i == 1 and "serper_variable_keywords" in self.config.config["step1"]:
                box.insert("1.0", self.config.config["step1"]["serper_variable_keywords"])
            
            box.grid(row=i, column=1, columnspan=2, sticky='ew')
            self.keyword_boxes.append(box)
        
        self.keyword_boxes_container.columnconfigure(1, weight=1)
    
    def setup_step2_tab(self, notebook):
        """Setup Step 2: AI Analysis configuration tab with multi-score fields."""
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Step 2: AI Analysis")
        
        # Create main canvas with scrollbar for the entire tab
        canvas = tk.Canvas(frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Store canvas reference for mousewheel handling
        self._scrollable_canvases.append(canvas)
        
        # Pack scrollbar FIRST so it gets space before canvas expands
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        row = 0
        
        # === AI Provider/Model Configuration ===
        ttk.Label(scrollable_frame, text="AI Configuration", font=('Arial', 12, 'bold')).grid(row=row, column=0, columnspan=6, sticky='w', pady=(0, 10))
        row += 1
        
        # AI Provider selection
        ttk.Label(scrollable_frame, text="AI Provider:").grid(row=row, column=0, sticky='w')
        self.ai_provider = tk.StringVar(value=self.config.config["step4"].get("provider_choice", "claude"))
        ttk.Radiobutton(scrollable_frame, text="Claude", variable=self.ai_provider, value="claude").grid(row=row, column=1, sticky='w')
        ttk.Radiobutton(scrollable_frame, text="OpenAI", variable=self.ai_provider, value="openai").grid(row=row, column=2, sticky='w')
        ttk.Radiobutton(scrollable_frame, text="Gemini", variable=self.ai_provider, value="gemini").grid(row=row, column=3, sticky='w')
        ttk.Label(scrollable_frame, text="(Claude recommended for accuracy)", font=('Arial', 8), foreground='gray').grid(row=row, column=4, sticky='w', padx=5)
        row += 1
        
        # AI Model selection
        ttk.Label(scrollable_frame, text="AI Model:").grid(row=row, column=0, sticky='w')
        self.ai_model_choice = tk.StringVar(value=self.config.config["step4"].get("model_choice", "model_1"))
        old_choice = self.ai_model_choice.get()
        if old_choice == "fastest":
            self.ai_model_choice.set("model_1")
        elif old_choice == "best":
            self.ai_model_choice.set("model_4")
        
        self.model_labels = []
        for i in range(4):
            rb = ttk.Radiobutton(scrollable_frame, text=f"Model {i+1}", variable=self.ai_model_choice, value=f"model_{i+1}")
            rb.grid(row=row, column=1+i, sticky='w')
            self.model_labels.append(rb)
        row += 1
        ttk.Label(scrollable_frame, text="Model 1 = cheapest/fastest, Model 4 = smartest/slowest", 
                 font=('Arial', 8), foreground='gray').grid(row=row, column=1, columnspan=4, sticky='w')
        row += 1
        
        # API Keys
        ttk.Label(scrollable_frame, text="API Key (Claude/OpenAI):").grid(row=row, column=0, sticky='w')
        self.ai_api_key = tk.StringVar(value=self.config.config["step4"]["api_key"])
        ttk.Entry(scrollable_frame, textvariable=self.ai_api_key, width=50, show="•").grid(row=row, column=1, columnspan=3, sticky='ew')
        ttk.Label(scrollable_frame, text="console.anthropic.com or platform.openai.com", font=('Arial', 8), foreground='gray').grid(row=row, column=4, sticky='w', padx=5)
        row += 1
        
        ttk.Label(scrollable_frame, text="API Key (Gemini):").grid(row=row, column=0, sticky='w')
        self.gemini_api_key = tk.StringVar(value=self.config.config["step4"].get("gemini_api_key", ""))
        ttk.Entry(scrollable_frame, textvariable=self.gemini_api_key, width=50, show="•").grid(row=row, column=1, columnspan=3, sticky='ew')
        ttk.Label(scrollable_frame, text="aistudio.google.com", font=('Arial', 8), foreground='gray').grid(row=row, column=4, sticky='w', padx=5)
        row += 1
        
        ttk.Label(scrollable_frame, text="Credit Limit ($):").grid(row=row, column=0, sticky='w')
        self.credit_limit = tk.StringVar(value=str(self.config.config["step4"].get("credit_limit", "50")))
        ttk.Entry(scrollable_frame, textvariable=self.credit_limit, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(max AI spend - stops when reached. Start with $5-10 for testing)", font=('Arial', 8), foreground='gray').grid(row=row, column=2, columnspan=3, sticky='w')
        row += 1
        
        # Update model descriptions
        self.update_model_descriptions()
        self.ai_provider.trace('w', lambda *args: self.update_model_descriptions())
        
        # === Good Leads Reference Configuration ===
        ttk.Separator(scrollable_frame, orient='horizontal').grid(row=row, column=0, columnspan=6, sticky='ew', pady=10)
        row += 1
        
        ttk.Label(scrollable_frame, text="Good Leads Reference", font=('Arial', 12, 'bold')).grid(row=row, column=0, columnspan=6, sticky='w', pady=(0, 5))
        row += 1
        
        ttk.Label(scrollable_frame, text="Good Leads Domains:").grid(row=row, column=0, sticky='w')
        self.good_leads_domains = tk.StringVar(value=self.config.config["step4"].get("good_leads_domains", ""))
        ttk.Entry(scrollable_frame, textvariable=self.good_leads_domains, width=60).grid(row=row, column=1, columnspan=4, sticky='ew')
        row += 1
        ttk.Label(scrollable_frame, text="Comma-separated list of domains to scrape as examples of ideal customers (e.g., company1.com, company2.com)", 
                 font=('Arial', 8), foreground='gray').grid(row=row, column=1, columnspan=4, sticky='w')
        row += 1
        
        # Good leads scraping settings
        ttk.Label(scrollable_frame, text="Good Leads Scraping Settings:", font=('Arial', 10, 'italic')).grid(row=row, column=0, columnspan=4, sticky='w', pady=(10, 5))
        row += 1
        
        ttk.Label(scrollable_frame, text="Max Pages per Site:").grid(row=row, column=0, sticky='w')
        self.good_leads_max_pages = tk.StringVar(value=str(self.config.config["step4"].get("good_leads_max_pages_per_site", 12)))
        ttk.Entry(scrollable_frame, textvariable=self.good_leads_max_pages, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="Max Depth:").grid(row=row, column=2, sticky='e', padx=(20, 5))
        self.good_leads_max_depth = tk.StringVar(value=str(self.config.config["step4"].get("good_leads_max_depth", 2)))
        ttk.Entry(scrollable_frame, textvariable=self.good_leads_max_depth, width=10).grid(row=row, column=3, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="Max Chars per Page:").grid(row=row, column=0, sticky='w')
        self.good_leads_max_chars_per_page = tk.StringVar(value=str(self.config.config["step4"].get("good_leads_max_chars_per_page", 50000)))
        ttk.Entry(scrollable_frame, textvariable=self.good_leads_max_chars_per_page, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="Aggregate Char Cap:").grid(row=row, column=2, sticky='e', padx=(20, 5))
        self.good_leads_aggregate_cap = tk.StringVar(value=str(self.config.config["step4"].get("good_leads_aggregate_char_cap", 120000)))
        ttk.Entry(scrollable_frame, textvariable=self.good_leads_aggregate_cap, width=10).grid(row=row, column=3, sticky='w')
        row += 1
        
        # Summarization settings
        ttk.Label(scrollable_frame, text="Summarization Settings:", font=('Arial', 10, 'italic')).grid(row=row, column=0, columnspan=4, sticky='w', pady=(10, 5))
        row += 1
        
        ttk.Label(scrollable_frame, text="Summarization Prompt:").grid(row=row, column=0, sticky='nw')
        self.good_leads_summarization_prompt = tk.Text(scrollable_frame, width=70, height=4, wrap='word')
        default_prompt = self.config.config["step4"].get("good_leads_summarization_prompt", 
            "Analyze these websites of ideal customer companies. For each, summarize: what type of business they are, their main products/services, their location/headquarters, their company size/funding stage, and what makes them an ideal customer. Remove marketing fluff and focus on concrete facts.")
        self.good_leads_summarization_prompt.insert("1.0", default_prompt)
        self.good_leads_summarization_prompt.grid(row=row, column=1, columnspan=4, sticky='ew', pady=2)
        row += 1
        ttk.Label(scrollable_frame, text="Prompt for AI to summarize good leads websites before scoring (one API call for all)", 
                 font=('Arial', 8), foreground='gray').grid(row=row, column=1, columnspan=4, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="Max Summary Chars:").grid(row=row, column=0, sticky='w')
        self.good_leads_max_summary_chars = tk.StringVar(value=str(self.config.config["step4"].get("good_leads_max_summary_chars", 8000)))
        ttk.Entry(scrollable_frame, textvariable=self.good_leads_max_summary_chars, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(max chars for combined summary of all good leads)", 
                 font=('Arial', 8), foreground='gray').grid(row=row, column=2, columnspan=3, sticky='w')
        row += 1
        
        # === Scoring Fields Configuration ===
        ttk.Separator(scrollable_frame, orient='horizontal').grid(row=row, column=0, columnspan=6, sticky='ew', pady=10)
        row += 1
        
        # Header with count control
        scoring_header = ttk.Frame(scrollable_frame)
        scoring_header.grid(row=row, column=0, columnspan=6, sticky='ew', pady=(0, 5))
        ttk.Label(scoring_header, text="Scoring Fields", font=('Arial', 12, 'bold')).pack(side='left')
        ttk.Label(scoring_header, text="   Number of fields:").pack(side='left', padx=(20, 5))
        self.scoring_field_count = tk.StringVar(value=str(self.config.config["step4"].get("scoring_field_count", 20)))
        ttk.Entry(scoring_header, textvariable=self.scoring_field_count, width=5).pack(side='left')
        ttk.Button(scoring_header, text="Update", command=lambda: self._rebuild_scoring_fields(scrollable_frame)).pack(side='left', padx=5)
        row += 1
        
        ttk.Label(scrollable_frame, text="Configure fields for AI to score. Empty/disabled fields are skipped. 'score' = numeric rating, 'text' = category selection.", 
                 font=('Arial', 9), foreground='gray').grid(row=row, column=0, columnspan=6, sticky='w')
        row += 1
        
        # Store reference to scrollable_frame and starting row for rebuild
        self.scoring_fields_scrollable_frame = scrollable_frame
        self.scoring_fields_start_row = row
        
        # Container for scoring fields
        self.scoring_fields_container = ttk.Frame(scrollable_frame)
        self.scoring_fields_container.grid(row=row, column=0, columnspan=6, sticky='ew')
        row += 1
        
        # Initialize scoring field widgets storage and build
        self.scoring_field_widgets = []
        self._rebuild_scoring_fields(scrollable_frame, initial=True)
        
        # Configure scrollable frame column weights
        scrollable_frame.columnconfigure(1, weight=1)
    
    def _rebuild_scoring_fields(self, scrollable_frame, initial=False):
        """Rebuild scoring fields based on current count."""
        # Save current values before destroying (unless initial build)
        current_values = []
        if not initial:
            for widgets in self.scoring_field_widgets:
                try:
                    field = {
                        "enabled": widgets['enabled'].get(),
                        "type": widgets['type'].get(),
                        "title": widgets['title'].get().strip(),
                        "min": widgets['min'].get(),
                        "max": widgets['max'].get(),
                        "prompt": widgets['prompt'].get("1.0", tk.END).strip(),
                        "allow_unlisted": widgets['allow_unlisted'].get(),
                        "allow_multiple": widgets['allow_multiple'].get(),
                        "options": widgets['options'].get()
                    }
                    current_values.append(field)
                except:
                    current_values.append({})
        
        # Destroy existing widgets
        for widget in self.scoring_fields_container.winfo_children():
            widget.destroy()
        
        # Get count
        try:
            count = int(self.scoring_field_count.get())
            count = max(1, min(50, count))  # Clamp between 1 and 50
        except ValueError:
            count = 20
        
        # Update config
        self.config.config["step4"]["scoring_field_count"] = count
        
        # Load existing fields from config (for initial load)
        existing_fields = self.config.config["step4"].get("scoring_fields", [])
        
        # Create new scoring fields
        self.scoring_field_widgets = []
        row = 0
        
        for i in range(count):
            field_frame = ttk.LabelFrame(self.scoring_fields_container, text=f"Field {i+1}", padding=5)
            field_frame.grid(row=row, column=0, columnspan=6, sticky='ew', pady=5, padx=5)
            row += 1
            
            field_widgets = {}
            
            # Get field data: first from saved values, then from config
            if i < len(current_values) and current_values[i]:
                field_data = current_values[i]
            elif i < len(existing_fields):
                field_data = existing_fields[i]
            else:
                field_data = {}
            
            # Row 0: Enable, Type, Title
            field_widgets['enabled'] = tk.BooleanVar(value=field_data.get('enabled', False))
            ttk.Checkbutton(field_frame, text="Enabled", variable=field_widgets['enabled']).grid(row=0, column=0, sticky='w')
            
            field_widgets['type'] = tk.StringVar(value=field_data.get('type', 'score'))
            ttk.Label(field_frame, text="Type:").grid(row=0, column=1, sticky='w', padx=(10, 0))
            type_combo = ttk.Combobox(field_frame, textvariable=field_widgets['type'], values=['score', 'text'], width=8, state='readonly')
            type_combo.grid(row=0, column=2, sticky='w')
            
            ttk.Label(field_frame, text="Title:").grid(row=0, column=3, sticky='w', padx=(10, 0))
            field_widgets['title'] = tk.StringVar(value=field_data.get('title', ''))
            ttk.Entry(field_frame, textvariable=field_widgets['title'], width=25).grid(row=0, column=4, sticky='w')
            
            # Row 1: Score-specific fields (min, max) OR Text-specific fields (allow_unlisted, allow_multiple)
            score_frame = ttk.Frame(field_frame)
            score_frame.grid(row=1, column=0, columnspan=6, sticky='ew', pady=2)
            
            ttk.Label(score_frame, text="Min:").grid(row=0, column=0, sticky='w')
            field_widgets['min'] = tk.StringVar(value=str(field_data.get('min', 0)))
            ttk.Entry(score_frame, textvariable=field_widgets['min'], width=5).grid(row=0, column=1, sticky='w')
            
            ttk.Label(score_frame, text="Max:").grid(row=0, column=2, sticky='w', padx=(10, 0))
            field_widgets['max'] = tk.StringVar(value=str(field_data.get('max', 10)))
            ttk.Entry(score_frame, textvariable=field_widgets['max'], width=5).grid(row=0, column=3, sticky='w')
            
            # Text-specific options
            field_widgets['allow_unlisted'] = tk.BooleanVar(value=field_data.get('allow_unlisted', True))
            ttk.Checkbutton(score_frame, text="Allow unlisted", variable=field_widgets['allow_unlisted']).grid(row=0, column=4, sticky='w', padx=(20, 0))
            
            field_widgets['allow_multiple'] = tk.BooleanVar(value=field_data.get('allow_multiple', False))
            ttk.Checkbutton(score_frame, text="Allow multiple", variable=field_widgets['allow_multiple']).grid(row=0, column=5, sticky='w', padx=(10, 0))
            
            # Row 2: Prompt
            ttk.Label(field_frame, text="Prompt:").grid(row=2, column=0, sticky='nw', pady=2)
            field_widgets['prompt'] = tk.Text(field_frame, width=70, height=2, wrap='word')
            prompt_value = field_data.get('prompt', '')
            field_widgets['prompt'].insert("1.0", prompt_value)
            field_widgets['prompt'].grid(row=2, column=1, columnspan=5, sticky='ew', pady=2)
            
            # Row 3: Options (for text type) - single line entry, semicolon-separated
            ttk.Label(field_frame, text="Options:").grid(row=3, column=0, sticky='w', pady=2)
            existing_options = field_data.get('options', [])
            if isinstance(existing_options, list):
                options_str = "; ".join(existing_options)
            else:
                options_str = existing_options if existing_options else ""
            field_widgets['options'] = tk.StringVar(value=options_str)
            options_entry = ttk.Entry(field_frame, textvariable=field_widgets['options'], width=70)
            options_entry.grid(row=3, column=1, columnspan=5, sticky='ew', pady=2)
            
            ttk.Label(field_frame, text="(semicolon-separated for text type, ignored for score type)", 
                     font=('Arial', 8), foreground='gray').grid(row=4, column=1, columnspan=5, sticky='w')
            
            # Store field widgets
            self.scoring_field_widgets.append(field_widgets)
            
            # Configure column weights
            field_frame.columnconfigure(4, weight=1)
        
        self.scoring_fields_container.columnconfigure(0, weight=1)
    
    def update_model_descriptions(self):
        """Update model radio button labels with model names and costs from config."""
        provider = self.ai_provider.get()
        models_key = f"{provider}_models"
        models = self.config.config["step4"].get(models_key, [])
        
        for i, label in enumerate(self.model_labels):
            if i < len(models):
                model = models[i]
                name = model.get("name", f"Model {i+1}")
                # Check for cost_per_1k first, then cost_per_100 (convert to per 1k)
                if "cost_per_1k" in model:
                    cost = model.get("cost_per_1k", 0)
                elif "cost_per_100" in model:
                    cost = model.get("cost_per_100", 0) * 10
                else:
                    cost = 0
                label.config(text=f"{name} (${cost:.2f}/1K sites)")
            else:
                label.config(text=f"Model {i+1} (Not configured)")
    
    def _rebuild_positive_factors(self, initial=False):
        """Rebuild positive factors based on current count."""
        # Save current values before destroying
        current_values = []
        if not initial:
            for factor in self.positive_factors:
                try:
                    current_values.append({
                        "name": factor["name"].get(),
                        "weight": factor["weight"].get(),
                        "sensitivity": factor["sensitivity"].get(),
                        "keywords": factor["keywords"].get()
                    })
                except:
                    current_values.append({})
        
        # Destroy existing widgets
        for widget in self.positive_factors_container.winfo_children():
            widget.destroy()
        
        # Get count
        try:
            count = int(self.positive_factor_count.get())
            count = max(1, min(50, count))
        except ValueError:
            count = 8
        
        # Update config
        self.config.config["step3"]["positive_factor_count"] = count
        
        # Load from config
        factor_data_list = self.config.config["step3"].get("positive_factors", [])
        
        # Create new factors
        self.positive_factors = []
        for i in range(count):
            # Get data: first from saved values, then from config
            if i < len(current_values) and current_values[i]:
                factor_data = current_values[i]
            elif i < len(factor_data_list):
                factor_data = factor_data_list[i]
            else:
                factor_data = {"name": f"Factor {i+1}", "weight": "100", "sensitivity": "1", "keywords": ""}
            
            name_var = tk.StringVar(value=factor_data.get("name", f"Factor {i+1}"))
            weight_var = tk.StringVar(value=str(factor_data.get("weight", 100)))
            sensitivity_var = tk.StringVar(value=str(factor_data.get("sensitivity", 1)))
            keywords_var = tk.StringVar(value=factor_data.get("keywords", ""))
            
            ttk.Entry(self.positive_factors_container, textvariable=name_var, width=15).grid(row=i, column=0, sticky='w', padx=5)
            ttk.Entry(self.positive_factors_container, textvariable=weight_var, width=10).grid(row=i, column=1, sticky='w', padx=5)
            ttk.Entry(self.positive_factors_container, textvariable=sensitivity_var, width=10).grid(row=i, column=2, sticky='w', padx=5)
            ttk.Entry(self.positive_factors_container, textvariable=keywords_var, width=40).grid(row=i, column=3, sticky='w', padx=5)
            
            self.positive_factors.append({
                "name": name_var,
                "weight": weight_var,
                "sensitivity": sensitivity_var,
                "keywords": keywords_var
            })
    
    def _rebuild_negative_factors(self, initial=False):
        """Rebuild negative factors based on current count."""
        # Save current values before destroying
        current_values = []
        if not initial:
            for factor in self.negative_factors:
                try:
                    current_values.append({
                        "name": factor["name"].get(),
                        "weight": factor["weight"].get(),
                        "sensitivity": factor["sensitivity"].get(),
                        "keywords": factor["keywords"].get()
                    })
                except:
                    current_values.append({})
        
        # Destroy existing widgets
        for widget in self.negative_factors_container.winfo_children():
            widget.destroy()
        
        # Get count
        try:
            count = int(self.negative_factor_count.get())
            count = max(1, min(50, count))
        except ValueError:
            count = 8
        
        # Update config
        self.config.config["step3"]["negative_factor_count"] = count
        
        # Load from config
        factor_data_list = self.config.config["step3"].get("negative_factors", [])
        
        # Create new factors
        self.negative_factors = []
        for i in range(count):
            # Get data: first from saved values, then from config
            if i < len(current_values) and current_values[i]:
                factor_data = current_values[i]
            elif i < len(factor_data_list):
                factor_data = factor_data_list[i]
            else:
                factor_data = {"name": f"Disqualifier {i+1}", "weight": "100", "sensitivity": "1", "keywords": ""}
            
            name_var = tk.StringVar(value=factor_data.get("name", f"Disqualifier {i+1}"))
            weight_var = tk.StringVar(value=str(factor_data.get("weight", 100)))
            sensitivity_var = tk.StringVar(value=str(factor_data.get("sensitivity", 1)))
            keywords_var = tk.StringVar(value=factor_data.get("keywords", ""))
            
            ttk.Entry(self.negative_factors_container, textvariable=name_var, width=15).grid(row=i, column=0, sticky='w', padx=5)
            ttk.Entry(self.negative_factors_container, textvariable=weight_var, width=10).grid(row=i, column=1, sticky='w', padx=5)
            ttk.Entry(self.negative_factors_container, textvariable=sensitivity_var, width=10).grid(row=i, column=2, sticky='w', padx=5)
            ttk.Entry(self.negative_factors_container, textvariable=keywords_var, width=40).grid(row=i, column=3, sticky='w', padx=5)
            
            self.negative_factors.append({
                "name": name_var,
                "weight": weight_var,
                "sensitivity": sensitivity_var,
                "keywords": keywords_var
            })
    
    def setup_step3_tab(self, notebook):
        """Setup Step 3: Run tab with timeline-style progress display."""
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Step 3: Run")
        
        # Store reference to control frame for adding button later
        self.control_frame = frame
        
        # Initialize stats tracker
        self.stats_tracker = RunStatsTracker()
        
        # ============================================================
        # HEADER - Title and Run Button
        # ============================================================
        header_frame = ttk.Frame(frame)
        header_frame.pack(fill='x', padx=20, pady=(15, 10))
        
        ttk.Label(header_frame, text="Lead Generation Pipeline", 
                  font=('Segoe UI', 16, 'bold')).pack(side='left')
        
        self.run_button = ttk.Button(header_frame, text="▶ Start Run", 
                                      command=self.run_pipeline, style='Accent.TButton')
        self.run_button.pack(side='right', padx=10)
        
        # Save and Exit Run button (only shown during runs)
        self.save_exit_run_btn = ttk.Button(header_frame, text="💾 Save & Exit Run", 
                                             command=self.save_and_exit_run)
        self.save_exit_run_btn.pack(side='right', padx=5)
        self.save_exit_run_btn.pack_forget()  # Hidden by default
        
        # View Leads button
        self.view_leads_btn = ttk.Button(header_frame, text="📊 View Leads", 
                                          command=self.view_all_leads)
        self.view_leads_btn.pack(side='right', padx=5)
        
        # ============================================================
        # TIMELINE PROGRESS VIEW
        # ============================================================
        timeline_frame = ttk.LabelFrame(frame, text=" Progress Timeline ", padding=10)
        timeline_frame.pack(fill='x', padx=20, pady=10)
        
        # Time labels row (Start time on left, ETA on right)
        time_row = ttk.Frame(timeline_frame)
        time_row.pack(fill='x', pady=(0, 5))
        
        self.start_time_label = ttk.Label(time_row, text="Start: --:--:--", 
                                           font=('Segoe UI', 9))
        self.start_time_label.pack(side='left')
        
        self.eta_label = ttk.Label(time_row, text="ETA: —", 
                                    font=('Segoe UI', 9, 'bold'))
        self.eta_label.pack(side='right')
        
        self.elapsed_label = ttk.Label(time_row, text="Elapsed: 0s", 
                                        font=('Segoe UI', 9))
        self.elapsed_label.pack(side='right', padx=20)
        
        # Timeline canvas - proportional stage widths
        self.timeline_canvas = tk.Canvas(timeline_frame, height=60, bg='#f0f0f0', 
                                          highlightthickness=1, highlightbackground='#ccc')
        self.timeline_canvas.pack(fill='x', pady=5)
        
        # Bind resize to redraw timeline
        self.timeline_canvas.bind('<Configure>', self._draw_timeline)
        
        # Stage labels row (below timeline)
        self.stage_labels_frame = ttk.Frame(timeline_frame)
        self.stage_labels_frame.pack(fill='x')
        
        # Stage weights for proportional widths - loaded from historical data
        learner = get_timing_learner()
        self.stage_weights = learner.get_learned_weights()
        self.timing_confidence = learner.get_confidence_level()
        
        self.stage_names = {1: "Search", 2: "Scrape", 3: "Score", 4: "AI Analysis", 5: "Contacts"}
        self.stage_colors = {
            1: ('#3498db', '#2980b9'),  # Blue
            2: ('#9b59b6', '#8e44ad'),  # Purple
            3: ('#2ecc71', '#27ae60'),  # Green
            4: ('#e74c3c', '#c0392b'),  # Red
            5: ('#f39c12', '#d68910'),  # Orange
        }
        
        # Show confidence level indicator
        confidence_label = ttk.Label(timeline_frame, text=f"ETA confidence: {self.timing_confidence}", 
                                      font=('Segoe UI', 8), foreground='gray')
        confidence_label.pack(anchor='e')
        
        # ============================================================
        # CURRENT STAGE INFO
        # ============================================================
        current_frame = ttk.Frame(frame)
        current_frame.pack(fill='x', padx=20, pady=10)
        
        # Left side: Stage info
        stage_info = ttk.Frame(current_frame)
        stage_info.pack(side='left', fill='x', expand=True)
        
        self.stage_label = ttk.Label(stage_info, text="Ready to Start", 
                                      font=('Segoe UI', 14, 'bold'))
        self.stage_label.pack(anchor='w')
        
        self.desc_label = ttk.Label(stage_info, text="Click 'Start Run' to begin", 
                                     font=('Segoe UI', 10), foreground='gray')
        self.desc_label.pack(anchor='w')
        
        # Right side: Percentage
        pct_frame = ttk.Frame(current_frame)
        pct_frame.pack(side='right', padx=20)
        
        self.pct_label = ttk.Label(pct_frame, text="0%", 
                                    font=('Segoe UI', 36, 'bold'))
        self.pct_label.pack()
        
        # Batch progress
        batch_frame = ttk.Frame(frame)
        batch_frame.pack(fill='x', padx=20, pady=5)
        
        ttk.Label(batch_frame, text="Current batch:", font=('Segoe UI', 9)).pack(side='left')
        self.batch_label = ttk.Label(batch_frame, text="— / —", 
                                      font=('Segoe UI', 9, 'bold'))
        self.batch_label.pack(side='left', padx=5)
        
        self.stage_progress = ttk.Progressbar(batch_frame, length=300, mode='determinate')
        self.stage_progress.pack(side='left', padx=10)
        
        # ============================================================
        # DETAILS GRID
        # ============================================================
        ttk.Separator(frame, orient='horizontal').pack(fill='x', padx=20, pady=10)
        
        details_frame = ttk.LabelFrame(frame, text=" Statistics ", padding=10)
        details_frame.pack(fill='x', padx=20, pady=5)
        
        # 3-column grid
        for i in range(3):
            details_frame.columnconfigure(i, weight=1)
        
        # Row 1
        self._add_stat_pair(details_frame, "Discovered:", "discovered_label", 0, 0)
        self._add_stat_pair(details_frame, "Scraped:", "scraped_label", 0, 1)
        self._add_stat_pair(details_frame, "Scored:", "scored_label", 0, 2)
        
        # Row 2
        self._add_stat_pair(details_frame, "AI Analyzed:", "analyzed_label", 1, 0)
        self._add_stat_pair(details_frame, "Contacts:", "contacts_label", 1, 1)
        self._add_stat_pair(details_frame, "Search Combos:", "combos_label", 1, 2)
        
        # ============================================================
        # STATUS BAR
        # ============================================================
        status_frame = ttk.Frame(frame)
        status_frame.pack(fill='x', padx=20, pady=10)
        
        ttk.Label(status_frame, text="Status:", font=('Segoe UI', 9)).pack(side='left')
        self.status_label = ttk.Label(status_frame, text="Ready", 
                                       font=('Segoe UI', 9), foreground='gray')
        self.status_label.pack(side='left', padx=5)
        
        # Start timer update loop
        self.start_stats_timer()
    
    def _add_stat_pair(self, parent, label_text, attr_name, row, col):
        """Helper to add a label/value pair to the stats grid."""
        cell = ttk.Frame(parent)
        cell.grid(row=row, column=col, sticky='ew', padx=10, pady=3)
        
        ttk.Label(cell, text=label_text, font=('Segoe UI', 9)).pack(side='left')
        label = ttk.Label(cell, text="—", font=('Segoe UI', 9, 'bold'))
        label.pack(side='right')
        setattr(self, attr_name, label)
    
    def _draw_timeline(self, event=None):
        """Draw the timeline with proportional stage widths."""
        canvas = self.timeline_canvas
        canvas.delete('all')
        
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        
        if width < 50:
            return  # Too small to draw
        
        # Calculate total weight
        total_weight = sum(self.stage_weights.values())
        
        # Draw stages
        x = 0
        padding = 2
        bar_height = 30
        bar_y = (height - bar_height) // 2
        
        tracker = self.stats_tracker
        current_stage = tracker.current_stage
        stage_progress = 0
        if tracker.total_batches > 0:
            stage_progress = tracker.current_batch / tracker.total_batches
        
        for stage_num in range(1, 6):
            stage_width = (self.stage_weights[stage_num] / total_weight) * (width - 10)
            
            # Determine fill color based on completion
            if stage_num < current_stage:
                # Completed - filled with color
                fill_color = self.stage_colors[stage_num][0]
                text_color = 'white'
            elif stage_num == current_stage:
                # Current stage - partial fill
                fill_color = self.stage_colors[stage_num][1]
                text_color = 'white'
            else:
                # Future - gray
                fill_color = '#ddd'
                text_color = '#888'
            
            # Draw stage background
            canvas.create_rectangle(
                x + padding, bar_y, 
                x + stage_width - padding, bar_y + bar_height,
                fill=fill_color, outline='', tags=f'stage{stage_num}'
            )
            
            # Draw progress within current stage
            if stage_num == current_stage and stage_progress > 0:
                progress_width = stage_width * stage_progress
                canvas.create_rectangle(
                    x + padding, bar_y,
                    x + padding + progress_width - 4, bar_y + bar_height,
                    fill=self.stage_colors[stage_num][0], outline=''
                )
                
                # Draw position marker (the & placeholder concept)
                marker_x = x + padding + progress_width
                canvas.create_polygon(
                    marker_x, bar_y - 5,
                    marker_x - 6, bar_y - 12,
                    marker_x + 6, bar_y - 12,
                    fill='#333', outline=''
                )
            
            # Draw stage label
            label_text = f"S{stage_num}"
            canvas.create_text(
                x + stage_width / 2, bar_y + bar_height / 2,
                text=label_text, fill=text_color, font=('Segoe UI', 9, 'bold')
            )
            
            x += stage_width
        
        # Draw stage names below (only on larger widths)
        if width > 400:
            x = 0
            for stage_num in range(1, 6):
                stage_width = (self.stage_weights[stage_num] / total_weight) * (width - 10)
                name = self.stage_names[stage_num]
                canvas.create_text(
                    x + stage_width / 2, bar_y + bar_height + 10,
                    text=name, fill='#666', font=('Segoe UI', 8)
                )
        
    def update_stats_display(self):
        """Update all stats display labels from tracker."""
        tracker = self.stats_tracker
        
        # Main percentage
        pct = tracker.get_percent_complete()
        self.pct_label.configure(text=f"{int(pct)}%")
        
        # Time labels
        self.elapsed_label.configure(text=f"Elapsed: {tracker.get_elapsed_formatted()}")
        self.eta_label.configure(text=f"ETA: {tracker.get_eta_formatted()}")
        
        # Start time (only set once)
        if tracker.start_time and "Start:" in self.start_time_label.cget('text'):
            start_str = datetime.fromtimestamp(tracker.start_time).strftime('%H:%M:%S')
            self.start_time_label.configure(text=f"Started: {start_str}")
        
        # Current stage info
        self.stage_label.configure(text=tracker.get_stage_name())
        self.desc_label.configure(text=tracker.stage_description)
        self.batch_label.configure(text=tracker.get_batch_info())
        
        # Stage progress bar
        if tracker.total_batches > 0:
            stage_pct = (tracker.current_batch / tracker.total_batches) * 100
            self.stage_progress['value'] = stage_pct
        else:
            self.stage_progress['value'] = 0
        
        # Redraw timeline
        self._draw_timeline()
        
        # Statistics grid
        if tracker.websites_discovered > 0:
            self.discovered_label.configure(text=str(tracker.websites_discovered))
        if tracker.websites_scraped > 0:
            self.scraped_label.configure(text=str(tracker.websites_scraped))
        if tracker.websites_scored > 0:
            self.scored_label.configure(text=str(tracker.websites_scored))
        if tracker.websites_analyzed > 0:
            self.analyzed_label.configure(text=str(tracker.websites_analyzed))
        if tracker.websites_with_contacts > 0:
            self.contacts_label.configure(text=str(tracker.websites_with_contacts))
        if tracker.total_search_combinations > 0:
            self.combos_label.configure(text=str(tracker.total_search_combinations))
        
        # Update progress bar in bottom ribbon
        self.progress_var.set(pct)
        
        # Force UI update
        self.root.update()
    
    def log_progress(self, message):
        """Handle progress callback - parse structured messages or display status."""
        # Update status label with latest message (truncate if too long)
        display_msg = message if len(message) < 80 else message[:77] + "..."
        self.status_label.configure(text=display_msg)
        
        # Parse structured progress updates
        if message.startswith("[") and "/" in message:
            # Batch progress: "[5/100] Searching: ..."
            try:
                batch_part = message.split("]")[0][1:]
                current, total = map(int, batch_part.split("/"))
                self.stats_tracker.update_batch(current, total)
            except:
                pass
        
        # Update display
        self.update_stats_display()
    
    def start_stats_timer(self):
        """Start a timer that updates elapsed time every second during runs."""
        def update_timer():
            if self.is_running and self.stats_tracker.start_time:
                # Only update elapsed time label (lightweight)
                self.elapsed_label.configure(text=self.stats_tracker.get_elapsed_formatted())
                self.eta_label.configure(text=self.stats_tracker.get_eta_formatted())
            # Schedule next update
            self.root.after(1000, update_timer)
        
        # Start the timer loop
        update_timer()
    
    def setup_advanced_tab(self, notebook):
        """Setup Advanced Settings tab with all configurable settings, organized by step."""
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="Advanced Settings")
        
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
        
        row = 0
        
        # ============================================================
        # GITHUB SYNC SETTINGS
        # ============================================================
        ttk.Label(scrollable_frame, text="GitHub Sync Settings", font=('Arial', 12, 'bold')).grid(row=row, column=0, columnspan=4, sticky='w', pady=(0, 10))
        row += 1
        
        # GitHub auto-sync toggle
        self.github_auto_sync = tk.BooleanVar(value=self.config.config.get("github_auto_sync", False))
        ttk.Checkbutton(scrollable_frame, text="Enable automatic GitHub sync on save", 
                       variable=self.github_auto_sync).grid(row=row, column=0, columnspan=3, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="When enabled, configuration changes are automatically committed and pushed to GitHub.", 
                 font=('Arial', 8), foreground='gray').grid(row=row, column=0, columnspan=4, sticky='w')
        row += 1
        
        ttk.Separator(scrollable_frame, orient='horizontal').grid(row=row, column=0, columnspan=4, sticky='ew', pady=10)
        row += 1
        
        # ============================================================
        # AI OPTIMIZATION AGENT SETTINGS
        # ============================================================
        ttk.Label(scrollable_frame, text="AI Optimization Agent Settings", font=('Arial', 12, 'bold')).grid(row=row, column=0, columnspan=4, sticky='w', pady=(0, 10))
        row += 1
        
        ttk.Label(scrollable_frame, text="Configure the AI agent that optimizes search inputs based on your business description.", 
                 font=('Arial', 9), foreground='gray').grid(row=row, column=0, columnspan=4, sticky='w')
        row += 1
        
        # Agent enabled toggle
        agent_config = self.config.config.get("ai_optimization_agent", {})
        self.ai_agent_enabled = tk.BooleanVar(value=agent_config.get("enabled", True))
        ttk.Checkbutton(scrollable_frame, text="Enable AI Input Optimization Agent", 
                       variable=self.ai_agent_enabled).grid(row=row, column=0, columnspan=3, sticky='w')
        row += 1
        
        # Agent prompt
        ttk.Label(scrollable_frame, text="AI Optimization Prompt:", font=('Arial', 10, 'bold')).grid(row=row, column=0, sticky='nw', pady=(10, 5))
        row += 1
        
        ttk.Label(scrollable_frame, text="This prompt instructs the AI how to analyze user inputs and generate optimal search configuration.", 
                 font=('Arial', 8), foreground='gray').grid(row=row, column=0, columnspan=4, sticky='w')
        row += 1
        
        # Create frame for prompt text widget
        prompt_frame = ttk.Frame(scrollable_frame)
        prompt_frame.grid(row=row, column=0, columnspan=4, sticky='ew', pady=5)
        
        self.ai_agent_prompt = tk.Text(prompt_frame, width=90, height=15, wrap='word')
        self.ai_agent_prompt.insert("1.0", agent_config.get("prompt", ""))
        self.ai_agent_prompt.pack(side='left', fill='x', expand=True)
        
        prompt_scrollbar = ttk.Scrollbar(prompt_frame, orient='vertical', command=self.ai_agent_prompt.yview)
        prompt_scrollbar.pack(side='right', fill='y')
        self.ai_agent_prompt.config(yscrollcommand=prompt_scrollbar.set)
        row += 1
        
        # Reset to default button
        def reset_agent_prompt():
            default_prompt = self.config.default_config.get("ai_optimization_agent", {}).get("prompt", "")
            self.ai_agent_prompt.delete("1.0", "end")
            self.ai_agent_prompt.insert("1.0", default_prompt)
        
        ttk.Button(scrollable_frame, text="Reset to Default Prompt", command=reset_agent_prompt).grid(row=row, column=0, sticky='w', pady=5)
        row += 1
        
        ttk.Separator(scrollable_frame, orient='horizontal').grid(row=row, column=0, columnspan=4, sticky='ew', pady=10)
        row += 1
        
        # ============================================================
        # PERFORMANCE SETTINGS (Speed Optimizations)
        # ============================================================
        ttk.Label(scrollable_frame, text="0. PERFORMANCE SETTINGS (Speed Optimizations)", font=('Arial', 12, 'bold')).grid(row=row, column=0, columnspan=4, sticky='w', pady=(0, 10))
        row += 1
        
        # AI Batch Size
        ttk.Label(scrollable_frame, text="0.1 AI Batch Size:").grid(row=row, column=0, sticky='w')
        perf_config = self.config.config.get("performance", {})
        self.ai_batch_size = tk.StringVar(value=str(perf_config.get("ai_batch_size", 5)))
        ttk.Entry(scrollable_frame, textvariable=self.ai_batch_size, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(parallel AI requests - higher = faster)").grid(row=row, column=2, sticky='w')
        row += 1
        
        # Rate Limiter Success Threshold
        ttk.Label(scrollable_frame, text="0.2 Rate Limiter Speed-Up After:").grid(row=row, column=0, sticky='w')
        self.rate_success_threshold = tk.StringVar(value=str(perf_config.get("rate_limiter_success_threshold", 5)))
        ttk.Entry(scrollable_frame, textvariable=self.rate_success_threshold, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="consecutive successes (lower = faster)").grid(row=row, column=2, sticky='w')
        row += 1
        
        # Logging Level
        ttk.Label(scrollable_frame, text="0.3 Logging Level:").grid(row=row, column=0, sticky='w')
        self.logging_level = tk.StringVar(value=perf_config.get("logging_level", "moderate"))
        logging_combo = ttk.Combobox(scrollable_frame, textvariable=self.logging_level, 
                                      values=["none (0% overhead)", "limited (2% overhead)", "moderate (5% overhead)", "detailed (10% overhead)"], 
                                      width=25, state="readonly")
        logging_combo.grid(row=row, column=1, columnspan=2, sticky='w')
        row += 1
        
        # Debug File Interval
        ttk.Label(scrollable_frame, text="0.4 Debug File Interval:").grid(row=row, column=0, sticky='w')
        self.debug_file_interval = tk.StringVar(value=str(perf_config.get("debug_file_interval", 10)))
        ttk.Entry(scrollable_frame, textvariable=self.debug_file_interval, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(write 1 debug file per N AI calls)").grid(row=row, column=2, sticky='w')
        row += 1
        
        # Always Write Debug Files
        self.always_write_debug = tk.BooleanVar(value=perf_config.get("always_write_debug_files", False))
        ttk.Checkbutton(scrollable_frame, text="0.5 Always Write Debug Files (override interval)", variable=self.always_write_debug).grid(row=row, column=0, columnspan=3, sticky='w')
        row += 1
        
        # Fuzzy Match Threshold
        ttk.Label(scrollable_frame, text="0.6 Fuzzy Match Threshold:").grid(row=row, column=0, sticky='w')
        self.perf_fuzzy_threshold = tk.StringVar(value=str(perf_config.get("fuzzy_match_threshold", 85)))
        ttk.Entry(scrollable_frame, textvariable=self.perf_fuzzy_threshold, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(0-100, set to 100 for exact matching only - faster)").grid(row=row, column=2, sticky='w')
        row += 1
        
        # CSV Delimiter
        csv_config = self.config.config.get("csv_output", {})
        ttk.Label(scrollable_frame, text="0.7 CSV Multi-Value Delimiter:").grid(row=row, column=0, sticky='w')
        self.csv_delimiter = tk.StringVar(value=csv_config.get("delimiter", ";"))
        ttk.Entry(scrollable_frame, textvariable=self.csv_delimiter, width=5).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(separates multiple values in one cell, e.g., organs: Liver; Pancreas)").grid(row=row, column=2, sticky='w')
        row += 1
        
        # ============================================================
        # STEP 1: DISCOVERY SETTINGS
        # ============================================================
        ttk.Label(scrollable_frame, text="1. STEP 1: Discovery - API Configuration", font=('Arial', 12, 'bold')).grid(row=row, column=0, columnspan=4, sticky='w', pady=(20, 10))
        row += 1
        
        ttk.Label(scrollable_frame, text="1.1 API Provider:").grid(row=row, column=0, sticky='w')
        self.api_choice = tk.StringVar(value=self.config.config["step1"]["api_choice"])
        ttk.Radiobutton(scrollable_frame, text="Serper.dev", variable=self.api_choice, value="serper").grid(row=row, column=1, sticky='w')
        ttk.Radiobutton(scrollable_frame, text="SerpAPI", variable=self.api_choice, value="serpapi").grid(row=row, column=2, sticky='w')
        ttk.Label(scrollable_frame, text="(both search Google - Serper is cheaper)").grid(row=row, column=3, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="1.2 Search API Key:").grid(row=row, column=0, sticky='w')
        self.api_key = tk.StringVar(value=self.config.config["step1"]["api_key"])
        ttk.Entry(scrollable_frame, textvariable=self.api_key, width=50, show="•").grid(row=row, column=1, columnspan=2, sticky='ew')
        ttk.Label(scrollable_frame, text="(get from serper.dev or serpapi.com)").grid(row=row, column=3, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="1.3 Region:").grid(row=row, column=0, sticky='w')
        self.region = tk.StringVar(value=self.config.config["step1"]["region"])
        ttk.Entry(scrollable_frame, textvariable=self.region, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(2-letter code: us, gb, de, etc.)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="1.4 Max Results per Search:").grid(row=row, column=0, sticky='w')
        self.max_results = tk.StringVar(value=str(self.config.config["step1"]["max_results"]))
        ttk.Entry(scrollable_frame, textvariable=self.max_results, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(websites per query - typical: 50-100)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="1.5 Max Number of Searches:").grid(row=row, column=0, sticky='w')
        self.combo_cap = tk.StringVar(value=str(self.config.config["step1"]["serper_combo_cap"]))
        ttk.Entry(scrollable_frame, textvariable=self.combo_cap, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(limits keyword combinations - prevents runaway costs)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="1.6 Verify Domains:").grid(row=row, column=0, sticky='w')
        self.verify_domains = tk.BooleanVar(value=self.config.config["step1"].get("verify_domains", True))
        ttk.Checkbutton(scrollable_frame, text="Enable domain verification (HEAD requests)", variable=self.verify_domains).grid(row=row, column=1, columnspan=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="1.7 Rate Limit - Initial (sec):").grid(row=row, column=0, sticky='w')
        self.rate_limit_initial = tk.StringVar(value=str(self.config.config["step1"].get("rate_limit_initial", 0.35)))
        ttk.Entry(scrollable_frame, textvariable=self.rate_limit_initial, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(starting delay between API calls)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="1.8 Rate Limit - Min (sec):").grid(row=row, column=0, sticky='w')
        self.rate_limit_min = tk.StringVar(value=str(self.config.config["step1"].get("rate_limit_min", 0.05)))
        ttk.Entry(scrollable_frame, textvariable=self.rate_limit_min, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(fastest allowed - too low causes rate limits)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="1.9 Rate Limit - Max (sec):").grid(row=row, column=0, sticky='w')
        self.rate_limit_max = tk.StringVar(value=str(self.config.config["step1"].get("rate_limit_max", 2.0)))
        ttk.Entry(scrollable_frame, textvariable=self.rate_limit_max, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(slowest delay when errors occur)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="1.10 Re-analysis Period (days):").grid(row=row, column=0, sticky='w')
        self.reanalysis_period = tk.StringVar(value=str(self.config.config["step1"].get("reanalysis_period", 0)))
        ttk.Entry(scrollable_frame, textvariable=self.reanalysis_period, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(0 = analyze all new)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="1.11 Request Timeout (sec):").grid(row=row, column=0, sticky='w')
        self.request_timeout = tk.StringVar(value=str(self.config.config["step1"].get("request_timeout_seconds", 15)))
        ttk.Entry(scrollable_frame, textvariable=self.request_timeout, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(how long to wait before giving up)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="1.12 Concurrency:").grid(row=row, column=0, sticky='w')
        self.step1_concurrency = tk.StringVar(value=str(self.config.config["step1"].get("concurrency", 25)))
        ttk.Entry(scrollable_frame, textvariable=self.step1_concurrency, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(parallel domain verifications)").grid(row=row, column=2, sticky='w')
        row += 1
        
        # ============================================================
        # STEP 2: SCRAPING SETTINGS
        # ============================================================
        ttk.Label(scrollable_frame, text="2. STEP 2: Scraping Configuration", font=('Arial', 12, 'bold')).grid(row=row, column=0, columnspan=4, sticky='w', pady=(20, 10))
        row += 1
        
        ttk.Label(scrollable_frame, text="2.1 Max Pages per Site:").grid(row=row, column=0, sticky='w')
        self.max_pages = tk.StringVar(value=str(self.config.config["step2"]["max_pages_per_site"]))
        ttk.Entry(scrollable_frame, textvariable=self.max_pages, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(pages to crawl per website - typical: 8-15)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="2.2 Max Depth:").grid(row=row, column=0, sticky='w')
        self.max_depth = tk.StringVar(value=str(self.config.config["step2"]["max_depth"]))
        ttk.Entry(scrollable_frame, textvariable=self.max_depth, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(clicks from homepage - 2 is usually enough)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="2.3 Global Concurrency:").grid(row=row, column=0, sticky='w')
        self.global_concurrency = tk.StringVar(value=str(self.config.config["step2"]["global_concurrency"]))
        ttk.Entry(scrollable_frame, textvariable=self.global_concurrency, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(total parallel requests - higher = faster)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="2.4 Per-Domain Concurrency:").grid(row=row, column=0, sticky='w')
        self.per_domain_concurrency = tk.StringVar(value=str(self.config.config["step2"]["per_domain_concurrency"]))
        ttk.Entry(scrollable_frame, textvariable=self.per_domain_concurrency, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(requests to one site - too high may get blocked)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="2.5 Timeout (seconds):").grid(row=row, column=0, sticky='w')
        self.timeout = tk.StringVar(value=str(self.config.config["step2"]["timeout_sec"]))
        ttk.Entry(scrollable_frame, textvariable=self.timeout, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(page load timeout - slow sites need more)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="2.6 Aggregate Char Cap:").grid(row=row, column=0, sticky='w')
        self.aggregate_char_cap = tk.StringVar(value=str(self.config.config["step2"].get("aggregate_char_cap", 120000)))
        ttk.Entry(scrollable_frame, textvariable=self.aggregate_char_cap, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(max total chars combined per site)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="2.7 Max Chars per Page:").grid(row=row, column=0, sticky='w')
        self.max_chars_per_page = tk.StringVar(value=str(self.config.config["step2"].get("max_chars_per_page", 50000)))
        ttk.Entry(scrollable_frame, textvariable=self.max_chars_per_page, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(prevents huge pages from dominating)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="2.8 Max Chars per Scrape:").grid(row=row, column=0, sticky='w')
        self.max_chars_per_scrape = tk.StringVar(value=str(self.config.config["step2"].get("max_chars_per_scrape", 200000)))
        ttk.Entry(scrollable_frame, textvariable=self.max_chars_per_scrape, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(absolute max per website across all pages)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="2.9 Contact Priority Keywords:").grid(row=row, column=0, sticky='nw')
        self.contact_priority_keywords = tk.StringVar(value=self.config.config["step2"].get("contact_priority_keywords", "contact, team, about, leadership, management, executives, staff, people, our-team, meet-the-team, who-we-are, about-us, contact-us"))
        contact_entry = ttk.Entry(scrollable_frame, textvariable=self.contact_priority_keywords, width=60)
        contact_entry.grid(row=row, column=1, columnspan=2, sticky='ew')
        row += 1
        ttk.Label(scrollable_frame, text="(comma-separated, highest crawl priority)").grid(row=row, column=1, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="2.10 User Agent:").grid(row=row, column=0, sticky='w')
        self.user_agent = tk.StringVar(value=self.config.config["step2"].get("user_agent", "LeadGenBot/1.0 (+https://susclinicals.com/) Unified"))
        ttk.Entry(scrollable_frame, textvariable=self.user_agent, width=60).grid(row=row, column=1, columnspan=2, sticky='ew')
        row += 1
        ttk.Label(scrollable_frame, text="(how scraper identifies itself to websites - change if sites block you)", 
                 font=('Arial', 8), foreground='gray').grid(row=row, column=1, columnspan=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="2.11 Read Limit (bytes):").grid(row=row, column=0, sticky='w')
        self.read_limit_bytes = tk.StringVar(value=str(self.config.config["step2"].get("read_limit_bytes", 2000000)))
        ttk.Entry(scrollable_frame, textvariable=self.read_limit_bytes, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(max bytes to read per page)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="2.12 Min Chars per Page:").grid(row=row, column=0, sticky='w')
        self.min_chars_per_page = tk.StringVar(value=str(self.config.config["step2"].get("min_chars_per_page", 400)))
        ttk.Entry(scrollable_frame, textvariable=self.min_chars_per_page, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(pages with less are skipped)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="2.13 Robots Cache TTL (sec):").grid(row=row, column=0, sticky='w')
        self.robots_cache_ttl = tk.StringVar(value=str(self.config.config["step2"].get("robots_cache_ttl_sec", 3600)))
        ttk.Entry(scrollable_frame, textvariable=self.robots_cache_ttl, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(how long to remember robots.txt - 3600 = 1 hour)").grid(row=row, column=2, sticky='w')
        row += 1
        
        self.respect_robots = tk.BooleanVar(value=self.config.config["step2"].get("respect_robots", True))
        ttk.Checkbutton(scrollable_frame, text="2.14 Respect robots.txt", variable=self.respect_robots).grid(row=row, column=0, columnspan=2, sticky='w')
        ttk.Label(scrollable_frame, text="(follow site's crawl rules - keep ON to be polite)").grid(row=row, column=2, sticky='w')
        row += 1
        
        self.follow_sitemaps = tk.BooleanVar(value=self.config.config["step2"].get("follow_sitemaps", True))
        ttk.Checkbutton(scrollable_frame, text="2.15 Follow sitemaps", variable=self.follow_sitemaps).grid(row=row, column=0, columnspan=2, sticky='w')
        ttk.Label(scrollable_frame, text="(use sitemap.xml to find important pages)").grid(row=row, column=2, sticky='w')
        row += 1
        
        # ============================================================
        # STEP 3: SCORING SETTINGS
        # ============================================================
        ttk.Label(scrollable_frame, text="3. STEP 3: Scoring Configuration", font=('Arial', 12, 'bold')).grid(row=row, column=0, columnspan=4, sticky='w', pady=(20, 10))
        row += 1
        
        # Multi-select thresholds with OR logic
        ttk.Label(scrollable_frame, text="3.1 Threshold Selection (OR logic - lead passes if ANY checked threshold is met):", font=('Arial', 10, 'italic')).grid(row=row, column=0, columnspan=4, sticky='w')
        row += 1
        
        self.use_score_threshold = tk.BooleanVar(value=self.config.config["step3"].get("use_score_threshold", True))
        ttk.Checkbutton(scrollable_frame, text="Use Score Threshold", variable=self.use_score_threshold).grid(row=row, column=0, sticky='w')
        ttk.Label(scrollable_frame, text="Score >=").grid(row=row, column=1, sticky='e')
        self.threshold_value = tk.StringVar(value=str(self.config.config["step3"].get("threshold_value", 75)))
        ttk.Entry(scrollable_frame, textvariable=self.threshold_value, width=10).grid(row=row, column=2, sticky='w')
        row += 1
        
        self.use_percentage_threshold = tk.BooleanVar(value=self.config.config["step3"].get("use_percentage_threshold", False))
        ttk.Checkbutton(scrollable_frame, text="Use Percentage Threshold", variable=self.use_percentage_threshold).grid(row=row, column=0, sticky='w')
        ttk.Label(scrollable_frame, text="Top %").grid(row=row, column=1, sticky='e')
        self.percentage_value = tk.StringVar(value=str(self.config.config["step3"].get("percentage_value", 20)))
        ttk.Entry(scrollable_frame, textvariable=self.percentage_value, width=10).grid(row=row, column=2, sticky='w')
        row += 1
        
        self.use_count_threshold = tk.BooleanVar(value=self.config.config["step3"].get("use_count_threshold", False))
        ttk.Checkbutton(scrollable_frame, text="Use Count Threshold", variable=self.use_count_threshold).grid(row=row, column=0, sticky='w')
        ttk.Label(scrollable_frame, text="Top #").grid(row=row, column=1, sticky='e')
        self.count_value = tk.StringVar(value=str(self.config.config["step3"].get("count_value", 100)))
        ttk.Entry(scrollable_frame, textvariable=self.count_value, width=10).grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="3.2 Fuzzy Match Threshold:").grid(row=row, column=0, sticky='w')
        self.fuzzy_match_threshold = tk.StringVar(value=str(self.config.config["step3"].get("fuzzy_match_threshold", 85)))
        ttk.Entry(scrollable_frame, textvariable=self.fuzzy_match_threshold, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(0-100, for keyword matching)").grid(row=row, column=2, sticky='w')
        row += 1
        
        # Positive factors with dynamic count
        pos_header = ttk.Frame(scrollable_frame)
        pos_header.grid(row=row, column=0, columnspan=4, sticky='ew', pady=(20, 10))
        ttk.Label(pos_header, text="Positive Factors", font=('Arial', 12, 'bold')).pack(side='left')
        ttk.Label(pos_header, text="   Number of factors:").pack(side='left', padx=(20, 5))
        self.positive_factor_count = tk.StringVar(value=str(self.config.config["step3"].get("positive_factor_count", 8)))
        ttk.Entry(pos_header, textvariable=self.positive_factor_count, width=5).pack(side='left')
        ttk.Button(pos_header, text="Update", command=self._rebuild_positive_factors).pack(side='left', padx=5)
        row += 1
        
        # Explanation of factor columns
        ttk.Label(scrollable_frame, text="Weight = importance (100=normal, 200=2x). Sensitivity = matches needed for full credit. Keywords = comma-separated terms that ADD points.", 
                 font=('Arial', 8), foreground='gray').grid(row=row, column=0, columnspan=4, sticky='w', pady=(0,5))
        row += 1
        
        # Headers for positive factors
        ttk.Label(scrollable_frame, text="Name").grid(row=row, column=0, sticky='w', padx=5)
        ttk.Label(scrollable_frame, text="Weight").grid(row=row, column=1, sticky='w', padx=5)
        ttk.Label(scrollable_frame, text="Sensitivity").grid(row=row, column=2, sticky='w', padx=5)
        ttk.Label(scrollable_frame, text="Keywords").grid(row=row, column=3, sticky='w', padx=5)
        row += 1
        
        # Container for positive factors
        self.positive_factors_container = ttk.Frame(scrollable_frame)
        self.positive_factors_container.grid(row=row, column=0, columnspan=4, sticky='ew')
        self.positive_factors_scrollable_frame = scrollable_frame
        row += 1
        
        # Build initial positive factors
        self.positive_factors = []
        self._rebuild_positive_factors(initial=True)
        
        # Negative factors with dynamic count
        neg_header = ttk.Frame(scrollable_frame)
        neg_header.grid(row=row, column=0, columnspan=4, sticky='ew', pady=(20, 10))
        ttk.Label(neg_header, text="Negative Factors", font=('Arial', 12, 'bold')).pack(side='left')
        ttk.Label(neg_header, text="   Number of factors:").pack(side='left', padx=(20, 5))
        self.negative_factor_count = tk.StringVar(value=str(self.config.config["step3"].get("negative_factor_count", 8)))
        ttk.Entry(neg_header, textvariable=self.negative_factor_count, width=5).pack(side='left')
        ttk.Button(neg_header, text="Update", command=self._rebuild_negative_factors).pack(side='left', padx=5)
        row += 1
        
        # Explanation of negative factor columns
        ttk.Label(scrollable_frame, text="Weight = penalty size (100=normal). Sensitivity = matches needed for full penalty. Keywords = comma-separated terms that SUBTRACT points.", 
                 font=('Arial', 8), foreground='gray').grid(row=row, column=0, columnspan=4, sticky='w', pady=(0,5))
        row += 1
        
        # Headers for negative factors
        ttk.Label(scrollable_frame, text="Name").grid(row=row, column=0, sticky='w', padx=5)
        ttk.Label(scrollable_frame, text="Weight").grid(row=row, column=1, sticky='w', padx=5)
        ttk.Label(scrollable_frame, text="Sensitivity").grid(row=row, column=2, sticky='w', padx=5)
        ttk.Label(scrollable_frame, text="Keywords").grid(row=row, column=3, sticky='w', padx=5)
        row += 1
        
        # Container for negative factors
        self.negative_factors_container = ttk.Frame(scrollable_frame)
        self.negative_factors_container.grid(row=row, column=0, columnspan=4, sticky='ew')
        self.negative_factors_scrollable_frame = scrollable_frame
        row += 1
        
        # Build initial negative factors
        self.negative_factors = []
        self._rebuild_negative_factors(initial=True)
        
        # ============================================================
        # STEP 4: AI ANALYSIS SETTINGS
        # ============================================================
        ttk.Label(scrollable_frame, text="4. STEP 4: AI Analysis Configuration", font=('Arial', 12, 'bold')).grid(row=row, column=0, columnspan=4, sticky='w', pady=(20, 10))
        row += 1
        
        # Model configuration - store all model vars for saving later
        self.model_config_vars = {"claude": [], "openai": [], "gemini": []}
        
        # Header for model config
        ttk.Label(scrollable_frame, text="Model Configuration (Name | API ID | Cost per 1K sites)", font=('Arial', 10, 'bold')).grid(row=row, column=0, columnspan=4, sticky='w', pady=(5, 5))
        row += 1
        ttk.Label(scrollable_frame, text="Update when providers release new models. Cost is estimated $ per 1,000 leads analyzed.", 
                 font=('Arial', 8), foreground='gray').grid(row=row, column=0, columnspan=4, sticky='w')
        row += 1
        
        for provider in ["claude", "openai", "gemini"]:
            provider_label = {"claude": "Claude", "openai": "OpenAI", "gemini": "Gemini"}[provider]
            ttk.Label(scrollable_frame, text=f"{provider_label} Models:", font=('Arial', 9, 'bold')).grid(row=row, column=0, sticky='w', pady=(10, 2))
            row += 1
            
            models = self.config.config["step4"].get(f"{provider}_models", [])
            for i in range(4):
                model = models[i] if i < len(models) else {"name": "", "api_id": "", "cost_per_1k": 0}
                
                name_var = tk.StringVar(value=model.get("name", ""))
                api_id_var = tk.StringVar(value=model.get("api_id", ""))
                # Check for cost_per_1k first, then cost_per_100 (convert to per 1k)
                if "cost_per_1k" in model:
                    cost_value = model.get("cost_per_1k", 0)
                elif "cost_per_100" in model:
                    cost_value = model.get("cost_per_100", 0) * 10
                else:
                    cost_value = 0
                cost_var = tk.StringVar(value=str(cost_value))
                
                ttk.Label(scrollable_frame, text=f"  Model {i+1}:").grid(row=row, column=0, sticky='w')
                ttk.Entry(scrollable_frame, textvariable=name_var, width=15).grid(row=row, column=1, sticky='w', padx=2)
                ttk.Entry(scrollable_frame, textvariable=api_id_var, width=30).grid(row=row, column=2, sticky='w', padx=2)
                ttk.Entry(scrollable_frame, textvariable=cost_var, width=8).grid(row=row, column=3, sticky='w', padx=2)
                
                self.model_config_vars[provider].append({
                    "name": name_var,
                    "api_id": api_id_var,
                    "cost_per_1k": cost_var
                })
                row += 1
        
        ttk.Label(scrollable_frame, text="(Changes here will update the model selection dropdown)", font=('Arial', 8), foreground='gray').grid(row=row, column=1, columnspan=3, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="4.5 Company Description Prompt:").grid(row=row, column=0, sticky='nw', padx=(0, 10))
        ttk.Label(scrollable_frame, text="(optional - customize how AI describes companies, leave empty for default)", 
                 font=('Arial', 8), foreground='gray').grid(row=row, column=1, columnspan=3, sticky='nw')
        row += 1
        
        # Create frame for text box and scrollbar
        prompt_frame = ttk.Frame(scrollable_frame)
        prompt_frame.grid(row=row, column=1, columnspan=3, sticky='ew', padx=(0, 0))
        
        self.company_description_prompt = tk.Text(prompt_frame, width=60, height=6, wrap='word')
        prompt_scrollbar = ttk.Scrollbar(prompt_frame, orient="vertical", command=self.company_description_prompt.yview)
        self.company_description_prompt.configure(yscrollcommand=prompt_scrollbar.set)
        
        # Load existing prompt if available
        existing_prompt = self.config.config["step4"].get("company_description_prompt", "")
        if existing_prompt:
            self.company_description_prompt.insert("1.0", existing_prompt)
        
        self.company_description_prompt.pack(side='left', fill='both', expand=True)
        prompt_scrollbar.pack(side='right', fill='y')
        row += 1
        
        ttk.Label(scrollable_frame, text="4.6 Max Tokens:").grid(row=row, column=0, sticky='w')
        self.max_tokens = tk.StringVar(value=str(self.config.config["step4"].get("max_tokens", 4000)))
        ttk.Entry(scrollable_frame, textvariable=self.max_tokens, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(AI response length limit)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="4.7 Max Retries:").grid(row=row, column=0, sticky='w')
        self.max_retries = tk.StringVar(value=str(self.config.config["step4"].get("max_retries", 3)))
        ttk.Entry(scrollable_frame, textvariable=self.max_retries, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(retry failed AI calls this many times)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="4.8 Batch Size:").grid(row=row, column=0, sticky='w')
        self.batch_size = tk.StringVar(value=str(self.config.config["step4"].get("batch_size", 5)))
        ttk.Entry(scrollable_frame, textvariable=self.batch_size, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(leads processed per batch)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="4.9 Checkpoint Interval:").grid(row=row, column=0, sticky='w')
        self.checkpoint_interval = tk.StringVar(value=str(self.config.config["step4"].get("checkpoint_interval", 5)))
        ttk.Entry(scrollable_frame, textvariable=self.checkpoint_interval, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(save progress every N leads)").grid(row=row, column=2, sticky='w')
        row += 1
        
        ttk.Label(scrollable_frame, text="4.10 Log Level:").grid(row=row, column=0, sticky='w')
        self.log_level = tk.StringVar(value=self.config.config["step4"].get("log_level", "INFO"))
        log_combo = ttk.Combobox(scrollable_frame, textvariable=self.log_level, values=["DEBUG", "INFO", "WARNING", "ERROR"], width=10)
        log_combo.grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(INFO for normal, DEBUG for troubleshooting)").grid(row=row, column=2, sticky='w')
        row += 1
        
        # ============================================================
        # STEP 5: CONTACT EXTRACTION SETTINGS
        # ============================================================
        ttk.Label(scrollable_frame, text="5. STEP 5: Contact Extraction Configuration", font=('Arial', 12, 'bold')).grid(row=row, column=0, columnspan=4, sticky='w', pady=(20, 10))
        row += 1
        
        # Enable/Disable checkbox
        self.contact_extraction_enabled = tk.BooleanVar(value=self.config.config.get("step5", {}).get("enabled", True))
        ttk.Checkbutton(scrollable_frame, text="5.1 Enable Contact Extraction", variable=self.contact_extraction_enabled).grid(row=row, column=0, columnspan=2, sticky='w')
        ttk.Label(scrollable_frame, text="(turn OFF if you only need company info, not individual contacts)").grid(row=row, column=2, sticky='w')
        row += 1
        
        # Max contacts
        ttk.Label(scrollable_frame, text="5.2 Max Contacts per Lead:").grid(row=row, column=0, sticky='w')
        self.max_contacts = tk.StringVar(value=str(self.config.config.get("step5", {}).get("max_contacts", 5)))
        ttk.Entry(scrollable_frame, textvariable=self.max_contacts, width=10).grid(row=row, column=1, sticky='w')
        ttk.Label(scrollable_frame, text="(people to extract per company - typical: 3-5)").grid(row=row, column=2, sticky='w')
        row += 1
        
        # Contact extraction prompt
        ttk.Label(scrollable_frame, text="5.3 Contact Extraction Prompt:").grid(row=row, column=0, sticky='nw', padx=(0, 10))
        
        contact_prompt_frame = ttk.Frame(scrollable_frame)
        contact_prompt_frame.grid(row=row, column=1, columnspan=3, sticky='ew', padx=(0, 0))
        
        self.contact_extraction_prompt = tk.Text(contact_prompt_frame, width=60, height=4, wrap='word')
        contact_prompt_scrollbar = ttk.Scrollbar(contact_prompt_frame, orient="vertical", command=self.contact_extraction_prompt.yview)
        self.contact_extraction_prompt.configure(yscrollcommand=contact_prompt_scrollbar.set)
        
        existing_contact_prompt = self.config.config.get("step5", {}).get("contact_extraction_prompt", "")
        if existing_contact_prompt:
            self.contact_extraction_prompt.insert("1.0", existing_contact_prompt)
        
        self.contact_extraction_prompt.pack(side='left', fill='both', expand=True)
        contact_prompt_scrollbar.pack(side='right', fill='y')
        row += 1
        
        # Configurable Title Keywords for Scoring
        ttk.Label(scrollable_frame, text="5.4 Contact Scoring Title Keywords (comma-separated):", font=('Arial', 10, 'italic')).grid(row=row, column=0, columnspan=4, sticky='w', pady=(10, 5))
        row += 1
        ttk.Label(scrollable_frame, text="Seniority = how senior the person is. Fit = how relevant their role is to your target market. Both scored 1-4.", 
                 font=('Arial', 8), foreground='gray').grid(row=row, column=0, columnspan=4, sticky='w', pady=(0,5))
        row += 1
        
        # Seniority 4 titles
        ttk.Label(scrollable_frame, text="Seniority 4 (Highest):").grid(row=row, column=0, sticky='w')
        self.seniority_4_titles = tk.StringVar(value=self.config.config.get("step5", {}).get("seniority_4_titles", "CEO, Founder, Co-Founder, Chairman, President, Owner, Chief Executive Officer, Managing Director, Principal, Proprietor"))
        ttk.Entry(scrollable_frame, textvariable=self.seniority_4_titles, width=60).grid(row=row, column=1, columnspan=2, sticky='ew')
        row += 1
        
        # Seniority 3 titles
        ttk.Label(scrollable_frame, text="Seniority 3 (High):").grid(row=row, column=0, sticky='w')
        self.seniority_3_titles = tk.StringVar(value=self.config.config.get("step5", {}).get("seniority_3_titles", "CSO, CTO, CMO, COO, CFO, CBO, Chief Scientific Officer, Chief Technology Officer, Chief Medical Officer, Chief Operating Officer, Vice President, VP, EVP, SVP, Executive Vice President, Senior Vice President, Global Head, Head of, Division Head, Department Head"))
        ttk.Entry(scrollable_frame, textvariable=self.seniority_3_titles, width=60).grid(row=row, column=1, columnspan=2, sticky='ew')
        row += 1
        
        # Seniority 2 titles
        ttk.Label(scrollable_frame, text="Seniority 2 (Medium):").grid(row=row, column=0, sticky='w')
        self.seniority_2_titles = tk.StringVar(value=self.config.config.get("step5", {}).get("seniority_2_titles", "Director, Senior Director, Executive Director, Scientific Advisor, Senior Scientist, Associate Vice President, AVP, Group Director, Regional Director, Lead Scientist, Principal Scientist, Staff Scientist"))
        ttk.Entry(scrollable_frame, textvariable=self.seniority_2_titles, width=60).grid(row=row, column=1, columnspan=2, sticky='ew')
        row += 1
        
        # Seniority 1 titles
        ttk.Label(scrollable_frame, text="Seniority 1 (Lower):").grid(row=row, column=0, sticky='w')
        self.seniority_1_titles = tk.StringVar(value=self.config.config.get("step5", {}).get("seniority_1_titles", "Associate Director, Manager, Senior Manager, Scientist, Principal Investigator, PI, Group Leader, Data Scientist, Research Scientist, Project Lead, Team Lead, Coordinator, Analyst, Specialist, Associate"))
        ttk.Entry(scrollable_frame, textvariable=self.seniority_1_titles, width=60).grid(row=row, column=1, columnspan=2, sticky='ew')
        row += 1
        
        # Fit 4 titles
        ttk.Label(scrollable_frame, text="Fit 4 (Excellent):").grid(row=row, column=0, sticky='w')
        self.fit_4_titles = tk.StringVar(value=self.config.config.get("step5", {}).get("fit_4_titles", "Preclinical, Translational, Discovery, CEO, Founder, President, Chief Executive, Principal, Owner, Co-Founder, Chairman"))
        ttk.Entry(scrollable_frame, textvariable=self.fit_4_titles, width=60).grid(row=row, column=1, columnspan=2, sticky='ew')
        row += 1
        
        # Fit 3 titles
        ttk.Label(scrollable_frame, text="Fit 3 (Good):").grid(row=row, column=0, sticky='w')
        self.fit_3_titles = tk.StringVar(value=self.config.config.get("step5", {}).get("fit_3_titles", "Scientific, Research, R&D, In Vivo, In Vitro, Laboratory, Lab Director, CSO, CTO, VP Research, Head of Research, Research Director, Science, Innovation"))
        ttk.Entry(scrollable_frame, textvariable=self.fit_3_titles, width=60).grid(row=row, column=1, columnspan=2, sticky='ew')
        row += 1
        
        # Fit 2 titles
        ttk.Label(scrollable_frame, text="Fit 2 (Moderate):").grid(row=row, column=0, sticky='w')
        self.fit_2_titles = tk.StringVar(value=self.config.config.get("step5", {}).get("fit_2_titles", "Oncology, Cancer, Immunology, Drug Development, Medical Affairs, Pharmacology, Clinical Development, Therapeutics, Biopharmaceutical, Life Sciences, Biotech, Healthcare"))
        ttk.Entry(scrollable_frame, textvariable=self.fit_2_titles, width=60).grid(row=row, column=1, columnspan=2, sticky='ew')
        row += 1
        
        # Fit 1 titles
        ttk.Label(scrollable_frame, text="Fit 1 (Lower):").grid(row=row, column=0, sticky='w')
        self.fit_1_titles = tk.StringVar(value=self.config.config.get("step5", {}).get("fit_1_titles", "Business Development, Operations, Economic, Project Management, Administrative, Finance, Legal, HR, Human Resources, Marketing, Sales, Communications, IT, Information Technology"))
        ttk.Entry(scrollable_frame, textvariable=self.fit_1_titles, width=60).grid(row=row, column=1, columnspan=2, sticky='ew')
        row += 1
        
        # Store canvas reference for mousewheel handling
        self._scrollable_canvases.append(canvas)
        
        # Pack scrollbar FIRST so it gets space before canvas expands
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        scrollable_frame.columnconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
    
    def setup_bottom_ribbon(self):
        """Setup bottom ribbon with progress bar and Save and Exit button."""
        ribbon = ttk.Frame(self.root)
        ribbon.pack(fill='x', side='bottom', padx=10, pady=(0, 10))
        
        # Save and Exit button on the left
        self.save_exit_button = ttk.Button(ribbon, text="Save and Exit", command=self.save_and_exit, style='Accent.TButton')
        self.save_exit_button.pack(side='left', padx=(0, 20))
        
        # Progress bar on the right
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(ribbon, variable=self.progress_var, maximum=100, length=400)
        self.progress_bar.pack(side='right', fill='x', expand=True, padx=(20, 0))
    
    def save_and_exit(self):
        """Save configuration and exit. If bot is running, ensure it's properly saved."""
        # Save configuration (don't show message box, we'll handle exit)
        success = self.save_config(show_message=False)
        
        if not success:
            # Save failed - ask user if they want to exit anyway
            result = messagebox.askyesno(
                "Save Failed", 
                "Failed to save configuration! Do you still want to exit?\n\n"
                "Click 'No' to stay and try again, or 'Yes' to exit without saving."
            )
            if not result:
                return  # User chose not to exit
        
        # Close GUI
        self.root.quit()
        self.root.destroy()
    
    def on_window_close(self):
        """Handle window close (X button) - prompt to save before closing."""
        result = messagebox.askyesnocancel(
            "Save Before Closing",
            "Do you want to save your configuration before closing?\n\n"
            "Yes = Save and exit\n"
            "No = Exit without saving\n"
            "Cancel = Stay in application"
        )
        
        if result is None:
            # Cancel - do nothing, stay in the application
            return
        elif result:
            # Yes - save and exit
            self.save_and_exit()
        else:
            # No - exit without saving
            self.root.quit()
            self.root.destroy()
    
    def save_config(self, show_message=True) -> bool:
        """Save current configuration - all variables are persisted for future runs.
        Returns True on success, False on failure."""
        # ============================================================
        # USER INPUTS (ONBOARDING)
        # ============================================================
        if "user_inputs" not in self.config.config:
            self.config.config["user_inputs"] = {}
        
        # Check if onboarding fields exist (they might not if GUI was created before this update)
        if hasattr(self, 'input_business_name'):
            self.config.config["user_inputs"]["business_name"] = self.input_business_name.get()
            self.config.config["user_inputs"]["website_url"] = self.input_website_url.get()
            self.config.config["user_inputs"]["product_description"] = self.input_product_description.get()
            self.config.config["user_inputs"]["price_min"] = self.input_price_min.get()
            self.config.config["user_inputs"]["price_max"] = self.input_price_max.get()
            self.config.config["user_inputs"]["ideal_customer"] = self.input_ideal_customer.get("1.0", "end").strip()
            self.config.config["user_inputs"]["company_size"] = self.input_company_size.get()
            self.config.config["user_inputs"]["geography"] = self.input_geography.get()
            self.config.config["user_inputs"]["seniority_levels"] = self.input_seniority_levels.get()
            self.config.config["user_inputs"]["departments"] = self.input_departments.get()
            self.config.config["user_inputs"]["exclusions"] = self.input_exclusions.get("1.0", "end").strip()
            self.config.config["user_inputs"]["good_leads"] = self.input_good_leads.get("1.0", "end").strip()
            self.config.config["user_inputs"]["search_keywords"] = self.input_search_keywords.get("1.0", "end").strip()
            self.config.config["user_inputs"]["other_context"] = self.input_other_context.get("1.0", "end").strip()
            self.config.config["user_inputs"]["extract_contacts"] = self.input_extract_contacts.get()
            
            # Save single prompt response if in single prompt mode
            if hasattr(self, 'single_prompt_text'):
                self.config.config["user_inputs"]["single_prompt_response"] = self.single_prompt_text.get("1.0", "end").strip()
            
            # Sync user inputs to actual pipeline config
            # Good leads -> step4.good_leads_domains
            good_leads_raw = self.config.config["user_inputs"]["good_leads"]
            # Parse URLs from the text (comma, newline, or space separated)
            good_leads_urls = [url.strip() for url in good_leads_raw.replace('\n', ',').replace(' ', ',').split(',') if url.strip()]
            # Extract domains from URLs
            good_leads_domains = []
            for url in good_leads_urls:
                if url:
                    # Remove protocol and www
                    domain = url.replace('https://', '').replace('http://', '').replace('www.', '')
                    # Take just the domain part
                    domain = domain.split('/')[0]
                    if domain:
                        good_leads_domains.append(domain)
            self.config.config["step4"]["good_leads_domains"] = ", ".join(good_leads_domains)
            
            # Extract contacts -> step5.enabled
            self.config.config["step5"]["enabled"] = self.config.config["user_inputs"]["extract_contacts"]
        
        # ============================================================
        # GITHUB SYNC SETTINGS
        # ============================================================
        self.config.config["github_auto_sync"] = self.github_auto_sync.get()
        
        # ============================================================
        # AI OPTIMIZATION AGENT SETTINGS
        # ============================================================
        if "ai_optimization_agent" not in self.config.config:
            self.config.config["ai_optimization_agent"] = {}
        
        if hasattr(self, 'ai_agent_enabled'):
            self.config.config["ai_optimization_agent"]["enabled"] = self.ai_agent_enabled.get()
        if hasattr(self, 'ai_agent_prompt'):
            self.config.config["ai_optimization_agent"]["prompt"] = self.ai_agent_prompt.get("1.0", "end").strip()
        
        # ============================================================
        # PERFORMANCE SETTINGS
        # ============================================================
        if "performance" not in self.config.config:
            self.config.config["performance"] = {}
        
        self.config.config["performance"]["ai_batch_size"] = int(self.ai_batch_size.get())
        self.config.config["performance"]["rate_limiter_success_threshold"] = int(self.rate_success_threshold.get())
        
        # Parse logging level (remove the overhead text)
        logging_val = self.logging_level.get()
        if "none" in logging_val.lower():
            self.config.config["performance"]["logging_level"] = "none"
        elif "limited" in logging_val.lower():
            self.config.config["performance"]["logging_level"] = "limited"
        elif "detailed" in logging_val.lower():
            self.config.config["performance"]["logging_level"] = "detailed"
        else:
            self.config.config["performance"]["logging_level"] = "moderate"
        
        self.config.config["performance"]["debug_file_interval"] = int(self.debug_file_interval.get())
        self.config.config["performance"]["always_write_debug_files"] = self.always_write_debug.get()
        self.config.config["performance"]["fuzzy_match_threshold"] = int(self.perf_fuzzy_threshold.get())
        
        # Save CSV output settings
        if "csv_output" not in self.config.config:
            self.config.config["csv_output"] = {}
        self.config.config["csv_output"]["delimiter"] = self.csv_delimiter.get()
        
        # Also update step4 async batch size
        self.config.config["step4"]["async_batch_size"] = int(self.ai_batch_size.get())
        
        # ============================================================
        # STEP 1: DISCOVERY SETTINGS
        # ============================================================
        self.config.config["step1"]["api_choice"] = self.api_choice.get()
        self.config.config["step1"]["api_key"] = self.api_key.get()
        self.config.config["step1"]["region"] = self.region.get()
        self.config.config["step1"]["max_results"] = int(self.max_results.get())
        self.config.config["step1"]["serper_combo_cap"] = int(self.combo_cap.get())
        self.config.config["step1"]["verify_domains"] = self.verify_domains.get()
        self.config.config["step1"]["rate_limit_initial"] = float(self.rate_limit_initial.get())
        self.config.config["step1"]["rate_limit_min"] = float(self.rate_limit_min.get())
        self.config.config["step1"]["rate_limit_max"] = float(self.rate_limit_max.get())
        self.config.config["step1"]["reanalysis_period"] = int(self.reanalysis_period.get())
        self.config.config["step1"]["request_timeout_seconds"] = int(self.request_timeout.get())
        self.config.config["step1"]["concurrency"] = int(self.step1_concurrency.get())
        
        # Save keyword boxes and count
        self.config.config["step1"]["keyword_box_count"] = int(self.keyword_box_count.get())
        keyword_boxes_data = []
        for i, box in enumerate(self.keyword_boxes):
            keywords = box.get("1.0", "end").strip()
            keyword_boxes_data.append(keywords)
        self.config.config["step1"]["keyword_boxes"] = keyword_boxes_data
        
        # ============================================================
        # STEP 2: SCRAPING SETTINGS
        # ============================================================
        self.config.config["step2"]["max_pages_per_site"] = int(self.max_pages.get())
        self.config.config["step2"]["max_depth"] = int(self.max_depth.get())
        self.config.config["step2"]["global_concurrency"] = int(self.global_concurrency.get())
        self.config.config["step2"]["per_domain_concurrency"] = int(self.per_domain_concurrency.get())
        self.config.config["step2"]["timeout_sec"] = int(self.timeout.get())
        self.config.config["step2"]["aggregate_char_cap"] = int(self.aggregate_char_cap.get())
        self.config.config["step2"]["max_chars_per_page"] = int(self.max_chars_per_page.get())
        self.config.config["step2"]["max_chars_per_scrape"] = int(self.max_chars_per_scrape.get())
        self.config.config["step2"]["contact_priority_keywords"] = self.contact_priority_keywords.get()
        self.config.config["step2"]["user_agent"] = self.user_agent.get()
        self.config.config["step2"]["read_limit_bytes"] = int(self.read_limit_bytes.get())
        self.config.config["step2"]["min_chars_per_page"] = int(self.min_chars_per_page.get())
        self.config.config["step2"]["robots_cache_ttl_sec"] = int(self.robots_cache_ttl.get())
        self.config.config["step2"]["respect_robots"] = self.respect_robots.get()
        self.config.config["step2"]["follow_sitemaps"] = self.follow_sitemaps.get()
        
        # ============================================================
        # STEP 3: SCORING SETTINGS (Multi-select thresholds)
        # ============================================================
        self.config.config["step3"]["use_score_threshold"] = self.use_score_threshold.get()
        self.config.config["step3"]["use_percentage_threshold"] = self.use_percentage_threshold.get()
        self.config.config["step3"]["use_count_threshold"] = self.use_count_threshold.get()
        self.config.config["step3"]["threshold_value"] = self.threshold_value.get()
        self.config.config["step3"]["percentage_value"] = int(self.percentage_value.get())
        self.config.config["step3"]["count_value"] = int(self.count_value.get())
        self.config.config["step3"]["fuzzy_match_threshold"] = int(self.fuzzy_match_threshold.get())
        
        # Save positive factors and count
        self.config.config["step3"]["positive_factor_count"] = int(self.positive_factor_count.get())
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
        
        # Save negative factors and count
        self.config.config["step3"]["negative_factor_count"] = int(self.negative_factor_count.get())
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
        
        # ============================================================
        # STEP 4: AI ANALYSIS SETTINGS
        # ============================================================
        provider = self.ai_provider.get()
        model_choice = self.ai_model_choice.get()
        
        self.config.config["step4"]["provider_choice"] = provider
        self.config.config["step4"]["api_provider"] = provider
        self.config.config["step4"]["model_choice"] = model_choice
        self.config.config["step4"]["api_key"] = self.ai_api_key.get()
        self.config.config["step4"]["gemini_api_key"] = self.gemini_api_key.get()
        
        # Save model configurations from advanced settings
        for prov in ["claude", "openai", "gemini"]:
            if hasattr(self, 'model_config_vars') and prov in self.model_config_vars:
                models = []
                for model_vars in self.model_config_vars[prov]:
                    try:
                        cost = float(model_vars["cost_per_1k"].get() or 0)
                    except ValueError:
                        cost = 0
                    models.append({
                        "name": model_vars["name"].get().strip(),
                        "api_id": model_vars["api_id"].get().strip(),
                        "cost_per_1k": cost
                    })
                self.config.config["step4"][f"{prov}_models"] = models
        
        # Set the actual model API ID based on provider and model choice
        models_key = f"{provider}_models"
        models = self.config.config["step4"].get(models_key, [])
        
        # Extract model index (model_1 -> 0, model_2 -> 1, etc.)
        try:
            model_idx = int(model_choice.split("_")[1]) - 1 if "_" in model_choice else 0
        except (ValueError, IndexError):
            model_idx = 0
        
        if model_idx < len(models):
            self.config.config["step4"]["model"] = models[model_idx].get("api_id", "")
        
        self.config.config["step4"]["max_tokens"] = int(self.max_tokens.get())
        self.config.config["step4"]["max_retries"] = int(self.max_retries.get())
        self.config.config["step4"]["batch_size"] = int(self.batch_size.get())
        self.config.config["step4"]["checkpoint_interval"] = int(self.checkpoint_interval.get())
        self.config.config["step4"]["log_level"] = self.log_level.get()
        self.config.config["step4"]["credit_limit"] = float(self.credit_limit.get())
        
        # Save good leads configuration
        self.config.config["step4"]["good_leads_domains"] = self.good_leads_domains.get().strip()
        self.config.config["step4"]["good_leads_max_pages_per_site"] = int(self.good_leads_max_pages.get() or 12)
        self.config.config["step4"]["good_leads_max_depth"] = int(self.good_leads_max_depth.get() or 2)
        self.config.config["step4"]["good_leads_max_chars_per_page"] = int(self.good_leads_max_chars_per_page.get() or 50000)
        self.config.config["step4"]["good_leads_aggregate_char_cap"] = int(self.good_leads_aggregate_cap.get() or 120000)
        self.config.config["step4"]["good_leads_summarization_prompt"] = self.good_leads_summarization_prompt.get("1.0", tk.END).strip()
        self.config.config["step4"]["good_leads_max_summary_chars"] = int(self.good_leads_max_summary_chars.get() or 8000)
        
        # Save company description prompt
        self.config.config["step4"]["company_description_prompt"] = self.company_description_prompt.get("1.0", tk.END).strip()
        
        # Save scoring fields configuration and count
        self.config.config["step4"]["scoring_field_count"] = int(self.scoring_field_count.get())
        scoring_fields = []
        for widgets in self.scoring_field_widgets:
            field = {
                "enabled": widgets['enabled'].get(),
                "type": widgets['type'].get(),
                "title": widgets['title'].get().strip(),
                "min": int(widgets['min'].get()) if widgets['min'].get().strip() else 0,
                "max": int(widgets['max'].get()) if widgets['max'].get().strip() else 10,
                "prompt": widgets['prompt'].get("1.0", tk.END).strip(),
                "allow_unlisted": widgets['allow_unlisted'].get(),
                "allow_multiple": widgets['allow_multiple'].get(),
                "options": [opt.strip() for opt in widgets['options'].get().split(";") if opt.strip()]
            }
            scoring_fields.append(field)
        self.config.config["step4"]["scoring_fields"] = scoring_fields
        
        # Update the model descriptions in the UI after saving
        self.update_model_descriptions()
        
        # ============================================================
        # STEP 5: CONTACT EXTRACTION SETTINGS
        # ============================================================
        if "step5" not in self.config.config:
            self.config.config["step5"] = {}
        self.config.config["step5"]["enabled"] = self.contact_extraction_enabled.get()
        self.config.config["step5"]["max_contacts"] = int(self.max_contacts.get())
        self.config.config["step5"]["contact_extraction_prompt"] = self.contact_extraction_prompt.get("1.0", tk.END).strip()
        
        # Save configurable contact scoring title keywords
        self.config.config["step5"]["seniority_4_titles"] = self.seniority_4_titles.get()
        self.config.config["step5"]["seniority_3_titles"] = self.seniority_3_titles.get()
        self.config.config["step5"]["seniority_2_titles"] = self.seniority_2_titles.get()
        self.config.config["step5"]["seniority_1_titles"] = self.seniority_1_titles.get()
        self.config.config["step5"]["fit_4_titles"] = self.fit_4_titles.get()
        self.config.config["step5"]["fit_3_titles"] = self.fit_3_titles.get()
        self.config.config["step5"]["fit_2_titles"] = self.fit_2_titles.get()
        self.config.config["step5"]["fit_1_titles"] = self.fit_1_titles.get()
        
        # Save config with GitHub sync based on setting
        sync_to_github = self.config.config.get("github_auto_sync", False)
        success = self.config.save_config(sync_to_github=sync_to_github)
        if show_message:
            if success:
                messagebox.showinfo("Success", "Configuration saved successfully!")
            else:
                messagebox.showerror("Error", "Failed to save configuration! Check file permissions and try again.")
        return success
    
    def load_config(self):
        """Load configuration from file."""
        self.config = UnifiedConfig()
        messagebox.showinfo("Success", "Configuration loaded successfully!")
        # Refresh GUI with loaded values
        self.root.destroy()
        self.__init__()
    
    def run_pipeline(self):
        """Run all pipeline steps with stats tracking."""
        self.is_running = True
        self.save_config(show_message=False)
        
        # Create run folder for this run
        if self.resume_run_folder and os.path.exists(self.resume_run_folder):
            # Resuming a previous run
            self.current_run_folder = self.resume_run_folder
            self.run_state_tracker = RunStateTracker(self.current_run_folder)
            run_number = self.run_state_tracker.state.get('run_number', get_next_run_number())
        else:
            # New run - create folder
            self.current_run_folder, run_number = create_run_folder()
            self.run_state_tracker = RunStateTracker(self.current_run_folder)
            self.run_state_tracker.start_run(run_number)
            
            # Copy config to run folder
            config_copy_path = os.path.join(self.current_run_folder, "config.json")
            with open(config_copy_path, 'w', encoding='utf-8') as f:
                json.dump(self.config.config, f, indent=2)
        
        # Write run details text file
        details_path = os.path.join(self.current_run_folder, "run_details.txt")
        with open(details_path, 'w', encoding='utf-8') as f:
            f.write(f"Sherpa Lead Generator - Run {run_number}\n")
            f.write(f"{'=' * 40}\n\n")
            f.write(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Run Folder: {self.current_run_folder}\n\n")
            f.write(f"Configuration Summary:\n")
            f.write(f"  - AI Provider: {self.config.config.get('step4', {}).get('provider_choice', 'claude')}\n")
            f.write(f"  - Max Searches: {self.config.config.get('step1', {}).get('serper_combo_cap', 500)}\n")
            f.write(f"  - Max Results per Search: {self.config.config.get('step1', {}).get('max_results', 100)}\n")
        
        # Initialize stats tracker and update UI
        self.stats_tracker.start_run()
        self.run_button.configure(text="⏸ Running...", state='disabled')
        
        # Log run config to training data collector (non-blocking)
        try:
            training_collector = get_training_collector()
            training_collector.log_run_config(
                run_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
                config=self.config.config
            )
        except Exception as e:
            print(f"Training data logging (non-critical): {e}")
        
        # Show Save & Exit Run button during runs
        self.save_exit_run_btn.pack(side='right', padx=5)
        
        self.update_stats_display()
        
        # Track output files
        output_files = []
        import glob
        
        try:
            # ============================================================
            # STEP 1: Website Discovery
            # ============================================================
            combo_cap = int(self.config.config.get("step1", {}).get("serper_combo_cap", 500))
            self.stats_tracker.start_stage(1, total_batches=combo_cap, 
                                           description="Finding websites via search API")
            self.stats_tracker.set_search_combinations(combo_cap)
            self.run_state_tracker.update_stage(1, "Website Discovery", 0, combo_cap)
            self.update_stats_display()
            
            discovery = WebsiteDiscovery(self.config, progress_callback=self.log_progress)
            success = asyncio.run(discovery.run_discovery())
            
            if not success:
                self.log_progress("ERROR: Step 1 failed")
                messagebox.showerror("Error", "Step 1 (Website Discovery) failed. Check the log for details.")
                self.reset_run_state()
                return
            
            self.stats_tracker.complete_stage(1)
            
            # Get discovered websites count
            step1_files = glob.glob("data/leads_raw_*.csv")
            if step1_files:
                step1_file = max(step1_files, key=os.path.getmtime)
                output_files.append(f"Step 1: {step1_file}")
                try:
                    import pandas as pd
                    df = pd.read_csv(step1_file)
                    self.stats_tracker.set_websites_discovered(len(df))
                except:
                    pass
            
            self.update_stats_display()
            
            # ============================================================
            # STEP 2: Website Scraping
            # ============================================================
            websites_to_scrape = self.stats_tracker.websites_discovered or 100
            self.stats_tracker.start_stage(2, total_batches=websites_to_scrape,
                                           description="Extracting content from websites")
            self.stats_tracker.set_websites_to_scrape(websites_to_scrape)
            self.update_stats_display()
            
            scraper = WebsiteScraper(self.config, progress_callback=self.log_progress)
            success = asyncio.run(scraper.run_scraping())
            
            if not success:
                self.log_progress("ERROR: Step 2 failed")
                self.reset_run_state()
                return
            
            self.stats_tracker.complete_stage(2)
            self.stats_tracker.websites_scraped = websites_to_scrape
            self.update_stats_display()
            
            # ============================================================
            # Good Leads Reference Scraping & Summarization (before scoring)
            # ============================================================
            good_leads_domains = self.config.config.get("step4", {}).get("good_leads_domains", "").strip()
            if good_leads_domains:
                self.log_progress("Scraping and summarizing good leads reference websites...")
                try:
                    good_leads_scraper = GoodLeadsScraper(self.config, progress_callback=self.log_progress)
                    good_leads_summary = asyncio.run(good_leads_scraper.run_scrape_and_summarize())
                    if good_leads_summary:
                        self.log_progress(f"Good leads summary generated ({len(good_leads_summary)} chars)")
                        # Save the summary to config for use in AI analysis
                        self.config.config["step4"]["good_leads_summary_cache"] = good_leads_summary
                    else:
                        self.log_progress("No good leads summary generated (check domains or API key)")
                except Exception as e:
                    self.log_progress(f"WARNING: Good leads scraping failed: {e}")
                    # Continue anyway - this is optional
            
            # ============================================================
            # STEP 3: Factor-based Scoring
            # ============================================================
            self.stats_tracker.start_stage(3, total_batches=self.stats_tracker.websites_scraped,
                                           description="Evaluating websites with scoring factors")
            self.update_stats_display()
            
            scorer = FactorScorer(self.config, progress_callback=self.log_progress)
            success = scorer.run_scoring()
            
            if not success:
                self.log_progress("ERROR: Step 3 failed")
                self.reset_run_state()
                return
            
            self.stats_tracker.complete_stage(3)
            
            # Get scored count from results file
            step3_files = glob.glob("data/scoring_results_*.csv")
            if step3_files:
                step3_file = max(step3_files, key=os.path.getmtime)
                output_files.append(f"Step 3: {step3_file}")
                try:
                    import pandas as pd
                    df = pd.read_csv(step3_file)
                    self.stats_tracker.websites_scored = len(df)
                except:
                    pass
            
            self.update_stats_display()
            
            # ============================================================
            # STEP 4: AI Analysis
            # ============================================================
            websites_to_analyze = self.stats_tracker.websites_scored or 50
            self.stats_tracker.start_stage(4, total_batches=websites_to_analyze,
                                           description="AI-powered lead qualification")
            self.update_stats_display()
            
            analyzer = AIAnalyzer(self.config, progress_callback=self.log_progress)
            success = analyzer.run_ai_analysis()
            
            if not success:
                self.log_progress("ERROR: Step 4 failed")
                self.reset_run_state()
                return
            
            self.stats_tracker.complete_stage(4)
            
            # Get analyzed count
            step4_files = glob.glob("data/ai_analysis_results_*.csv")
            if step4_files:
                step4_file = max(step4_files, key=os.path.getmtime)
                output_files.append(f"Step 4: {step4_file}")
                try:
                    import pandas as pd
                    df = pd.read_csv(step4_file)
                    self.stats_tracker.websites_analyzed = len(df)
                except:
                    pass
            
            self.update_stats_display()
            
            # ============================================================
            # STEP 5: Contact Extraction
            # ============================================================
            if self.config.config.get("step5", {}).get("enabled", True):
                contacts_to_extract = self.stats_tracker.websites_analyzed or 25
                self.stats_tracker.start_stage(5, total_batches=contacts_to_extract,
                                               description="Extracting contact information")
                self.update_stats_display()
                
                contact_extractor = ContactExtractor(self.config, progress_callback=self.log_progress)
                success = contact_extractor.run_contact_extraction()
                
                self.stats_tracker.complete_stage(5)
                
                if success:
                    step5_files = glob.glob("data/contacts_results_*.csv")
                    if step5_files:
                        step5_file = max(step5_files, key=os.path.getmtime)
                        output_files.append(f"Step 5: {step5_file}")
                        try:
                            import pandas as pd
                            df = pd.read_csv(step5_file)
                            self.stats_tracker.websites_with_contacts = len(df)
                        except:
                            pass
            
            # ============================================================
            # COMPLETION
            # ============================================================
            self.stats_tracker.current_stage = 5
            self.stats_tracker.stage_description = "Pipeline completed successfully!"
            self.update_stats_display()
            
            # Copy final CSV to run folder
            if self.current_run_folder:
                # Find the most recent AI analysis results or comprehensive data
                final_csv = None
                step5_files = glob.glob("data/contacts_results_*.csv")
                step4_files = glob.glob("data/ai_analysis_results_*.csv")
                
                if step5_files:
                    final_csv = max(step5_files, key=os.path.getmtime)
                elif step4_files:
                    final_csv = max(step4_files, key=os.path.getmtime)
                
                if final_csv and os.path.exists(final_csv):
                    dest_csv = os.path.join(self.current_run_folder, f"results.csv")
                    shutil.copy2(final_csv, dest_csv)
                    output_files.append(f"Run Output: {dest_csv}")
                
                # Update run details with completion info
                details_path = os.path.join(self.current_run_folder, "run_details.txt")
                with open(details_path, 'a', encoding='utf-8') as f:
                    f.write(f"\n\nCompletion:\n")
                    f.write(f"  - End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"  - Elapsed: {self.stats_tracker.get_elapsed_formatted()}\n")
                    f.write(f"  - Websites Discovered: {self.stats_tracker.websites_discovered}\n")
                    f.write(f"  - Websites Scraped: {self.stats_tracker.websites_scraped}\n")
                    f.write(f"  - Websites Scored: {self.stats_tracker.websites_scored}\n")
                    f.write(f"  - Websites Analyzed: {self.stats_tracker.websites_analyzed}\n")
                    f.write(f"  - Websites with Contacts: {self.stats_tracker.websites_with_contacts}\n")
                
                # Mark run as complete in state tracker
                if self.run_state_tracker:
                    self.run_state_tracker.state['websites_discovered'] = self.stats_tracker.websites_discovered
                    self.run_state_tracker.state['websites_scraped'] = self.stats_tracker.websites_scraped
                    self.run_state_tracker.state['websites_scored'] = self.stats_tracker.websites_scored
                    self.run_state_tracker.state['websites_analyzed'] = self.stats_tracker.websites_analyzed
                    self.run_state_tracker.state['websites_with_contacts'] = self.stats_tracker.websites_with_contacts
                    self.run_state_tracker.mark_complete()
            
            # Update stage label to show completion
            self.stage_label.configure(text="✓ Complete")
            self.desc_label.configure(text="All pipeline stages finished successfully")
            self.status_label.configure(text="🎉 All steps completed!", foreground='green')
            
            # Record timing data for future ETA improvements (lightweight)
            self.stats_tracker.record_completed_run()
            
            # Sync training data to GitHub (non-blocking, after run completes)
            try:
                self.log_progress("Syncing training data to GitHub...")
                success, msg = git_push_training_data()
                if success:
                    self.log_progress(f"Training data sync: {msg}")
                else:
                    self.log_progress(f"Training data sync warning: {msg}")
            except Exception as e:
                self.log_progress(f"Training data sync (non-critical): {e}")
            
            self.is_running = False
            self.run_button.configure(text="▶ Start Run", state='normal')
            self.save_exit_run_btn.pack_forget()  # Hide save & exit button
            
            # Show completion message
            elapsed = self.stats_tracker.get_elapsed_formatted()
            total_found = self.stats_tracker.websites_discovered
            analyzed = self.stats_tracker.websites_analyzed
            
            messagebox.showinfo("Success", 
                f"Pipeline completed successfully!\n\n"
                f"Total time: {elapsed}\n"
                f"Websites discovered: {total_found}\n"
                f"Websites analyzed: {analyzed}\n\n"
                f"Run folder: {self.current_run_folder}\n\n"
                f"Output files:\n" + "\n".join(output_files))
            
        except Exception as e:
            self.log_progress(f"ERROR: {str(e)}")
            messagebox.showerror("Error", f"Pipeline failed: {str(e)}")
            self.reset_run_state()
    
    def reset_run_state(self):
        """Reset UI state after run ends (success or failure)."""
        self.is_running = False
        self.run_button.configure(text="▶ Start Run", state='normal')
        self.save_exit_run_btn.pack_forget()  # Hide save & exit button
        self.status_label.configure(text="Run ended", foreground='gray')
        
        # Sync training data to GitHub on run end (non-blocking)
        try:
            git_push_training_data()
        except:
            pass  # Silent fail for training data sync
    
    def save_and_exit_run(self):
        """Save current run state and exit the pipeline gracefully."""
        if not self.is_running:
            messagebox.showinfo("Not Running", "No run is currently in progress.")
            return
        
        result = messagebox.askyesnocancel(
            "Save and Exit Run",
            "Do you want to save the current run state and exit?\n\n"
            "• Yes - Save progress and stop the run (can resume later)\n"
            "• No - Stop without saving\n"
            "• Cancel - Continue running"
        )
        
        if result is None:
            # Cancel - continue running
            return
        elif result:
            # Yes - save state and exit
            if self.run_state_tracker:
                self.run_state_tracker.state['websites_discovered'] = self.stats_tracker.websites_discovered
                self.run_state_tracker.state['websites_scraped'] = self.stats_tracker.websites_scraped
                self.run_state_tracker.state['websites_scored'] = self.stats_tracker.websites_scored
                self.run_state_tracker.state['websites_analyzed'] = self.stats_tracker.websites_analyzed
                self.run_state_tracker.state['websites_with_contacts'] = self.stats_tracker.websites_with_contacts
                self.run_state_tracker.pause_run()
            
            # Save current data to run folder
            if self.current_run_folder:
                # Copy latest CSV to run folder
                step5_files = glob.glob("data/contacts_results_*.csv")
                step4_files = glob.glob("data/ai_analysis_results_*.csv")
                step3_files = glob.glob("data/scoring_results_*.csv")
                
                final_csv = None
                if step5_files:
                    final_csv = max(step5_files, key=os.path.getmtime)
                elif step4_files:
                    final_csv = max(step4_files, key=os.path.getmtime)
                elif step3_files:
                    final_csv = max(step3_files, key=os.path.getmtime)
                
                if final_csv and os.path.exists(final_csv):
                    dest_csv = os.path.join(self.current_run_folder, "results_partial.csv")
                    shutil.copy2(final_csv, dest_csv)
                
                # Update run details
                details_path = os.path.join(self.current_run_folder, "run_details.txt")
                with open(details_path, 'a', encoding='utf-8') as f:
                    f.write(f"\n\nPaused:\n")
                    f.write(f"  - Pause Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"  - Current Stage: {self.stats_tracker.current_stage}\n")
                    f.write(f"  - Websites Discovered: {self.stats_tracker.websites_discovered}\n")
                    f.write(f"  - Websites Analyzed: {self.stats_tracker.websites_analyzed}\n")
            
            messagebox.showinfo("Run Saved", 
                f"Run state saved to:\n{self.current_run_folder}\n\n"
                f"You can resume this run later from the main menu.")
        
        # Reset state regardless of save choice
        self.reset_run_state()
        self.stage_label.configure(text="Run Stopped")
        self.desc_label.configure(text="Run was stopped by user")
        self.status_label.configure(text="Stopped", foreground='orange')
    
    def view_all_leads(self):
        """Open a window showing all leads sorted by stage and score."""
        logger = ComprehensiveLogger()
        python_threshold = self.config.config.get("step3", {}).get("score_threshold", 75.0)
        
        leads = logger.get_all_leads_sorted(python_threshold)
        
        # Create new window
        view_window = tk.Toplevel(self.root)
        view_window.title("All Leads - Sorted by Stage and Score")
        view_window.geometry("1000x700")
        view_window.resizable(True, True)
        
        # Make maximized (windowed fullscreen - keeps title bar and close button)
        view_window.state('zoomed')
        
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
        """Export the current leads view to CSV with sanitized content and failed domains."""
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
                    'Stage': sanitize_for_csv(values[0]),
                    'Python Score': values[1],
                    'AI Score': values[2],
                    'Good Lead': values[3],
                    'URL': sanitize_for_csv(values[4]),
                    'Notes': sanitize_for_csv(values[5]),
                    'Processing Date': datetime.now(timezone.utc).isoformat()
                })
            
            # Add failed domains from files if they exist
            csv_config = self.config.config.get("csv_output", {})
            if csv_config.get("include_failed_domains", True):
                import glob
                failed_files = glob.glob("data/failed_*.csv")
                for f in failed_files:
                    try:
                        fdf = pd.read_csv(f)
                        for _, row in fdf.iterrows():
                            leads_data.append({
                                'Stage': 'FAILED',
                                'Python Score': 'N/A',
                                'AI Score': 'N/A',
                                'Good Lead': 'No',
                                'URL': sanitize_for_csv(row.get('url', '')),
                                'Notes': sanitize_for_csv(row.get('error', 'Unknown error')),
                                'Processing Date': row.get('processing_date', '')
                            })
                    except:
                        pass
            
            # Write to CSV
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                if leads_data:
                    writer = csv.DictWriter(f, fieldnames=leads_data[0].keys())
                    writer.writeheader()
                    writer.writerows(leads_data)
            
            messagebox.showinfo("Success", f"Leads exported to {filename}\n\nIncludes {len(leads_data)} total entries")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export CSV: {str(e)}")
    
    def run(self):
        """Run the GUI application."""
        self.root.mainloop()

# ============================================================
# DEVELOPER OPTIONS GUI
# ============================================================

class DeveloperOptionsGUI:
    """
    Developer Options GUI for managing training data, AI model integration,
    and data collection settings. Only accessible when no run is active.
    """
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Developer Options - Sherpa Lead Generator")
        self.root.geometry("1200x800")
        self.root.state('zoomed')  # Maximize window
        
        self.training_collector = get_training_collector()
        
        self.setup_gui()
        self.refresh_stats()
    
    def setup_gui(self):
        """Setup the developer options interface."""
        # Main container
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill='both', expand=True)
        
        # Title
        title_frame = ttk.Frame(main_frame)
        title_frame.pack(fill='x', pady=(0, 10))
        
        ttk.Label(title_frame, text="🔧 Developer Options", 
                  font=('Arial', 18, 'bold')).pack(side='left')
        
        ttk.Button(title_frame, text="← Back to Main Menu", 
                   command=self.back_to_menu).pack(side='right')
        
        # Create notebook for tabs
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill='both', expand=True)
        
        # Tab 1: Training Data Overview
        self.setup_overview_tab(notebook)
        
        # Tab 2: Data Import
        self.setup_import_tab(notebook)
        
        # Tab 3: Keyword Analysis
        self.setup_keyword_tab(notebook)
        
        # Tab 4: Business Documents
        self.setup_docs_tab(notebook)
        
        # Tab 5: Export & Sync
        self.setup_sync_tab(notebook)
        
        # Tab 6: AI Model Settings
        self.setup_ai_settings_tab(notebook)
        
        # Tab 7: Raw Data Explorer
        self.setup_explorer_tab(notebook)
    
    def setup_overview_tab(self, notebook):
        """Setup Training Data Overview tab."""
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="📊 Overview")
        
        # Stats display
        stats_frame = ttk.LabelFrame(frame, text="Training Data Statistics", padding=10)
        stats_frame.pack(fill='x', pady=5)
        
        # Create grid of stats
        self.stat_labels = {}
        stat_items = [
            ('total_runs', 'Total Runs Tracked'),
            ('total_leads', 'Total Leads Tracked'),
            ('leads_with_feedback', 'Leads with User Feedback'),
            ('user_confirmed_good', 'User Confirmed Good'),
            ('user_confirmed_bad', 'User Confirmed Bad'),
            ('unique_keywords', 'Unique Keywords'),
            ('business_docs', 'Business Documents'),
            ('feedback_imports', 'Feedback Imports')
        ]
        
        for i, (key, label) in enumerate(stat_items):
            row = i // 4
            col = i % 4
            
            item_frame = ttk.Frame(stats_frame)
            item_frame.grid(row=row, column=col, padx=20, pady=10, sticky='w')
            
            ttk.Label(item_frame, text=label, font=('Arial', 9)).pack()
            self.stat_labels[key] = ttk.Label(item_frame, text="--", font=('Arial', 16, 'bold'))
            self.stat_labels[key].pack()
        
        # Last sync info
        sync_frame = ttk.LabelFrame(frame, text="Last GitHub Sync", padding=10)
        sync_frame.pack(fill='x', pady=5)
        
        self.last_sync_label = ttk.Label(sync_frame, text="No sync recorded", font=('Arial', 10))
        self.last_sync_label.pack(anchor='w')
        
        # Top keywords display
        keywords_frame = ttk.LabelFrame(frame, text="Top Performing Keywords (by user feedback)", padding=10)
        keywords_frame.pack(fill='both', expand=True, pady=5)
        
        columns = ('Keyword', 'Good Leads', 'Total Leads', 'Effectiveness %')
        self.top_keywords_tree = ttk.Treeview(keywords_frame, columns=columns, show='headings', height=10)
        
        for col in columns:
            self.top_keywords_tree.heading(col, text=col)
            self.top_keywords_tree.column(col, width=150)
        
        self.top_keywords_tree.pack(fill='both', expand=True)
        
        # Refresh button
        ttk.Button(frame, text="🔄 Refresh Stats", command=self.refresh_stats).pack(pady=10)
    
    def setup_import_tab(self, notebook):
        """Setup Data Import tab."""
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="📥 Import Data")
        
        # CSV Import section
        csv_frame = ttk.LabelFrame(frame, text="Import User Feedback CSV", padding=10)
        csv_frame.pack(fill='x', pady=5)
        
        ttk.Label(csv_frame, text="Import a CSV file with URL and feedback columns.\n"
                  "Expected columns: 'url' (or 'website', 'domain') and 'is_good_lead' (or 'good_lead', 'feedback')\n"
                  "Feedback values: 1/true/yes/good for good leads, 0/false/no/bad for bad leads",
                  font=('Arial', 9)).pack(anchor='w', pady=5)
        
        csv_btn_frame = ttk.Frame(csv_frame)
        csv_btn_frame.pack(fill='x', pady=5)
        
        self.csv_path_var = tk.StringVar()
        ttk.Entry(csv_btn_frame, textvariable=self.csv_path_var, width=80).pack(side='left', padx=(0, 10))
        ttk.Button(csv_btn_frame, text="Browse...", command=self.browse_csv).pack(side='left', padx=5)
        ttk.Button(csv_btn_frame, text="Import CSV", command=self.import_csv).pack(side='left', padx=5)
        
        self.csv_import_status = ttk.Label(csv_frame, text="", font=('Arial', 9))
        self.csv_import_status.pack(anchor='w', pady=5)
        
        # Import history
        history_frame = ttk.LabelFrame(frame, text="Import History", padding=10)
        history_frame.pack(fill='both', expand=True, pady=5)
        
        columns = ('Timestamp', 'Source File', 'Total Rows', 'Matched', 'Good', 'Bad')
        self.import_history_tree = ttk.Treeview(history_frame, columns=columns, show='headings', height=10)
        
        for col in columns:
            self.import_history_tree.heading(col, text=col)
            self.import_history_tree.column(col, width=120)
        
        self.import_history_tree.pack(fill='both', expand=True)
        
        ttk.Button(frame, text="🔄 Refresh History", command=self.refresh_import_history).pack(pady=5)
    
    def setup_keyword_tab(self, notebook):
        """Setup Keyword Analysis tab."""
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="🔑 Keyword Analysis")
        
        # Controls
        control_frame = ttk.Frame(frame)
        control_frame.pack(fill='x', pady=5)
        
        ttk.Button(control_frame, text="🔄 Refresh Analysis", 
                   command=self.refresh_keyword_analysis).pack(side='left', padx=5)
        ttk.Button(control_frame, text="📊 Calculate Correlations", 
                   command=self.show_correlations).pack(side='left', padx=5)
        ttk.Button(control_frame, text="📤 Export Report", 
                   command=self.export_keyword_report).pack(side='left', padx=5)
        
        # Keyword performance table
        table_frame = ttk.LabelFrame(frame, text="Keyword Performance", padding=10)
        table_frame.pack(fill='both', expand=True, pady=5)
        
        columns = ('Keyword', 'Times Used', 'Leads Generated', 'Good Leads', 'Effectiveness %', 'Last Used')
        self.keyword_tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=20)
        
        for col in columns:
            self.keyword_tree.heading(col, text=col)
            self.keyword_tree.column(col, width=120)
        
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.keyword_tree.yview)
        self.keyword_tree.configure(yscrollcommand=scrollbar.set)
        
        self.keyword_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # Correlation display area
        self.correlation_frame = ttk.LabelFrame(frame, text="Correlations", padding=10)
        self.correlation_frame.pack(fill='x', pady=5)
        
        self.correlation_text = tk.Text(self.correlation_frame, height=8, wrap='word')
        self.correlation_text.pack(fill='x')
    
    def setup_docs_tab(self, notebook):
        """Setup Business Documents tab."""
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="📄 Business Docs")
        
        # Upload section
        upload_frame = ttk.LabelFrame(frame, text="Add Business Document", padding=10)
        upload_frame.pack(fill='x', pady=5)
        
        ttk.Label(upload_frame, text="Add meeting notes, company overviews, ICP documents, etc.\n"
                  "Supported formats: .txt, .md",
                  font=('Arial', 9)).pack(anchor='w', pady=5)
        
        upload_btn_frame = ttk.Frame(upload_frame)
        upload_btn_frame.pack(fill='x', pady=5)
        
        self.doc_path_var = tk.StringVar()
        ttk.Entry(upload_btn_frame, textvariable=self.doc_path_var, width=60).pack(side='left', padx=(0, 10))
        ttk.Button(upload_btn_frame, text="Browse...", command=self.browse_doc).pack(side='left', padx=5)
        
        ttk.Label(upload_btn_frame, text="Type:").pack(side='left', padx=(20, 5))
        self.doc_type_var = tk.StringVar(value='general')
        doc_type_combo = ttk.Combobox(upload_btn_frame, textvariable=self.doc_type_var, width=15,
                                       values=['general', 'meeting_notes', 'icp', 'overview', 'market_research', 'competitor'])
        doc_type_combo.pack(side='left', padx=5)
        
        ttk.Button(upload_btn_frame, text="Add Document", command=self.add_document).pack(side='left', padx=20)
        
        self.doc_upload_status = ttk.Label(upload_frame, text="", font=('Arial', 9))
        self.doc_upload_status.pack(anchor='w', pady=5)
        
        # Documents list
        docs_frame = ttk.LabelFrame(frame, text="Stored Documents", padding=10)
        docs_frame.pack(fill='both', expand=True, pady=5)
        
        columns = ('ID', 'Type', 'Filename', 'Upload Date', 'Keywords Found')
        self.docs_tree = ttk.Treeview(docs_frame, columns=columns, show='headings', height=12)
        
        for col in columns:
            self.docs_tree.heading(col, text=col)
        
        self.docs_tree.column('ID', width=50)
        self.docs_tree.column('Type', width=100)
        self.docs_tree.column('Filename', width=200)
        self.docs_tree.column('Upload Date', width=150)
        self.docs_tree.column('Keywords Found', width=300)
        
        self.docs_tree.pack(fill='both', expand=True)
        
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill='x', pady=5)
        ttk.Button(btn_frame, text="🔄 Refresh", command=self.refresh_docs_list).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="👁 View Content", command=self.view_doc_content).pack(side='left', padx=5)
    
    def setup_sync_tab(self, notebook):
        """Setup Export & Sync tab."""
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="☁ Export & Sync")
        
        # GitHub Sync section
        github_frame = ttk.LabelFrame(frame, text="GitHub Synchronization", padding=10)
        github_frame.pack(fill='x', pady=5)
        
        ttk.Label(github_frame, text="Sync training data with GitHub repository.\n"
                  "This allows you to share training data across machines and back up your data.",
                  font=('Arial', 9)).pack(anchor='w', pady=5)
        
        btn_frame = ttk.Frame(github_frame)
        btn_frame.pack(fill='x', pady=10)
        
        ttk.Button(btn_frame, text="⬆ Push to GitHub", 
                   command=self.push_to_github).pack(side='left', padx=10)
        ttk.Button(btn_frame, text="⬇ Pull from GitHub", 
                   command=self.pull_from_github).pack(side='left', padx=10)
        
        self.sync_status = ttk.Label(github_frame, text="", font=('Arial', 10))
        self.sync_status.pack(anchor='w', pady=5)
        
        # Export section
        export_frame = ttk.LabelFrame(frame, text="Export Training Data", padding=10)
        export_frame.pack(fill='x', pady=5)
        
        ttk.Label(export_frame, text="Export all training data to CSV files for ML training or backup.\n"
                  "Exports: leads, keyword performance, search stats, configs, business docs",
                  font=('Arial', 9)).pack(anchor='w', pady=5)
        
        export_btn_frame = ttk.Frame(export_frame)
        export_btn_frame.pack(fill='x', pady=10)
        
        ttk.Button(export_btn_frame, text="📤 Export All Data", 
                   command=self.export_all_data).pack(side='left', padx=10)
        ttk.Button(export_btn_frame, text="📂 Open Export Folder", 
                   command=self.open_export_folder).pack(side='left', padx=10)
        
        self.export_status = ttk.Label(export_frame, text="", font=('Arial', 10))
        self.export_status.pack(anchor='w', pady=5)
        
        # Sync history
        history_frame = ttk.LabelFrame(frame, text="Sync History", padding=10)
        history_frame.pack(fill='both', expand=True, pady=5)
        
        columns = ('Timestamp', 'Type', 'Direction', 'Records', 'Status')
        self.sync_history_tree = ttk.Treeview(history_frame, columns=columns, show='headings', height=8)
        
        for col in columns:
            self.sync_history_tree.heading(col, text=col)
            self.sync_history_tree.column(col, width=150)
        
        self.sync_history_tree.pack(fill='both', expand=True)
    
    def setup_ai_settings_tab(self, notebook):
        """Setup AI Model Settings tab for future AI integration."""
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="🤖 AI Settings")
        
        # Future AI Integration section
        info_frame = ttk.LabelFrame(frame, text="Future AI Model Integration", padding=10)
        info_frame.pack(fill='x', pady=5)
        
        ttk.Label(info_frame, text="This section will allow you to configure and test AI models\n"
                  "trained on your collected data. Features coming soon:\n\n"
                  "• Upload custom fine-tuned models\n"
                  "• Test model predictions on historical data\n"
                  "• A/B test different model configurations\n"
                  "• Automatic configuration suggestions based on past performance",
                  font=('Arial', 10)).pack(anchor='w', pady=10)
        
        # Placeholder settings
        settings_frame = ttk.LabelFrame(frame, text="Model Configuration (Placeholder)", padding=10)
        settings_frame.pack(fill='x', pady=5)
        
        row1 = ttk.Frame(settings_frame)
        row1.pack(fill='x', pady=5)
        
        ttk.Label(row1, text="Model Provider:").pack(side='left', padx=5)
        self.ai_provider_var = tk.StringVar(value='none')
        provider_combo = ttk.Combobox(row1, textvariable=self.ai_provider_var, width=20,
                                       values=['none', 'openai_finetune', 'anthropic_finetune', 'local_llama', 'custom'])
        provider_combo.pack(side='left', padx=5)
        provider_combo.configure(state='disabled')
        
        ttk.Label(row1, text="(Coming Soon)").pack(side='left', padx=10)
        
        row2 = ttk.Frame(settings_frame)
        row2.pack(fill='x', pady=5)
        
        ttk.Label(row2, text="Custom Model Path:").pack(side='left', padx=5)
        self.custom_model_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.custom_model_var, width=50, state='disabled').pack(side='left', padx=5)
        ttk.Button(row2, text="Browse...", state='disabled').pack(side='left', padx=5)
        
        # Training data readiness
        readiness_frame = ttk.LabelFrame(frame, text="Training Data Readiness", padding=10)
        readiness_frame.pack(fill='x', pady=5)
        
        self.readiness_labels = {}
        readiness_items = [
            ('leads_ready', 'Leads with AI scores', 50, 'Minimum 50 leads with AI analysis'),
            ('feedback_ready', 'User feedback entries', 20, 'Minimum 20 user feedback entries'),
            ('keywords_ready', 'Tracked keywords', 10, 'Minimum 10 keywords with performance data'),
            ('docs_ready', 'Business documents', 1, 'At least 1 business document for context')
        ]
        
        for key, label, threshold, desc in readiness_items:
            item_frame = ttk.Frame(readiness_frame)
            item_frame.pack(fill='x', pady=3)
            
            self.readiness_labels[key] = ttk.Label(item_frame, text="⏳", font=('Arial', 12))
            self.readiness_labels[key].pack(side='left', padx=5)
            
            ttk.Label(item_frame, text=f"{label}: ", font=('Arial', 10, 'bold')).pack(side='left')
            ttk.Label(item_frame, text=desc, font=('Arial', 9)).pack(side='left', padx=10)
        
        ttk.Button(frame, text="🔄 Check Readiness", command=self.check_readiness).pack(pady=10)
    
    def setup_explorer_tab(self, notebook):
        """Setup Raw Data Explorer tab."""
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="🔍 Data Explorer")
        
        # Table selector
        selector_frame = ttk.Frame(frame)
        selector_frame.pack(fill='x', pady=5)
        
        ttk.Label(selector_frame, text="Select Table:").pack(side='left', padx=5)
        self.table_var = tk.StringVar(value='lead_outcomes')
        table_combo = ttk.Combobox(selector_frame, textvariable=self.table_var, width=25,
                                    values=['lead_outcomes', 'keyword_performance', 'search_term_stats',
                                            'run_configs', 'business_docs', 'feedback_imports', 'sync_history'])
        table_combo.pack(side='left', padx=5)
        table_combo.bind('<<ComboboxSelected>>', lambda e: self.load_table_data())
        
        ttk.Button(selector_frame, text="🔄 Load", command=self.load_table_data).pack(side='left', padx=10)
        
        # Row limit
        ttk.Label(selector_frame, text="Limit:").pack(side='left', padx=(20, 5))
        self.limit_var = tk.StringVar(value='100')
        ttk.Entry(selector_frame, textvariable=self.limit_var, width=8).pack(side='left', padx=5)
        
        # Data display
        data_frame = ttk.Frame(frame)
        data_frame.pack(fill='both', expand=True, pady=5)
        
        self.data_tree = ttk.Treeview(data_frame, show='headings', height=25)
        
        h_scrollbar = ttk.Scrollbar(data_frame, orient='horizontal', command=self.data_tree.xview)
        v_scrollbar = ttk.Scrollbar(data_frame, orient='vertical', command=self.data_tree.yview)
        self.data_tree.configure(xscrollcommand=h_scrollbar.set, yscrollcommand=v_scrollbar.set)
        
        self.data_tree.pack(side='left', fill='both', expand=True)
        v_scrollbar.pack(side='right', fill='y')
        h_scrollbar.pack(side='bottom', fill='x')
        
        # Status
        self.explorer_status = ttk.Label(frame, text="", font=('Arial', 9))
        self.explorer_status.pack(anchor='w', pady=5)
    
    # ==================== Action Methods ====================
    
    def refresh_stats(self):
        """Refresh all statistics."""
        try:
            stats = self.training_collector.get_training_stats()
            
            # Update stat labels
            for key, label in self.stat_labels.items():
                value = stats.get(key, 0)
                label.configure(text=str(value))
            
            # Update last sync
            last_sync = stats.get('last_sync', {})
            if last_sync.get('timestamp'):
                sync_text = f"{last_sync['direction']} ({last_sync['type']}) - {last_sync['timestamp'][:19]} - {last_sync['status']}"
            else:
                sync_text = "No sync recorded"
            self.last_sync_label.configure(text=sync_text)
            
            # Update top keywords
            for item in self.top_keywords_tree.get_children():
                self.top_keywords_tree.delete(item)
            
            for kw in stats.get('top_keywords', []):
                self.top_keywords_tree.insert('', 'end', values=(
                    kw['keyword'],
                    kw['good'],
                    kw['total'],
                    f"{kw['rate']*100:.1f}%"
                ))
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh stats: {str(e)}")
    
    def browse_csv(self):
        """Browse for CSV file."""
        filepath = filedialog.askopenfilename(
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if filepath:
            self.csv_path_var.set(filepath)
    
    def import_csv(self):
        """Import user feedback CSV."""
        filepath = self.csv_path_var.get()
        if not filepath:
            messagebox.showwarning("Warning", "Please select a CSV file first.")
            return
        
        result = self.training_collector.import_user_feedback_csv(filepath)
        
        if result.get('success'):
            status = f"✅ Imported: {result['total_rows']} rows, {result['matched_urls']} matched, {result['good_leads']} good, {result['bad_leads']} bad"
            self.csv_import_status.configure(text=status, foreground='green')
            self.refresh_stats()
            self.refresh_import_history()
            
            # Auto-sync to GitHub
            self.auto_sync_github("csv_import")
        else:
            self.csv_import_status.configure(text=f"❌ Error: {result.get('error')}", foreground='red')
    
    def refresh_import_history(self):
        """Refresh import history table."""
        for item in self.import_history_tree.get_children():
            self.import_history_tree.delete(item)
        
        try:
            conn = sqlite3.connect(self.training_collector.db_path)
            cursor = conn.execute("""
                SELECT import_timestamp, source_file, total_rows, matched_urls, 
                       good_leads_count, bad_leads_count
                FROM feedback_imports
                ORDER BY import_timestamp DESC
                LIMIT 50
            """)
            
            for row in cursor.fetchall():
                self.import_history_tree.insert('', 'end', values=row)
            
            conn.close()
        except Exception as e:
            print(f"Error refreshing import history: {e}")
    
    def refresh_keyword_analysis(self):
        """Refresh keyword analysis table."""
        for item in self.keyword_tree.get_children():
            self.keyword_tree.delete(item)
        
        try:
            df = self.training_collector.get_keyword_effectiveness_report()
            
            for _, row in df.iterrows():
                self.keyword_tree.insert('', 'end', values=(
                    row['keyword'],
                    row['times_used'],
                    row['leads_generated'],
                    row['good_leads_generated'],
                    f"{row['effectiveness_pct']:.1f}%",
                    row['last_used'][:10] if row['last_used'] else ''
                ))
        except Exception as e:
            print(f"Error refreshing keyword analysis: {e}")
    
    def show_correlations(self):
        """Show search term correlations."""
        try:
            result = self.training_collector.calculate_search_term_correlations()
            
            self.correlation_text.delete('1.0', 'end')
            
            text = f"Analyzed {result['total_keywords_analyzed']} keywords\n"
            text += f"Keywords with user feedback: {result['keywords_with_feedback']}\n\n"
            text += "Top correlated keywords (by user feedback):\n"
            
            for i, item in enumerate(result['correlations'][:10]):
                if item['user_feedback_count'] > 0:
                    text += f"  {i+1}. {item['keyword']}: {item['user_good_rate']*100:.0f}% good ({item['user_feedback_count']} feedback)\n"
            
            self.correlation_text.insert('1.0', text)
        except Exception as e:
            self.correlation_text.delete('1.0', 'end')
            self.correlation_text.insert('1.0', f"Error: {str(e)}")
    
    def export_keyword_report(self):
        """Export keyword report to CSV."""
        try:
            df = self.training_collector.get_keyword_effectiveness_report()
            
            filepath = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv")],
                initialfile=f"keyword_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )
            
            if filepath:
                df.to_csv(filepath, index=False)
                messagebox.showinfo("Success", f"Report exported to: {filepath}")
        except Exception as e:
            messagebox.showerror("Error", f"Export failed: {str(e)}")
    
    def browse_doc(self):
        """Browse for document file."""
        filepath = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("Markdown files", "*.md"), ("All files", "*.*")]
        )
        if filepath:
            self.doc_path_var.set(filepath)
    
    def add_document(self):
        """Add a business document."""
        filepath = self.doc_path_var.get()
        if not filepath:
            messagebox.showwarning("Warning", "Please select a document first.")
            return
        
        result = self.training_collector.add_business_doc(
            filepath, 
            doc_type=self.doc_type_var.get()
        )
        
        if result.get('success'):
            status = f"✅ Added: {result['filename']} ({result['keywords_count']} keywords extracted)"
            self.doc_upload_status.configure(text=status, foreground='green')
            self.refresh_docs_list()
            self.refresh_stats()
            
            # Auto-sync to GitHub
            self.auto_sync_github("doc_upload")
        else:
            self.doc_upload_status.configure(text=f"❌ Error: {result.get('error')}", foreground='red')
    
    def refresh_docs_list(self):
        """Refresh documents list."""
        for item in self.docs_tree.get_children():
            self.docs_tree.delete(item)
        
        try:
            conn = sqlite3.connect(self.training_collector.db_path)
            cursor = conn.execute("""
                SELECT id, doc_type, filename, upload_timestamp, keywords_extracted
                FROM business_docs
                ORDER BY upload_timestamp DESC
            """)
            
            for row in cursor.fetchall():
                keywords_preview = row[4][:50] + '...' if row[4] and len(row[4]) > 50 else row[4]
                self.docs_tree.insert('', 'end', values=(
                    row[0], row[1], row[2], row[3][:19] if row[3] else '', keywords_preview
                ))
            
            conn.close()
        except Exception as e:
            print(f"Error refreshing docs list: {e}")
    
    def view_doc_content(self):
        """View selected document content."""
        selection = self.docs_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a document first.")
            return
        
        doc_id = self.docs_tree.item(selection[0], 'values')[0]
        
        try:
            conn = sqlite3.connect(self.training_collector.db_path)
            cursor = conn.execute("SELECT filename, content FROM business_docs WHERE id = ?", (doc_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                # Create popup window
                popup = tk.Toplevel(self.root)
                popup.title(f"Document: {row[0]}")
                popup.geometry("800x600")
                popup.resizable(True, True)
                popup.state('zoomed')  # Windowed fullscreen
                
                text = tk.Text(popup, wrap='word')
                text.pack(fill='both', expand=True)
                text.insert('1.0', row[1])
                text.configure(state='disabled')
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load document: {str(e)}")
    
    def push_to_github(self):
        """Push training data to GitHub."""
        self.sync_status.configure(text="⏳ Pushing to GitHub...")
        self.root.update()
        
        success, message = git_push_training_data()
        
        if success:
            self.sync_status.configure(text=f"✅ {message}", foreground='green')
            self.training_collector.log_sync('training_data', 'push', [], 0, 'success')
        else:
            self.sync_status.configure(text=f"❌ {message}", foreground='red')
            self.training_collector.log_sync('training_data', 'push', [], 0, 'failed', message)
        
        self.refresh_sync_history()
    
    def pull_from_github(self):
        """Pull training data from GitHub."""
        self.sync_status.configure(text="⏳ Pulling from GitHub...")
        self.root.update()
        
        success, message = git_pull_training_data()
        
        if success:
            self.sync_status.configure(text=f"✅ {message}", foreground='green')
            self.training_collector.log_sync('training_data', 'pull', [], 0, 'success')
        else:
            self.sync_status.configure(text=f"❌ {message}", foreground='red')
            self.training_collector.log_sync('training_data', 'pull', [], 0, 'failed', message)
        
        self.refresh_sync_history()
        self.refresh_stats()
    
    def auto_sync_github(self, trigger: str):
        """Automatically sync to GitHub after certain actions."""
        try:
            success, message = git_push_training_data()
            if success:
                self.training_collector.log_sync(trigger, 'push', [], 0, 'success')
            # Don't show errors for auto-sync, just log them
        except:
            pass
    
    def refresh_sync_history(self):
        """Refresh sync history table."""
        for item in self.sync_history_tree.get_children():
            self.sync_history_tree.delete(item)
        
        try:
            conn = sqlite3.connect(self.training_collector.db_path)
            cursor = conn.execute("""
                SELECT timestamp, sync_type, direction, records_count, status
                FROM sync_history
                ORDER BY timestamp DESC
                LIMIT 20
            """)
            
            for row in cursor.fetchall():
                self.sync_history_tree.insert('', 'end', values=row)
            
            conn.close()
        except Exception as e:
            print(f"Error refreshing sync history: {e}")
    
    def export_all_data(self):
        """Export all training data."""
        self.export_status.configure(text="⏳ Exporting...")
        self.root.update()
        
        result = self.training_collector.export_for_training()
        
        if result.get('success'):
            files = result.get('files', [])
            self.export_status.configure(
                text=f"✅ Exported {len(files)} files to training_data/exports/",
                foreground='green'
            )
            
            # Auto-sync
            self.auto_sync_github("export")
        else:
            self.export_status.configure(
                text=f"❌ Export failed: {result.get('error')}",
                foreground='red'
            )
    
    def open_export_folder(self):
        """Open export folder in file explorer."""
        export_path = os.path.abspath(self.training_collector.exports_dir)
        os.makedirs(export_path, exist_ok=True)
        
        if sys.platform == 'win32':
            os.startfile(export_path)
        elif sys.platform == 'darwin':
            subprocess.run(['open', export_path])
        else:
            subprocess.run(['xdg-open', export_path])
    
    def check_readiness(self):
        """Check training data readiness."""
        stats = self.training_collector.get_training_stats()
        
        thresholds = {
            'leads_ready': (stats.get('total_leads', 0), 50),
            'feedback_ready': (stats.get('leads_with_feedback', 0), 20),
            'keywords_ready': (stats.get('unique_keywords', 0), 10),
            'docs_ready': (stats.get('business_docs', 0), 1)
        }
        
        for key, (value, threshold) in thresholds.items():
            if value >= threshold:
                self.readiness_labels[key].configure(text="✅", foreground='green')
            else:
                self.readiness_labels[key].configure(text=f"❌ ({value}/{threshold})", foreground='red')
    
    def load_table_data(self):
        """Load data from selected table."""
        table = self.table_var.get()
        limit = int(self.limit_var.get() or 100)
        
        # Clear existing data
        self.data_tree.delete(*self.data_tree.get_children())
        
        try:
            conn = sqlite3.connect(self.training_collector.db_path)
            
            # Get column names
            cursor = conn.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cursor.fetchall()]
            
            # Configure treeview columns
            self.data_tree['columns'] = columns
            for col in columns:
                self.data_tree.heading(col, text=col)
                self.data_tree.column(col, width=100, minwidth=50)
            
            # Get data
            cursor = conn.execute(f"SELECT * FROM {table} LIMIT ?", (limit,))
            rows = cursor.fetchall()
            
            for row in rows:
                # Truncate long values for display
                display_row = []
                for val in row:
                    if val is None:
                        display_row.append('')
                    elif isinstance(val, str) and len(val) > 50:
                        display_row.append(val[:50] + '...')
                    else:
                        display_row.append(str(val))
                self.data_tree.insert('', 'end', values=display_row)
            
            conn.close()
            self.explorer_status.configure(text=f"Loaded {len(rows)} rows from {table}")
            
        except Exception as e:
            self.explorer_status.configure(text=f"Error: {str(e)}")
    
    def back_to_menu(self):
        """Go back to main menu."""
        self.root.destroy()
        app = InitialPopupGUI()
        app.run()
    
    def run(self):
        """Run the developer options GUI."""
        self.root.mainloop()


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def main():
    """Main entry point for the Sherpa Lead Generator application."""
    import traceback
    
    print("Sherpa Lead Generator")
    print("=" * 40)
    print("Starting GUI application...")
    
    try:
        app = InitialPopupGUI()
        print("GUI initialized successfully. Window should be visible.")
        app.run()
    except KeyboardInterrupt:
        print("\nApplication interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nERROR: Failed to start application!")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        print("\nFull traceback:")
        traceback.print_exc()
        
        # Try to show error in a message box if tkinter is available
        try:
            root = tk.Tk()
            root.withdraw()  # Hide main window
            messagebox.showerror("Startup Error", 
                               f"Failed to start application:\n\n{str(e)}\n\nCheck console for details.")
            root.destroy()
        except:
            pass
        
        input("\nPress Enter to exit...")
        sys.exit(1)

if __name__ == "__main__":
    main()
