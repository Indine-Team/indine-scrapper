# indine-scrapper

A Python/Selenium pipeline that scrapes restaurant listings and menus from [elmenus.com](https://elmenus.com) across configurable cities and areas, producing structured JSON menu data plus ready-made Google Maps search links for every restaurant collected.

The project runs in two stages:

1. **`list_expander.py`** — discovers restaurant URLs for each city/area combination.
2. **`scrapper.py`** — visits each restaurant URL, validates it, and extracts its full menu.

Both stages are built for long, unattended runs against a headless Chrome browser: they checkpoint their progress to disk, skip work that's already done, and recover automatically from browser crashes and memory exhaustion.

---

## How it works

```
data.json                    (cities → list of areas to scrape)
     │
     ▼
list_expander.py             opens each "top-restaurants" listing page,
     │                        clicks "load more" repeatedly, collects
     │                        every restaurant link
     ▼
restaurants/{city}_{area}_restaurants.json   (list of restaurant URLs)
     │
     ▼
scrapper.py                  visits every restaurant URL, validates it,
     │                        scrolls to load the full menu, expands
     │                        price-variant modals, parses items
     ▼
menus/{city}_{area}_menus.json               (full structured menu data)
menus/{city}_{area}_skipped.json             (log of skipped/failed URLs)
restaurants/{city}_{area}_restaurants_googleMaps.txt  (Maps search links)
```

`list_expander.py` also imports and calls `scrapper.py` directly at the end of each area's discovery step, so a single `python list_expander.py` run performs the entire pipeline end-to-end, city by city, area by area.

---

## Project structure

| File | Purpose |
|---|---|
| `data.json` | Input config — a dict of `{city: [area, area, ...]}` defining what to scrape. Ships pre-populated with Cairo and ~60 of its neighborhoods/districts. |
| `list_expander.py` | Stage 1: expands each area's restaurant listing page and collects restaurant URLs. |
| `scrapper.py` | Stage 2: visits each restaurant URL, validates it, and extracts menu items, pricing, and metadata. |
| `requirements.txt` | Python dependencies (`selenium`, `beautifulsoup4`). |
| `Dockerfile` | Container image with Google Chrome pre-installed, for running the scraper on a server. |

Generated at runtime (not checked in):

| Folder/File | Contents |
|---|---|
| `restaurants/{city}_{area}_restaurants.json` | Deduplicated list of restaurant detail-page URLs for that area. |
| `restaurants/{city}_{area}_restaurants_googleMaps.txt` | One Google Maps search link per scraped restaurant (`name + area + city`). |
| `menus/{city}_{area}_menus.json` | Full menu + metadata for every successfully scraped restaurant. |
| `menus/{city}_{area}_skipped.json` | Every URL that was skipped or failed, with a reason. |

---

## Requirements

- Python 3.10+
- Google Chrome installed locally (or use the provided Docker image)
- Dependencies from `requirements.txt`:
  - `selenium==4.21.0` (uses Selenium Manager, so it auto-downloads a matching ChromeDriver — no separate driver install needed)
  - `beautifulsoup4==4.12.3`

Install locally:

```bash
pip install -r requirements.txt
```

---

## Usage

### Run the full pipeline

```bash
python list_expander.py
```

This reads `data.json`, and for every `(city, area)` pair:
1. Skips discovery if `restaurants/{city}_{area}_restaurants.json` already exists.
2. Otherwise scrapes the listing page and writes the restaurant URL list.
3. Immediately runs `scrapper.py` against that URL list to pull menus.

### Run only the menu scraper

If restaurant URL lists already exist under `restaurants/`, you can re-run just the menu stage (e.g. to pick up new validation logic, or resume a partial run):

```bash
python scrapper.py
```

This processes every `*_restaurants.json` file found in `restaurants/`, skipping any restaurant already present in the corresponding `menus/{city}_{area}_menus.json`.

### Run with Docker

```bash
docker build -t indine-scrapper .
docker run -v $(pwd)/menus:/app/menus -v $(pwd)/restaurants:/app/restaurants indine-scrapper
```

Mounting `menus/` and `restaurants/` keeps scraped data on the host between container runs. The image defaults to `CMD ["python", "list_expander.py"]`, running the full pipeline.

---

## Restaurant validation rules

Not every restaurant found is scraped — `scrapper.py` filters out pages that don't meet quality thresholds before parsing a menu:

| Check | Result if it fails |
|---|---|
| Page has no menu at all (`"no food here"` / `"online menu is unavailable"`) | Skipped: `no_food_here` / `online_menu_unavailable` |
| Listing is delivery-only | Skipped: `delivery_only` |
| Average rating is below 2.0 | Skipped: `rating_below_2` |
| Fewer than 4,000 ratings | Skipped: `insufficient_reviews` |
| Restaurant name already exists in the area's menu file | Skipped: `already_scraped` |
| No menu section (`.cat-section`) appears after waiting | Skipped: `menu_not_found` |

All skips are logged with a reason to `menus/{city}_{area}_skipped.json` rather than silently discarded.

---

## Menu extraction details

For each qualifying restaurant, `scrapper.py`:

1. Scrolls the page repeatedly to trigger lazy-loaded menu items (up to 30 scrolls, or until item count stabilizes or hits a 200-item cap).
2. Parses each menu item's name, description, price, and category from the rendered HTML via BeautifulSoup.
3. Detects items with size/price variants (e.g. small/medium/large) and opens each item's modal individually to extract every size and its price, expanding one menu row into multiple priced entries.
4. Computes an `estimatedPrice` for the restaurant as the average price across items categorized as "Top Dishes".
5. Writes the result to `menus/{city}_{area}_menus.json` **incrementally after every restaurant**, so progress isn't lost if the run is interrupted.

### Output schema (per restaurant, in `menus/{city}_{area}_menus.json`)

```json
{
  "restaurant": "Restaurant Name",
  "averageRating": 4.3,
  "ratingsCount": 15234,
  "address": "Street address",
  "city": "cairo",
  "area": "maadi",
  "query_string": "Restaurant Name Maadi cairo",
  "url": "https://elmenus.com/...",
  "estimatedPrice": 180,
  "menu": [
    {
      "name": "Chicken Shawarma – Large",
      "description": "Grilled chicken, garlic sauce, pickles",
      "price": 220,
      "categoryName": "Top Dishes"
    }
  ]
}
```

`query_string` (restaurant + area + city) is also used to build a Google Maps search link for that restaurant, saved to `restaurants/{city}_{area}_restaurants_googleMaps.txt`.

---

## Resilience & performance features

The scraper is designed to run unattended for hours against many restaurants, so it includes several layers of self-recovery and memory hygiene:

- **Headless Chrome tuned for low memory use**: images disabled, remote fonts disabled, GPU disabled, JS heap capped (`--js-flags=--max-old-space-size=1024`), background timers/networking/renderer throttled off, single renderer process.
- **Proactive driver recycling**: the Chrome driver is fully restarted every 10 restaurants (`RESTART_EVERY`), before memory pressure has a chance to build up and crash the tab.
- **Crash recovery**: if the driver/tab crashes mid-scrape (`WebDriverException` / `InvalidSessionIdException`), the driver is rebuilt and the same URL is retried once before being marked as permanently skipped (`tab_crashed_retry_failed`).
- **Idempotent, resumable runs**: both stages check existing output files first and skip URLs/restaurants that are already recorded, so a run can be safely stopped and restarted at any point.
- **Timestamped checkpoint logging**: fine-grained `checkpoint()` log lines trace exactly where each restaurant is in the scrape (page load → metadata wait → menu wait → parsing), making it easy to diagnose where a hang or crash occurred.
- **Between-page cleanup**: navigates to `about:blank` and forces a V8 garbage collection between restaurants to release memory.
