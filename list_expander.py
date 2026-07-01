import time, json
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import re
import os

# ---------- config ----------
DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
BASE_URL = "https://elmenus.com/{city}/dineout/{area}/top-restaurants"
MAX_CLICKS = 20
CLICK_WAIT = 2
RESTAURANTS_FOLDER = "restaurants"
# ----------------------------

def extract_area_from_url(url):
    pattern = r"/dineout/([^/]+)/top-restaurants"
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    return "unknown_area"

def create_folders():
    os.makedirs(RESTAURANTS_FOLDER, exist_ok=True)
    print(f"Created folder: {RESTAURANTS_FOLDER}")

def scrape_restaurant_links(start_url):
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--start-maximized")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    
    area = extract_area_from_url(start_url)
    print(f"Opening list page for area: {area}")
    driver.get(start_url)

    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".card-content.clickable-item"))
        )
    except Exception:
        print(f"No restaurants found for area: {area}. Skipping.")
        driver.quit()
        return [], area
    
    # ---------- expand list ----------
    clicks = 0
    while clicks < MAX_CLICKS:
        try:
            btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.load-more-btn"))
            )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(0.2)
            driver.execute_script("arguments[0].click();", btn)
            clicks += 1
            print(f"Clicked load-more: {clicks}/{MAX_CLICKS}")
            time.sleep(CLICK_WAIT)
        except Exception:
            print("No more load-more button found or clickable. Stopping expansion.")
            break
    
    time.sleep(1)
    
    # ---------- collect every link ----------
    cards = driver.find_elements(By.CSS_SELECTOR, "div.card-content.clickable-item")
    hrefs = []
    for card in cards:
        anchor = card.find_elements(By.CSS_SELECTOR, "a.clickable-anchor")
        if anchor:
            href = anchor[0].get_attribute("href")
            if href and not href.lower().startswith("javascript"):
                hrefs.append(href.strip())
    
    hrefs = list(dict.fromkeys(hrefs))
    print(f"Collected {len(hrefs)} unique restaurant hrefs")
    if hrefs:
        print(f"Sample URL: {hrefs[0][:80]}...")
    
    driver.quit()
    return hrefs, area

def extract_city_from_url(url):
    """Extract city from URL path: .../cairo/... → 'cairo'"""
    path = urlparse(url).path.strip("/")
    if path:
        parts = path.split("/")
        if parts:
            return parts[0]  # first segment is the city
    return None

def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def scrape_city_area(city, area):
    url = BASE_URL.format(city=city, area=area)
    print(f"\n{'='*50}")
    print(f"SCRAPING: {city} / {area}")
    print(f"URL: {url}")
    print(f"{'='*50}")

    hrefs, _ = scrape_restaurant_links(url)

    area_file = os.path.join(RESTAURANTS_FOLDER, f"{city}_{area}_restaurants.json")
    existing_urls = set()
    if os.path.exists(area_file):
        with open(area_file, "r", encoding="utf-8") as f:
            existing_urls = set(json.load(f))

    new_urls = [u for u in hrefs if u not in existing_urls]
    duplicates = len(hrefs) - len(new_urls)
    print(f"Found {len(hrefs)} total, {len(new_urls)} new, {duplicates} duplicates removed")

    if new_urls:
        all_urls = list(existing_urls) + new_urls
        with open(area_file, "w", encoding="utf-8") as f:
            json.dump(all_urls, f, ensure_ascii=False, indent=2)
        print(f"✓ Saved {len(new_urls)} new URLs to {area_file} (total: {len(all_urls)})")

    return area_file

def main():
    create_folders()
    data = load_data()

    from scrapper import scrape_menus, create_menu_folders
    create_menu_folders()

    for city, areas in data.items():
        print(f"\n{'#'*60}")
        print(f"# CITY: {city} ({len(areas)} areas)")
        print(f"{'#'*60}")

        for area in areas:
            area_file = scrape_city_area(city, area)
            if os.path.exists(area_file):
                print(f"\n  SCRAPING MENUS FOR: {city} / {area}")
                scrape_menus(area_file)

    print(f"\n{'='*60}")
    print("ALL CITIES COMPLETED!")
    print(f"{'='*60}")

    from upload import upload_results
    upload_results()

if __name__ == "__main__":
    main()