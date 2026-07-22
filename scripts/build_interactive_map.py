"""Build the interactive companion page (docs/index.html) for the TSA claims
analysis: a real, hoverable, filterable map and category breakdown, plus the
existing model-diagnostic charts embedded as static images.

Data sources (not shipped in this repo; download and place under data/raw/):
  - Official DHS TSA claims releases, 2002-2015 (5 files):
      https://www.dhs.gov/tsa-claims-data
      claims-2002-2006_0.xls, claims-2007-2009_0.xls, claims-2010-2013_0.xls,
      claims-2014.xls, claims-data-2015-as-of-feb-9-2016.xlsx
  - Global Airport Database (real airport coordinates), raw colon-delimited
    format: https://www.partow.net/miscellaneous/airportdatabase/
      GlobalAirportDatabase.txt

Only columns present in every DHS release's schema are used (schemas differ
by era -- e.g. 2010+ has "Item Category" instead of "Item" and no separate
"Claim Amount"/"Status" columns), so nothing is fabricated to paper over the
schema differences: Date Received, Airport Code, Claim Type, Claim Site,
Disposition.

Usage: python scripts/build_interactive_map.py
Writes: data/tsa_claims_geo.json (small, derived, committed) and docs/index.html.
"""

import base64
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
FIGURES = ROOT / "figures"
DOCS = ROOT / "docs"
PAYLOAD_PATH = ROOT / "data" / "tsa_claims_geo.json"

DHS_FILES = [
    ("claims-2002-2006_0.xls", "Received through 2006"),
    ("claims-2007-2009_0.xls", "Received from 2007-2009"),
    ("claims-2010-2013_0.xls", "interactive_report"),
    ("claims-2014.xls", "interactive_report"),
    ("claims-data-2015-as-of-feb-9-2016.xlsx", "interactive_report"),
]
COMMON_COLS = ["Date Received", "Airport Code", "Claim Type", "Claim Site", "Disposition"]
APPROVE_LIKE = {"Approve in Full", "Settle", "Approved", "Settled"}


def build_payload() -> dict:
    frames = []
    for fname, sheet in DHS_FILES:
        df = pd.read_excel(RAW / fname, sheet_name=sheet)
        df.columns = [c.strip() for c in df.columns]
        frames.append(df[COMMON_COLS].copy())
    tsa = pd.concat(frames, ignore_index=True)

    tsa["Date Received"] = pd.to_datetime(tsa["Date Received"], errors="coerce")
    tsa = tsa[tsa["Date Received"].dt.year.between(2002, 2016)].copy()
    tsa["Year"] = tsa["Date Received"].dt.year
    for c in ["Claim Type", "Claim Site", "Disposition"]:
        tsa[c] = tsa[c].astype(str).str.strip()
    tsa["Airport Code"] = tsa["Airport Code"].astype(str).str.strip().str.upper()
    tsa["approved"] = tsa["Disposition"].isin(APPROVE_LIKE)

    cols = ["ICAO", "IATA", "AirportName", "City", "Country",
           "LatDeg", "LatMin", "LatSec", "LatDir", "LonDeg", "LonMin", "LonSec",
           "LonDir", "Altitude", "LatDecimal", "LonDecimal"]
    air = pd.read_csv(RAW / "GlobalAirportDatabase.txt", sep=":", header=None,
                      names=cols, na_values=["N/A"])
    air = air[(air["Country"] == "USA") & (air["IATA"] != "N/A") &
             (air["LatDecimal"] != 0)][["IATA", "AirportName", "City",
                                        "LatDecimal", "LonDecimal"]]
    air = air.drop_duplicates(subset="IATA")

    by_airport = (tsa.groupby("Airport Code").size().rename("claims")
                 .reset_index().rename(columns={"Airport Code": "iata"}))
    by_airport = by_airport.merge(air, left_on="iata", right_on="IATA", how="inner")
    by_airport = by_airport[(by_airport["LonDecimal"].between(-130, -60)) &
                            (by_airport["LatDecimal"].between(20, 55))]

    def nested_counts(df, key_col):
        out = {}
        for code, grp in df.groupby("Airport Code"):
            out[code] = dict(zip(grp[key_col], grp["n"].astype(int)))
        return out

    by_type = nested_counts(
        tsa.groupby(["Airport Code", "Claim Type"]).size().rename("n").reset_index(),
        "Claim Type")
    by_site = nested_counts(
        tsa.groupby(["Airport Code", "Claim Site"]).size().rename("n").reset_index(),
        "Claim Site")

    airports = []
    for _, row in by_airport.iterrows():
        code = row["iata"]
        airports.append({
            "code": code, "name": row["AirportName"], "city": row["City"],
            "lat": round(float(row["LatDecimal"]), 4),
            "lon": round(float(row["LonDecimal"]), 4),
            "claims": int(row["claims"]),
            "byType": by_type.get(code, {}),
            "bySite": by_site.get(code, {}),
        })
    airports.sort(key=lambda a: -a["claims"])

    return {
        "totalClaims": int(len(tsa)),
        "dateRange": [str(tsa["Date Received"].min().date()),
                     str(tsa["Date Received"].max().date())],
        "overallApprovalRate": round(float(tsa["approved"].mean()) * 100, 1),
        "airports": airports,
        "claimTypeCounts": tsa["Claim Type"].value_counts().to_dict(),
        "claimSiteCounts": tsa["Claim Site"].value_counts().to_dict(),
    }


def img_b64(name: str) -> str:
    return base64.b64encode((FIGURES / name).read_bytes()).decode("ascii")


TEMPLATE = r"""<meta charset="utf-8">
<title>TSA Claims Board</title>
<style>
:root {
  color-scheme: dark;
  --surface: #0B1220; --page: #070B12;
  --ink: #EAF0F6; --ink-2: #C9D6E3; --muted: #7C8798;
  --rule: rgba(201,214,227,.10); --rule-soft: rgba(201,214,227,.06);
  --amber: #FFC24B; --amber-soft: rgba(255,194,75,.12);
  --grid: rgba(201,214,227,.08);
  --c1: #3987e5; --c2: #d95926; --c3: #199e70; --c4: #9085e9; --other: #4b5563;
}
* { box-sizing: border-box; }
html, body { background: var(--page); }
body {
  margin: 0; color: var(--ink);
  font: 400 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.mono { font-family: ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace; }
.page { max-width: 1080px; margin: 0 auto; padding: 40px 20px 64px; }

/* masthead: departure-board frame */
.board { border: 1px solid var(--rule); border-radius: 4px; background: var(--surface);
  padding: 22px 26px; box-shadow: 0 1px 2px rgba(0,0,0,.4); }
.board__row { display: flex; justify-content: space-between; align-items: baseline;
  flex-wrap: wrap; gap: 8px; }
.eyebrow { font-size: 11px; letter-spacing: .24em; text-transform: uppercase;
  color: var(--amber); margin: 0; }
h1 { font-size: clamp(22px, 4vw, 30px); margin: 6px 0 4px; letter-spacing: .01em; }
.sub { color: var(--muted); margin: 0; font-size: 13.5px; }
.liveline { display: flex; align-items: center; gap: 7px; color: var(--muted);
  font-size: 12px; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--amber);
  box-shadow: 0 0 6px var(--amber); }

/* stat tiles: split-flap counters */
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px,1fr));
  gap: 12px; margin: 20px 0; }
.tile { background: var(--surface); border: 1px solid var(--rule); border-radius: 4px;
  padding: 16px 18px; }
.tile .l { font-size: 11px; letter-spacing: .12em; text-transform: uppercase;
  color: var(--muted); margin-bottom: 8px; }
.tile .v { font-size: 30px; font-weight: 600; color: var(--amber);
  letter-spacing: .01em; }
  /* no tabular-nums here: .mono (below) already gives every character equal
     width, which is what the split-flap shuffle needs to avoid jitter --
     tabular-nums would be redundant on top of a monospace font stack. */
.tile .n { font-size: 12px; color: var(--muted); margin-top: 6px; }

/* sections */
section { margin-top: 10px; }
.sect { display: flex; align-items: baseline; gap: 12px; margin: 30px 0 4px;
  flex-wrap: wrap; }
.sect h2 { font-size: 17px; margin: 0; }
.sect .note { color: var(--muted); font-size: 12.5px; }
.sect .spacer { flex: 1; }
.card { background: var(--surface); border: 1px solid var(--rule); border-radius: 4px;
  padding: 18px 20px; }

/* filter chips */
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chips button { background: none; border: 1px solid var(--rule); color: var(--ink-2);
  font: 500 12.5px system-ui; padding: 5px 12px; border-radius: 99px; cursor: pointer;
  display: inline-flex; align-items: center; gap: 6px; }
.chips button:hover { border-color: var(--amber); }
.chips button[aria-pressed="true"] { background: var(--amber-soft); color: var(--amber);
  border-color: var(--amber); }
.chips .sw { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }

svg { display: block; width: 100%; height: auto; }
svg text { font: 11px system-ui, sans-serif; fill: var(--muted); }
.legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--ink-2);
  margin-top: 8px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend .sw { width: 10px; height: 10px; border-radius: 2px; }

.tt { position: fixed; pointer-events: none; z-index: 9; background: #0F1830;
  border: 1px solid var(--rule); border-radius: 4px; padding: 8px 11px;
  font-size: 12.5px; display: none; color: var(--ink-2);
  box-shadow: 0 6px 20px rgba(0,0,0,.5); max-width: 240px; }
.tt b { color: var(--amber); font-variant-numeric: tabular-nums; }
.tt .code { color: var(--ink); font-weight: 600; }

table { border-collapse: collapse; width: 100%; font-size: 13px; }
th { text-align: left; color: var(--muted); font-weight: 600; font-size: 11px;
  letter-spacing: .06em; text-transform: uppercase; padding: 6px 12px 8px 0;
  border-bottom: 1px solid var(--rule); }
td { padding: 6px 12px 6px 0; border-bottom: 1px solid var(--rule-soft);
  font-variant-numeric: tabular-nums; }
tr:last-child td { border-bottom: none; }
.tblwrap { overflow-x: auto; }
.tblwrap.scroll { max-height: 420px; overflow-y: auto; }
.tblwrap.scroll thead th { position: sticky; top: 0; background: var(--surface); }

.gallery { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px,1fr));
  gap: 14px; }
.gallery figure { margin: 0; background: var(--surface); border: 1px solid var(--rule);
  border-radius: 4px; padding: 12px; }
.gallery img { width: 100%; border-radius: 2px; display: block; }
.gallery figcaption { font-size: 12px; color: var(--muted); margin-top: 8px; }

footer { color: var(--muted); font-size: 12.5px; margin-top: 32px; line-height: 1.6;
  border-top: 1px solid var(--rule); padding-top: 16px; }
footer a { color: var(--ink-2); }

@media (prefers-reduced-motion: reduce) { .flip { transition: none !important; } }
</style>
<div class="page">

<div class="board">
  <div class="board__row">
    <div>
      <p class="eyebrow">TSA Claims &middot; U.S. Airports &middot; 2002&ndash;2015</p>
      <h1 class="mono">CLAIMS BOARD</h1>
      <p class="sub">Official DHS claims releases, joined to real airport coordinates.
        Hover the map, filter by claim type.</p>
    </div>
    <div class="liveline"><span class="dot"></span> <span id="rangeline"></span></div>
  </div>
</div>

<div class="tiles" id="tiles"></div>

<section>
  <div class="sect">
    <h2>Where claims happen</h2>
    <span class="note" id="mapnote"></span>
    <span class="spacer"></span>
    <div class="chips" id="typefilter"></div>
  </div>
  <div class="card">
    <div id="map"></div>
    <div class="legend" id="maplegend"></div>
  </div>
</section>

<section>
  <div class="sect">
    <h2>All airports</h2>
    <span class="note" id="tabnote"></span>
  </div>
  <div class="card tblwrap scroll"><table id="topTable"></table></div>
</section>

<section>
  <div class="sect">
    <h2>Predicting claim approval</h2>
    <span class="note">Balanced logistic regression, evaluated on held-out claims (static from the analysis notebook)</span>
  </div>
  <div class="gallery">
    <figure><img src="data:image/png;base64,__IMG_ROC__" alt="ROC curve for the approval model">
      <figcaption>ROC curve: model vs. random baseline</figcaption></figure>
    <figure><img src="data:image/png;base64,__IMG_CM__" alt="Confusion matrix for the approval model">
      <figcaption>Confusion matrix at the default threshold</figcaption></figure>
    <figure><img src="data:image/png;base64,__IMG_FI__" alt="Feature importance for the approval model">
      <figcaption>Strongest predictors of approval vs. denial</figcaption></figure>
  </div>
</section>

<footer>
  Data: official DHS TSA claims releases 2002&ndash;2015 (five files, schemas
  differ by era; only fields present in every era are used here &mdash;
  date, airport, claim type, claim site, disposition) joined to airport
  coordinates from the real
  <a href="https://www.partow.net/miscellaneous/airportdatabase/">Global Airport
  Database</a>. This page is a companion to
  <a href="https://github.com/KelsonLam/tsa-airport-claims">tsa_claims_analysis.ipynb</a>,
  which covers the full cleaning, EDA, and modeling in one linear notebook; this
  page exists for the parts that benefit from hovering and filtering, the map and
  the category breakdowns, rather than trying to make a ROC curve interactive.
</footer>
</div>
<div class="tt" id="tt"></div>
<script>
const DATA = __DATA__;
const NS = 'http://www.w3.org/2000/svg';
const CAT_COLORS = ['var(--c1)','var(--c2)','var(--c3)','var(--c4)'];
const tt = document.getElementById('tt');
const fmt = new Intl.NumberFormat('en-US');

function el(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}
function showTT(html, x, y) {
  tt.innerHTML = html; tt.style.display = 'block';
  const w = tt.offsetWidth;
  tt.style.left = Math.min(x + 14, innerWidth - w - 8) + 'px';
  tt.style.top = (y + 14) + 'px';
}
function hideTT() { tt.style.display = 'none'; }

document.getElementById('rangeline').textContent =
  `${DATA.dateRange[0]} → ${DATA.dateRange[1]}`;
document.getElementById('mapnote').textContent =
  `${DATA.airports.length} airports with recorded claims`;
document.getElementById('tabnote').textContent = `All ${DATA.airports.length}, ranked by the active filter`;

// ---------- split-flap counter animation ----------
// setTimeout-driven (not requestAnimationFrame): rAF doesn't reliably settle
// under a headless-Chrome virtual time budget, which left a prior version of
// this showing mid-shuffle digits in an automated screenshot.
// Cycles letters for letter positions and digits for digit positions, like a
// real split-flap board (airport codes flip through letters, not just counts).
function flip(elm, targetText, steps = 14, stepMs = 55) {
  const chars = String(targetText).split('');
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
    elm.textContent = targetText;
    return;
  }
  const randomFor = (c) => /[0-9]/.test(c) ? String(Math.floor(Math.random() * 10))
    : /[A-Za-z]/.test(c) ? String.fromCharCode(65 + Math.floor(Math.random() * 26))
    : c;
  let i = 0;
  function tick() {
    i++;
    if (i >= steps) { elm.textContent = targetText; return; }
    const settle = Math.floor((i / steps) ** 2 * chars.length * 1.6);
    elm.textContent = chars.map((c, d) => d < settle ? c : randomFor(c)).join('');
    setTimeout(tick, stepMs);
  }
  tick();
}

// ---------- stat tiles ----------
(function () {
  const totalAirports = DATA.airports.length;
  const busiest = DATA.airports[0];
  const stats = [
    ['Total claims', fmt.format(DATA.totalClaims), `${DATA.dateRange[0].slice(0,4)}–${DATA.dateRange[1].slice(0,4)}`],
    ['Approval rate', DATA.overallApprovalRate.toFixed(1) + '%', 'approved or settled'],
    ['Airports on file', fmt.format(totalAirports), 'with at least one claim'],
    ['Busiest airport', busiest.code, `${fmt.format(busiest.claims)} claims`],
  ];
  const box = document.getElementById('tiles');
  stats.forEach(([label, target, note], i) => {
    const tile = document.createElement('div'); tile.className = 'tile';
    tile.innerHTML = `<div class="l">${label}</div>` +
      `<div class="v mono"></div><div class="n">${note}</div>`;
    box.appendChild(tile);
    const v = tile.querySelector('.v');
    setTimeout(() => flip(v, target), i * 120);
  });
})();

// ---------- claim-type filter (drives map sizing + legend) ----------
const topTypes = Object.entries(DATA.claimTypeCounts)
  .sort((a, b) => b[1] - a[1]);
const shownTypes = topTypes.slice(0, 4).map(t => t[0]);
let activeType = 'all';

(function renderFilter() {
  const box = document.getElementById('typefilter');
  const allBtn = document.createElement('button');
  allBtn.textContent = 'All claim types'; allBtn.dataset.type = 'all';
  box.appendChild(allBtn);
  shownTypes.forEach((t, i) => {
    const b = document.createElement('button');
    b.dataset.type = t;
    b.innerHTML = `<span class="sw" style="background:${CAT_COLORS[i]}"></span>${t}`;
    box.appendChild(b);
  });
  box.querySelectorAll('button').forEach(b => {
    b.addEventListener('click', () => { activeType = b.dataset.type; renderAll(); });
  });
})();

function syncFilterPressed() {
  document.querySelectorAll('#typefilter button').forEach(b =>
    b.setAttribute('aria-pressed', b.dataset.type === activeType));
}

function countFor(airport) {
  if (activeType === 'all') return airport.claims;
  return airport.byType[activeType] || 0;
}

// ---------- map: real lat/lon on a flight-tracker style grid ----------
function renderMap() {
  const box = document.getElementById('map'); box.innerHTML = '';
  const W = 1000, H = 560, P = {l: 10, r: 10, t: 10, b: 10};
  const LON = [-125, -66], LAT = [24, 50];
  const x = lon => P.l + (lon - LON[0]) / (LON[1] - LON[0]) * (W - P.l - P.r);
  const y = lat => H - P.b - (lat - LAT[0]) / (LAT[1] - LAT[0]) * (H - P.t - P.b);

  const svg = el('svg', {viewBox: `0 0 ${W} ${H}`}, box);
  // faint lat/lon reference grid (flight-tracker style, no political borders needed)
  for (let lon = -120; lon <= -70; lon += 10)
    el('line', {x1: x(lon), x2: x(lon), y1: P.t, y2: H - P.b,
      stroke: 'var(--grid)', 'stroke-width': 1}, svg);
  for (let lat = 25; lat <= 50; lat += 5)
    el('line', {x1: P.l, x2: W - P.r, y1: y(lat), y2: y(lat),
      stroke: 'var(--grid)', 'stroke-width': 1}, svg);

  const values = DATA.airports.map(countFor).filter(v => v > 0);
  const max = Math.max(...values, 1);
  const color = activeType === 'all' ? 'var(--amber)'
    : CAT_COLORS[shownTypes.indexOf(activeType)] || 'var(--other)';

  // Candidates for a text label: the busiest airports under the active
  // filter (not a fixed all-time top 5), so the labeled points always match
  // the biggest bubbles actually on screen.
  const ranked = DATA.airports.map(a => ({a, v: countFor(a)}))
    .filter(r => r.v > 0).sort((p, q) => q.v - p.v);
  const labelCandidates = ranked.slice(0, 8).map(r => r.a.code);
  const placedLabels = []; // {x, y, w} boxes already placed, in svg units

  ranked.forEach(({a, v}) => {
    const cx = x(a.lon), cy = y(a.lat);
    const r = 2 + Math.sqrt(v / max) * 22;

    // Visible mark stays true to scale; a separate, larger transparent
    // circle carries the actual hover/hit target so small airports (r < 12)
    // aren't a pinpoint target a reader has to land on dead-center.
    const hit = el('circle', {cx, cy, r: Math.max(r, 12), fill: 'transparent'}, svg);
    const dot = el('circle', {cx, cy, r: r.toFixed(2), fill: color, opacity: .58,
      stroke: 'var(--surface)', 'stroke-width': 2}, svg);
    hit.style.cursor = 'pointer';
    const showThis = ev => {
      const label = activeType === 'all' ? 'All claim types' : activeType;
      showTT(`<span class="code">${a.code}</span> — ${a.name}<br>` +
        `${label}: <b>${fmt.format(v)}</b> claims`, ev.clientX, ev.clientY);
    };
    hit.addEventListener('mousemove', showThis);
    hit.addEventListener('mouseleave', hideTT);
    dot.addEventListener('mousemove', showThis);
    dot.addEventListener('mouseleave', hideTT);

    if (!labelCandidates.includes(a.code)) return;
    // Skip a label that would collide with one already placed, rather than
    // stacking unreadable text -- exact identity is still one hover (or a
    // row in the table below) away, which is the documented fallback for
    // colliding end-labels.
    const w = a.code.length * 7 + 6, lx = cx - w / 2, ly = cy - r - 14;
    const collides = placedLabels.some(p =>
      lx < p.x + p.w && lx + w > p.x && Math.abs(ly - p.y) < 14);
    if (collides) return;
    placedLabels.push({x: lx, y: ly, w});
    const label = el('text', {x: cx, y: cy - r - 5,
      'text-anchor': 'middle', fill: 'var(--ink-2)', 'font-weight': 600}, svg);
    label.textContent = a.code;
  });
}

function renderLegend() {
  const box = document.getElementById('maplegend');
  if (activeType === 'all') {
    box.innerHTML = `<span><i class="sw" style="background:var(--amber)"></i>
      Bubble size = total claims at that airport</span>`;
  } else {
    const c = CAT_COLORS[shownTypes.indexOf(activeType)];
    box.innerHTML = `<span><i class="sw" style="background:${c}"></i>
      Bubble size = "${activeType}" claims at that airport</span>`;
  }
}

// ---------- full airport table (table-view twin of the map) ----------
function renderTable() {
  const ranked = [...DATA.airports]
    .map(a => ({a, v: countFor(a)}))
    .filter(r => r.v > 0)
    .sort((x, y) => y.v - x.v);
  document.getElementById('topTable').innerHTML =
    '<thead><tr><th>Code</th><th>Airport</th><th>City</th><th>Claims</th></tr></thead>' +
    '<tbody>' + ranked.map(({a, v}) =>
      `<tr><td class="mono">${a.code}</td><td>${a.name}</td>` +
      `<td>${a.city}</td><td>${fmt.format(v)}</td></tr>`).join('') + '</tbody>';
}

function renderAll() { renderMap(); renderLegend(); renderTable(); syncFilterPressed(); }
renderAll();
</script>
"""


def main() -> None:
    payload = build_payload()
    PAYLOAD_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAYLOAD_PATH.write_text(json.dumps(payload), encoding="utf-8")
    print(f"Wrote {PAYLOAD_PATH} ({PAYLOAD_PATH.stat().st_size / 1024:.0f} KB)")

    html = (TEMPLATE
            .replace("__DATA__", json.dumps(payload))
            .replace("__IMG_ROC__", img_b64("roc_curve.png"))
            .replace("__IMG_CM__", img_b64("confusion_matrix.png"))
            .replace("__IMG_FI__", img_b64("feature_importance.png")))
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    (DOCS / ".nojekyll").touch()
    print(f"Wrote {DOCS / 'index.html'} ({(DOCS / 'index.html').stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
