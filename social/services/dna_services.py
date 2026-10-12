"""
Style DNA matching service.
Calculates percentage similarity between two users based on their
style identities, fashion occasions, color palettes, and closet silhouettes.
"""

def calculate_dna_match(user_a, user_b):
    """
    Computes a 0-100% Style DNA match score between user_a and user_b.
    Returns:
        dict: {
            'score': int,
            'display': str,
            'common_styles': list[str],
            'common_vibes': list[str],
            'description': str
        }
    """
    if not user_a or not user_b:
        return {'score': 50, 'display': '50% Match', 'common_styles': [], 'common_vibes': [], 'description': 'Neutral style baseline.'}

    if user_a.id == user_b.id:
        return {'score': 100, 'display': '100% Match', 'common_styles': ['Identical DNA'], 'common_vibes': ['Self'], 'description': 'Your own profile.'}

    pref_a = getattr(user_a, 'preferences', None)
    pref_b = getattr(user_b, 'preferences', None)

    styles_a = set(pref_a.style_match) if pref_a and pref_a.style_match else set()
    styles_b = set(pref_b.style_match) if pref_b and pref_b.style_match else set()

    dress_a = set(pref_a.what_do_you_dress_for) if pref_a and pref_a.what_do_you_dress_for else set()
    dress_b = set(pref_b.what_do_you_dress_for) if pref_b and pref_b.what_do_you_dress_for else set()

    palette_a = pref_a.color_palette if pref_a else ''
    palette_b = pref_b.color_palette if pref_b else ''

    common_styles = list(styles_a & styles_b)
    common_vibes = list(dress_a & dress_b)

    # Style match score (Weight: 45%)
    if styles_a and styles_b:
        style_sim = len(common_styles) / len(styles_a | styles_b)
    else:
        style_sim = 0.65  # baseline compatibility

    # Dress-for occasion score (Weight: 30%)
    if dress_a and dress_b:
        dress_sim = len(common_vibes) / len(dress_a | dress_b)
    else:
        dress_sim = 0.60

    # Color palette match (Weight: 15%)
    if palette_a and palette_b:
        palette_sim = 1.0 if palette_a == palette_b else 0.40
    else:
        palette_sim = 0.60

    # Silhouette / country synergy (Weight: 10%)
    loc_sim = 0.90 if getattr(user_a, 'country', None) and user_a.country == getattr(user_b, 'country', None) else 0.50

    raw_score = (style_sim * 45) + (dress_sim * 30) + (palette_sim * 15) + (loc_sim * 10)
    final_score = int(round(max(35, min(98, raw_score))))

    if final_score >= 80:
        desc = f"Aesthetic Twins! Shared aesthetic: {', '.join(common_styles[:2]) or 'Modern Clean'}."
    elif final_score >= 65:
        desc = f"Strong wardrobe resonance across {', '.join(common_vibes[:2]) or 'lifestyle staples'}."
    else:
        desc = "Complementary eclectic fashion perspectives."

    return {
        'score': final_score,
        'display': f"{final_score}% Match",
        'common_styles': common_styles,
        'common_vibes': common_vibes,
        'description': desc
    }
