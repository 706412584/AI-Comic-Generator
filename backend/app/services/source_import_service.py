import re


LINE_CHAPTER_TITLE_RE = re.compile(
    r"(?m)^\s*(第\s*[0-9一二三四五六七八九十百千万零〇两]+\s*[章节回卷][^\n\r]*)\s*$"
)
INLINE_CHAPTER_TITLE_RE = re.compile(
    r"第\s*([0-9一二三四五六七八九十百千万零〇两]+)\s*([章节回卷])([^\n\r]{0,60})"
)
CHAPTER_MARK_RE = re.compile(r"^第\s*[0-9一二三四五六七八九十百千万零〇两]+\s*[章节回卷]")
CHINESE_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def chinese_number_to_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)

    total = 0
    section = 0
    number = 0
    has_unit = False
    for char in value:
        if char in CHINESE_DIGITS:
            number = CHINESE_DIGITS[char]
        elif char in CHINESE_UNITS:
            has_unit = True
            unit = CHINESE_UNITS[char]
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = 0
            else:
                section += (number or 1) * unit
            number = 0
        else:
            return None
    result = total + section + number
    if not has_unit and result == 0 and value not in {"零", "〇"}:
        return None
    return result


def clean_title(title: str) -> str:
    title = re.sub(r"[\r\n]+", " ", title).strip()
    return title[:200]


def is_chapter_title_line(title: str) -> bool:
    title = title.strip()
    if not title or len(title) > 120:
        return False
    suffix = CHAPTER_MARK_RE.sub("", title, count=1).strip(" ：:、.．-—_《》（）()\t")
    if suffix in {"正文", "内容", "正文开始", "章节内容"}:
        return False
    return True


def count_text_chars(text: str) -> int:
    return len((text or "").strip())


def extract_chapter_number(title: str) -> int | None:
    match = re.search(r"第\s*([0-9一二三四五六七八九十百千万零〇两]+)\s*[章节回卷]", title)
    if not match:
        return None
    return chinese_number_to_int(match.group(1))


def find_chapter_matches(text: str) -> list[tuple[int, str, int | None]]:
    line_matches = [
        (match.start(), clean_title(match.group(1)), extract_chapter_number(match.group(1)))
        for match in LINE_CHAPTER_TITLE_RE.finditer(text)
        if is_chapter_title_line(match.group(1))
    ]

    inline_matches = []
    for match in INLINE_CHAPTER_TITLE_RE.finditer(text):
        number = chinese_number_to_int(match.group(1))
        if number is None:
            continue
        title = clean_title(match.group(0))
        if not is_chapter_title_line(title):
            continue
        inline_matches.append((match.start(), title, number))

    if not inline_matches:
        return line_matches

    start_index = next((index for index, (_, _, number) in enumerate(inline_matches) if number == 1), 0)
    filtered = []
    expected = None
    for item in inline_matches[start_index:]:
        _, _, number = item
        if expected is None:
            expected = number
        if number == expected:
            filtered.append(item)
            expected += 1
        elif number and expected and number > expected:
            filtered.append(item)
            expected = number + 1
    return filtered if len(filtered) > len(line_matches) else line_matches


def find_custom_chapter_matches(text: str, pattern: str) -> list[tuple[int, str, int | None]]:
    compiled = re.compile(pattern, re.MULTILINE)
    matches = []
    for match in compiled.finditer(text):
        title = match.group(1) if match.groups() else match.group(0)
        title = clean_title(title)
        if is_chapter_title_line(title):
            matches.append((match.start(), title, extract_chapter_number(title)))
    return matches


def split_novel_chapters(raw_text: str, pattern: str | None = None) -> list[dict]:
    text = (raw_text or "").replace("\ufeff", "").strip()
    if not text:
        return []

    matches = find_custom_chapter_matches(text, pattern) if pattern else find_chapter_matches(text)
    if not matches:
        return [{"sequence": 1, "title": "全文", "raw_text": text, "raw_word_count": count_text_chars(text)}]

    chapters = []
    preface = text[:matches[0][0]].strip()
    if preface:
        chapters.append({
            "sequence": len(chapters) + 1,
            "title": "序章",
            "raw_text": preface,
            "raw_word_count": count_text_chars(preface),
        })

    for index, (start, title, _number) in enumerate(matches):
        end = matches[index + 1][0] if index + 1 < len(matches) else len(text)
        chapter_text = text[start:end].strip()
        chapters.append({
            "sequence": len(chapters) + 1,
            "title": title,
            "raw_text": chapter_text,
            "raw_word_count": count_text_chars(chapter_text),
        })

    return chapters
