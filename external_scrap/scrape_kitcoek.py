import requests
from bs4 import BeautifulSoup
import json
import time
from urllib.parse import urljoin

# List of all URLs to scrape
urls = [
    "https://www.kitcoek.in/",
    "https://www.kitcoek.in/about",
    "https://www.kitcoek.in/founder-trustees",
    "https://www.kitcoek.in/board-of-directors",
    "https://www.kitcoek.in/director",
    "https://www.kitcoek.in/office-administration",
    "https://www.kitcoek.in/milestones",
    "https://www.kitcoek.in/internal-quality-assurance-cell",
    "https://www.kitcoek.in/nirf",
    "https://www.kitcoek.in/aicte-approval",
    "https://www.kitcoek.in/manditory-disclosure",
    "https://www.kitcoek.in/admission-undergraduate",
    "https://www.kitcoek.in/admission-postgraduate",
    "https://www.kitcoek.in/scholarships",
    "https://www.kitcoek.in/apply-admission",
    "https://www.kitcoek.in/best-biotechnology-engineering-college-kolhapur-biotechnology-engineering-college",
    "https://www.kitcoek.in/best-civil-engineering-college-kolhapur-civil-engineering-college",
    "https://www.kitcoek.in/best-environmental-engineering-college-kolhapur-environmental-engineering-college",
    "https://www.kitcoek.in/best-cse-college-kolhapur-best-computer-science-engineering-college",
    "https://www.kitcoek.in/best-cse-college-kolhapur-best-computer-science-business-systems",
    "https://www.kitcoek.in/best-cse-college-kolhapur-best-computer-science-engineering-artificial-intelligence-machine-learning",
    "https://www.kitcoek.in/best-electrical-engineering-college-kolhapur-electrical-engineering-college",
    "https://www.kitcoek.in/best-mechanical-engineering-college-kolhapur-mechanical-engineering-college",
    "https://www.kitcoek.in/best-basic-science-and-humanities-engineering-college-kolhapur-basic-science-and-humanities-engineering-college",
    "https://www.kitcoek.in/online-syllabus",
    "https://www.kitcoek.in/studentClubs",
    "https://portal.coepvlab.ac.in/vlab/",
    "https://www.kitcoek.in/administration-staff",
    "https://www.kitcoek.in/semister-exam-timetable",
    "https://www.kitcoek.in/notice",
    "https://www.kitcoek.in/results",
    "https://www.kitcoek.in/paper-setting-documents",
    "https://www.kitcoek.in/remuneration-format",
    "https://www.kitcoek.in/tnp",
]

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

all_data = {}
failed_urls = []

for url in urls:
    print(f"Scraping: {url}")
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer"]):
            script.decompose()
        
        # Extract title
        title = soup.find('title')
        title_text = title.get_text(strip=True) if title else "No Title"
        
        # Extract meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        meta_description = meta_desc['content'] if meta_desc and meta_desc.get('content') else ""
        
        # Extract all text with structure
        # Get all elements that contain text
        text_content = []
        
        # Extract headings
        for i in range(1, 7):
            headings = soup.find_all(f'h{i}')
            for h in headings:
                text = h.get_text(strip=True)
                if text:
                    text_content.append(f"[H{i}] {text}")
        
        # Extract paragraphs
        paragraphs = soup.find_all('p')
        for p in paragraphs:
            text = p.get_text(strip=True)
            if text:
                text_content.append(f"[P] {text}")
        
        # Extract list items
        lists = soup.find_all(['ul', 'ol'])
        for lst in lists:
            items = lst.find_all('li')
            for item in items:
                text = item.get_text(strip=True)
                if text:
                    text_content.append(f"[LI] {text}")
        
        # Extract table content
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                row_text = ' | '.join(cell.get_text(strip=True) for cell in cells if cell.get_text(strip=True))
                if row_text:
                    text_content.append(f"[TABLE_ROW] {row_text}")
        
        # Extract div text (often contains important content)
        divs = soup.find_all('div')
        for div in divs:
            # Only get divs that have direct text (not just children)
            text = div.get_text(strip=True)
            # Filter out very short snippets and duplicates
            if text and len(text) > 20:
                # Check if this text is already captured
                is_duplicate = False
                for existing in text_content:
                    if text in existing or existing in text:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    text_content.append(f"[DIV] {text}")
        
        # Extract span text
        spans = soup.find_all('span')
        for span in spans:
            text = span.get_text(strip=True)
            if text and len(text) > 10:
                is_duplicate = False
                for existing in text_content:
                    if text in existing or existing in text:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    text_content.append(f"[SPAN] {text}")
        
        # Also get all visible text as a fallback
        full_text = soup.get_text(separator='\n', strip=True)
        
        all_data[url] = {
            'title': title_text,
            'meta_description': meta_description,
            'structured_text': text_content,
            'full_text': full_text
        }
        
        print(f"  ✓ Success - {len(text_content)} structured elements, {len(full_text)} chars")
        time.sleep(1)  # Be polite
        
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        failed_urls.append((url, str(e)))

# Save as JSON
with open('kitcoek_scraped_data.json', 'w', encoding='utf-8') as f:
    json.dump(all_data, f, ensure_ascii=False, indent=2)

# Save as Markdown for easy reading
with open('kitcoek_scraped_data.md', 'w', encoding='utf-8') as f:
    for url, data in all_data.items():
        f.write(f"\n{'='*80}\n")
        f.write(f"URL: {url}\n")
        f.write(f"Title: {data['title']}\n")
        f.write(f"{'='*80}\n\n")
        f.write(f"## Structured Content\n\n")
        for item in data['structured_text']:
            f.write(f"{item}\n\n")
        f.write(f"\n## Full Text\n\n")
        f.write(data['full_text'])
        f.write("\n\n")

# Save plain text for vector DB
with open('kitcoek_plain_text.txt', 'w', encoding='utf-8') as f:
    for url, data in all_data.items():
        f.write(f"\n{'='*80}\n")
        f.write(f"SOURCE: {url}\n")
        f.write(f"TITLE: {data['title']}\n")
        f.write(f"{'='*80}\n\n")
        f.write(data['full_text'])
        f.write("\n\n")

print(f"\n{'='*60}")
print(f"Scraping Complete!")
print(f"Total URLs attempted: {len(urls)}")
print(f"Successfully scraped: {len(all_data)}")
print(f"Failed: {len(failed_urls)}")
if failed_urls:
    print(f"\nFailed URLs:")
    for url, error in failed_urls:
        print(f"  - {url}: {error}")
print(f"\nFiles created:")
print(f"  - kitcoek_scraped_data.json (structured JSON)")
print(f"  - kitcoek_scraped_data.md (markdown format)")
print(f"  - kitcoek_plain_text.txt (plain text for vector DB)")
