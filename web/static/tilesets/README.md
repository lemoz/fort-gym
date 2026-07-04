# Bundled tilesets

## oddball-16x16.png

- **Name**: Oddball 16x16 (Dwarf Fortress tileset, CP437 grid, 256x256 px, 16x16 px per tile)
- **Author**: HexaBlu
- **Source**: https://github.com/HexabluDEV/Oddball-16 (`Oddball_16x16.png`, branch `main`, fetched 2026-07-04)
- **License**: Creative Commons Attribution 4.0 International (CC BY 4.0),
  https://creativecommons.org/licenses/by/4.0/
- **Upstream license statement**: "These tilesets are licensed under a Creative
  Commons Attribution 4.0 International License. So feel free to use and edit
  them however you like, but please make sure to credit HexaBlu somewhere if
  you do!"
- **Modifications**: none (byte-identical copy; magenta background is keyed to
  transparent at runtime in the replay renderer).

Used by the replay UI (`web/index.html`) "Graphical" glyph mode: recorded DF
CopyScreen text is re-skinned through this sprite sheet by mapping each
recorded character to its CP437 tile. This is a presentation-layer re-skin
only — the evidence is the same recorded text shown in the ASCII mode.
