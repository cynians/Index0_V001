class TextEditing:
    """
    Shared cursor and buffer operations for small in-app text editors.
    """

    WORD_CHARS = {"_", "-"}

    @staticmethod
    def clamp_cursor(buffer_text, cursor):
        return max(0, min(len(str(buffer_text or "")), int(cursor)))

    @staticmethod
    def insert_text(buffer_text, cursor, text):
        text = str(text or "")
        if not text:
            return str(buffer_text or ""), TextEditing.clamp_cursor(buffer_text, cursor)

        buffer_text = str(buffer_text or "")
        cursor = TextEditing.clamp_cursor(buffer_text, cursor)
        return buffer_text[:cursor] + text + buffer_text[cursor:], cursor + len(text)

    @staticmethod
    def delete_before_cursor(buffer_text, cursor):
        buffer_text = str(buffer_text or "")
        cursor = TextEditing.clamp_cursor(buffer_text, cursor)
        if cursor <= 0:
            return buffer_text, cursor
        return buffer_text[:cursor - 1] + buffer_text[cursor:], cursor - 1

    @staticmethod
    def delete_after_cursor(buffer_text, cursor):
        buffer_text = str(buffer_text or "")
        cursor = TextEditing.clamp_cursor(buffer_text, cursor)
        if cursor >= len(buffer_text):
            return buffer_text, cursor
        return buffer_text[:cursor] + buffer_text[cursor + 1:], cursor

    @staticmethod
    def word_start_before_cursor(buffer_text, cursor):
        buffer_text = str(buffer_text or "")
        cursor = TextEditing.clamp_cursor(buffer_text, cursor)
        index = cursor
        while index > 0 and buffer_text[index - 1].isspace():
            index -= 1
        while index > 0 and (
            buffer_text[index - 1].isalnum()
            or buffer_text[index - 1] in TextEditing.WORD_CHARS
        ):
            index -= 1
        return index

    @staticmethod
    def word_end_after_cursor(buffer_text, cursor):
        buffer_text = str(buffer_text or "")
        cursor = TextEditing.clamp_cursor(buffer_text, cursor)
        index = cursor
        while index < len(buffer_text) and buffer_text[index].isspace():
            index += 1
        while index < len(buffer_text) and (
            buffer_text[index].isalnum()
            or buffer_text[index] in TextEditing.WORD_CHARS
        ):
            index += 1
        return index

    @staticmethod
    def delete_word_before_cursor(buffer_text, cursor):
        buffer_text = str(buffer_text or "")
        cursor = TextEditing.clamp_cursor(buffer_text, cursor)
        start = TextEditing.word_start_before_cursor(buffer_text, cursor)
        return buffer_text[:start] + buffer_text[cursor:], start

    @staticmethod
    def delete_word_after_cursor(buffer_text, cursor):
        buffer_text = str(buffer_text or "")
        cursor = TextEditing.clamp_cursor(buffer_text, cursor)
        end = TextEditing.word_end_after_cursor(buffer_text, cursor)
        return buffer_text[:cursor] + buffer_text[end:], cursor

    @staticmethod
    def line_start_before_cursor(buffer_text, cursor):
        buffer_text = str(buffer_text or "")
        cursor = TextEditing.clamp_cursor(buffer_text, cursor)
        return buffer_text.rfind("\n", 0, cursor) + 1

    @staticmethod
    def line_end_after_cursor(buffer_text, cursor):
        buffer_text = str(buffer_text or "")
        cursor = TextEditing.clamp_cursor(buffer_text, cursor)
        line_end = buffer_text.find("\n", cursor)
        return len(buffer_text) if line_end == -1 else line_end

    @staticmethod
    def parse_lines(buffer_text):
        lines = []
        for raw_line in str(buffer_text or "").splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("-"):
                stripped = stripped[1:].strip()
            if stripped:
                lines.append(stripped)
        return lines
