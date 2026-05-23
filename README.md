# Album Ripper

Downloads a full album as tagged MP3s with embedded lyrics and album art, then zips everything up.

## GitHub Actions (recommended)

1. Go to **Actions → Download Album → Run workflow**
2. Enter the artist name and album name
3. Once done, download the zip from the **Artifacts** section of the run

## Local

```bash
pip install -r requirements.txt
sudo apt install ffmpeg  # or brew install ffmpeg on mac

python download.py --artist "Kendrick Lamar" --album "DAMN."
```

Output goes to `output/Artist - Album/` and a zip is created alongside it.

## What it does

- Finds the album tracklist from Wikipedia
- Downloads each track from YouTube as 192kbps MP3
- Fetches synced lyrics from lrclib.net and embeds them into the MP3
- Embeds album art from iTunes
- Zips everything into one file
