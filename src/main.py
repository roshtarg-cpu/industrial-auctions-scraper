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
    Uses multi-strategy selectors with graceful fallbacks.
    """
    try:
        # Extract URL - multiple strategies
        url = None
        link = (
            auction_element.find('a', {'data-auction-url': True}) or
            auction_element.find('a', class_=lambda x: x and 'auction-link' in x) or
            auction_element.find('a', href=lambda x: x and '/auction/' in x) or
            auction_element.find('a')
        )
        if link and link.get('href'):
            href = link['href']
            url = href if href.startswith('http') else f"{base_url}{href}"
        
        # Extract title
        title = None
        title_elem = (
            auction_element.find(attrs={'data-auction-title': True}) or
            auction_element.find('h2') or
            auction_element.find('h3') or
            auction_element.find(class_=lambda x: x and 'title' in str(x).lower())
        )
        if title_elem:
            title = title_elem.get_text(strip=True)
        
        # Extract auction ID from URL or data attribute
        auction_id = None
        if url:
            parts = url.rstrip('/').split('/')
            if parts:
                auction_id = parts[-1]
        if not auction_id:
            id_elem = auction_element.find(attrs={'data-auction-id': True})
            if id_elem:
                auction_id = id_elem.get('data-auction-id')
        
        # Extract location
        location = None
        location_elem = (
            auction_element.find(attrs={'data-location': True}) or
            auction_element.find(class_=lambda x: x and 'location' in str(x).lower()) or
            auction_element.find('span', string=lambda x: x and ('location' in str(x).lower() or ',' in str(x)))
        )
        if location_elem:
            location = location_elem.get_text(strip=True)
        
        # Extract dates
        start_date = None
        end_date = None
        date_elem = (
            auction_element.find(attrs={'data-start-date': True}) or
            auction_element.find(class_=lambda x: x and 'date' in str(x).lower())
        )
        if date_elem:
            start_date = date_elem.get('data-start-date') or date_elem.get_text(strip=True)
        
        end_date_elem = (
            auction_element.find(attrs={'data-end-date': True}) or
            auction_element.find(class_=lambda x: x and 'end-date' in str(x).lower())
        )
        if end_date_elem:
            end_date = end_date_elem.get('data-end-date') or end_date_elem.get_text(strip=True)
        
        # Extract category
        category = None
        category_elem = (
            auction_element.find(attrs={'data-category': True}) or
            auction_element.find(class_=lambda x: x and 'category' in str(x).lower()) or
            auction_element.find('span', class_=lambda x: x and 'tag' in str(x).lower())
        )
        if category_elem:
            category = category_elem.get('data-category') or category_elem.get_text(strip=True)
        
        # Extract description
        description = None
        desc_elem = (
            auction_element.find(attrs={'data-description': True}) or
            auction_element.find(class_=lambda x: x and 'description' in str(x).lower()) or
            auction_element.find('p')
        )
        if desc_elem:
            description = desc_elem.get_text(strip=True)
        
        # Extract image URL
        image_url = None
        img_elem = (
            auction_element.find('img', attrs={'data-src': True}) or
            auction_element.find('img', src=True)
        )
        if img_elem:
            image_url = img_elem.get('data-src') or img_elem.get('src')
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
            proxy_conf = await Actor.create_proxy_configuration(proxy_config)
            proxy_url = await proxy_conf.new_url()
        
        # Use RESIDENTIAL proxy as specified
        if not proxy_url:
            proxy_conf = await Actor.create_proxy_configuration(
                actor_proxy_input={'useApifyProxy': True, 'apifyProxyGroups': ['RESIDENTIAL']}
            )
            proxy_url = await proxy_conf.new_url()
        
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
                
                # Find auction containers using multiple strategies
                auction_containers = (
                    soup.find_all(attrs={'data-auction': True}) or
                    soup.find_all('article', class_=lambda x: x and 'auction' in str(x).lower()) or
                    soup.find_all('div', class_=lambda x: x and 'auction' in str(x).lower()) or
                    soup.find_all('article') or
                    []
                )
                
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
            'actorId': actor_input.actor_id,
            'actorRunId': actor_input.actor_run_id,
            'defaultDatasetId': actor_input.default_dataset_id,
            'startedAt': actor_input.started_at.isoformat() if actor_input.started_at else None,
            'input': input_data,
            'stats': {
                'itemsScraped': results_count,
                'requestsMade': 1,
            }
        })
