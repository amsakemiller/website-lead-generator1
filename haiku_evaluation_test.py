#!/usr/bin/env python3
"""
Haiku 3.5 Evaluation Test Script
================================
Scrapes 15 biomedical company websites and evaluates Claude Haiku 3.5's analysis quality.
"""

import asyncio
import aiohttp
from aiohttp import ClientSession, ClientTimeout
import json
import re
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time

# Try to import trafilatura for better text extraction
try:
    import trafilatura
except ImportError:
    trafilatura = None

# API Configuration - reads from unified_config.json or environment variable
def get_api_key():
    """Get API key from config file or environment."""
    config_path = "unified_config.json"
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = json.load(f)
            return config.get("step4", {}).get("api_key", "")
    return os.environ.get("ANTHROPIC_API_KEY", "")

ANTHROPIC_API_KEY = get_api_key()
HAIKU_MODEL = "claude-3-5-haiku-20241022"

# Target websites to evaluate
TARGET_WEBSITES = [
    ("J&J/Janssen", "https://www.jnj.com"),
    ("Guerbet", "https://usa.guerbet.com"),
    ("ABK Biomedical", "https://abkbiomedical.com"),
    ("BD", "https://www.bd.com"),
    ("Earli", "https://www.earli.com"),
    ("TriSalus", "https://trisaluslifesci.com"),
    ("Aura Biosciences", "https://www.aurabiosciences.com"),
    ("BetaGlue", "https://betaglue.com"),
    ("Boston Scientific", "https://www.bostonscientific.com"),
    ("Mirai Medical", "https://mirai-medical.com"),
    ("Prana Thoracic", "https://www.pranasurgical.com"),
    ("Stryker", "https://www.stryker.com"),
    ("Rakuten Medical", "https://rakuten-med.com/us"),
    ("ImCheck Therap.", "https://www.imchecktherapeutics.com"),
    ("EngageBio", "https://www.engagebio.com"),
]

# Scoring fields configuration (same as in unified_leadgen.py)
SCORING_FIELDS = [
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
]


class WebsiteScraper:
    """Scrapes website content for analysis."""
    
    def __init__(self):
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
    def extract_text(self, html: str, url: str) -> str:
        """Extract clean text from HTML."""
        if trafilatura:
            try:
                txt = trafilatura.extract(html, url=url, include_comments=False, include_tables=False) or ""
                txt = re.sub(r"\s+", " ", txt).strip()
                return txt
            except Exception:
                pass
        
        soup = BeautifulSoup(html, "html.parser")
        for bad in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
            bad.decompose()
        text = soup.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text).strip()
        return text
    
    def discover_links(self, base_url: str, html: str, max_links: int = 20) -> List[str]:
        """Discover internal links for crawling."""
        soup = BeautifulSoup(html, "html.parser")
        links = set()
        base_domain = urlparse(base_url).netloc.lower()
        
        priority_keywords = ["about", "product", "solution", "technology", "pipeline", "research", 
                           "innovation", "platform", "therapeutics", "therapy", "treatment",
                           "team", "leadership", "investors", "funding", "news", "press"]
        
        scored_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            
            abs_url = urljoin(base_url, href)
            parsed = urlparse(abs_url)
            
            # Only follow same-domain links
            if parsed.netloc.lower() != base_domain:
                continue
            
            # Clean URL
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if clean_url in links:
                continue
            
            links.add(clean_url)
            
            # Score by priority keywords
            path_lower = parsed.path.lower()
            score = sum(1 for kw in priority_keywords if kw in path_lower)
            scored_links.append((score, clean_url))
        
        # Sort by score and return top links
        scored_links.sort(key=lambda x: x[0], reverse=True)
        return [url for _, url in scored_links[:max_links]]
    
    async def fetch_page(self, session: ClientSession, url: str) -> Optional[str]:
        """Fetch a single page."""
        try:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status == 200:
                    ct = resp.headers.get("Content-Type", "")
                    if "text/html" in ct or "application/xhtml" in ct:
                        return await resp.text(errors="ignore")
        except Exception as e:
            print(f"  Error fetching {url}: {e}")
        return None
    
    async def scrape_website(self, name: str, url: str, max_pages: int = 5) -> Dict[str, Any]:
        """Scrape a website and return aggregated content."""
        print(f"\n{'='*60}")
        print(f"Scraping: {name} ({url})")
        print(f"{'='*60}")
        
        timeout = ClientTimeout(total=30)
        headers = {"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
        
        all_text = []
        pages_scraped = 0
        
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            # Fetch main page
            html = await self.fetch_page(session, url)
            if html:
                text = self.extract_text(html, url)
                if text:
                    all_text.append(text[:15000])
                    pages_scraped += 1
                    print(f"  [OK] Main page: {len(text)} chars")
                
                # Discover and crawl additional pages
                links = self.discover_links(url, html, max_links=max_pages * 2)
                for link in links[:max_pages - 1]:
                    await asyncio.sleep(0.3)  # Be polite
                    sub_html = await self.fetch_page(session, link)
                    if sub_html:
                        sub_text = self.extract_text(sub_html, link)
                        if sub_text and len(sub_text) > 200:
                            all_text.append(sub_text[:10000])
                            pages_scraped += 1
                            print(f"  [OK] {link.split('/')[-1] or 'subpage'}: {len(sub_text)} chars")
            
        # Aggregate content
        aggregated = " ".join(all_text)[:50000]  # Cap at 50k chars
        
        result = {
            "name": name,
            "url": url,
            "pages_scraped": pages_scraped,
            "content_length": len(aggregated),
            "content": aggregated,
            "scraped_at": datetime.now().isoformat()
        }
        
        print(f"  Total: {pages_scraped} pages, {len(aggregated)} chars")
        return result


class HaikuAnalyzer:
    """Analyzes scraped content using Claude Haiku 3.5."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = HAIKU_MODEL
        
    def build_prompt(self, url: str, content: str) -> str:
        """Build the analysis prompt."""
        field_instructions = []
        json_fields = []
        
        for field in SCORING_FIELDS:
            if not field.get("enabled"):
                continue
                
            title = field.get("title", "")
            prompt = field.get("prompt", "")
            field_type = field.get("type", "score")
            
            # Create safe key
            key = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')
            
            if field_type == "score":
                min_val = field.get("min", 0)
                max_val = field.get("max", 10)
                field_instructions.append(f"""
=== {title} (Score: {min_val}-{max_val}) ===
{prompt}
""")
                json_fields.append(f'    "{key}": <integer {min_val}-{max_val}>')
            else:
                options = field.get("options", [])
                allow_multiple = field.get("allow_multiple", False)
                options_text = f"\nAvailable options: {', '.join(options)}"
                if allow_multiple:
                    options_text += "\nMultiple selections allowed - separate with ';'"
                
                field_instructions.append(f"""
=== {title} (Text Selection) ===
{prompt}{options_text}
""")
                json_fields.append(f'    "{key}": "<selected option(s)>"')
        
        prompt = f"""You are an expert business analyst specializing in identifying high-quality B2B leads in the healthcare, medical device, and pharmaceutical industries.

Analyze the following website and provide scores/classifications for each field below.

{"".join(field_instructions)}

Website URL: {url}
Website Content: {content[:12000]}

Please provide your analysis in the following JSON format:
{{
{chr(10).join(json_fields)},
    "company_description": "<brief 1-2 sentence company description>",
    "reasoning": "<detailed explanation of your overall assessment>",
    "key_indicators": "<semicolon-separated list of positive indicators>",
    "red_flags": "<semicolon-separated list of any concerns>"
}}

IMPORTANT: Use ';' instead of commas in all text fields to separate multiple items.
"""
        return prompt
    
    async def analyze(self, name: str, url: str, content: str) -> Dict[str, Any]:
        """Analyze a website using Claude Haiku 3.5."""
        print(f"\nAnalyzing with Haiku 3.5: {name}...")
        
        prompt = self.build_prompt(url, content)
        
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }
        
        payload = {
            "model": self.model,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}]
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                    timeout=ClientTimeout(total=60)
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        content_text = result['content'][0]['text']
                        
                        # Extract JSON from response
                        start_idx = content_text.find('{')
                        end_idx = content_text.rfind('}') + 1
                        if start_idx != -1 and end_idx > start_idx:
                            json_str = content_text[start_idx:end_idx]
                            analysis = json.loads(json_str)
                            analysis['name'] = name
                            analysis['url'] = url
                            analysis['model'] = self.model
                            analysis['analyzed_at'] = datetime.now().isoformat()
                            print(f"  [OK] Analysis complete")
                            return analysis
                        else:
                            print(f"  [FAIL] Could not extract JSON from response")
                            return {"name": name, "url": url, "error": "No JSON in response", "raw": content_text}
                    else:
                        error_text = await resp.text()
                        print(f"  [FAIL] API Error {resp.status}: {error_text[:200]}")
                        return {"name": name, "url": url, "error": f"HTTP {resp.status}", "details": error_text[:500]}
        except Exception as e:
            print(f"  [FAIL] Exception: {e}")
            return {"name": name, "url": url, "error": str(e)}


async def main():
    """Main evaluation function."""
    print("="*80)
    print("HAIKU 3.5 EVALUATION TEST")
    print("="*80)
    print(f"Model: {HAIKU_MODEL}")
    print(f"Websites to test: {len(TARGET_WEBSITES)}")
    print()
    
    # Create output directory
    os.makedirs("evaluation_results", exist_ok=True)
    
    # Initialize components
    scraper = WebsiteScraper()
    analyzer = HaikuAnalyzer(ANTHROPIC_API_KEY)
    
    # Scrape all websites
    print("\n" + "="*80)
    print("PHASE 1: SCRAPING WEBSITES")
    print("="*80)
    
    scraped_data = []
    for name, url in TARGET_WEBSITES:
        result = await scraper.scrape_website(name, url, max_pages=5)
        scraped_data.append(result)
        await asyncio.sleep(1)  # Rate limiting between sites
    
    # Save scraped content
    scraped_file = f"evaluation_results/scraped_content_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(scraped_file, 'w', encoding='utf-8') as f:
        # Save without full content for readability
        summary = [{k: v for k, v in item.items() if k != 'content'} for item in scraped_data]
        json.dump(summary, f, indent=2)
    print(f"\nScraped data summary saved to: {scraped_file}")
    
    # Analyze with Haiku 3.5
    print("\n" + "="*80)
    print("PHASE 2: ANALYZING WITH CLAUDE HAIKU 3.5")
    print("="*80)
    
    haiku_results = []
    for data in scraped_data:
        if data.get("content"):
            result = await analyzer.analyze(data["name"], data["url"], data["content"])
            haiku_results.append(result)
            await asyncio.sleep(1)  # Rate limiting between API calls
        else:
            haiku_results.append({"name": data["name"], "url": data["url"], "error": "No content scraped"})
    
    # Save Haiku results
    haiku_file = f"evaluation_results/haiku_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(haiku_file, 'w', encoding='utf-8') as f:
        json.dump(haiku_results, f, indent=2)
    print(f"\nHaiku analysis saved to: {haiku_file}")
    
    # Print summary table
    print("\n" + "="*80)
    print("HAIKU 3.5 ANALYSIS RESULTS SUMMARY")
    print("="*80)
    print(f"\n{'Company':<25} {'US':<4} {'Fund':<5} {'Stage':<6} {'Preclin':<8} {'Overall':<8} {'Type'}")
    print("-"*100)
    
    for result in haiku_results:
        if "error" in result:
            print(f"{result.get('name', 'Unknown'):<25} ERROR: {result.get('error', '')[:50]}")
        else:
            name = result.get('name', 'Unknown')[:24]
            us = result.get('us_based', 'N/A')
            fund = result.get('well_funded', 'N/A')
            stage = result.get('development_stage', 'N/A')
            preclin = result.get('preclinical_fit', 'N/A')
            overall = result.get('overall_score', 'N/A')
            btype = str(result.get('business_type', 'N/A'))[:30]
            print(f"{name:<25} {us:<4} {fund:<5} {stage:<6} {preclin:<8} {overall:<8} {btype}")
    
    # Save content for manual review
    print("\n" + "="*80)
    print("SAVING CONTENT FOR MANUAL REVIEW")
    print("="*80)
    
    review_file = f"evaluation_results/content_for_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(review_file, 'w', encoding='utf-8') as f:
        for data, haiku in zip(scraped_data, haiku_results):
            f.write("="*100 + "\n")
            f.write(f"COMPANY: {data['name']}\n")
            f.write(f"URL: {data['url']}\n")
            f.write(f"Pages Scraped: {data.get('pages_scraped', 0)}\n")
            f.write(f"Content Length: {data.get('content_length', 0)} chars\n")
            f.write("="*100 + "\n\n")
            
            f.write("--- HAIKU 3.5 ANALYSIS ---\n")
            if "error" not in haiku:
                f.write(f"US-Based: {haiku.get('us_based', 'N/A')}\n")
                f.write(f"Well-Funded: {haiku.get('well_funded', 'N/A')}\n")
                f.write(f"Business Type: {haiku.get('business_type', 'N/A')}\n")
                f.write(f"Target Organ/System: {haiku.get('target_organ_system', 'N/A')}\n")
                f.write(f"Development Stage: {haiku.get('development_stage', 'N/A')}\n")
                f.write(f"Therapeutic Focus: {haiku.get('therapeutic_focus', 'N/A')}\n")
                f.write(f"Preclinical Fit: {haiku.get('preclinical_fit', 'N/A')}\n")
                f.write(f"Overall Score: {haiku.get('overall_score', 'N/A')}\n")
                f.write(f"\nDescription: {haiku.get('company_description', 'N/A')}\n")
                f.write(f"\nReasoning: {haiku.get('reasoning', 'N/A')}\n")
                f.write(f"\nKey Indicators: {haiku.get('key_indicators', 'N/A')}\n")
                f.write(f"\nRed Flags: {haiku.get('red_flags', 'N/A')}\n")
            else:
                f.write(f"ERROR: {haiku.get('error', 'Unknown')}\n")
            
            f.write("\n--- SCRAPED CONTENT (First 8000 chars) ---\n")
            content = data.get('content', '')[:8000]
            f.write(content + "\n" if content else "(No content)\n")
            f.write("\n\n")
    
    print(f"Review file saved to: {review_file}")
    
    print("\n" + "="*80)
    print("EVALUATION COMPLETE!")
    print("="*80)
    print(f"\nFiles generated:")
    print(f"  1. {scraped_file}")
    print(f"  2. {haiku_file}")
    print(f"  3. {review_file}")
    print("\nNext steps:")
    print("  1. Review the scraped content in the review file")
    print("  2. Assign your own scores for comparison")
    print("  3. Evaluate Haiku 3.5's accuracy")
    
    return haiku_results, scraped_data


if __name__ == "__main__":
    results = asyncio.run(main())
