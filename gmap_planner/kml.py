"""KML building stage: chunk days into layers and write KML files."""

import os
import re
import xml.etree.ElementTree as ET

from .config import DAY_COLORS, MAX_LAYERS_PER_FILE

# Characters not allowed in Windows file/folder names.
_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_folder_name(name: str) -> str:
    """Turn a trip name into a safe folder name (cross-platform)."""
    cleaned = _INVALID_NAME_CHARS.sub("", (name or "").strip()).rstrip(". ")
    return cleaned or "Trip"


def numbered_pin_href(n: int, color: str = "0288D1") -> str:
    """Google My Maps icon URL: a solid-color teardrop pin with `n` in solid white.

    3-layer stack (pin-container, round container, blank-shape) so the digit fills
    solid instead of rendering as a hollow outline. `color` (hex RGB, no #) tints the
    whole pin; the number is always white for contrast. `psize` shrinks as digits grow.
    Works for any `n` (not capped at the old 1-10 paddle PNGs).
    """
    psize = 20 if n < 10 else 17 if n < 100 else 12
    return (
        "https://mt.google.com/vt/icon/name="
        "icons/onion/SHARED-mymaps-pin-container_4x.png,"
        "icons/onion/SHARED-mymaps-container_4x.png,"
        "icons/onion/1899-blank-shape_pin_4x.png"
        f"&highlight={color},{color},ffffff&scale=4.0&color=ffffffff"
        f"&font=fonts/Roboto-Regular.ttf&ay=46&psize={psize}&text={n}"
    )


def chunk_days(days: list[dict], layers_per_file: int) -> list[list[dict]]:
    """Split days into chunks of at most `layers_per_file` (one day = one layer)."""
    size = max(1, min(layers_per_file, MAX_LAYERS_PER_FILE))
    return [days[i:i + size] for i in range(0, len(days), size)]


def build_kml_file(days_slice: list[dict]) -> ET.ElementTree:
    """Build one KML file where each day is its own <Folder> (= one My Maps layer)."""
    kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    doc = ET.SubElement(kml, "Document")

    day_numbers = [d["day"] for d in days_slice]
    name_text = f"Days {day_numbers[0]}-{day_numbers[-1]}" if len(day_numbers) > 1 else f"Day {day_numbers[0]}"
    ET.SubElement(doc, "name").text = name_text

    for day in days_slice:
        color = DAY_COLORS[(day["day"] - 1) % len(DAY_COLORS)]
        folder = ET.SubElement(doc, "Folder")
        date_str = day.get("date") or ""
        folder_name = f"Day {day['day']}" + (f" ({date_str})" if date_str else "")
        ET.SubElement(folder, "name").text = folder_name
        for idx, loc in enumerate(day.get("locations", []), start=1):
            pm = ET.SubElement(folder, "Placemark")
            ET.SubElement(pm, "name").text = loc["name"]
            ET.SubElement(pm, "description").text = loc.get("notes", "")
            style = ET.SubElement(pm, "Style")
            icon_style = ET.SubElement(style, "IconStyle")
            icon = ET.SubElement(icon_style, "Icon")
            ET.SubElement(icon, "href").text = numbered_pin_href(idx, color)
            label_style = ET.SubElement(style, "LabelStyle")
            ET.SubElement(label_style, "scale").text = "0.8"
            point = ET.SubElement(pm, "Point")
            ET.SubElement(point, "coordinates").text = f"{loc['lng']},{loc['lat']},0"

    return ET.ElementTree(kml)


def write_kml_files(chunks: list[list[dict]], output_dir: str) -> list[str]:
    paths = []
    for chunk in chunks:
        tree = build_kml_file(chunk)
        ET.indent(tree, space="  ")
        first, last = chunk[0]["day"], chunk[-1]["day"]
        filename = f"{first}.kml" if first == last else f"{first}-{last}.kml"
        path = os.path.join(output_dir, filename)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        paths.append(path)
    return paths
