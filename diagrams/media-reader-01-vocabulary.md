# Правило 1: словарь и те, кто его читает

**Главная мысль: словарь живёт в `rules/src/media_reader.rs`, и каждый, кому он нужен, читает
его оттуда. Файл, который называет состояние сам, читает факт второй раз.**

```mermaid
flowchart TD
    HOME["media_reader.rs — Wired, Reader, MediaReader, word(), writes(), READER_WORD"]
    HOME --> J["журнал: part читается через Carried::verdict"]
    HOME --> R["слова отказа: читаются из ответа, а не из названия состояния"]
    HOME --> B["Routing: строка читателя рисует слово из Reader::word()"]
    HOME --> S["дверь сохранения: пишет то, что разрешил Reader::writes()"]
    HOME --> P["строка, которая отвечает: называет Wired::Nothing и говорит почему"]
```

Слово, которого у таблицы языка нет, сказано как его говорит программа, а не как догадка.
`READER_WORD` назван один раз: `audio` не правило этого файла, и `text` не требует читателя.

Проверяет: `scripts/check_media_reader.py`, список READERS. Отрицательный тест —
`scripts/test_guards_fail.py`.
