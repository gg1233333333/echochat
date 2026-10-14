"""Extract the attachment text stored with a message; originals are not retained."""

from io import BytesIO
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 24 * 1024 * 1024
MAX_FILES = 10
MAX_TEXT_CHARS = 8000
TEXT_EXTENSIONS = {
    "txt",
    "md",
    "csv",
    "json",
    "log",
    "xml",
    "yml",
    "yaml",
    "html",
    "css",
    "scss",
    "less",
    "js",
    "jsx",
    "ts",
    "tsx",
    "vue",
    "py",
    "java",
    "c",
    "cpp",
    "cc",
    "h",
    "hpp",
    "cs",
    "php",
    "rb",
    "go",
    "rs",
    "kt",
    "swift",
    "sql",
    "sh",
}
EXTENSIONS = TEXT_EXTENSIONS | {"pdf", "doc", "docx"}
ATTACHMENT_LIMITS = {
    "max_file_bytes": MAX_FILE_BYTES,
    "max_total_bytes": MAX_TOTAL_BYTES,
    "max_files": MAX_FILES,
    "max_text_chars": MAX_TEXT_CHARS,
    "extensions": sorted(EXTENSIONS),
}
TEXT_MIMES = {
    "text/plain",
    "text/csv",
    "text/markdown",
    "application/json",
    "application/xml",
    "text/xml",
    "text/html",
    "text/css",
    "text/x-python",
    "text/x-java-source",
    "text/x-c",
    "text/x-c++",
    "text/x-script.python",
    "application/javascript",
    "text/javascript",
}
DOCUMENT_MIMES = {
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


class AttachmentError(ValueError):
    def __init__(self, message: str, code: str = "INVALID_ATTACHMENT") -> None:
        super().__init__(message)
        self.code = code


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted:
        raise AttachmentError("PDF 已加密，请先解密后上传。")
    chunks: list[str] = []
    length = 0
    for page in reader.pages:
        chunk = (page.extract_text() or "").strip()
        if chunk:
            length += len(chunk) + (2 if chunks else 0)
            chunks.append(chunk)
        if length > MAX_TEXT_CHARS:
            break
    return "\n\n".join(chunks)


def _docx_text(data: bytes) -> str:
    with ZipFile(BytesIO(data)) as archive:
        # The upload limit measures compressed bytes; also bound XML expansion.
        if sum(item.file_size for item in archive.infolist()) > 64 * 1024 * 1024:
            raise AttachmentError("DOCX 解压后的内容过大，请拆分后上传。")
    document = Document(BytesIO(data))
    chunks: list[str] = []
    length = 0
    # Body paragraphs include table cells in their original reading order.
    for element in document.element.body.iter(qn("w:p")):
        chunk = Paragraph(element, document).text.strip()
        if chunk:
            length += len(chunk) + (1 if chunks else 0)
            chunks.append(chunk)
        if length > MAX_TEXT_CHARS:
            break
    return "\n".join(chunks).strip()


def parse_attachment(data: bytes, name: str, mime: str | None = None) -> dict:
    if not isinstance(name, str) or not name or "\x00" in name:
        raise AttachmentError("附件文件名无效。")
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    if not name or len(name) > 255:
        raise AttachmentError("附件文件名无效或过长。")
    if len(data) > MAX_FILE_BYTES:
        raise AttachmentError(f"{name} 超过单文件 8 MiB 限制。", "ATTACHMENT_TOO_LARGE")
    mime = (mime or "application/octet-stream").split(";", 1)[0].strip().lower()
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    kind = extension if extension in EXTENSIONS else DOCUMENT_MIMES.get(mime)
    if kind is None and mime in TEXT_MIMES:
        kind = "txt"
    if kind is None:
        raise AttachmentError(f"{name} 的格式暂不支持，请上传文本、文档或常见代码文件。")

    note = ""
    try:
        if kind == "doc":
            text = ""
            note = "DOC 格式仅提供文件信息，请转换为 DOCX 后上传以读取正文。"
        elif kind == "pdf":
            text = _pdf_text(data)
            if not text.strip():
                note = "PDF 没有可提取的文本，仅提供文件信息；扫描件需要先识别为文字。"
        elif kind == "docx":
            text = _docx_text(data)
            if not text.strip():
                note = "DOCX 没有可提取的文本，仅提供文件信息。"
        else:
            encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
            text = data.decode(encoding).strip()
            if "\x00" in text:
                raise AttachmentError(f"{name} 含有二进制内容，无法作为文本读取。")
            if not text:
                note = "文本文件为空，仅提供文件信息。"
    except AttachmentError:
        raise
    except UnicodeDecodeError as exc:
        raise AttachmentError(f"{name} 不是有效的 UTF-8 文本，请转换编码后上传。") from exc
    except Exception as exc:
        raise AttachmentError(f"无法解析 {name}，文件可能已损坏或格式不匹配。") from exc

    truncated = len(text) > MAX_TEXT_CHARS
    if truncated:
        note = "内容已截断，仅保留前 8000 字符。"
    return {
        "name": name,
        "size": len(data),
        "mime": mime,
        "extracted_text": text[:MAX_TEXT_CHARS],
        "status": "extracted" if text else "metadata_only",
        "note": note,
        "truncated": truncated,
    }


def parse_attachments(files: list[tuple[str, str | None, bytes]]) -> list[dict]:
    if len(files) > MAX_FILES:
        raise AttachmentError("每次最多上传 10 个附件。", "TOO_MANY_ATTACHMENTS")
    if sum(len(data) for _, _, data in files) > MAX_TOTAL_BYTES:
        raise AttachmentError("附件总大小超过 24 MiB 限制。", "ATTACHMENTS_TOO_LARGE")
    return [parse_attachment(data, name, mime) for name, mime, data in files]
