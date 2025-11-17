
import csv
import re
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse


# Configuration
BASE_URL = "https://www.univ-eloued.dz/ar/"
OUTPUT_FILE = "univ_eloued_activities.csv"
CSV_SEPARATOR = ";"
TIMEOUT = 15
MAX_PAGES = 1  # Set to None to scrape all pages


def clean_text(text):
    """Clean and normalize text by removing excessive whitespace and control characters."""
    if not text:
        return ""
    
    # Remove newlines, carriage returns, and tabs
    text = re.sub(r'[\n\r\t]+', ' ', text)
    # Remove multiple consecutive spaces
    text = re.sub(r'\s+', ' ', text)
    # Strip leading and trailing whitespace
    text = text.strip()
    return text
def parse_date_string(s):
    """Try to parse a date string and return ISO date 'YYYY-MM-DD'."""
    if not s:
        return None
    s = s.strip()

    # Try ISO / RFC datetime first
    try:
        # Handle trailing Z
        clean = s.replace('Z', '+00:00')
        dt = datetime.fromisoformat(clean)
        return dt.strftime('%Y-%m-%d')
    except Exception:
        pass

    # Common English formats
    formats = ['%B %d, %Y', '%b %d, %Y', '%d %B %Y', '%d %b %Y', '%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y']
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime('%Y-%m-%d')
        except Exception:
            continue

    # Arabic month names mapping
    arabic_months = {
        'يناير': 1, 'فبراير': 2, 'مارس': 3, 'أبريل': 4, 'إبريل': 4,
        'ماي': 5, 'مايو': 5, 'يونيو': 6, 'يوليو': 7, 'أغسطس': 8,
        'اغسطس': 8, 'سبتمبر': 9, 'أكتوبر': 10, 'اكتوبر': 10,
        'نوفمبر': 11, 'ديسمبر': 12, 'دجمبر': 12
    }

    # Try to match Arabic pattern: <month> <day> , <year> or <day> <month> <year>
    m = re.search(r'(%s)\s+(\d{1,2})[,\s]+(\d{4})' % '|'.join(arabic_months.keys()), s)
    if m:
        month_name = m.group(1)
        day = int(m.group(2))
        year = int(m.group(3))
        month = arabic_months.get(month_name)
        try:
            dt = datetime(year, month, day)
            return dt.strftime('%Y-%m-%d')
        except Exception:
            pass

    # Fallback: search for English month pattern in the text
    m2 = re.search(r'([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})', s)
    if m2:
        try:
            dt = datetime.strptime(m2.group(0), '%B %d, %Y')
            return dt.strftime('%Y-%m-%d')
        except Exception:
            try:
                dt = datetime.strptime(m2.group(0), '%b %d, %Y')
                return dt.strftime('%Y-%m-%d')
            except Exception:
                pass

    return None


def extract_event_date(soup):
    """Try multiple strategies to extract the event/publication date from an article page.

    Returns ISO date string 'YYYY-MM-DD' when possible, otherwise None.
    """

    # 1) <time datetime="..."> tag
    time_tag = soup.find('time')
    if time_tag:
        dt_attr = time_tag.get('datetime')
        if dt_attr:
            parsed = parse_date_string(dt_attr)
            if parsed:
                return parsed
        # fallback to text inside time tag
        text = clean_text(time_tag.get_text())
        parsed = parse_date_string(text)
        if parsed:
            return parsed

    # 2) Meta tags commonly used
    meta_names = ['article:published_time', 'published_time', 'date', 'dcterms.date', 'dc.date', 'pubdate', 'publication_date', 'datePublished']
    for name in meta_names:
        meta = soup.find('meta', attrs={'property': name}) or soup.find('meta', attrs={'name': name})
        if meta and meta.get('content'):
            parsed = parse_date_string(meta['content'])
            if parsed:
                return parsed

    # 3) Elements whose class or id suggests a date
    date_elements = soup.find_all(class_=re.compile(r'date|time|post-date|entry-date|تاريخ|نشر', re.I))
    for el in date_elements:
        text = clean_text(el.get_text())
        parsed = parse_date_string(text)
        if parsed:
            return parsed

    # 4) Search body text for English or Arabic date patterns
    body_text = clean_text(soup.get_text())
    # English pattern
    m = re.search(r'([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})', body_text)
    if m:
        parsed = parse_date_string(m.group(0))
        if parsed:
            return parsed

    # Arabic months pattern
    arabic_months_regex = r'(يناير|فبراير|مارس|أبريل|إبريل|ماي|مايو|يونيو|يوليو|أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر|دجمبر)'
    m2 = re.search(arabic_months_regex + r'\s+(\d{1,2})[,\s]+(\d{4})', body_text)
    if m2:
        parsed = parse_date_string(m2.group(0))
        if parsed:
            return parsed

    return None


def fetch_page(url, session=None):
    """Fetch a web page and return its HTML content."""
    if session is None:
        session = requests.Session()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    }
    
    response = session.get(url, headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or 'utf-8'
    
    return response.text


def extract_links(html, base_url):
    """Extract article links from a category page HTML"""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    
    # Strategy 1: Find <article> elements and extract links
    for article in soup.find_all('article'):
        link = article.find('a', href=True)
        if link:
            url = urljoin(base_url, link['href'])
            if url not in seen:
                seen.add(url)
                links.append(url)
    
    # Strategy 2: Find heading elements (h1-h4) with links
    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4']):
        link = heading.find('a', href=True)
        if link:
            url = urljoin(base_url, link['href'])
            if url not in seen:
                seen.add(url)
                links.append(url)
    
    # Strategy 3: Find all internal links (same domain)
    parsed_base = urlparse(base_url)
    domain = parsed_base.netloc
    
    for link in soup.find_all('a', href=True):
        url = urljoin(base_url, link['href'])
        parsed_url = urlparse(url)
        
        if parsed_url.netloc.endswith(domain) and url not in seen:
            # Skip pagination links pointing to the current page
            if url.rstrip('/') != base_url.rstrip('/'):
                seen.add(url)
                links.append(url)
    
    return links


def extract_article_data(html, article_url):
    """Extract title, date, description from an article page HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Extract title
    title = ""
    h1 = soup.find('h1')
    if h1:
        title = clean_text(h1.get_text())
    elif soup.title:
        title = clean_text(soup.title.string)

    # Extract summary/description
    summary = ""

    # Try meta description first
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if meta_desc and meta_desc.get('content'):
        summary = clean_text(meta_desc['content'])

    # Try first paragraph in known content containers
    if not summary:
        content_selectors = [
            'entry-content', 'post-content', 'content', 'td-post-content',
            'article-body', 'article-content', 'main-content'
        ]
        for selector in content_selectors:
            container = soup.find(class_=selector)
            if container:
                paragraph = container.find('p')
                if paragraph:
                    summary = clean_text(paragraph.get_text())
                    break

    # Fallback: first paragraph on the page
    if not summary:
        paragraph = soup.find('p')
        if paragraph:
            summary = clean_text(paragraph.get_text())

    # Extract event/publication date from the article
    event_date = extract_event_date(soup)
    # If cannot find a date, leave empty (do not use today's date)
    date_value = event_date if event_date else ""

    return {
        'Title': title,
        'Date': date_value,
        'Description': summary,
        'Link': article_url
    }


def find_next_page_url(html, current_url):
    """Find the URL of the next page from pagination links in the HTML."""
    soup = BeautifulSoup(html, "html.parser")
    
    # Look for next button with common class names
    next_button = soup.find('a', class_=['next', 'next-page', 'pagination-next'])
    if next_button and next_button.get('href'):
        return urljoin(current_url, next_button['href'])
    
    # Look for any link with "next" text
    for link in soup.find_all('a'):
        text = link.get_text(strip=True).lower()
        href = link.get('href')
        if href and ('next' in text or '→' in text):
            return urljoin(current_url, href)
    
    return None


def scrape_activities():
    """
    Main function to orchestrate the web scraping process.
    Fetches all activities and saves them to CSV.
    """
    print("=" * 70)
    print("University of El Oued - Web Scraper")
    print("=" * 70)
    
    session = requests.Session()
    all_data = []
    page_num = 0
    current_url = BASE_URL
    
    # Scrape pages (with pagination support)
    while current_url and (MAX_PAGES is None or page_num < MAX_PAGES):
        page_num += 1
        print(f"\nProcessing page {page_num}...")
        print(f"URL: {current_url}")
        
        try:
            # Fetch the category page
            print("  Fetching page content...")
            page_html = fetch_page(current_url, session)
            
            # Extract article links
            print("  Searching for article links...")
            article_links = extract_links(page_html, current_url)
            
            if not article_links:
                print("  No articles found on this page.")
            else:
                print(f"  Found {len(article_links)} article(s).")
                
                # Extract data from each article
                for idx, link in enumerate(article_links, 1):
                    try:
                        print(f"    Fetching article {idx}/{len(article_links)}...", end=" ")
                        article_html = fetch_page(link, session)
                        article_data = extract_article_data(article_html, link)
                        all_data.append(article_data)
                        print("OK")
                    except Exception as e:
                        print(f"FAILED ({str(e)[:30]})")
            
            # Look for next page
            print("  Looking for next page...")
            next_page = find_next_page_url(page_html, current_url)
            current_url = next_page
            
            if not next_page:
                print("  No next page found. Stopping.")
        
        except Exception as e:
            print(f"  Error processing page: {e}")
            break
    
    # Save to CSV
    print("\n" + "=" * 70)
    print(f"Saving results to {OUTPUT_FILE}...")
    
    try:
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['Title', 'Date', 'Description', 'Link']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=CSV_SEPARATOR)
            
            writer.writeheader()
            for row in all_data:
                writer.writerow(row)
        
        # Print summary
        print("=" * 70)
        print("Scraping completed successfully!")
        print("=" * 70)
        print(f"Pages processed: {page_num}")
        print(f"Articles extracted: {len(all_data)}")
        print(f"Output file: {OUTPUT_FILE}")
        print("=" * 70)
    
    except Exception as e:
        print(f"Error saving CSV: {e}")


if __name__ == '__main__':
    scrape_activities()
