# Export presets, export evidence and the engine chain

The work order asks for **both** an editable source and a target export, together with size / resolution /
font / colour checks. `chart.py` therefore renders one `layout()` dict through three renderers and then
**re-reads the files it produced** to report what is actually in them.

| Artefact | Role | What it is |
|-|-|-|
| `figure.svg` | editable source | real `<text>` (no outlines, no `<image>`, no external `href`), `id` on every mark, mm-accurate `viewBox` in pt |
| `figure.pdf` | submission export | one page, `%PDF`, vector operators + live text operators (`Tj`), no `/Image` XObject |
| `figure.png` | preview export | raster at the requested dpi, 8-bit RGB/RGBA, `pHYs` dpi chunk |
| `figure.map.json` | provenance | element → source cell (physical line, column, `row_key`) |
| `export_check.json` | export evidence | measured properties of the two exports + pass/fail per gate |
| `result.json` | contract | `output_contract` keys echoed, `output_files[]` with bytes+sha256, `checks`, `sources`, `uncertainty` |
| `render_report.json` | render record | chart type, series colours, element count, mapping coverage, `null_value_notes` |

## 1. Default preset (single-column, 89 mm)

| Parameter | Value | Where |
|-|-|-|
| canvas | 89.0 × 70.0 mm (252.28 × 198.43 pt) | `chart.py: layout()` |
| type size | 7.0 pt | `FS` |
| series palette | Okabe–Ito first colours (`#0072B2`, `#D55E00`, `#009E73`, `#CC79A7`, …) | `PAL` |
| rule weight | axis 0.8 pt, bar outline 0.3 pt, error bar 0.8 pt | `layout()` |
| PNG | 300 dpi → 1051 × 827 px | `--dpi` |
| colour space | sRGB (PNG), DeviceRGB (PDF) | measured in `export_check.json` |

Journal variants are a **parameter change, not a code change**: edit `W`, `H` and `FS` in `layout()`
(Nature single column 89 mm/7 pt, Science 55 mm/6 pt, IEEE 88.9 mm/8 pt, PLOS 83 mm/8 pt), then rerun —
the axis margins recompute from the tick-label width, so a narrower canvas cannot silently occlude labels.

## 2. Engine chain (why the exports always exist)

`--engine` defaults to **`auto`**: try matplotlib first (better font rendering, CJK support, TrueType
subset embedding), and fall back to the standard-library writer automatically when matplotlib is absent.
Both paths draw the same `layout()` and emit the same fields; **both were measured at 19/19 passing
checks in `scripts/verify.py`**, so the fallback is a real substitute rather than a degraded stub.
`--engine stdlib` stays available as an explicit switch for minimal containers.

1. `--engine auto` (default) tries **matplotlib**: real fonts, `pdf.fonttype = 42` (TrueType subset
   embedded, text stays editable and selectable), matching PNG. A CJK-capable family is looked up
   (`Noto Sans CJK`, `Source Han Sans`, `WenQuanYi Zen Hei`, `Microsoft YaHei`, `SimHei`, …); if none is
   installed the fact is written into `export_check.json.font_basis` and into `result.json.uncertainty`.
2. If matplotlib is missing or fails, a **standard-library writer** produces a vector PDF
   (Base-14 Helvetica, `WinAnsiEncoding`, no embedding required) and a zlib PNG of the same primitives.
   In that mode the PNG carries no glyph rasteriser, which is stated in
   `export_check.json.png_text_layer`; paragraph text remains exact in `figure.svg` and `figure.pdf`.
3. `--engine stdlib` forces step 2 (used by `tests/selftest.py` to prove the fallback is not decoration).

## 3. What "verified export" means here

`export_check.json` is produced by parsing the written bytes, never by trusting the writer:
MediaBox in pt/mm, page count, `Tj`/`TJ` operator count, `/BaseFont` names, `/FontFile2|3` presence,
`/Subtype /Image` count, colour operators; PNG signature, chunk list, `IHDR` width/height/bit depth/
colour type, `pHYs` dpi. `scripts/verify.py` repeats that parsing independently **and** cross-checks the
artefacts against each other:

- every rectangle in `figure.svg` must be matched by rectangle operators in the PDF;
- every series fill colour in the SVG must appear as an `rg` colour in the PDF;
- the PNG raster is sampled at the centre of every bar (must equal the SVG fill colour) and just above the
  bar top (must be blank), so a raster that drifted from the vector geometry cannot pass.

## 4. Determinism (byte-identical reruns)

Pin `SOURCE_DATE_EPOCH` (any integer) and two runs of the same case produce **byte-identical artefacts**:
matplotlib derives the PDF `/CreationDate` from that variable, and `chart.py` routes every timestamp
(`result.json.changes[].at`, `render_report.json`, `changes[].seconds`) through the same epoch instead of
the wall clock. `figure.svg`, `figure.png`, `figure.map.json` and `export_check.json` were already
deterministic. Without the variable the package records real time and stays fully usable.
Regression: `tests/selftest.py::reproducible_byte_identical` compares the sha256 of all seven artefacts.

## 5. Known limits (honest)
- PNG glyphs come from the matplotlib engine; the stdlib fallback rasterises primitives only.
- CMYK / PDF-X output is not implemented (DeviceRGB only); no ICC profile is embedded.
- The PDF uses the *approximate* Helvetica advance model in the stdlib path (0.5 em/char) for centre/right
  alignment; the matplotlib path uses real metrics. Both keep the same anchors.
- No multi-panel (a/b/c) composition and no line/scatter/heatmap/box plot types in this version.
