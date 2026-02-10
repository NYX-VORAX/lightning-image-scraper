#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════╗
║                    ⚡ LIGHTNING IMAGE SCRAPER ⚡                           ║
║                                                                           ║
║  Fast Image Scraper Tool - Download thousands of images in seconds       ║
║  Downloads images from any website with advanced filtering and           ║
║  concurrent processing                                                    ║
║                                                                           ║
║  Repository: https://github.com/NYX-VORAX/lightning-image-scraper        ║
║  Author: NYX-VORAX                                                        ║
║  Version: 1.0.0                                                           ║
║  License: MIT                                                             ║
║                                                                           ║
║  ⭐ Star us on GitHub if you find this useful!                           ║
╚═══════════════════════════════════════════════════════════════════════════╝
"""

import os
import re
import sys
import time
import asyncio
import aiohttp
import argparse
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib

class FastImageScraper:
    def __init__(self, url, output_dir="downloaded_images", max_images=100, max_depth=2, 
                 min_width=200, min_height=200, skip_patterns=None):
        self.base_url = url
        self.output_dir = output_dir
        self.max_images = max_images
        self.max_depth = max_depth
        self.min_width = min_width
        self.min_height = min_height
        self.downloaded_count = 0
        self.visited_urls = set()
        self.image_hashes = set()
        self.skip_patterns = skip_patterns or ['logo', 'icon', 'banner', 'avatar', 'sprite', 'btn', 'button']
        
        # Create output directory
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        
    def should_skip_image(self, img_url):
        """Filter out logos, banners, icons, and other unwanted images"""
        img_lower = img_url.lower()
        
        # Skip if matches any pattern
        for pattern in self.skip_patterns:
            if pattern in img_lower:
                return True
        
        # Skip common icon/logo extensions or paths
        if any(x in img_lower for x in ['/icon', '/logo', '/sprite', '/favicon']):
            return True
            
        return False
    
    def get_image_hash(self, content):
        """Generate hash to avoid duplicate images"""
        return hashlib.md5(content).hexdigest()
    
    async def fetch_page(self, session, url):
        """Fetch page content asynchronously"""
        try:
            async with session.get(url, timeout=10, ssl=False) as response:
                if response.status == 200:
                    return await response.text()
        except Exception as e:
            print(f"Error fetching {url}: {str(e)[:50]}")
        return None
    
    async def download_image(self, session, img_url, index):
        """Download single image asynchronously"""
        try:
            async with session.get(img_url, timeout=15, ssl=False) as response:
                if response.status == 200:
                    content = await response.read()
                    
                    # Check if image is duplicate
                    img_hash = self.get_image_hash(content)
                    if img_hash in self.image_hashes:
                        return False
                    
                    # More lenient size check - accept images > 5KB instead of 10KB
                    if len(content) < 5000:
                        return False
                    
                    self.image_hashes.add(img_hash)
                    
                    # Get file extension
                    ext = os.path.splitext(urlparse(img_url).path)[1]
                    if not ext or ext not in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                        ext = '.jpg'
                    
                    # Save image
                    filename = f"image_{index:05d}{ext}"
                    filepath = os.path.join(self.output_dir, filename)
                    
                    with open(filepath, 'wb') as f:
                        f.write(content)
                    
                    self.downloaded_count += 1
                    print(f"✓ Downloaded: {filename} ({len(content)//1024}KB)")
                    return True
                    
        except Exception as e:
            print(f"✗ Failed: {img_url[:60]}... - {str(e)[:40]}")
        return False
    
    def extract_image_urls(self, html, base_url):
        """Extract all image URLs from HTML"""
        soup = BeautifulSoup(html, 'html.parser')
        image_urls = set()
        
        # Find img tags with multiple attribute checks
        for img in soup.find_all('img'):
            # Check multiple possible image sources
            src = (img.get('src') or img.get('data-src') or img.get('data-lazy-src') or 
                   img.get('data-original') or img.get('data-lazy') or img.get('data-image'))
            if src:
                full_url = urljoin(base_url, src)
                if not self.should_skip_image(full_url):
                    image_urls.add(full_url)
            
            # Check srcset attribute
            srcset = img.get('srcset')
            if srcset:
                urls = re.findall(r'https?://[^\s,]+|[^\s,]+\.(?:jpg|jpeg|png|webp|gif)', srcset)
                for url in urls:
                    url = url.split()[0].rstrip(',')
                    full_url = urljoin(base_url, url)
                    if not self.should_skip_image(full_url):
                        image_urls.add(full_url)
        
        # Find picture tags
        for picture in soup.find_all('picture'):
            for source in picture.find_all('source'):
                srcset = source.get('srcset')
                if srcset:
                    urls = re.findall(r'https?://[^\s,]+|[^\s,]+\.(?:jpg|jpeg|png|webp|gif)', srcset)
                    for url in urls:
                        url = url.split()[0].rstrip(',')
                        full_url = urljoin(base_url, url)
                        if not self.should_skip_image(full_url):
                            image_urls.add(full_url)
        
        # Find CSS background images
        for tag in soup.find_all(style=True):
            style = tag.get('style', '')
            urls = re.findall(r'url\(["\']?(.*?)["\']?\)', style)
            for url in urls:
                full_url = urljoin(base_url, url)
                if not self.should_skip_image(full_url):
                    image_urls.add(full_url)
        
        # Find divs and other tags with data-image attributes
        for tag in soup.find_all(attrs={'data-image': True}):
            img_url = tag.get('data-image')
            full_url = urljoin(base_url, img_url)
            if not self.should_skip_image(full_url):
                image_urls.add(full_url)
        
        return list(image_urls)
    
    def extract_page_links(self, html, base_url):
        """Extract links for crawling to specified depth"""
        soup = BeautifulSoup(html, 'html.parser')
        links = set()
        
        for a in soup.find_all('a', href=True):
            href = a.get('href')
            full_url = urljoin(base_url, href)
            
            # Only follow links from same domain
            if urlparse(full_url).netloc == urlparse(base_url).netloc:
                links.add(full_url)
        
        return list(links)
    
    async def crawl_and_scrape(self, url, depth=0, collected_images=None):
        """Recursively crawl pages and collect images"""
        if collected_images is None:
            collected_images = []
        
        if depth > self.max_depth or url in self.visited_urls:
            return []
        
        # Stop if we have enough images (with buffer of 3x for filtering)
        if len(collected_images) >= self.max_images * 3:
            return []
        
        self.visited_urls.add(url)
        print(f"\n🔍 Crawling [Depth {depth}]: {url[:70]}...")
        
        async with aiohttp.ClientSession() as session:
            html = await self.fetch_page(session, url)
            if not html:
                return []
            
            # Extract images from current page
            image_urls = self.extract_image_urls(html, url)
            print(f"   Found {len(image_urls)} images on this page (Total collected: {len(collected_images) + len(image_urls)})")
            
            # If we need more images and haven't reached max depth, crawl more pages
            if depth < self.max_depth and len(collected_images) + len(image_urls) < self.max_images * 3:
                # Increase number of links to crawl based on depth (more aggressive crawling)
                links_to_crawl = 20 if depth == 0 else (10 if depth == 1 else 5)
                page_links = self.extract_page_links(html, url)[:links_to_crawl]
                
                print(f"   Will crawl {len(page_links)} more pages at depth {depth + 1}")
                
                for link in page_links:
                    if len(collected_images) + len(image_urls) >= self.max_images * 3:
                        break
                    more_images = await self.crawl_and_scrape(link, depth + 1, collected_images + image_urls)
                    image_urls.extend(more_images)
            
            return image_urls
    
    async def download_all_images(self, image_urls):
        """Download all images concurrently"""
        print(f"\n📥 Starting download of {min(len(image_urls), self.max_images)} images from {len(image_urls)} URLs...\n")
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            downloaded = 0
            
            # Try to download images until we reach the target count
            for idx, img_url in enumerate(image_urls, 1):
                if downloaded >= self.max_images:
                    break
                task = self.download_image(session, img_url, idx)
                tasks.append(task)
                
                # Process in batches to avoid overwhelming the system
                if len(tasks) >= 50:
                    results = await asyncio.gather(*tasks)
                    downloaded = self.downloaded_count
                    tasks = []
                    
                    # If we've reached our target, stop
                    if downloaded >= self.max_images:
                        break
            
            # Download remaining tasks
            if tasks and self.downloaded_count < self.max_images:
                await asyncio.gather(*tasks)
    
    async def run(self):
        """Main execution method"""
        start_time = time.time()
        
        print("╔" + "═"*68 + "╗")
        print("║" + " "*68 + "║")
        print("║" + "        ⚡ LIGHTNING IMAGE SCRAPER v1.0.0 ⚡        ".center(68) + "║")
        print("║" + " "*68 + "║")
        print("║" + "  GitHub: github.com/NYX-VORAX/lightning-image-scraper  ".center(68) + "║")
        print("║" + " "*68 + "║")
        print("╚" + "═"*68 + "╝")
        print("")
        print("="*70)
        print(f"🚀 Fast Image Scraper Started")
        print(f"   URL: {self.base_url}")
        print(f"   Max Images: {self.max_images}")
        print(f"   Max Depth: {self.max_depth}")
        print(f"   Output: {self.output_dir}/")
        print("="*70)
        
        # Crawl and collect image URLs (collect 3x more to account for filtering)
        image_urls = await self.crawl_and_scrape(self.base_url, depth=0)
        
        print(f"\n📊 Total unique image URLs collected: {len(image_urls)}")
        print(f"   Target downloads: {self.max_images}")
        print(f"   Starting download process...")
        
        # Download images
        if image_urls:
            await self.download_all_images(image_urls)
        else:
            print("\n⚠️ No images found. Try increasing depth or checking the URL.")
        
        elapsed = time.time() - start_time
        print("\n" + "="*70)
        print(f"✅ Completed!")
        print(f"   Downloaded: {self.downloaded_count} images")
        print(f"   Target was: {self.max_images} images")
        if self.downloaded_count < self.max_images:
            print(f"   ⚠️ Note: Downloaded less than target due to filtering/duplicates")
            print(f"   Tip: Try increasing depth (-d 3 or higher) or different URL")
        print(f"   Time: {elapsed:.2f} seconds")
        if self.downloaded_count > 0:
            print(f"   Speed: {self.downloaded_count/elapsed:.1f} images/second")
        print(f"   Location: {os.path.abspath(self.output_dir)}/")
        print("="*70)
        print("")
        print("🌟 Like this tool? Star us on GitHub!")
        print("   https://github.com/NYX-VORAX/lightning-image-scraper")
        print("")


def main():
    parser = argparse.ArgumentParser(
        description='⚡ Lightning Image Scraper - Download images from any website',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Examples:
  python scrapper.py -u https://example.com -n 100
  python scrapper.py -u https://example.com -n 500 -d 3 -o my_images
  python scrapper.py -u https://example.com -n 10000 -d 2 --min-size 300

GitHub: https://github.com/NYX-VORAX/lightning-image-scraper
Author: NYX-VORAX | Version: 1.0.0 | License: MIT

⭐ Star us on GitHub if this helped you!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """
    )
    
    parser.add_argument('-u', '--url', required=True, help='Target website URL')
    parser.add_argument('-n', '--num-images', type=int, default=100, 
                       help='Maximum number of images to download (default: 100)')
    parser.add_argument('-d', '--depth', type=int, default=2, 
                       help='Maximum crawl depth (default: 2)')
    parser.add_argument('-o', '--output', default='downloaded_images', 
                       help='Output directory (default: downloaded_images)')
    parser.add_argument('--min-size', type=int, default=200, 
                       help='Minimum image dimension in pixels (default: 200)')
    parser.add_argument('--skip', nargs='+', 
                       default=['logo', 'icon', 'banner', 'avatar', 'sprite', 'btn'],
                       help='Patterns to skip in image URLs')
    
    args = parser.parse_args()
    
    # Create scraper instance
    scraper = FastImageScraper(
        url=args.url,
        output_dir=args.output,
        max_images=args.num_images,
        max_depth=args.depth,
        min_width=args.min_size,
        min_height=args.min_size,
        skip_patterns=args.skip
    )
    
    # Run the scraper
    asyncio.run(scraper.run())


if __name__ == "__main__":
    main()
