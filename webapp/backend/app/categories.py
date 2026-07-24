"""Maps every parser/analyser module name to a UI navigation category.

This is the single source of truth for grouping — the frontend never hardcodes this
mapping, it asks the API (see routers/cases.py `/meta/categories`). Anything not listed
here (new parsers added upstream) falls into "other" automatically, so nothing is ever
silently left off the nav.
"""

CATEGORIES = [
    {"id": "processes", "label": "Processes & Tasks"},
    {"id": "apps", "label": "Apps & Installs"},
    {"id": "network", "label": "Network & WiFi"},
    {"id": "crashes", "label": "Crashes & Stability"},
    {"id": "security", "label": "Security & Privacy"},
    {"id": "system", "label": "System & Hardware"},
    {"id": "logs", "label": "System Logs & Timeline"},
    {"id": "reports", "label": "Reports & Meta"},
    {"id": "other", "label": "Other"},
]

_ASSIGNMENTS: dict[str, str] = {
    # processes
    "ps": "processes",
    "psthread": "processes",
    "taskinfo": "processes",
    "ps_matrix": "processes",
    "ps_everywhere": "processes",
    "spindumpnosymbols": "processes",
    "kbdebug": "processes",
    # apps & installs
    "appinstallation": "apps",
    "itunesstore": "apps",
    "mobileinstallation": "apps",
    "mobileactivation": "apps",
    "mobilebackup": "apps",
    "apps": "apps",
    "uuid2path": "apps",
    "olddsc": "apps",
    # network & wifi
    "wifi_known_networks": "network",
    "wifinetworks": "network",
    "wifiscan": "network",
    "wifisecurity": "network",
    "networkextension": "network",
    "networkextensioncache": "network",
    "swcutil": "network",
    "brctl": "network",
    "wifi_geolocation": "network",
    "wifi_geolocation_kml": "network",
    "remotectl_dumpstate": "network",
    # crashes & stability
    "crashlogs": "crashes",
    "shutdownlogs": "crashes",
    # security & privacy
    "security_sysdiagnose": "security",
    "accessibility_tcc": "security",
    "transparency": "security",
    "transparency_json": "security",
    "containermanager": "security",
    "lockdownd": "security",
    "mcsettingsevents": "security",
    "mcstate_shared_profile": "security",
    "mcstateshared": "security",
    "yarascan": "security",
    # system & hardware
    "sys": "system",
    "disks": "system",
    "battery_bdc": "system",
    "ioacpiplane": "system",
    "iodevicetree": "system",
    "iofirewire": "system",
    "iopower": "system",
    "ioservice": "system",
    "iousb": "system",
    "plists": "system",
    "plist": "system",
    "avconference_callsettings": "system",
    # logs & timeline
    "logarchive": "logs",
    "logdata_statistics": "logs",
    "logdata_statistics_txt": "logs",
    "powerlogs": "logs",
    # reports & meta
    "coverage": "reports",
    "file_stats": "reports",
    "summary": "reports",
    "demo_parser": "reports",
    "demo_analyser": "reports",
}


def category_for(name: str) -> str:
    return _ASSIGNMENTS.get(name, "other")
