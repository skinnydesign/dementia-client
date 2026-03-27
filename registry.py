"""
Module Registry
===============
Each module is a dict describing a section of the app.
Modules are shown/hidden based on:
  1. ENABLED_MODULES config (comma-separated env var)
  2. User toggling visibility via the Settings page (stored in session)

To add a new module:
  1. Add an entry to AVAILABLE_MODULES below
  2. Create a blueprint in app/blueprints/
  3. Create templates in templates/<slug>/
  4. Register the blueprint in app/__init__.py
"""

AVAILABLE_MODULES = [
    {
        'slug':        'todos',
        'label':       'Todos',
        'description': 'Manage your todo list',
        'icon':        'check-square',
        'url':         '/todos',
        'nav_order':   1,
    },
    # ── Future modules — uncomment and implement when ready ──────────────────
    # {
    #     'slug':        'notes',
    #     'label':       'Notes',
    #     'description': 'Quick notes and scratchpad',
    #     'icon':        'file-text',
    #     'url':         '/notes',
    #     'nav_order':   2,
    # },
    # {
    #     'slug':        'calendar',
    #     'label':       'Calendar',
    #     'description': 'Upcoming events',
    #     'icon':        'calendar',
    #     'url':         '/calendar',
    #     'nav_order':   3,
    # },
]


def get_available_modules() -> list:
    return AVAILABLE_MODULES


def get_enabled_modules(app_config: dict, session: dict) -> list:
    """
    Returns modules that are both configured as enabled AND not hidden by the user.
    Priority: session overrides > app config defaults.
    """
    config_enabled = app_config.get('ENABLED_MODULES', [])
    # Session stores a set of slugs the user has explicitly hidden
    user_hidden    = set(session.get('hidden_modules', []))

    return [
        m for m in AVAILABLE_MODULES
        if m['slug'] in config_enabled and m['slug'] not in user_hidden
    ]


def get_visible_nav(app_config: dict, session: dict) -> list:
    """Returns enabled modules sorted by nav_order for use in the sidebar."""
    modules = get_enabled_modules(app_config, session)
    return sorted(modules, key=lambda m: m.get('nav_order', 99))
