"""
Industrial Auctions Scraper - Main module
Scrapes auction listings from industrial-auctions.com
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from apify import Actor
import httpx
from bs4 import BeautifulSoup


async def scrape_auction(session: httpx.AsyncClient, auction_element: Any, base_url: str) -> Optional[Dict[str, Any]]:
    """
    Extract auction data from a single auction container element.
    Selector strategy based on industrial-auctions.com actual structure.
    """
    try:
        # Extract URL
        url = None
        link = auction_element.find('a', href=lambda x: x and '/auctions/' in str(x))
        if link and link.get('href'):
            href = link['href']
            url = href if href.startswith('http') else f"{base_url}{href}"
        
        # Extract auction ID from URL
        auction_id = None
        if url:
            parts = url.rstrip('/').split('/')
            if parts:
                # Format: /en/auctions/2312-description/
                segment = parts[-1] if parts[-1] else parts[-2]
                auction_id = segment.split('-')[0]
        
        # Extract title from .auction-heading div
        title = None
        title_elem = auction_element.find('div', class_='auction-heading')
        if title_elem:
            title = title_elem.get_text(strip=True)
        
        # Extract dates from .auction-dates__entry divs
        start_date = None
        end_date = None
        date_entries = auction_element.find_all('div', class_='auction-dates__entry')
        for entry in date_entries:
            text = entry.get_text(strip=True)
            if 'Starts' in text:
                start_date = text.replace('Starts', '').strip()
            elif 'ends' in text.lower():
                end_date = text.replace('Auction ends', '').replace('auction ends', '').strip()
        
        # Extract location from title (format: "...in Location (CODE)")
        location = None
        if title:
            import re
            match = re.search(r'in\s+([^(]+)\s*\([A-Z]{2}\)', title)
            if match:
                location = match.group(1).strip()
        
        # Category from title (text after colon, before " in")
        category = None
        if title and ':' in title:
            after_colon = title.split(':', 1)[1]
            if ' in ' in after_colon:
                category = after_colon.split(' in ')[0].strip()
            else:
                category = after_colon.strip()
        
        # Description - not in listing, would need detail page
        description = None
        
        # Extract image URL
        image_url = None
        img_elem = auction_element.find('img', src=True)
        if img_elem:
            image_url = img_elem.get('src')
            if image_url and not image_url.startswith('http'):
                image_url = f"{base_url}{image_url}"
        
        return {
            'url': url,
            'title': title,
            'auctionId': auction_id,
            'location': location,
            'startDate': start_date,
            'endDate': end_date,
            'category': category,
            'description': description,
            'imageUrl': image_url,
            'scrapedAt': datetime.now(timezone.utc).isoformat()
        }
    
    except Exception as e:
        Actor.log.warning(f"Error extracting auction data: {e}")
        return None


async def main() -> None:
    """
    Main scraper entry point.
    """
    async with Actor:
        # Get input - NO await (synchronous)
        actor_input = Actor.get_env()
        input_data = await Actor.get_input() or {}
        
        # Extract input parameters
        max_results = input_data.get('maxResults', 3)
        category_filter = input_data.get('category', '')
        location_filter = input_data.get('location', '')
        proxy_config = input_data.get('proxyConfiguration')
        
        Actor.log.info(f'Starting Industrial Auctions scraper')
        Actor.log.info(f'Max results: {max_results}, Category: {category_filter or "All"}, Location: {location_filter or "All"}')
        
        base_url = 'https://www.industrial-auctions.com'
        auctions_url = f'{base_url}/en/auctions'
        
        # Get proxy URL if configured  
        proxy_url = None
        if proxy_config:
            try:
                proxy_conf = await Actor.create_proxy_configuration(proxy_config)
                proxy_url = await proxy_conf.new_url()
                Actor.log.info('Using custom proxy configuration')
            except Exception as e:
                Actor.log.warning(f'Proxy configuration failed: {e}, continuing without proxy')
        
        # Site has LIGHT protection - works without proxy
        
        # Configure httpx client
        client_kwargs = {
            'follow_redirects': True,
            'timeout': 30.0,
            'headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }
        }
        
        if proxy_url:
            client_kwargs['proxies'] = {'http://': proxy_url, 'https://': proxy_url}
        
        results_count = 0
        
        async with httpx.AsyncClient(**client_kwargs) as session:
            try:
                Actor.log.info(f'Fetching auctions from {auctions_url}')
                response = await session.get(auctions_url)
                response.raise_for_status()
                
                Actor.log.info(f'Response status: {response.status_code}')
                
                # Parse HTML
                soup = BeautifulSoup(response.text, 'lxml')
                
                # Find auction containers - use actual class from site
                auction_containers = soup.find_all('div', class_='auction-block')
                
                Actor.log.info(f'Found {len(auction_containers)} auction containers')
                
                if not auction_containers:
                    Actor.log.warning('No auction containers found - page structure may have changed')
                
                for container in auction_containers:
                    if results_count >= max_results:
                        break
                    
                    # Extract auction data
                    auction_data = await scrape_auction(session, container, base_url)
                    
                    if not auction_data:
                        continue
                    
                    # Apply filters
                    if category_filter and auction_data.get('category'):
                        if category_filter.lower() not in auction_data['category'].lower():
                            continue
                    
                    if location_filter and auction_data.get('location'):
                        if location_filter.lower() not in auction_data['location'].lower():
                            continue
                    
                    # Push result immediately
                    await Actor.push_data(auction_data)
                    results_count += 1
                    
                    Actor.log.info(f'Scraped auction {results_count}/{max_results}: {auction_data.get("title", "N/A")}')
                
                Actor.log.info(f'Scraping completed. Total results: {results_count}')
                
            except httpx.HTTPError as e:
                Actor.log.error(f'HTTP error occurred: {e}')
                raise
            except Exception as e:
                Actor.log.error(f'Unexpected error: {e}')
                raise
        
        # Save task metadata at end
        await Actor.set_value('SAVED-TASK', {
            'actorId': actor_input.get('actor_id'),
            'actorRunId': actor_input.get('actor_run_id'),
            'defaultDatasetId': actor_input.get('default_dataset_id'),
            'startedAt': actor_input.get('started_at'),
            'input': input_data,
            'stats': {
                'itemsScraped': results_count,
                'requestsMade': 1,
            }
        })
