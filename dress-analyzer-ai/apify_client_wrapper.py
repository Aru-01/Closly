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
