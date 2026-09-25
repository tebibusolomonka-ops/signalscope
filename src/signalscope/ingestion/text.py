from bs4 import BeautifulSoup, Tag

# Their text is never part of what a reader sees.
HIDDEN_TAGS = ["script", "style", "noscript", "template"]
# Each of these starts a new line in the plain text.
BLOCK_TAGS = [
    "address",
    "article",
    "blockquote",
    "dd",
    "div",
    "dt",
    "figcaption",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "p",
    "pre",
    "section",
    "td",
    "th",
    "tr",
]


def html_to_text(html: str) -> str:
    """Readable plain text from HTML, with one line per paragraph or other block."""
    return element_text(BeautifulSoup(html, "html.parser"))


def element_text(element: Tag) -> str:
    """Plain text of a parsed element. The element is changed in place."""
    for hidden in element.find_all(HIDDEN_TAGS):
        hidden.decompose()
    for line_break in element.find_all("br"):
        line_break.replace_with("\n")
    for block in element.find_all(BLOCK_TAGS):
        block.insert_before("\n")
        block.insert_after("\n")
    lines = (" ".join(line.split()) for line in element.get_text().splitlines())
    return "\n".join(line for line in lines if line)
