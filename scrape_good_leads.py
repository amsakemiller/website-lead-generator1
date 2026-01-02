#!/usr/bin/env python3
"""
Scrape all 15 good leads to analyze content and extract keywords.
"""

import asyncio
import aiohttp
from aiohttp import ClientSession, ClientTimeout
import re
import json
import os
from datetime import datetime
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from collections import Counter

try:
    import trafilatura
except ImportError:
    trafilatura = None

# All 15 good leads
GOOD_LEADS = [
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


class GoodLeadsScraper:
    def __init__(self):
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        
    def extract_text(self, html: str, url: str) -> str:
        if trafilatura:
            try:
                txt = trafilatura.extract(html, url=url, include_comments=False, include_tables=False) or ""
                return re.sub(r"\s+", " ", txt).strip()
            except:
                pass
        soup = BeautifulSoup(html, "html.parser")
        for bad in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            bad.decompose()
        return re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()
    
    def discover_links(self, base_url: str, html: str, max_links: int = 15) -> list:
        soup = BeautifulSoup(html, "html.parser")
        base_domain = urlparse(base_url).netloc.lower()
        priority_keywords = ["about", "product", "solution", "technology", "pipeline", "research", 
                           "innovation", "platform", "therapeutic", "therapy", "treatment",
                           "science", "oncology", "cancer", "device", "clinical", "preclinical"]
        
        scored_links = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            abs_url = urljoin(base_url, href)
            parsed = urlparse(abs_url)
            if parsed.netloc.lower() != base_domain:
                continue
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
            if clean_url in seen:
                continue
            seen.add(clean_url)
            path_lower = parsed.path.lower()
            score = sum(1 for kw in priority_keywords if kw in path_lower)
            scored_links.append((score, clean_url))
        
        scored_links.sort(key=lambda x: x[0], reverse=True)
        return [url for _, url in scored_links[:max_links]]
    
    async def fetch_page(self, session: ClientSession, url: str) -> str:
        try:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status == 200:
                    ct = resp.headers.get("Content-Type", "")
                    if "text/html" in ct or "application/xhtml" in ct:
                        return await resp.text(errors="ignore")
        except Exception as e:
            print(f"    Error: {url} - {e}")
        return None
    
    async def scrape_website(self, name: str, url: str, max_pages: int = 8) -> dict:
        print(f"\n[{name}] Scraping {url}...")
        
        timeout = ClientTimeout(total=25)
        headers = {"User-Agent": self.user_agent}
        
        all_text = []
        pages_scraped = 0
        
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            html = await self.fetch_page(session, url)
            if html:
                text = self.extract_text(html, url)
                if text and len(text) > 100:
                    all_text.append(text[:20000])
                    pages_scraped += 1
                    print(f"    Main page: {len(text)} chars")
                
                links = self.discover_links(url, html, max_links=max_pages * 2)
                for link in links[:max_pages - 1]:
                    await asyncio.sleep(0.2)
                    sub_html = await self.fetch_page(session, link)
                    if sub_html:
                        sub_text = self.extract_text(sub_html, link)
                        if sub_text and len(sub_text) > 200:
                            all_text.append(sub_text[:15000])
                            pages_scraped += 1
        
        aggregated = " ".join(all_text)[:80000]
        
        result = {
            "name": name,
            "url": url,
            "domain": urlparse(url).netloc,
            "pages_scraped": pages_scraped,
            "content_length": len(aggregated),
            "content": aggregated,
            "scraped_at": datetime.now().isoformat()
        }
        
        print(f"    Total: {pages_scraped} pages, {len(aggregated)} chars")
        return result


def extract_keywords_from_content(scraped_data: list) -> dict:
    """Extract relevant keywords from all scraped content for factor scoring."""
    
    # Target keywords to look for (based on user criteria)
    target_organs = ["bile", "biliary", "bladder", "brain", "glioma", "colorectal", "colon", 
                    "kidney", "renal", "liver", "hepatic", "lung", "pulmonary", "pancreas", 
                    "pancreatic", "soft tissue", "sarcoma"]
    
    cancer_terms = ["oncology", "cancer", "tumor", "tumour", "malignant", "carcinoma", 
                   "neoplasm", "metastatic", "solid tumor", "ablation", "interventional"]
    
    device_terms = ["medical device", "device", "catheter", "implant", "ablation", 
                   "interventional", "minimally invasive", "endoscopic", "drug delivery",
                   "microsphere", "radiofrequency", "rf ablation", "microwave", "ultrasound",
                   "thermal", "cryoablation", "embolization", "electroporation"]
    
    stage_terms = ["preclinical", "pre-clinical", "translational", "early stage", 
                  "r&d", "research and development", "proof of concept", "animal study",
                  "in vivo", "in vitro", "laboratory", "bench"]
    
    funding_terms = ["series a", "series b", "series c", "funding", "raised", "investment",
                    "venture", "grant", "nih", "sbir", "sttr", "cprit", "capital"]
    
    us_terms = ["usa", "united states", "us-based", "us headquarters", "boston", "san francisco",
               "new york", "california", "texas", "massachusetts", "pennsylvania", "new jersey",
               "chicago", "houston", "philadelphia", "austin", "denver", "seattle", "miami"]
    
    # Negative indicators (not ideal leads)
    negative_terms = ["phase iii", "phase 3", "fda approved", "fda-approved", "cleared", 
                     "on market", "commercial", "fortune 500", "listed company", 
                     "bone marrow", "leukemia", "lymphoma", "myeloma", "hematologic",
                     "liquid cancer", "blood cancer"]
    
    # Count occurrences across all content
    all_content = " ".join([d.get("content", "").lower() for d in scraped_data if d.get("content")])
    
    def count_matches(terms, content):
        counts = {}
        for term in terms:
            count = content.count(term.lower())
            if count > 0:
                counts[term] = count
        return counts
    
    results = {
        "organs": count_matches(target_organs, all_content),
        "cancer": count_matches(cancer_terms, all_content),
        "devices": count_matches(device_terms, all_content),
        "stage": count_matches(stage_terms, all_content),
        "funding": count_matches(funding_terms, all_content),
        "us_location": count_matches(us_terms, all_content),
        "negative": count_matches(negative_terms, all_content),
        "total_content_chars": len(all_content),
        "websites_with_content": sum(1 for d in scraped_data if d.get("content"))
    }
    
    return results


def select_optimal_good_leads(scraped_data: list, max_count: int = 6) -> list:
    """
    Select optimal subset of good leads for maximum variation with minimum AI cost.
    Prioritize:
    - Websites that actually scraped content
    - Variety in company types (big vs small, device vs pharma, US vs non-US)
    - Shorter content (lower AI cost)
    """
    # Filter to only those with content
    with_content = [d for d in scraped_data if d.get("content") and len(d.get("content", "")) > 500]
    
    if len(with_content) <= max_count:
        return [d["url"] for d in with_content]
    
    # Score for selection based on diversity and cost
    scored = []
    for d in with_content:
        content = d.get("content", "").lower()
        
        # Diversity factors
        is_small = any(term in content for term in ["startup", "series a", "early stage", "founded 20"])
        is_big = any(term in content for term in ["fortune 500", "global", "nasdaq", "nyse"])
        is_device = any(term in content for term in ["medical device", "device", "catheter", "implant"])
        is_pharma = any(term in content for term in ["pharmaceutical", "drug", "therapy", "therapeutic"])
        has_oncology = any(term in content for term in ["oncology", "cancer", "tumor"])
        
        # Cost factor (prefer shorter content)
        content_len = len(d.get("content", ""))
        cost_score = max(0, 50000 - content_len) / 50000  # Higher score for shorter content
        
        scored.append({
            "url": d["url"],
            "name": d["name"],
            "is_small": is_small,
            "is_big": is_big,
            "is_device": is_device,
            "is_pharma": is_pharma,
            "has_oncology": has_oncology,
            "content_len": content_len,
            "cost_score": cost_score
        })
    
    # Select for diversity: prefer a mix
    selected = []
    categories = {"small": [], "big": [], "device": [], "pharma": [], "oncology": []}
    
    for s in scored:
        if s["is_small"]: categories["small"].append(s)
        if s["is_big"]: categories["big"].append(s)
        if s["is_device"]: categories["device"].append(s)
        if s["is_pharma"]: categories["pharma"].append(s)
        if s["has_oncology"]: categories["oncology"].append(s)
    
    # Pick one from each category (preferring lower cost)
    selected_urls = set()
    for cat in ["device", "oncology", "small", "pharma", "big"]:
        if len(selected) >= max_count:
            break
        cat_items = sorted(categories.get(cat, []), key=lambda x: -x["cost_score"])
        for item in cat_items:
            if item["url"] not in selected_urls:
                selected.append(item)
                selected_urls.add(item["url"])
                break
    
    # Fill remaining slots with shortest content
    remaining = [s for s in scored if s["url"] not in selected_urls]
    remaining.sort(key=lambda x: x["content_len"])
    for s in remaining:
        if len(selected) >= max_count:
            break
        selected.append(s)
    
    return [s["url"] for s in selected]


async def main():
    print("="*80)
    print("SCRAPING ALL 15 GOOD LEADS")
    print("="*80)
    
    os.makedirs("evaluation_results", exist_ok=True)
    
    scraper = GoodLeadsScraper()
    
    # Scrape all websites
    scraped_data = []
    for name, url in GOOD_LEADS:
        result = await scraper.scrape_website(name, url, max_pages=6)
        scraped_data.append(result)
        await asyncio.sleep(0.5)
    
    # Save full scraped data
    full_file = "evaluation_results/good_leads_full_scrape.json"
    with open(full_file, 'w', encoding='utf-8') as f:
        # Save without content for readability
        summary = [{k: v for k, v in item.items() if k != 'content'} for item in scraped_data]
        json.dump(summary, f, indent=2)
    print(f"\nScrape summary saved to: {full_file}")
    
    # Extract keywords
    print("\n" + "="*80)
    print("EXTRACTING KEYWORDS FROM CONTENT")
    print("="*80)
    keywords = extract_keywords_from_content(scraped_data)
    
    print("\n--- ORGAN KEYWORDS FOUND ---")
    for term, count in sorted(keywords["organs"].items(), key=lambda x: -x[1])[:15]:
        print(f"  {term}: {count}")
    
    print("\n--- CANCER TERMS FOUND ---")
    for term, count in sorted(keywords["cancer"].items(), key=lambda x: -x[1])[:15]:
        print(f"  {term}: {count}")
    
    print("\n--- DEVICE TERMS FOUND ---")
    for term, count in sorted(keywords["devices"].items(), key=lambda x: -x[1])[:15]:
        print(f"  {term}: {count}")
    
    print("\n--- STAGE TERMS FOUND ---")
    for term, count in sorted(keywords["stage"].items(), key=lambda x: -x[1])[:15]:
        print(f"  {term}: {count}")
    
    print("\n--- US LOCATION TERMS FOUND ---")
    for term, count in sorted(keywords["us_location"].items(), key=lambda x: -x[1])[:15]:
        print(f"  {term}: {count}")
    
    print("\n--- NEGATIVE TERMS FOUND ---")
    for term, count in sorted(keywords["negative"].items(), key=lambda x: -x[1])[:15]:
        print(f"  {term}: {count}")
    
    # Select optimal subset
    print("\n" + "="*80)
    print("SELECTING OPTIMAL SUBSET FOR GOOD_LEADS_DOMAINS")
    print("="*80)
    
    optimal_urls = select_optimal_good_leads(scraped_data, max_count=6)
    print("\nSelected domains for good_leads_domains:")
    for url in optimal_urls:
        name = next((d["name"] for d in scraped_data if d["url"] == url), "Unknown")
        chars = next((d["content_length"] for d in scraped_data if d["url"] == url), 0)
        print(f"  - {name}: {url} ({chars} chars)")
    
    # Save keywords and selections
    output = {
        "keywords": keywords,
        "optimal_good_leads": optimal_urls,
        "all_urls_for_good_leads": [url for _, url in GOOD_LEADS],
        "scraped_summary": [{k: v for k, v in item.items() if k != 'content'} for item in scraped_data]
    }
    
    keywords_file = "evaluation_results/keywords_and_selections.json"
    with open(keywords_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)
    print(f"\nKeywords and selections saved to: {keywords_file}")
    
    # Also save the full content for reference
    content_file = "evaluation_results/good_leads_content.txt"
    with open(content_file, 'w', encoding='utf-8') as f:
        for d in scraped_data:
            f.write("="*100 + "\n")
            f.write(f"COMPANY: {d['name']}\n")
            f.write(f"URL: {d['url']}\n")
            f.write(f"Pages: {d.get('pages_scraped', 0)}, Content: {d.get('content_length', 0)} chars\n")
            f.write("="*100 + "\n\n")
            f.write(d.get('content', '(no content)')[:10000] + "\n\n\n")
    print(f"Full content saved to: {content_file}")
    
    return scraped_data, keywords, optimal_urls


if __name__ == "__main__":
    asyncio.run(main())
