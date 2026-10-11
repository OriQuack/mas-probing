"""Descriptions of the values worker tools return."""

TOOL_LINES = {
    "web_search": "web_search: search the web (Google results); returns titles, URLs and snippets",
    "read_url": ("read_url: ask a question about a web page or online document; returns an answer written by a "
                 "reader model from the page's full text, not the text itself (optionally from an archived snapshot: "
                 "by default the latest on or before a date)"),
    "read_url_text": "read_url_text: read a web page or online document; returns the extracted raw text, page by page",
    "find_in_url": ("find_in_url: find a string in a web page or online document; returns each match with the text "
                    "around it"),
    "read_file": "read_file: read a file in the working directory (documents, spreadsheets, zips, text)",
    "view_image": "view_image: look at an image file or image URL",
    "run_python": "run_python: run Python in the working directory (no network)",
}
