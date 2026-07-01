import time, json
import os
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException
from urllib.parse import unquote, urlparse, quote
import re
import hashlib
from urllib.parse import unquote, urlparse

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────
MENUS_FOLDER = "menus"
RESTAURANTS_FOLDER = "restaurants"

FAKE_CUISINE_TAGS = {
    "MADE IN EGYPT",
    "SUPPORT GAZA",
    "100% EGYPTIAN",
    "EGYPTIAN MADE"
}

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def create_menu_folders():
    os.makedirs(MENUS_FOLDER, exist_ok=True)
    print(f"Created menu folder: {MENUS_FOLDER}")

def extract_area_from_filename(filename):
    pattern = r"(.+)_restaurants\.json"
    match = re.search(pattern, os.path.basename(filename))
    if match:
        return match.group(1)
    return "unknown_area"

def extract_city_from_url(url):
    """Extract city from URL path: .../cairo/... → 'cairo'"""
    path = urlparse(url).path.strip("/")
    if path:
        parts = path.split("/")
        if parts:
            return parts[0]  # first segment is the city
    return None

def has_no_menu(soup):
    """
    Detect pages that explicitly state they have no menu.
    Returns (True, reason_string) if no menu is found, else (False, None).
    """
    h2 = soup.find("h2", class_="title")
    print(f"Checking for no-menu indicators: {h2.get_text(strip=True) if h2 else 'No H2 found'}")
    if h2 and "no food here" in h2.get_text(strip=True).lower():
        return True, "no_food_here"

    h3 = soup.find("h3", class_="state-title")
    print(f"Checking for no-menu indicators: {h3.get_text(strip=True) if h3 else 'No H3 found'}")
    if h3 and "online menu is unavailable" in h3.get_text(strip=True).lower():
        return True, "online_menu_unavailable"

    return False, None

def final_price(txt: str) -> int:
    numbers = re.findall(r'\d+(?:\.\d+)?', txt.replace(',', ''))
    if not numbers:
        return None
    numeric_values = [float(num) for num in numbers]
    return int(min(numeric_values))

def close_modal(driver):
    try:
        WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.close-modal,button[data-dismiss='modal']"))
        ).click()
        time.sleep(.5)
    except Exception:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(.5)

def debug_modal_content(driver):
    try:
        modal = driver.find_element(By.CSS_SELECTOR, ".modal.fade.in, .modal.show")
        modal_html = modal.get_attribute("outerHTML")
        print("=" * 50)
        print("MODAL CONTENT:")
        print("=" * 50)
        print(modal_html[:2000])
        print("=" * 50)
        all_elements = modal.find_elements(By.CSS_SELECTOR, "*")
        for elem in all_elements[:20]:
            print(f"Tag: {elem.tag_name}, Text: {elem.text[:50] if elem.text else ''}")
    except Exception as e:
        print(f"Debug modal failed: {e}")

# ──────────────────────────────────────────────────────────────
# Stage 1 — Metadata extractors (used for validation)
# ──────────────────────────────────────────────────────────────
def extract_cuisines(soup):
    cuisines = []
    ul = soup.select_one("ul.cuisines-list.h-dots-list")
    if ul:
        for li in ul.select("li"):
            text = li.get_text(strip=True)
            if text and text.upper() not in FAKE_CUISINE_TAGS:
                cuisines.append(text)
    return cuisines

def extract_rating_value(soup):
    """Extract numeric rating from the star-rating widget."""
    rating_span = soup.select_one("div.rest-rate span.vue-star-rating-rating-text")
    if rating_span:
        text = rating_span.get_text(strip=True)
        match = re.search(r"[\d.]+", text)
        if match:
            return float(match.group())
    return None

def extract_ratings_count(soup):
    reviews_el = soup.select_one("a.reviews")
    if reviews_el:
        text = reviews_el.get_text(strip=True)
        match = re.search(r'\d+', text.replace(',', ''))
        if match:
            return int(match.group())
    return 0

def extract_restaurant_name(soup, fallback_url):
    name_el = soup.select_one("div.resturant-name h1")
    if name_el:
        span_el = name_el.select_one("span.green")
        if span_el:
            span_el.extract()
        name = name_el.get_text(strip=True)
        if('online' in name.lower()):
            name = name.replace("Order online", "")
        if name:
            print(f"Restaurant name found: '{name}'")
            return name
    name_match = re.search(r"/([^/]+)/?$", fallback_url)
    fallback = unquote(name_match.group(1)) if name_match else "unknown_restaurant"
    print(f"⚠️  Used fallback name: {fallback}")
    return fallback

def extract_area(soup):
    """
    Extract the area name from the anchor tag inside the location info-value.
    Example: <p class="info-value"><a href="...">Maadi</a></p> → returns "Maadi"
    """
    for item in soup.select("div.info-item"):
        if item:
            val = item.select_one("p.info-value")
            if val:
                anchor = val.select_one("a.address-link")
                if anchor:
                    area = anchor.get_text(strip=True)
                    return area
                # fallback: return full text if no anchor
                return val.get_text(strip=True)
    return None

def extract_location(soup):
    for item in soup.select("div.info-item"):
        val = item.select_one("p.info-value")
        if not val:
            continue
        
        anchor = val.select_one("a.address-link")
        area = anchor.get_text(strip=True) if anchor else None
        
        address = val.get_text(strip=True)
        if area:
            address = address.replace(area, "").strip()
        
        if address:
            return address
    return None
def is_delivery_only_page(soup):
    """Detect delivery-only from the detail-page address/location text."""
    area = extract_location(soup)
    if area and "delivery only" in area.lower():
        return True
    return False

# ──────────────────────────────────────────────────────────────
# Stage 2 — Menu parser
# ──────────────────────────────────────────────────────────────
def calculate_estimated_price(menu_items):
    if not menu_items:
        return None
    top_prices = [
        item['price'] for item in menu_items
        if item.get('categoryName', '').strip().lower() == 'top dishes'
        and item.get('price') is not None
    ]
    if not top_prices:
        return None
    return round(sum(top_prices) / len(top_prices))

def parse_menu(soup, driver, restaurant_url):
    items = []

    # ── 1. Scroll to load all lazy items ──
    print("  [DEBUG] Scrolling to load all menu items...")
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
    print(f"  [DEBUG] Final page height: {last_height}")

    # ── 2. Get fresh soup and live DOM elements after scrolling ──
    fresh_html = driver.page_source
    soup = BeautifulSoup(fresh_html, "html.parser")
    all_item_els = driver.find_elements(By.CSS_SELECTOR, '.menu-item.clickable-item')
    soup_items = soup.select('.menu-item.clickable-item')
    
    print(f"  [DEBUG] Live DOM items: {len(all_item_els)}")
    print(f"  [DEBUG] Soup items: {len(soup_items)}")

    # ── 3. Identify variant indices (price ranges) from live DOM ──
    variant_indices = set()
    for i, el in enumerate(all_item_els):
        try:
            p = el.find_element(By.CSS_SELECTOR, 'p.price')
            if p and '-' in p.text:
                variant_indices.add(i)
        except Exception:
            pass
    print(f"  [DEBUG] {len(variant_indices)} items have price ranges")

    # ── 4. Extract size variants by clicking each variant item (modal) ──
    cache = {}
    for idx in variant_indices:
        el = all_item_els[idx]
        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});", el
            )
            time.sleep(0.2)

            btn = el.find_element(By.CSS_SELECTOR, 'a.clickable-anchor')
            driver.execute_script("arguments[0].click();", btn)

            modal = None
            for _ in range(30):
                time.sleep(0.1)
                try:
                    modal = driver.find_element(
                        By.CSS_SELECTOR, '.modal.show, .modal.in, .modal.fade.in'
                    )
                    modal.find_element(By.CSS_SELECTOR, 'li.size span.cost')
                    break
                except Exception:
                    modal = None

            if not modal:
                print(f"  [DEBUG] Item {idx}: modal never appeared")
                continue

            sizes = []
            for li in modal.find_elements(By.CSS_SELECTOR, 'li.size'):
                try:
                    n = li.find_element(By.CSS_SELECTOR, 'p.input-label').text.strip()
                    v = li.find_element(By.CSS_SELECTOR, 'span.cost').text.strip()
                    if n and v:
                        sizes.append({'n': n, 'v': v})
                except Exception:
                    pass

            if sizes:
                cache[idx] = sizes
                print(f"  [DEBUG] Item {idx}: extracted {len(sizes)} size options")

            # close modal
            try:
                close_btn = modal.find_element(
                    By.CSS_SELECTOR, '[data-dismiss="modal"], .close, .modal .btn-close'
                )
                driver.execute_script("arguments[0].click();", close_btn)
            except Exception:
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()

            time.sleep(0.2)

        except Exception as e:
            print(f"  [DEBUG] Item {idx}: failed to expand ({e})")

    # ── 5. Build final items list (without item_id) ──
    for idx, it in enumerate(soup_items):
        cat_section = it.find_parent('div', class_='cat-section')
        if cat_section:
            section_title = cat_section.select_one('h2.section-title')
            if section_title:
                category_name = section_title.get_text(strip=True)
            else:
                section_title = cat_section.select_one('h3.section-title')
                if section_title:
                    span_el = section_title.select_one("span.count")
                    if span_el:
                        span_el.extract()
                    category_name = section_title.get_text(strip=True)
                else:
                    category_name = "Uncategorized"
        else:
            category_name = "Uncategorized"

        name_el = it.select_one('h5.title') or it.select_one('.title')
        name = name_el.get_text(strip=True) if name_el else "Unknown"

        desc_el = it.select_one('p.description')
        desc = desc_el.get_text(strip=True) if desc_el else ""

        price_el = it.select_one('p.price')
        pr = price_el.get_text(strip=True) if price_el else ""
        base = final_price(pr)

        if idx in cache:
            for sz in cache[idx]:
                item_name = f"{name} – {sz['n']}"
                items.append({
                    'name': item_name,
                    'description': desc,
                    'price': final_price(sz['v']),
                    'categoryName': category_name
                })
        else:
            items.append({
                'name': name,
                'description': desc,
                'price': base,
                'categoryName': category_name
            })

    print(f"  [DEBUG] parse_menu returning {len(items)} items")
    return items

# ──────────────────────────────────────────────────────────────
# Stage 1 — Validation (modified schema)
# ──────────────────────────────────────────────────────────────
def validate_restaurant(soup, url):
    """
    Returns (is_valid, reason, metadata).
    Reasons: delivery_only, rating_below_2, insufficient_reviews
    """
    name = extract_restaurant_name(soup, url)
    rating_value = extract_rating_value(soup)
    ratings_count = extract_ratings_count(soup)
    area = extract_area(soup)
    address = extract_location(soup)
    city = extract_city_from_url(url)

    # Build query_string: "restaurantName area city" (trim if some missing)
    parts = [name, area, city]
    query_string = " ".join(p for p in parts if p)

    metadata = {
        "restaurant": name,
        "averageRating": rating_value,
        "ratingsCount": ratings_count,
        "address": address,
        "city": city,
        "area": area,
        "query_string": query_string
    }

    if is_delivery_only_page(soup):
        return False, "delivery_only", metadata
    if rating_value < 2.0:
        return False, "rating_below_2", metadata
    if ratings_count < 100:
        return False, "insufficient_reviews", metadata

    return True, None, metadata

# ──────────────────────────────────────────────────────────────
# Core scraper
# ──────────────────────────────────────────────────────────────
def scrape_menus(input_file):
    # ---- determine city from filename or first URL ----
    city = None
    base = os.path.basename(input_file)   # e.g., "cairo_restaurants.json"
    if base.endswith("_restaurants.json"):
        city = base[:-len("_restaurants.json")]
    if not city:
        city = "unknown_city"

    # ---- load restaurant list (city file is a JSON array of URLs) ----
    raw = json.load(open(input_file, encoding="utf-8"))
    # Convert to list of dicts if they are plain strings
    if isinstance(raw, list) and raw and isinstance(raw[0], str):
        restaurants = [{"name": None, "url": u} for u in raw]
    else:
        restaurants = raw

    if not restaurants:
        print(f"No restaurants to process in {input_file}")
        return

    # sanity check: city can also be extracted from the first URL
    if city == "unknown_city":
        city = extract_city_from_url(restaurants[0]["url"]) or "unknown_city"

    print(f"Scraping menus for city: {city} (total restaurants: {len(restaurants)})")

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--start-maximized")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=opts)
    committed_data = []
    skipped_data = []

    # ---- process every restaurant in the list ----
    for r in restaurants:
        url = r["url"]
        print(f"\nProcessing {url}")
        try:
            driver.get(url)

            # Step 1: wait for page body
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "body"))
                )
            except TimeoutException:
                print(f" ⏭️  Skipped: page_did_not_load")
                skipped_data.append({"url": url, "reason": "page_did_not_load"})
                continue

            soup = BeautifulSoup(driver.page_source, "html.parser")

            # Step 2: early no‑menu check
            no_menu, no_menu_reason = has_no_menu(soup)
            if no_menu:
                print(f" ⏭️  Skipped: {no_menu_reason}")
                skipped_data.append({"url": url, "reason": no_menu_reason})
                continue

            # Step 3: wait for metadata widget
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((
                        By.CSS_SELECTOR,
                        "div.vue-star-rating, div.resturant-name h1"
                    ))
                )
            except TimeoutException:
                print(f" ⏭️  Skipped: missing_metadata")
                skipped_data.append({"url": url, "reason": "missing_metadata"})
                continue

            soup = BeautifulSoup(driver.page_source, "html.parser")

            # Step 4: validate (rating, reviews, delivery‑only)
            is_valid, reason, metadata = validate_restaurant(soup, url)
            if not is_valid:
                print(f" ⏭️  Skipped: {reason}")
                skipped_data.append({**metadata, "reason": reason})
                continue

            # Step 5: wait for menu sections
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".cat-section"))
                )
            except TimeoutException:
                print(f" ⏭️  Skipped: menu_not_found")
                skipped_data.append({**metadata, "reason": "menu_not_found"})
                continue

            soup = BeautifulSoup(driver.page_source, "html.parser")
            menu = parse_menu(soup, driver, url)
            estimated = calculate_estimated_price(menu)

            committed_data.append({
                **metadata,
                "estimatedPrice": estimated,
                "menu": menu
            })
            print(f" ✅ Committed with {len(menu)} menu items")
            time.sleep(1)

        except TimeoutException as te:
            print(f" ⏭️  Skipped: timeout ({te})")
            skipped_data.append({"url": url, "reason": "timeout", "error": str(te)})
        except Exception as e:
            print(f" ❌ Failed: {e}")
            skipped_data.append({"url": url, "reason": "exception", "error": str(e)})

    driver.quit()

    google_maps_links = []
    # collect from committed (all entries that have query_string)
    for item in committed_data:
        qs = item.get('query_string')
        if qs:
            link = f"https://www.google.com/maps/search/{quote(qs)}?hl=en"
            google_maps_links.append(link)

    # remove duplicates while preserving order
    unique_links = list(dict.fromkeys(google_maps_links))

    gmaps_filename = f"{city}_restaurants_googleMaps.txt"
    gmaps_path = os.path.join(RESTAURANTS_FOLDER, gmaps_filename)
    with open(gmaps_path, "w", encoding="utf-8") as f:
        f.write("\n".join(unique_links))

    if unique_links:
        print(f"Saved {len(unique_links)} Google Maps links to {gmaps_path}")
    # ---- Append to city menus file (deduplicate by URL) ----
    city_menus_file = os.path.join(MENUS_FOLDER, f"{city}_menus.json")
    existing_menus = []
    if os.path.exists(city_menus_file):
        with open(city_menus_file, "r", encoding="utf-8") as f:
            existing_menus = json.load(f)
        print(f"Loaded {len(existing_menus)} existing menus from {city_menus_file}")

    existing_urls = {item.get("url") for item in existing_menus if "url" in item}
    new_committed = [item for item in committed_data if item.get("url") not in existing_urls]
    duplicates = len(committed_data) - len(new_committed)
    print(f"New restaurants to add: {len(new_committed)}, duplicates skipped: {duplicates}")

    if new_committed:
        all_menus = existing_menus + new_committed
        with open(city_menus_file, "w", encoding="utf-8") as f:
            json.dump(all_menus, f, ensure_ascii=False, indent=2)
        print(f"✓ Saved {len(all_menus)} total menus to {city_menus_file}")

    # Save skipped log per city (append)
    city_skipped_file = os.path.join(MENUS_FOLDER, f"{city}_skipped.json")
    existing_skipped = []
    if os.path.exists(city_skipped_file):
        with open(city_skipped_file, "r", encoding="utf-8") as f:
            existing_skipped = json.load(f)
    all_skipped = existing_skipped + skipped_data
    with open(city_skipped_file, "w", encoding="utf-8") as f:
        json.dump(all_skipped, f, ensure_ascii=False, indent=2)
    if skipped_data:
        print(f"Skipped {len(skipped_data)} restaurants, log saved to {city_skipped_file}")

    return city_menus_file

# ──────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────
def main():
    create_menu_folders()

    if not os.path.exists(RESTAURANTS_FOLDER):
        print("Restaurant folder not found. Run list_expander.py first.")
        return

    # Get all city restaurant list files
    files = [os.path.join(RESTAURANTS_FOLDER, f)
             for f in os.listdir(RESTAURANTS_FOLDER)
             if f.endswith('_restaurants.json')]

    if not files:
        print("No restaurant list files found. Run list_expander.py first.")
        return

    for file_path in files:
        scrape_menus(file_path)

    print("\n" + "=" * 50)
    print("Scraping completed!")
    print(f"Menus saved to: {MENUS_FOLDER}/")
    print("=" * 50)

if __name__ == "__main__":
    main()