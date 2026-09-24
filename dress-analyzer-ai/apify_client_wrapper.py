# Apify-based Google search — used to verify brand name from logo text
from apify_client import ApifyClient
from config import settings

_apify_client = ApifyClient(settings.APIFY_API_TOKEN)


def search_brand_from_logo_text(logo_text: str, max_results: int = 5) -> list:
    """
    Runs a Google search via Apify for the given logo text
    and returns a list of organic search result items.
    """
    run_input = {
        "queries": f"{logo_text} clothing brand logo",
        "maxPagesPerQuery": 1,
        "resultsPerPage": max_results,
        "countryCode": "us",
    }

    run = _apify_client.actor(settings.APIFY_GOOGLE_ACTOR).call(run_input=run_input)

    results = []
    if not run or "defaultDatasetId" not in run:
        return results

    for item in _apify_client.dataset(run["defaultDatasetId"]).iterate_items():
        results.append(item)

    return results


def search_brand_by_reverse_image(image_url: str, max_results: int = 5) -> list:
    """
    Runs reverse image search via Apify using a public image URL,
    to identify the brand from an unrecognized/local logo.
    """
    run_input = {
        "imageUrl": image_url,   # exact field name — verify against the actor you choose in Apify console
        "maxResults": max_results,
    }

    run = _apify_client.actor("REPLACE_WITH_REVERSE_IMAGE_SEARCH_ACTOR_ID").call(run_input=run_input)

    results = []
    for item in _apify_client.dataset(run["defaultDatasetId"]).iterate_items():
        results.append(item)

    return results


def verify_brand_with_reverse_image_search(image_url: str) -> str | None:
    try:
        results = search_brand_by_reverse_image(image_url)
    except Exception:
        return None

    if not results:
        return None

    # Adjust field names below to match the actual actor's output structure
    top_item = results[0]
    matched_title = top_item.get("title") or top_item.get("pageTitle")
    return matched_title