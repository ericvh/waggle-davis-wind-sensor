#!/usr/bin/env python3
"""
Test script for debugging Tempest web scraping
Usage: python3 test_tempest_scraping.py [station_id]
Example: python3 test_tempest_scraping.py 98272
"""

import sys
import requests
import re
from datetime import datetime, timezone

try:
    from bs4 import BeautifulSoup
    HAS_BEAUTIFULSOUP = True
except ImportError:
    print("BeautifulSoup4 not installed. Install with: pip install beautifulsoup4")
    HAS_BEAUTIFULSOUP = False
    sys.exit(1)

def test_tempest_scraping(station_id):
    """Test scraping a Tempest station webpage"""
    
    base_url = f"https://tempestwx.com/station/{station_id}"
    print(f"Testing Tempest station: {station_id}")
    print(f"URL: {base_url}")
    print("=" * 60)
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        print("Fetching webpage...")
        response = requests.get(base_url, headers=headers, timeout=15)
        
        print(f"Status code: {response.status_code}")
        print(f"Content length: {len(response.content)} bytes")
        
        if response.status_code != 200:
            print(f"ERROR: HTTP {response.status_code}")
            return
        
        soup = BeautifulSoup(response.content, 'html.parser')
        page_text = soup.get_text()
        
        print(f"Page text length: {len(page_text)} characters")
        print("=" * 60)
        
        # Show page title
        title = soup.find('title')
        if title:
            print(f"Page title: {title.get_text().strip()}")
        
        # Look for any numbers that might be wind data
        print("\nSearching for wind data patterns...")
        
        # Wind speed patterns
        wind_speed_patterns = [
            r'Wind.*?(\d+(?:\.\d+)?)\s*mph',
            r'(\d+(?:\.\d+)?)\s*mph.*?wind',
            r'Speed.*?(\d+(?:\.\d+)?)\s*mph',
            r'"wind_speed".*?(\d+(?:\.\d+)?)',
            r'windSpeed.*?(\d+(?:\.\d+)?)',
            r'wind-speed.*?(\d+(?:\.\d+)?)',
            r'(\d+(?:\.\d+)?)\s*mph',  # Any number with mph
        ]
        
        print("\nWind speed searches:")
        for i, pattern in enumerate(wind_speed_patterns):
            matches = re.findall(pattern, page_text, re.IGNORECASE)
            if matches:
                print(f"  Pattern {i+1}: {pattern}")
                print(f"  Matches: {matches[:5]}")  # Show first 5 matches
        
        # Wind direction patterns
        wind_dir_patterns = [
            r'Direction.*?(\d+(?:\.\d+)?)\s*°?',
            r'(\d+(?:\.\d+)?)\s*°.*?direction',
            r'"wind_direction".*?(\d+(?:\.\d+)?)',
            r'windDirection.*?(\d+(?:\.\d+)?)',
            r'wind-direction.*?(\d+(?:\.\d+)?)',
            r'(\d+(?:\.\d+)?)\s*°',  # Any number with degree symbol
        ]
        
        print("\nWind direction searches:")
        for i, pattern in enumerate(wind_dir_patterns):
            matches = re.findall(pattern, page_text, re.IGNORECASE)
            if matches:
                # Filter for reasonable wind directions (0-360)
                valid_matches = [m for m in matches if 0 <= float(m) <= 360]
                if valid_matches:
                    print(f"  Pattern {i+1}: {pattern}")
                    print(f"  Valid matches: {valid_matches[:5]}")
        
        # Look for any mention of wind-related words
        print("\nWind-related content search:")
        wind_keywords = ['wind', 'mph', 'direction', 'gust', 'speed']
        for keyword in wind_keywords:
            # Find lines containing the keyword
            lines = page_text.split('\n')
            keyword_lines = [line.strip() for line in lines if keyword.lower() in line.lower() and line.strip()]
            if keyword_lines:
                print(f"\nLines containing '{keyword}':")
                for line in keyword_lines[:3]:  # Show first 3 lines
                    if len(line) > 100:
                        line = line[:100] + "..."
                    print(f"  {line}")
        
        # Save full content for manual inspection
        debug_filename = f"tempest_debug_{station_id}.html"
        with open(debug_filename, 'w', encoding='utf-8') as f:
            f.write(response.text)
        print(f"\nSaved full webpage to: {debug_filename}")
        
        # Save text content too
        text_filename = f"tempest_debug_{station_id}.txt"
        with open(text_filename, 'w', encoding='utf-8') as f:
            f.write(page_text)
        print(f"Saved text content to: {text_filename}")
        
        # Show first 1000 characters of page content
        print("\nFirst 1000 characters of page:")
        print("-" * 40)
        print(page_text[:1000])
        print("-" * 40)
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        station_id = sys.argv[1]
    else:
        station_id = "98272"  # Default to Lanai station
    
    test_tempest_scraping(station_id) 