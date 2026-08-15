import json

data = json.load(open('kitcoek_scraped_data.json', encoding='utf-8'))

print(f"{'URL':<75} {'Chars':>8} {'Elements':>10}")
print("=" * 95)
total = 0
for url, d in data.items():
    chars = len(d['full_text'])
    total += chars
    print(f"{url:<75} {chars:>8} {len(d['structured_text']):>10}")
print("=" * 95)
print(f"Total characters across all pages: {total:,}")
print(f"Total pages scraped: {len(data)}")
