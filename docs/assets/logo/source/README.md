# Logo sources

Everything needed to edit the logo or to redraw it from the original design.

| Path | What it is |
|---|---|
| `ambermeta_logo_text.svg` | the logo with "mber" and "eta" as editable text; start here to edit |
| `ambermeta_logo_text_dark.svg` | the same for dark backgrounds |
| `font/KumbhSans-Bold.ttf`, `font/OFL.txt` | the typeface and its license (SIL Open Font License 1.1) |
| `ambermeta_logo_original.png` | the design as the image model drew it, from which the SVGs were redrawn |
| `prompt.md` | the prompt for the image model |
| `tools/measure.py`, `tools/build_svg.py` | the scripts that redrew the original as SVG |

## Editing in Inkscape

1. Install `font/KumbhSans-Bold.ttf` (Windows: right-click, Install). Without it, Inkscape shows the
   text in a substitute font.
2. Open `ambermeta_logo_text.svg` and edit. Every part is a separate object: the drop (outline,
   shade, highlight, and a chain of two circles and a bar), the text, and the M (one stroke of
   36 px with round joins and five circles).
3. To publish, convert the text to paths (select it, Path > Object to Path), save as
   *Plain SVG*, and replace `../ambermeta_logo.svg`. For the dark variant, change the slate
   `#243442` to `#E6EDF3` and save as `../ambermeta_logo_dark.svg`. Export the PNG from the light
   variant at 2466 px width with a transparent background.

## Colors and geometry

| | Color |
|---|---|
| amber (drop, "mber") | `#E8A00A` |
| dark amber (shade of the drop) | `#CC8404` |
| slate ("eta", the M) | `#243442` |
| light gray (dark variant) | `#E6EDF3` |
| chain and highlight | `#FFFFFF` |

In the coordinates of the original image (2804 x 561 px), the text is Kumbh Sans Bold at
424.4 px with its baseline at y = 449. The M's nodes have a radius of 45 px (middle node 42.5 px),
and the chain's nodes 32 px with a bar of 22 px.

## Redrawing from the original

The chosen font was the best of 98 font files, each tested at all its weights, by the overlap of
every letter with the original (Kumbh Sans Bold: 84 to 96 % per letter). To redraw:

```
pip install numpy pillow opencv-python-headless potracer fonttools
python tools/measure.py ambermeta_logo_original.png work
python tools/build_svg.py work font/KumbhSans-Bold.ttf out
```

`out/` then holds `ambermeta_logo.svg`, `ambermeta_logo_text.svg`, and `ambermeta_icon.svg`.
They match the files here to within 0.1 px.

## Origin

The design was generated with an image model from OpenAI from the prompt in `prompt.md` and
redrawn as vector shapes with the scripts in `tools/`, which were written with AI assistance
(Claude Code).
