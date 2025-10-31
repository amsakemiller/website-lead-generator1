# Unified Lead Generation Tool

A comprehensive lead generation application that combines all steps into a single, easy-to-use GUI application.

## Features

- **Unified Interface**: Single GUI for all configuration and execution
- **Step 1: Website Discovery**: Search for relevant websites using Serper.dev or SerpAPI
- **Step 2: Website Scraping**: Intelligent scraping with smart page selection
- **Step 3: Factor-based Scoring**: Automated scoring based on relevant factors
- **Step 4: AI Analysis**: AI-powered lead qualification using Claude or OpenAI

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Run the unified application:
```bash
python unified_leadgen.py
```

## Usage

### Configuration

The application provides a tabbed interface for configuring each step:

1. **Step 1: Discovery** - Configure search API, keywords, and output settings
2. **Step 2: Scraping** - Set scraping parameters like concurrency and page limits
3. **Step 3: Scoring** - Configure scoring thresholds and output paths
4. **Step 4: AI Analysis** - Set up AI API credentials and analysis parameters
5. **Run Pipeline** - Select which steps to run and execute the pipeline

### Running the Pipeline

1. Configure all steps using the tabs
2. Go to the "Run Pipeline" tab
3. Select which steps you want to run
4. Click "Run Selected Steps"
5. Monitor progress in the text area

### Configuration Files

The application automatically creates and manages configuration files:
- `unified_config.json` - Main configuration file
- `logs/unified_leadgen.log` - Application logs

## Step Details

### Step 1: Website Discovery
- Uses Serper.dev or SerpAPI to search for relevant websites
- Combines set keywords with variable keywords for comprehensive searches
- Verifies domain accessibility before adding to leads list
- Outputs: `data/leads_raw.csv`

### Step 2: Website Scraping
- Intelligently scrapes websites with smart page selection
- Respects robots.txt and implements rate limiting
- Extracts and aggregates content from multiple pages
- Outputs: `data/webcrawl.db` (SQLite database)

### Step 3: Factor-based Scoring
- Scores websites based on positive and negative factors
- Factors include: US location, oncology focus, medical devices, preclinical research
- Disqualifiers include: non-US companies, post-clinical trials
- Outputs: `data/analysis_results.csv`

### Step 4: AI Analysis
- Uses AI to analyze high-scoring websites
- Identifies business patterns and lead quality
- Filters out news sites, academic institutions, and non-business content
- Outputs: `data/ai_analysis_results.csv`

## Output Files

- `data/leads_raw.csv` - Initial website list from discovery
- `data/webcrawl.db` - Scraped website content (SQLite)
- `data/analysis_results.csv` - Factor-based scores
- `data/ai_analysis_results.csv` - AI analysis results
- `logs/unified_leadgen.log` - Application logs

## API Keys Required

- **Step 1**: Serper.dev API key or SerpAPI key
- **Step 4**: Claude API key or OpenAI API key

## Troubleshooting

1. **API Key Issues**: Ensure your API keys are correctly configured in the respective tabs
2. **File Permissions**: Make sure the application has write permissions for output directories
3. **Network Issues**: Check your internet connection for API calls
4. **Rate Limiting**: Adjust rate limit delays if you encounter API rate limiting

## Logging

The application provides comprehensive logging:
- Console output for real-time progress
- Log files in the `logs/` directory
- Progress tracking in the GUI

## Support

For issues or questions:
1. Check the log files for detailed error information
2. Ensure all dependencies are installed correctly
3. Verify API keys and network connectivity
