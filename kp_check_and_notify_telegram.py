# kp_check_and_notify_telegram.py
import os, re, json, subprocess, time
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

# ============== CONFIG ==============

SEARCHES = [
    {"url": "https://www.kupujemprodajem.com/tv-i-video/tv-lcd-plazma-led/pretraga?categoryId=1054&groupId=640&priceFrom=70&priceTo=180&currency=eur&condition=used&condition=as-new&condition=new&ignoreUserId=no&order=posted%20desc&page=1", "name_filter": "SIZES"},
    {"url": "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s20&categoryId=23&groupId=75&priceFrom=65&priceTo=100&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&ignoreUserId=no&page=1", "name_filter": None},
    {"url": "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s21&categoryId=23&groupId=75&priceFrom=75&priceTo=125&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&ignoreUserId=no", "name_filter": None},
    {"url": "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s22&categoryId=23&groupId=75&priceFrom=80&priceTo=150&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&ignoreUserId=no", "name_filter": None},
    {"url": "https://www.kupujemprodajem.com/kompjuteri-laptop-i-tablet/tableti/pretraga?keywords=a9%2B&categoryId=1221&groupId=766&priceFrom=80&priceTo=180&currency=eur&condition=used&condition=as-new&condition=new&keywordsScope=description&hasPrice=yes&order=posted%20desc&ignoreUserId=no&page=1", "name_filter": "A9PLUS"},
    {"url": "https://www.kupujemprodajem.com/kompjuteri-laptop-i-tablet/laptopovi/pretraga?keywords=HP%20RYZEN&categoryId=1221&groupId=101&priceTo=350&currency=eur&condition=new&condition=as-new&condition=used&order=posted%20desc&ignoreUserId=no", "name_filter": None},
]

SIZES = ["40","42","43","46","47","48","49","50","55","60","4k","ultra hd","uhd","3840"]
A9_KEYWORDS = ["a9+", "a9 +", "a9plus", "a9 plus"]

USER_AGENT = "Mozilla/5.0"

STATE_FILE = ".kp_state.json"
GIT_RETRY = 3
GIT_RETRY_SLEEP = 2  # sec

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ============== HELPERS ==============

def log(*args):
    print("[kp]", *args)

def safe_slug(url):
    p = urlparse(url)
    return re.sub(r'[^0-9a-zA-Z_]', '_', (p.path + "?" + (p.query or "")))[:120]

def fetch_html(url):
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text

def parse_ads(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for sec in soup.select('section[class*="AdItem_adOuterHolder"]'):
        try:
            a = sec.select_one('a[href]')
            if not a: 
                continue
            link = urljoin("https://www.kupujemprodajem.com", a.get('href',''))
            title_tag = sec.select_one('.AdItem_name__iOZvA')
            title = title_tag.get_text(strip=True) if title_tag else ""
            # description: first p without svg inside .AdItem_adInfoHolder__Vljfb
            desc = ""
            info_holders = sec.select('.AdItem_adInfoHolder__Vljfb')
            if info_holders:
                for ih in info_holders:
                    for p in ih.find_all('p', recursive=False):
                        if p.find('svg'):
                            continue
                        txt = p.get_text(strip=True)
                        if txt:
                            desc = txt
                            break
                    if desc:
                        break
            price_tag = sec.select_one('.AdItem_price__VZ_at')
            price = price_tag.get_text(" ", strip=True) if price_tag else ""
            posted_svg = sec.select_one('.AdItem_postedStatus__4y6Ca svg')
            nonrenewed = False
            if posted_svg:
                fill = (posted_svg.get('fill') or "").strip().lower()
                if fill == "none":
                    nonrenewed = True
            out.append({"link": link, "title": title, "desc": desc, "price": price, "nonrenewed": nonrenewed})
        except Exception as e:
            # ignore single ad parsing errors
            continue
    return out

def name_match(ad, mode):
    text = (ad.get("title","") + " " + ad.get("desc","")).lower()
    if mode == "SIZES":
        return any(s in text for s in SIZES)
    if mode == "A9PLUS":
        return any(k in text for k in A9_KEYWORDS)
    return True

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log("State load error:", e)
            return {}
    return {}

def write_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def git_pull():
    # ensure we start from latest
    subprocess.run(["git","config","user.name","github-actions[bot]"], check=False)
    subprocess.run(["git","config","user.email","41898282+github-actions[bot]@users.noreply.github.com"], check=False)
    res = subprocess.run(["git","pull","--rebase","origin","main"], check=False)
    return res.returncode == 0

def git_commit_and_push():
    for attempt in range(1, GIT_RETRY+1):
        try:
            subprocess.run(["git","add", STATE_FILE], check=False)
            subprocess.run(["git","commit","-m","kp: update state [ci skip]"], check=False)
            # pull before push to avoid non-fast-forward
            subprocess.run(["git","pull","--rebase","origin","main"], check=False)
            res = subprocess.run(["git","push","origin","main"], check=False)
            if res.returncode == 0:
                log("git push succeeded")
                return True
            else:
                log(f"git push attempt {attempt} failed (code {res.returncode}). Retrying...")
        except Exception as e:
            log("git push exception:", e)
        time.sleep(GIT_RETRY_SLEEP)
    log("git push failed after retries")
    return False

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        log("Telegram env missing.")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": text})
        if r.status_code == 200:
            return True
        else:
            log("Telegram API error:", r.status_code, r.text)
            return False
    except Exception as e:
        log("Telegram send exception:", e)
        return False

# ============== MAIN ==============

def main():
    log("Starting. Doing initial git pull to sync state...")
    git_pull()

    state = load_state()  # dict: slug -> list of links
    if not isinstance(state, dict):
        state = {}

    all_new_ads = {}  # slug -> list of ad dicts (new only)
    new_state = {}    # slug -> current links (to be written)

    for cfg in SEARCHES:
        url = cfg["url"]
        mode = cfg.get("name_filter")
        slug = safe_slug(url)
        log("Processing", slug)
        try:
            html = fetch_html(url)
            ads = parse_ads(html)
            # keep only nonrenewed
            ads = [a for a in ads if a.get("nonrenewed")]
            # apply name filter if requested
            ads = [a for a in ads if name_match(a, mode)]
            current_links = [a["link"] for a in ads]
            old_links = set(state.get(slug, []))
            # new = those whose link not in old_links
            new_ads = [a for a in ads if a["link"] not in old_links]
            all_new_ads[slug] = new_ads
            new_state[slug] = current_links
            log(f"Found {len(ads)} ads (nonrenewed+filter). New: {len(new_ads)}")
        except Exception as e:
            log("Error processing", slug, e)
            all_new_ads[slug] = []
            new_state[slug] = state.get(slug, [])

    # write new_state to STATE_FILE locally
    write_state(new_state)

    # try to push the new state to remote; only if this succeeds we will send notifications
    if not git_commit_and_push():
        log("Aborting notifications because git push failed. This avoids duplicate notifications.")
        return

    # push succeeded -> send notifications for each search that has new ads
    total_new = 0
    for cfg in SEARCHES:
        slug = safe_slug(cfg["url"])
        new_ads = all_new_ads.get(slug, [])
        if not new_ads:
            continue
        total_new += len(new_ads)
        # build single message for this link (numeration from 1)
        lines = []
        for i, a in enumerate(new_ads, 1):
            lines.append(f"{i}. {a['title']}\n{a['desc']}\n{a['price']}\n{a['link']}")
        message = "\n\n".join(lines).strip()
        # send the message (one message per link)
        ok = send_telegram(message)
        if ok:
            # send separator message exactly as requested
            send_telegram("NOVI OGLASI\n.\n.")
        else:
            log("Warning: telegram send failed for", slug)
    log("Done. Total new ads notified:", total_new)

if __name__ == "__main__":
    main()
