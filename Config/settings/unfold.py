from django.urls import reverse_lazy

# Django Unfold Luxury Admin Dashboard Settings
UNFOLD = {
    "SITE_TITLE": "Closly Luxury Wardrobe Admin",
    "SITE_HEADER": "Closly Admin",
    "SITE_SUBHEADER": "AI Wardrobe & Stylist Platform",
    "SITE_SYMBOL": "checkroom",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "DASHBOARD_CALLBACK": "users.dashboard.dashboard_callback",
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Administration & Security",
                "separator": True,
                "items": [
                    {
                        "title": "Users Management",
                        "icon": "group",
                        "link": reverse_lazy("admin:users_user_changelist"),
                    },
                    {
                        "title": "Account Deletion Requests",
                        "icon": "person_remove",
                        "link": reverse_lazy(
                            "admin:users_accountdeletionrequest_changelist"
                        ),
                        "badge": "users.dashboard.pending_deletions_badge",
                    },
                    {
                        "title": "User Preferences",
                        "icon": "tune",
                        "link": reverse_lazy("admin:users_userpreference_changelist"),
                    },
                ],
            },
            {
                "title": "Closet & Digital Wardrobe",
                "separator": True,
                "items": [
                    {
                        "title": "Closet Items",
                        "icon": "checkroom",
                        "link": reverse_lazy("admin:closet_closetitem_changelist"),
                    },
                    {
                        "title": "Today's Outfits",
                        "icon": "styler",
                        "link": reverse_lazy("admin:social_todayoutfit_changelist"),
                    },
                    {
                        "title": "24h Stories",
                        "icon": "auto_stories",
                        "link": reverse_lazy("admin:social_story_changelist"),
                    },
                    {
                        "title": "Direct Messages",
                        "icon": "chat",
                        "link": reverse_lazy("admin:social_directmessage_changelist"),
                    },
                ],
            },
            {
                "title": "Affiliate & Loyalty",
                "separator": True,
                "items": [
                    {
                        "title": "Affiliate Products",
                        "icon": "shopping_bag",
                        "link": reverse_lazy(
                            "admin:affiliate_affiliateproduct_changelist"
                        ),
                    },
                    {
                        "title": "User Rewards Profiles",
                        "icon": "military_tech",
                        "link": reverse_lazy(
                            "admin:rewards_userrewardprofile_changelist"
                        ),
                    },
                    {
                        "title": "Reward Transactions",
                        "icon": "receipt_long",
                        "link": reverse_lazy(
                            "admin:rewards_rewardpointtransaction_changelist"
                        ),
                    },
                ],
            },
        ],
    },
}
