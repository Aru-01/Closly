# Primary Fashion Color Anchors (RGB Euclidean distance mapping)
FASHION_COLOR_PALETTES = [
    ((18, 18, 22), "Jet Black", "dark"),
    ((60, 64, 72), "Charcoal Grey", "dark"),
    ((145, 150, 156), "Heather Grey", "neutral"),
    ((248, 248, 250), "Pure White", "light"),
    ((238, 232, 218), "Off-White / Cream", "light"),
    ((214, 192, 160), "Warm Beige", "neutral"),
    ((165, 130, 95), "Camel Brown", "neutral"),
    ((78, 48, 28), "Espresso Brown", "dark"),
    ((26, 42, 74), "Navy Blue", "dark"),
    ((64, 102, 164), "Denim Blue", "neutral"),
    ((145, 175, 215), "Sky Blue", "light"),
    ((82, 102, 68), "Olive Green", "neutral"),
    ((35, 75, 50), "Emerald Green", "vibrant"),
    ((28, 72, 48), "Forest Green", "dark"),
    ((168, 36, 42), "Crimson Red", "vibrant"),
    ((108, 24, 38), "Burgundy", "dark"),
    ((224, 148, 164), "Pastel Pink", "light"),
    ((168, 146, 184), "Lavender", "light"),
    ((218, 172, 48), "Mustard Yellow", "vibrant"),
    ((214, 104, 46), "Terracotta Orange", "vibrant"),
]


def _color_distance(c1, c2):
    """Euclidean distance between two RGB colors"""
    return sum((a - b) ** 2 for a, b in zip(c1, c2)) ** 0.5


def detect_dominant_fashion_color(pil_image):
    """
    Extracts dominant color from image (or cropped region) and maps to standard fashion color names.
    Applies brightness filtering to reject extreme background shadows and blown highlights.
    """
    small_img = pil_image.convert('RGB').resize((100, 100))
    pixels = list(small_img.getdata())

    # Sample central 60% of pixels to avoid border/wall backgrounds
    width, height = small_img.size
    center_pixels = []
    x_min, x_max = int(width * 0.2), int(width * 0.8)
    y_min, y_max = int(height * 0.2), int(height * 0.8)

    for y in range(y_min, y_max):
        for x in range(x_min, x_max):
            center_pixels.append(pixels[y * width + x])

    if not center_pixels:
        center_pixels = pixels

    # Exclude extreme dark background doorway/shadows (< 45) and pure white blowouts (> 710)
    filtered_pixels = [p for p in center_pixels if 45 < sum(p) < 710]
    if not filtered_pixels:
        filtered_pixels = center_pixels

    # Calculate average RGB of the garment
    avg_r = sum(p[0] for p in filtered_pixels) // len(filtered_pixels)
    avg_g = sum(p[1] for p in filtered_pixels) // len(filtered_pixels)
    avg_b = sum(p[2] for p in filtered_pixels) // len(filtered_pixels)
    avg_color = (avg_r, avg_g, avg_b)

    # Specific garment tone heuristics
    r, g, b = avg_color
    if b > r + 10 and b >= g:
        return "Sky Blue", "light", avg_color
    if g > r + 8 and g > b + 5:
        return "Emerald Green", "vibrant", avg_color
    if r > 110 and g > 85 and r > g > b:
        return "Camel Brown", "neutral", avg_color

    # Find closest fashion color
    closest_color = min(
        FASHION_COLOR_PALETTES,
        key=lambda item: _color_distance(avg_color, item[0])
    )

    return closest_color[1], closest_color[2], avg_color


def sample_image_zone_color(pil_img, y_start_pct, y_end_pct, x_start_pct=0.25, x_end_pct=0.75):
    """
    Crops a specific vertical & horizontal zone of the image and detects its dominant color.
    Used for multi-item full body outfit segmentation.
    """
    w, h = pil_img.size
    x1 = max(0, int(w * x_start_pct))
    x2 = min(w, int(w * x_end_pct))
    y1 = max(0, int(h * y_start_pct))
    y2 = min(h, int(h * y_end_pct))
    if x2 <= x1 or y2 <= y1:
        return "Neutral", "neutral", (128, 128, 128)
    
    cropped = pil_img.crop((x1, y1, x2, y2))
    return detect_dominant_fashion_color(cropped)
