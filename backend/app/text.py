from markdown_it import MarkdownIt

markdown = MarkdownIt("commonmark", {"html": False})


def plain_preview(text: str, limit: int = 90) -> str:
    def parts(tokens):
        for token in tokens:
            if token.children:
                yield from parts(token.children)
            elif token.type in {"text", "code_inline", "fence", "code_block", "image"}:
                yield token.content
            elif token.type in {"softbreak", "hardbreak", "paragraph_close", "heading_close"}:
                yield " "

    value = " ".join("".join(parts(markdown.parse(text))).split())
    return value[:limit] + ("…" if len(value) > limit else "")
