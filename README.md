# ChekhovsGun

**English** · [简体中文](README.zh-CN.md)

> If a gun hangs on the wall in the first act, it must go off in the third.
> Everything you bookmark deserves the same.

**The things you saved come find you — right when you're scrolling past something related.**

We've all done it: you stumble onto a genuinely great tutorial, hit save, tell yourself
you'll watch it later, and it stays in that folder forever. ChekhovsGun inverts the
problem. Instead of hoping you'll remember to dig through your bookmarks, it waits until
you're **actually watching** something related and tells you "you already saved this" —
then reads you the relevant passage from what you saved.

Everything runs locally. Your bookmarks and your watch history never leave this machine.

<!-- YouTube and Bilibili are both supported, and saves on one side can fire on the
     other: a Chinese explainer you saved can surface while you're watching an English
     video, and vice versa. -->

---

## How it works

```
  Bookmarks                  Index                     While you scroll
┌──────────┐  subs / desc  ┌──────────────┐          ┌──────────────┐
│ YouTube  │──────────────▶│ chunks + vec │          │  extension   │
│  saves   │               │  + BM25 idx  │◀─────────│  sees the    │
│ Bilibili │──────────────▶│    SQLite    │  hybrid  │ current video│
└──────────┘               └──────────────┘retrieval └──────┬───────┘
                                   │                        │
                                   └────── matching save ───▶│  card pops
                                          + a short read     └──────────┘
```

1. **Ingest** — Pull saved videos from YouTube playlists / Liked / Watch Later and from
   Bilibili favorite folders and Watch Later, along with their subtitles (both Bilibili's
   human CC tracks and its AI-generated ones) and **top comments**. Videos with no
   subtitles at all fall back to local Whisper transcription.
2. **Index** — Cut subtitles into timestamped passages along the timeline, embed them,
   and build a BM25 inverted index alongside.
3. **Retrieve** — Hybrid retrieval fused with RRF, plus a separate **confidence** score
   that decides whether this is worth interrupting you at all.
4. **Fire** — The browser extension recognizes the video you're on; on a hit it floats a
   card, and clicking through jumps straight to the second where your saved video covers
   that exact thing.
5. **Holster** — When you've watched it, hit "digested" and it stops bothering you.
   That number — not the number of popups — is this project's success metric.

---

## Run it in 30 seconds

No API keys needed. See what it looks like first:

```bash
git clone https://github.com/JaspinXu/ChekhovsGun.git
cd ChekhovsGun
pip install -e .

chekhovsgun demo      # load sample saves and run one retrieval
chekhovsgun tray      # background daemon + tray icon, opens the dashboard
```

Don't want to install Python? [Releases](https://github.com/JaspinXu/ChekhovsGun/releases)
has a packaged single-file build — just double-click it. `chekhovsgun serve` remains the
equivalent foreground version.

`demo` prints something like this:

```
pretending you just scrolled onto:
  Why is my retrieval so bad? Chunking and hybrid search explained

  ChekhovsGun says:
    You already saved 1 related item(s); the closest is “How Vector Databases
    Actually Work” by Engineering Deep Dives. From it: …the real failure mode of
    pure vector search is exact terminology. Hybrid search with BM25 fixes the
    cases where embeddings blur a precise term.

  1. How Vector Databases Actually Work
     Engineering Deep Dives · youtube · Watch Later · score 1.00
     https://www.youtube.com/watch?v=Xpzbywj7HbQ&t=1000s
     [16:40] The real failure mode of pure vector search is exact terminology…
```

A Chinese query will hit English saves and the other way around — which is the whole
point of wiring up Bilibili and YouTube at the same time.

---

## Connect your own bookmarks

### Bilibili

Bilibili has no public API, so it uses the cookie from your browser. On a logged-in
bilibili.com page press F12 → Application → Cookies and copy `SESSDATA`:

```bash
export CHEKHOVSGUN_BILIBILI_SESSDATA="your SESSDATA"
export CHEKHOVSGUN_BILIBILI_UID="your uid"        # optional, auto-detected if omitted

chekhovsgun ingest --source bilibili --limit 20   # try 20 first
chekhovsgun ingest --source bilibili              # full sync
```

By default it syncs **every** folder you created, plus Watch Later. To restrict it to a
few:

```bash
export CHEKHOVSGUN_BILIBILI_FOLDERS="deep-learning,backend"   # folder names or media_ids
```

> SESSDATA lasts about a month; just copy a fresh one when it expires.
> It only ever lives in your own environment variables or `config.toml` — it is never
> sent anywhere.

### YouTube

Public and unlisted playlists need nothing but an API key (Google Cloud → enable the
YouTube Data API v3):

```bash
export CHEKHOVSGUN_YOUTUBE_API_KEY="AIza..."
export CHEKHOVSGUN_YOUTUBE_PLAYLISTS="PLxxxxxxxx,PLyyyyyyyy"

chekhovsgun ingest --source youtube
```

Liked (`LL`) and Watch Later (`WL`) are private to the account and need an OAuth access
token:

```bash
export CHEKHOVSGUN_YOUTUBE_OAUTH_TOKEN="ya29..."
chekhovsgun ingest --source youtube      # with no playlists set, grabs LL and WL
```

For better subtitle coverage, install the community transcript library:

```bash
pip install -e ".[youtube]"
```

### Don't want to configure any of it?

Any json / jsonl / csv / plain list of links imports directly:

```bash
chekhovsgun import my-saves.json          # Google Takeout exports work
chekhovsgun import urls.txt               # one link per line
```

---

## Install the browser extension

1. Open `chrome://extensions` in Chrome / Edge
2. Turn on "Developer mode" in the top right
3. Click "Load unpacked" and pick this repo's `extension/` directory
4. Make sure `chekhovsgun serve` is running

From then on, opening any video on YouTube or Bilibili floats a card in the bottom right
if something related is sitting in your bookmarks. Click the title bar to collapse it, ×
to dismiss, and "don't remind me about this video" to mute it until the browser restarts.

The extension talks only to `http://127.0.0.1:8700` and makes no other network requests.
Port, cooldown, and per-site enablement are all editable in the extension's options page.

---

## Three content sources

**Subtitles** do the heavy lifting. Bilibili's CC and AI tracks are both collected, with
human ones preferred; YouTube goes through the player route.

**Comments** are a goldmine most comparable tools ignore. Top comments routinely contain
what the video itself doesn't: corrections, the prerequisite the author skipped, "this
actually changed after 7.0." They're plain text and arrive in a single request — the best
value-per-byte content in the project.

```bash
chekhovsgun ingest --no-comments    # if you'd rather not
```

**Local transcription** is the fallback. In a real bookmark folder roughly a third of the
videos have neither kind of subtitle; those used to enter the index on title and
description alone, which retrieves badly and can't deep-link. faster-whisper now fills
them in locally:

```bash
pip install -e ".[whisper]"     # faster-whisper + yt-dlp
chekhovsgun ingest --source bilibili
```

Audio never leaves the machine. Because transcription is a minutes-scale rather than
milliseconds-scale operation, it has two gates: skip any single video over 45 minutes, and
spend at most 30 minutes per sync on transcription (both configurable). It hangs off the
pipeline rather than living inside an adapter — it works given any URL, so a third source
gets it for free.

---

## The life of a save

A save has three states, which exist to answer "what happens after it fires":

| State | Meaning | Still pops? | Counts toward digestion rate? |
| --- | --- | --- | --- |
| Active | Default | Yes | — |
| **Digested** | You went back, watched it, learned something | No | **Yes** |
| Muted | Stop bringing this up | No | No |

```bash
chekhovsgun mark https://www.bilibili.com/video/BV1xx --digested --tag attention
chekhovsgun items --status active          # what you still owe yourself
chekhovsgun items --tag attention
```

The card has a "✓ digested" button right on it, and the dashboard filters by state and
tag.

Two design details: **muting stops interruptions but not retrieval** — it still shows up
when you search deliberately; and **re-syncing never overwrites your marks**. `upsert`
deliberately leaves the `status` / `user_tags` / `note` columns alone, otherwise a nightly
sync would resurrect everything you'd already digested.

---

## How retrieval works (and why)

This is the part of the project that actually required thinking.

**Hybrid retrieval.** The default vector backend is a zero-dependency hashed n-gram
encoder — it works straight out of a clone, with no API key and no model download. The
price is that it has no real semantics and is easily fooled by text in the same register
on an unrelated topic. BM25's failure mode is exactly the opposite: dead accurate on
proper nouns (`KV cache`, `BV1xx4y1`), completely blind to paraphrase. Run both and fuse
with **RRF** — RRF looks only at ranks, not scores, so there's nothing to calibrate
between two scales that have nothing in common, and one outlier score can't drag the
result off course.

**Chinese tokenization.** Chinese has no spaces, so splitting on whitespace turns an
entire sentence into a single token. This uses CJK **character bigrams** combined with
Latin words, and the vector path and the BM25 path share the same tokenizer so both recall
routes see identical text.

**Confidence and ranking are two different things.** An RRF score can order results but
can't answer "should this pop up at all" — its range drifts with corpus size. So
confidence is computed separately on a 0–1 scale: vector cosine × IDF-weighted coverage of
the query terms, and if neither is high the result is judged irrelevant. A few details
matter:

- **Terms absent from the corpus don't count in the denominator.** "How I made my React
  app 10x faster" should be judged on `react` alone, not diluted by four words that could
  never appear in your saves.
- **Coverage is computed per writing system.** Chinese query terms can never appear in
  English subtitles; counting them in the denominator would make every cross-language hit
  look irrelevant — and cross-language is exactly this project's most valuable case.
- **A single matching term is not evidence.** "How do I braise pork" and a Redis explainer
  both contain "how do I." Coverage decays with saturation over the number of matched
  terms, so one term earns at most about 56% of the score.

**At most N passages per save.** A 40-minute lecture cuts into dozens of near-identical
chunks. The textbook answer is MMR, and it's wrong here: results are aggregated **by
save** in the end, and multiple passages from one save are corroborating evidence — MMR
deletes them, and in testing what it deleted was precisely the best-matching passage. A
per-save cap works far better.

Want better quality? Swap in a real multilingual encoder — one line of config:

```bash
pip install -e ".[neural]"
export CHEKHOVSGUN_EMBEDDING_BACKEND=sentence-transformers
chekhovsgun reindex
```

Or any OpenAI-compatible embedding endpoint (DashScope / SiliconFlow / Ollama / vLLM):

```bash
export CHEKHOVSGUN_EMBEDDING_BACKEND=openai
export CHEKHOVSGUN_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export CHEKHOVSGUN_EMBEDDING_API_KEY=sk-...
export CHEKHOVSGUN_EMBEDDING_MODEL=text-embedding-v3
chekhovsgun reindex
```

### Performance

On a synthetic library of 2,000 saves / 15,555 passages (`python scripts/benchmark.py`):

| Metric | Value |
| --- | --- |
| Index build | 10.3 s (~1500 passages/s, tokenization and embedding included) |
| Cold start (rebuild in-memory index) | 1.5 s |
| Retrieval p50 / p95 | **6.1 ms / 8.0 ms** |
| Full relate (including the read) | 7.3 ms |
| Disk | 65 MB |
| Resident memory (vector matrix) | 32 MB |

The things that made it fast, all measured rather than guessed:

- **BM25 runs on numpy.** Chinese tokenization produces character unigrams, and common
  characters have posting lists tens of thousands of entries long; walking one query in a
  Python loop took 56 ms — 90% of total query time. Numpy arrays plus fancy-indexed
  accumulation brought it down to 6 ms.
- **Skip high-frequency terms.** Tokens appearing in more than 35% of passages are
  dropped outright: their IDF is near zero so they can't change the ranking, yet they
  carry the longest posting lists.
- **Tokenization is persisted.** Tokenizing 15k passages takes 6 seconds, and it used to
  happen on every in-memory index rebuild; now it's computed at write time and stored in
  SQLite, cutting cold start to 1.5 s.
- **The cache key is a write counter.** Six COUNT queries used to run per request; the
  store's monotonic write counter costs nothing.

---

## That little "read"

On a hit, the card carries a sentence explaining how the save relates to what you're
watching and what you'd gain from going back. With an LLM configured it's generated;
without one it quotes the subtitle text directly — **quoting can never fabricate**, so the
default path is safe and the popup never hangs on a loading spinner.

```bash
export CHEKHOVSGUN_LLM_API_KEY=sk-...
export CHEKHOVSGUN_LLM_MODEL=gpt-4o-mini
export CHEKHOVSGUN_LLM_BASE_URL=            # any OpenAI-compatible endpoint
```

---

## Command line

| Command | What it does |
| --- | --- |
| `chekhovsgun demo` | Load sample data and run one retrieval |
| `chekhovsgun status` | Inventory, digestion rate, which sources are configured |
| `chekhovsgun ingest [--source X] [--limit N] [--force]` | Sync bookmarks |
| `chekhovsgun ingest --whisper` / `--no-comments` | Force local transcription / skip comments |
| `chekhovsgun import <file>` | Import from json/jsonl/csv/txt |
| `chekhovsgun search "query"` | Search your own saves |
| `chekhovsgun relate <url>` | Simulate: what would pop up on this video |
| `chekhovsgun mark <url> --digested` | Mark digested / muted / tagged |
| `chekhovsgun items --status active` | List what you still owe yourself |
| `chekhovsgun tray` | Background daemon with a tray icon |
| `chekhovsgun serve [--open]` | Foreground server + dashboard |
| `chekhovsgun reindex` | Rebuild vectors after changing the embedding backend |

---

## Where the data lives

| What | Where |
| --- | --- |
| Index database | `$CHEKHOVSGUN_HOME/index.db` (defaults to `~/.chekhovsgun/`, `%LOCALAPPDATA%` on Windows) |
| Config | `config.toml` in the same directory, or environment variables (see `.env.example`) |
| Credentials | Only in your environment variables / config file; always masked in API responses |

The server binds `127.0.0.1` only. No telemetry, no outbound reporting.

---

## Development

```bash
pip install -e ".[dev]"
pytest                      # everything
pytest tests/test_relevance.py -v   # golden-set regression for retrieval quality
```

`tests/test_relevance.py` is the file worth reading: it pins down concrete examples of
what *should* fire and what *shouldn't*, cross-language cases included. Any retrieval
change that breaks one of them goes red.

Adding a third source (Xiaohongshu, Zhihu, Pocket…) means implementing three methods from
`chekhovsgun/adapters/base.py`: list saves, fetch content, recognize a URL. The rest of
the code doesn't know where a chunk came from.

---

## Packaging

```bash
pip install -e ".[tray]" pyinstaller
pyinstaller chekhovsgun.spec        # → dist/ChekhovsGun(.exe)
```

Double-clicking the resulting single file gives you tray mode; run it with arguments and
it's still the full CLI (`ChekhovsGun.exe ingest --source bilibili`), so one binary does
both. Pushing a tag has CI build artifacts for all three platforms plus the extension zip.

## Known limitations

- The default hashed encoder has no real semantics. For cross-language and paraphrase
  cases, switch to a neural encoder (above).
- Bilibili SESSDATA expires in about a month; YouTube OAuth tokens expire in an hour, so
  long-running syncs need your own refresh.
- The Whisper fallback needs ffmpeg on the machine and is CPU-bound; the first run
  downloads a model.
- YouTube comments go through the Data API, and videos with comments disabled return 403 —
  that's expected, and they're skipped.
- The extension works on YouTube Shorts, but the vertical feed switches fast and the
  default 1.4 s debounce may still be too sensitive.
- The desktop browser isn't where most people scroll — phones are, and that's a different
  engineering problem.

## License

MIT

## Credits

Two projects informed the design: [Zangzhi Studio](https://github.com/Y-iyilin/zangzhi-studio)
(comments as a first-class content source, local transcription, the local-first stance) and
[Shiguang](https://github.com/zihuv/shiguang) (shipping as an installable package, and the
tag-and-organize library management). Both solve different problems than this one does, but
those particular calls were right.
