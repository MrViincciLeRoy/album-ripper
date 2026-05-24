import os
import re
import json
import zipfile
import argparse
import requests
from bs4 import BeautifulSoup
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, APIC, USLT, error as ID3Error
import yt_dlp

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
})


def find_wiki_url(artist, album):
    params = {
        "action": "query",
        "list": "search",
        "srsearch": f"{artist} {album} album",
        "srlimit": 5,
        "format": "json"
    }
    r = SESSION.get("https://en.wikipedia.org/w/api.php", params=params)
    results = r.json().get("query", {}).get("search", [])
    for result in results:
        title = result["title"].lower()
        if "album" in title or album.lower().replace(".", "") in title.lower():
            slug = result["title"].replace(" ", "_")
            return f"https://en.wikipedia.org/wiki/{requests.utils.quote(slug)}"
    if results:
        slug = results[0]["title"].replace(" ", "_")
        return f"https://en.wikipedia.org/wiki/{requests.utils.quote(slug)}"
    return None


def get_wiki_tracklist(artist, album, output_dir):
    url = find_wiki_url(artist, album)
    if not url:
        return [], None, []

    print(f"  Wikipedia: {url}")
    soup = BeautifulSoup(SESSION.get(url).text, "html.parser")

    tracks = []
    for table in soup.find_all("table", class_="tracklist"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue

            th = row.find("th", {"scope": "row"})
            track_no = th.get_text(strip=True).rstrip(".") if th else None

            raw_text = cells[0].get_text(strip=True)
            quoted = re.findall(r'["\u201c]([^"\u201d]+)["\u201d]', raw_text)
            if quoted:
                title = quoted[0].strip()
            else:
                a_tag = cells[0].find("a")
                title = a_tag.get_text(strip=True) if a_tag else raw_text.strip('"')

            if not title or re.match(r'^\d+:\d+', title):
                continue

            writers = [li.get_text(strip=True) for li in cells[1].find_all("li")] if len(cells) > 1 else []
            producers = []
            if len(cells) > 2:
                producers = [li.get_text(strip=True) for li in cells[2].find_all("li")]
                if not producers:
                    producers = [cells[2].get_text(strip=True)]

            length_cell = row.find("td", class_="tracklist-length")
            length = length_cell.get_text(strip=True) if length_cell else None

            tracks.append({
                "track_no": track_no,
                "title": title,
                "writers": writers,
                "producers": producers,
                "length": length,
            })

    with open(os.path.join(output_dir, "tracklist.json"), "w") as f:
        json.dump({"album": album, "artist": artist, "tracks": tracks}, f, indent=2)

    return [t["title"] for t in tracks], url, tracks


def get_album_art(artist, album):
    try:
        url = f"https://itunes.apple.com/search?term={requests.utils.quote(artist + ' ' + album)}&entity=album&limit=1"
        results = SESSION.get(url).json().get("results", [])
        if not results:
            return None
        art_url = results[0].get("artworkUrl100", "").replace("100x100", "600x600")
        return SESSION.get(art_url).content if art_url else None
    except Exception as e:
        print(f"  Art error: {e}")
        return None


def wiki_length_to_seconds(length_str):
    if not length_str:
        return None
    try:
        parts = length_str.strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except:
        return None


def get_lyrics(artist, title, wiki_length=None):
    try:
        results = SESSION.get(
            "https://lrclib.net/api/search",
            params={"q": f"{artist} {title}"},
            timeout=10
        ).json()
        if not results:
            return None, False

        wiki_secs = wiki_length_to_seconds(wiki_length)
        best_lyrics = None
        best_synced = False
        best_score = -1

        for result in results:
            t = result.get("trackName", "").lower()
            a = result.get("artistName", "").lower()
            plain = result.get("plainLyrics")
            synced = result.get("syncedLyrics")
            lrc_dur = result.get("duration")

            if not plain and not synced:
                continue

            score = 0
            if artist.lower() in a:
                score += 2
            if title.lower() in t:
                score += 2

            synced_match = False
            if wiki_secs and lrc_dur:
                if abs(wiki_secs - float(lrc_dur)) <= 5:
                    score += 3
                    synced_match = True

            if score > best_score:
                best_score = score
                best_lyrics = synced if synced else plain
                best_synced = synced_match and synced is not None

        return (best_lyrics.strip() if best_lyrics else None), best_synced

    except Exception as e:
        print(f"  Lyrics error: {e}")
        return None, False


# No cookies passed to yt-dlp — cookies enroll the account in YouTube's SABR
# experiment which breaks web/web_creator, and also cause ios/android to be
# skipped. Anonymous ios+android bypass all of that cleanly.
def build_ydl_opts(extra=None):
    opts = {
        "quiet": True,
        "no_warnings": False,
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "android"],
            }
        },
    }
    if extra:
        opts.update(extra)
    return opts


def search_youtube_track(artist, title):
    clean_title = re.sub(r'\(feat.*?\)|\(featuring.*?\)', '', title, flags=re.IGNORECASE).strip()
    query = f"{artist} {clean_title} official audio"
    opts = build_ydl_opts({"extract_flat": True})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            results = ydl.extract_info(f"ytsearch5:{query}", download=False)
        entries = results.get("entries", [])
        for e in entries:
            t = e.get("title", "").lower()
            dur = e.get("duration") or 0
            if any(x in t for x in ["full album", "mix", "playlist", "432hz", "slowed", "reverb"]):
                continue
            if dur > 600:
                continue
            return f"https://www.youtube.com/watch?v={e['id']}"
        if entries:
            return f"https://www.youtube.com/watch?v={entries[0]['id']}"
    except Exception as e:
        print(f"  Search error: {e}")
    return None


def download_track(url, out_dir, track_num, title):
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
    fname = f"{track_num:02d} - {safe_title}"
    opts = build_ydl_opts({
        "format": "bestaudio/best",
        "outtmpl": os.path.join(out_dir, f"{fname}.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "noplaylist": True,
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    return f"{fname}.mp3"


def tag_mp3(filepath, title, artist, album, track_num, art_bytes, lyrics):
    try:
        tags = ID3(filepath)
    except ID3Error:
        tags = ID3()
    tags[TIT2] = TIT2(encoding=3, text=title)
    tags[TPE1] = TPE1(encoding=3, text=artist)
    tags[TALB] = TALB(encoding=3, text=album)
    tags[TRCK] = TRCK(encoding=3, text=str(track_num))
    if art_bytes:
        tags[APIC] = APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=art_bytes)
    if lyrics:
        tags[USLT] = USLT(encoding=3, lang="eng", desc="", text=lyrics)
    tags.save(filepath, v2_version=3)


def zip_output(output_dir, artist, album):
    safe_name = re.sub(r'[\\/*?:"<>|]', "", f"{artist} - {album}")
    zip_path = f"{output_dir}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in os.listdir(output_dir):
            fpath = os.path.join(output_dir, fname)
            zf.write(fpath, arcname=os.path.join(safe_name, fname))
    return zip_path


def main():
    parser = argparse.ArgumentParser(description="Album downloader")
    parser.add_argument("--artist", required=True)
    parser.add_argument("--album", required=True)
    parser.add_argument("--output", default="output")
    parser.add_argument("--cookies", default="cookies.txt")  # kept for compat, not used
    args = parser.parse_args()

    artist = args.artist
    album = args.album
    output_dir = os.path.join(args.output, f"{artist} - {album}")
    os.makedirs(output_dir, exist_ok=True)

    print(f"\nFetching tracklist for {artist} - {album}...")
    wiki_tracks, wiki_url, tracklist_data = get_wiki_tracklist(artist, album, output_dir)

    if not wiki_tracks:
        raise Exception("No tracklist found.")

    print(f"\nFound {len(wiki_tracks)} tracks:")
    for t in tracklist_data:
        print(f"  {int(t['track_no']):>2}. {t['title']} ({t['length']})")

    print("\nFetching album art...")
    art_bytes = get_album_art(artist, album)
    print("  ✓ Art fetched" if art_bytes else "  ✗ No art found")

    downloaded, failed = [], []

    print("\nDownloading tracks...\n")
    for i, track in enumerate(tracklist_data, 1):
        title = track["title"]
        wiki_length = track["length"]
        print(f"[{i}/{len(tracklist_data)}] {title}")

        yt_url = search_youtube_track(artist, title)
        if not yt_url:
            print("  ✗ No YouTube result")
            failed.append(title)
            continue

        print(f"  → {yt_url}")
        try:
            fname = download_track(yt_url, output_dir, i, title)
            fpath = os.path.join(output_dir, fname)
            lyrics, synced = get_lyrics(artist, title, wiki_length)
            tag_mp3(fpath, title, artist, album, i, art_bytes, lyrics)

            if lyrics and synced:
                lyr_status = "lyrics ✓ (synced)"
            elif lyrics:
                lyr_status = "lyrics ✓ (unsynced)"
            else:
                lyr_status = "no lyrics"

            print(f"  ✓ Done ({lyr_status})")
            downloaded.append(title)
        except Exception as e:
            print(f"  ✗ Failed: {e}")
            failed.append(title)

    print("\nZipping files...")
    zip_path = zip_output(output_dir, artist, album)
    print(f"  ✓ Zip created: {zip_path}")

    print("\n========== SUMMARY ==========")
    print(f"  Downloaded : {len(downloaded)}/{len(tracklist_data)}")
    if failed:
        print("  Failed:")
        for t in failed:
            print(f"    - {t}")
    else:
        print("  All tracks downloaded successfully.")
    print(f"\n  Zip: {zip_path}")

    with open("zip_path.txt", "w") as f:
        f.write(zip_path)


if __name__ == "__main__":
    main()
