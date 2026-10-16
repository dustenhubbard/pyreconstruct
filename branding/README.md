# PyReconstruct brand kit

Everything here uses one look: the glass-stack mark on a graphite background,
with Inter for type. `preview.png` shows every social image at a glance.

## Social images

| File | Use it for |
|---|---|
| `social/github-social-preview-1280x640.png` | GitHub repo social preview (Settings > Social preview) and README header |
| `social/open-graph-1200x630.png` | Link previews: website og:image, LinkedIn, Facebook, Slack, Discord |
| `social/x-post-1600x900.png` | 16:9 post image for X, Bluesky, Mastodon, LinkedIn |
| `social/youtube-thumbnail-1280x720.png` | YouTube thumbnail / video title card |
| `social/slide-title-1920x1080.png` | Title slide and video intro (1080p) |
| `social/header-x-mastodon-1500x500.png` | X and Mastodon profile header |
| `social/banner-bluesky-3000x1000.png` | Bluesky profile banner |
| `social/banner-linkedin-1584x396.png` | LinkedIn personal profile background |
| `social/cover-linkedin-page-1128x191.png` | LinkedIn company/showcase page cover |
| `social/post-square-1080x1080.png` | Square post (Instagram, LinkedIn, Bluesky) |
| `social/post-portrait-1080x1350.png` | 4:5 portrait post (Instagram, LinkedIn) |
| `social/story-1080x1920.png` | 9:16 story / reel cover |
| `social/avatar-1024x1024.png` | Profile picture for any account (circle-safe) |
| `social/avatar-400x400.png` | Profile picture, small |

Notes:
- **GitHub social preview** has to be uploaded by hand: repo **Settings → General → Social preview**.
- **Banners** keep the bottom-left clear for the profile picture. On X, Mastodon and Bluesky the text sits
  above it; on LinkedIn it starts to the right of it.
- **Story** keeps text out of the top 250 px and bottom 340 px, where Instagram and TikTok draw their UI.
- **Avatar** is square; the stack fits inside the circle crop every platform applies.

## Logos

| Folder | What | When |
|---|---|---|
| `app-icon/` | The app icon tile (SVG, PNG 16 to 1024, macOS 1024 with Apple's padding and shadow, Windows `.ico`, Dev icon) | Anywhere the app itself is shown: download pages, docs, store listings. 16 to 48 px use the simplified small-size artwork. |
| `mark/` | The stack on its own, no tile (SVG, PNG 256 to 1024) | Large illustrative use, website hero, slides, stickers. Works on dark and light. |
| `lockup/horizontal-*` | Icon + wordmark side by side | Headers, footers, posters, slide corners |
| `lockup/stacked-*` | Icon above wordmark | Square spaces, title slides, posters |
| `lockup/wordmark-*` | "PyReconstruct" alone | When the icon is already nearby |

`on-dark` files have light text; `on-light` files have dark text. The text in every SVG is outlined, so the
files render the same without Inter installed.

Give the logo clear space of at least half the icon's height on every side. Don't recolor the stack,
stretch it, or put the light-text lockup on a light background.

## Colors

| Token | Hex | Use |
|---|---|---|
| Background (top-left) | `#151619` | Card and banner backgrounds, as a gradient… |
| Background (bottom-right) | `#0A0A0C` | …to this |
| Text | `#F5F5F7` | Titles on dark |
| Secondary text | `#A1A1AA` | Subtitles, the SERIAL-SECTION · VOLUME EM kicker |
| Muted text | `#71717A` | URLs, captions |
| Ink on light | `#14171C` | Text on light backgrounds |
| Icon tile | `#17253D` → `#0A101C` | The app icon's navy (inside the tile only) |

Segmentation colors (from the icon's cells; use for charts, highlights and accents, never for body text):
`#2DD4BF` teal · `#A78BFA` violet · `#FB7185` rose · `#38BDF8` sky · `#FBBF24` amber · `#4ADE80` green ·
`#F472B6` pink · `#818CF8` indigo. PyReconstruct Dev's badge is amber `#F59E0B`.

## Type

[Inter](https://rsms.me/inter/) (SIL Open Font License). Titles: Inter Display Bold, slightly tight tracking.
Body: Inter Regular. Kicker: Inter SemiBold, all caps, wide tracking (~0.18 em).

## Copy

- Name: **PyReconstruct**
- Kicker: **SERIAL-SECTION · VOLUME EM**
- One-liner: **Annotation and 3D reconstruction for volume electron microscopy.**
- Link: **github.com/dustenhubbard/PyReconstruct**
