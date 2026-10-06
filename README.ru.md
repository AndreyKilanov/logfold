<p align="center"><a href="README.md">English</a> · <b>Русский</b></p>

<p align="center">
  <img src="docs/assets/logo.png" alt="logfold" width="240">
</p>

<h3 align="center">Библиотека и утилита для больших логов: сворачивает строки в шаблоны и сравнивает два запуска.</h3>

<p align="center">
  <a href="https://github.com/AndreyKilanov/logfold/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/AndreyKilanov/logfold/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/logfold/"><img alt="PyPI" src="https://img.shields.io/pypi/v/logfold"></a>
  <a href="https://pypi.org/project/logfold/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/logfold"></a>
  <a href="https://github.com/AndreyKilanov/logfold/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/github/license/AndreyKilanov/logfold"></a>
  <a href="https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md"><img alt="Rust core" src="https://img.shields.io/badge/core-Rust-orange"></a>
</p>

---

logfold читает лог и заменяет переменные части сообщений (числа, IP-адреса, UUID, пути) на маски. Строки с одинаковым
текстом после этого группируются в шаблоны. Для каждого шаблона считаются число записей, время первого и последнего
появления, наибольший уровень важности и пример строки. Команда `diff` сравнивает два запуска, например до и после
деплоя, и показывает новые, пропавшие и заметно изменившие долю шаблоны.

Ядро написано на Rust, пользоваться можно из Python или из командной строки. Всё выполняется локально, данные никуда
не отправляются.

```
$ logfold diff before.log after.log --out diff.html --fail-on-new
before.log -> after.log: 1,265,631 -> 1,246,573 records, 2 new (2 WARN+), 1 disappeared, 3 changed, 9 unchanged, native engine, 3.41s

New templates (2)
    before      after    change  level  template
         0     44,102       new  ERROR  circuit breaker opened for upstream <IP>
         0     44,310       new  WARN   queue depth <NUM> exceeds limit on worker-<NUM>
```

## Что делает

- **Шаблоны.** `user alice failed login from 10.0.0.7` и остальные такие же строки сводятся к одной записи
  `user <*> failed login from <IP>`. Алгоритм совместим с Drain3. Средняя точность группировки на 16 наборах Loghub-2k:
  Drain3 0,7658, logfold в последовательном режиме 0,7658, в параллельном 0,7643.
- **Сравнение двух запусков.** Доли шаблонов считаются от числа записей в каждом запуске, поэтому разный размер логов не
  мешает. Шаблон считается изменившимся, если его доля выросла или упала не меньше чем в 2 раза и хотя бы в одном из
  запусков у него не меньше 10 записей (оба порога настраиваются) и G-тест показывает, что изменение вряд ли случайно
  (`--significance`, по умолчанию 0,01); самые значимые изменения идут первыми. Одинаковые входы дают пустой результат.
- **Один лог и несколько baseline.** `diff app.log --split-at ВРЕМЯ` сравнивает часть одного лога до времени с частью
  после него (`--since` и `--until` ограничивают любую команду диапазоном времени). `--baseline` (повторяемый) объединяет
  несколько хороших запусков: шаблон считается новым, только если его нет ни в одном из них, и редкие сообщения не шумят.
- **Код выхода для CI.** `--fail-on-new` завершает команду с кодом 2, если появились новые шаблоны,
  `--fail-on-new-alerts` — если среди них есть WARN, ERROR или FATAL. Переформулированное сообщение, которое
  сопоставление по умолчанию связало со старым, считается изменённым, а не новым; `--matcher exact` делает проверку строгой.
  `--out ФАЙЛ --append` дописывает текстовый или Markdown-отчёт в конец файла, а не заменяет его: так несколько шагов
  задания пишут одну сводку (`$GITHUB_STEP_SUMMARY`); см. [logfold в CI](https://github.com/AndreyKilanov/logfold/blob/main/docs/ci.md).
- **Память.** Файл читается потоком, расход памяти не зависит от его размера. Входы: файлы, gzip, стандартный ввод,
  несколько файлов как один запуск.
- **Параллельность.** Большой файл режется на куски (по умолчанию 64 МиБ), деревья кусков сливаются по порядку. При
  фиксированном размере куска результат не зависит от числа потоков. Стратегия выбирается автоматически: большой файл
  обрабатывается параллельно, а последовательно, если первый кусок показывает, что почти каждая строка — новое сообщение
  (`--strategy auto`, по умолчанию). `--warm-start` запускает каждый кусок с дерева первого: заметно меньше лишних
  шаблонов ценой того, что первый кусок обрабатывается отдельно.
- **Маски значений.** По умолчанию заменяются UUID, время, IP, hex, пути и числа; правила можно менять.
- **Отчёты.** HTML (один файл, без сетевых запросов, со строгим CSP), JSON с версионируемой схемой, текст, Markdown, CSV.
  В отчёт по умолчанию попадают примеры сырых строк; `--examples masked` или `none` убирает их.
- **Расширения.** Форматы логов, отчёты и сопоставления шаблонов для `diff` подключаются плагинами через точки входа
  или из папки с `.py`-файлами.

## Установка

```
pip install "logfold[cli]"
```

Нужен Python 3.10 или новее. Для Linux (x86_64, aarch64, musl), macOS (x86_64, arm64) и Windows (x86_64) на PyPI лежат
уже собранные пакеты, поэтому pip ничего не компилирует и Rust устанавливать не нужно. На других системах pip соберёт
пакет из исходников, для этого понадобится компилятор Rust. Без `[cli]` ставится только библиотека.

## Быстрый старт

Разобрать лог:

```
logfold analyze app.log --top 30 --out report.html
logfold analyze app.log --only-alerts     # только шаблоны WARN, ERROR и FATAL
logfold inspect app.log                   # как читается файл: формат, первые записи, уровни
```

Формат определяется по образцу файла (nginx, apache, syslog, journald, Kubernetes, JSON-строки, logfmt и другие). Если
уверенности нет, команда выводит варианты и просит указать `--format`. Строки стек-трейса с отступом присоединяются к
записи, с которой они начались.

Сравнить два запуска:

```
logfold diff before.log after.log --out diff.html --fail-on-new-alerts
logfold diff app.log --split-at 2026-10-06T12:00    # часть одного лога до времени против части после него
logfold diff good1.log after.log --baseline good2.log --baseline good3.log   # новый = нет ни в одном хорошем запуске
logfold diff before.log after.log --report markdown --out "$GITHUB_STEP_SUMMARY" --append   # в CI: добавить в сводку задания
```

Коды выхода: `0` — успех, `1` — ошибка, `2` — найдено то, что запрошено флагами `--fail-on-*`.

Сравнить сохранённые результаты, не читая логи заново:

```
logfold analyze before.log --out before.json
logfold analyze after.log  --out after.json
logfold diff before.json after.json
```

JSON-файл, записанный через `--out`, содержит все шаблоны, поэтому подходит для такого сравнения.

## Из Python

```python
from logfold import analyze, diff, load_analysis

result = analyze("app.log")  # формат определяется сам
for template in result.top(10):
    print(template.count, template.level, template.text)
result.to_html("report.html")
result.filter(min_level="WARN").save("alerts.md")  # отчёт выбирается по суффиксу

comparison = diff("before.log", "after.log")
comparison.new_templates
comparison.new_alerts  # новые шаблоны уровня WARN/ERROR/FATAL
comparison.to_html("diff.html")

# сравнение сохранённых результатов
diff(load_analysis("before.json"), load_analysis("after.json"))
```

`analyze()` и `diff()` возвращают неизменяемые dataclass-объекты.

## Форматы и параметры

| | |
|---|---|
| Форматы | `nginx`, `apache`, `nginx-error`, `syslog`, `journald`, `k8s` (CRI/containerd), `jsonl`, `app` (`<время> УРОВЕНЬ сообщение`), `logfmt`, `serilog-clef`, `haproxy`, `postgresql`, `postgresql-csv`, `docker-json`, `github-actions`, `log4j` (или свой `log4j:<шаблон>`), `plain`, свой `regex:<шаблон>`. Список: `logfold formats`. |
| Многострочные записи | `--multiline`; при `--format auto` включается сам, если найдены строки с отступом. |
| Схлопывание | `--depth` (4), `--sim-th` (0,4), `--max-children` (100), `--max-templates` (100000). Значения по умолчанию те же, что у Drain3. |
| Выполнение | `--strategy auto` (по умолчанию; параллельные куски, последовательно для логов из уникальных сообщений), `sequential`, `chunked`; `--threads`, `--chunk-mb`; `--warm-start` (по желанию, только для chunked). |
| Логи с почти уникальными строками | `--high-cardinality`: не больше 5000 шаблонов, остальное попадает в сводные, выполняется последовательно. На файле в 10 МБ с 84 тысячами разных строк 2,0 с превращаются в 0,14 с. |
| Отчёты | HTML, JSON, текст, Markdown, CSV; суффикс `--out` выбирает формат, `--report ИМЯ` выбирает отчёт явно, в том числе плагинный. |
| Сопоставление для `diff` | `jaccard` (по умолчанию), `jaccard-idf`, `overlap`, `rules:ФАЙЛ` (свои пары), `token_subset`, `exact`: связывают переформулированное сообщение с его прежней версией, чтобы оно не считалось одновременно новым и пропавшим. |
| Плагины | `logfold plugins list` (встроенные, установленные, доступные из каталога), `info ИМЯ`, `check`, `install ИМЯ`, `new`; для неизвестного имени подсказка с командой установки. |
| Скрипты | `--json` печатает JSON в stdout, коды выхода стабильны, формат JSON описан схемой в `docs/schema`. |

## Скорость

Замеры на одной машине (8 ядер, Windows 11); протокол зафиксирован до запусков, подробности и данные в
[`bench/RESULTS.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/RESULTS.md).

| | logfold, 16 потоков | [Drain3](https://github.com/logpai/Drain3) (Python) |
|---|---:|---:|
| лог доступа nginx, 100 МБ | 0,38 с | 5,26 с |
| лог приложения, 100 МБ | 0,41 с | 9,03 с |
| лог доступа nginx с маскированием значений | 0,45 с | 26,82 с |
| HDFS, 1,57 ГБ, настоящий лог | 0,94 с | не измерялось |
| `diff` двух логов по 100 МБ | 0,7 с | `diff` нет |

На настоящих логах от 0,7 до 1,6 ГБ пик памяти от 42 до 51 МБ с одним потоком и от 107 до 129 МБ с 16 потоками.

## Ограничения

> [!WARNING]
> Учтите до того, как запускать logfold на больших логах и сравнивать результаты.
>
> - Скорость измерялась только на Windows 11; на Linux и macOS проверялась корректность, но не скорость.
> - Параллельный режим строит дерево на каждый кусок и сливает их, поэтому на логах без масок он может вернуть больше
>   шаблонов, чем последовательный (HDFS без масок: 341 против 43; `--warm-start` доводит до 45 ценой
>   последовательного первого куска). На логах с очень большим числом разных сообщений
>   стратегия `auto` по умолчанию замечает это по первому куску и переходит на последовательный режим; ещё быстрее
>   `--high-cardinality`.
> - Сохранённые результаты сравниваются без пересчёта по общему дереву шаблонов, поэтому одно и то же событие может
>   попасть и в новые, и в пропавшие; для этого есть сопоставление (по умолчанию `jaccard`).

## Замеры и сообщения об ошибках

logfold измерялся на одной машине (Windows 11, 8 ядер). Если вы можете запустить его на другом железе (Linux, macOS,
ARM, более медленный диск, больше ядер) или на своих логах, будем рады получить цифры. Также нам нужны сообщения о
неверных результатах, падениях, плохой группировке шаблонов и о запусках, которые идут медленно или расходуют слишком
много памяти.

- **Замеры.** Запустите бенчмарк по описанию в [`bench/README.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/README.md) (протокол лежит в
  [`bench/PROTOCOL.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/PROTOCOL.md)) или засеките время своей команды и создайте
  [issue о производительности](https://github.com/AndreyKilanov/logfold/issues/new?template=performance.yml). Укажите время выполнения, скорость и пиковую
  память, команду, размер и формат входа, процессор и число ядер, объём памяти, тип диска, ОС, версию logfold и число
  потоков.
- **Ошибки.** Создайте [issue об ошибке](https://github.com/AndreyKilanov/logfold/issues/new?template=bug_report.yml): что ожидали и что получилось, команда или
  фрагмент на Python, который воспроизводит проблему, вывод `logfold --version` и `logfold info`, несколько строк входа
  без секретов.

Все формы собраны на [странице создания issue](https://github.com/AndreyKilanov/logfold/issues/new/choose); как оформлять issues, описано в
[CONTRIBUTING.md](https://github.com/AndreyKilanov/logfold/blob/main/CONTRIBUTING.md#issues). Issues принимаются на английском.

## Чем отличается от других

| | logfold | [Drain3](https://github.com/logpai/Drain3) | [logdrain](https://github.com/vnvo/logdrain) | [logdelta](https://github.com/antonsoo/logdelta) |
|---|---|---|---|---|
| Язык | ядро на Rust, Python API и CLI | Python | Rust | Rust |
| Качество шаблонов | как у Drain3 на Loghub-2k | эталон | Drain | на основе Drain |
| Сравнение двух запусков | да (`diff`, доли нормируются, пересчёт) | нет | нет (онлайн-сигнал «создан шаблон») | да (`diff`, несколько baseline, блоки) |
| Python API | да | да | нет | нет |
| Многопоточный разбор одного большого файла | да, детерминированно | нет | для CLI не описано | не описано |
| Отчёты | JSON, HTML, текст, Markdown, CSV | - | текст, JSON, CSV | терминал, JSON, Markdown |

Качество шаблонов: `python eval/quality.py` (точность группировки на 16 наборах Loghub-2k).

## Документация

Документация написана на английском.

- [Руководство](https://github.com/AndreyKilanov/logfold/blob/main/docs/guide.md): форматы, параметры, плагины, движки.
- [logfold в CI](https://github.com/AndreyKilanov/logfold/blob/main/docs/ci.md): GitHub Actions и GitLab CI, сводка
  задачи, проверки, откуда брать baseline.
- [Справочник командной строки](https://github.com/AndreyKilanov/logfold/blob/main/docs/cli.md): команды, опции, коды
  выхода.
- [Плагины](https://github.com/AndreyKilanov/logfold/blob/main/docs/plugins.md): использование и написание форматов,
  отчётов и сопоставлений; пример пакета —
  [`examples/logfold-example-plugin`](https://github.com/AndreyKilanov/logfold/tree/main/examples/logfold-example-plugin).
- [Справочник Python API](https://github.com/AndreyKilanov/logfold/blob/main/docs/api.md).
- [Алгоритм](https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md),
  [JSON-схемы](https://github.com/AndreyKilanov/logfold/tree/main/docs/schema) и
  [история изменений](https://github.com/AndreyKilanov/logfold/blob/main/CHANGELOG.md).

## Устройство

Чистое ядро (маскирование, токенизатор, Drain-совместимое дерево, слияние) без ввода-вывода, адаптеры файлов и
форматов, слой выполнения, тонкая прослойка PyO3 и Python-пакет сверху. Алгоритм описан в
[`docs/ALGORITHM.md`](https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md). Эталонный движок на чистом
Python реализует ту же спецификацию, движок на Rust проверяется против него на точное равенство результатов.

## Разработка

Правила веток, коммитов и критерии готовности — в
[CONTRIBUTING.md](https://github.com/AndreyKilanov/logfold/blob/main/CONTRIBUTING.md). Об уязвимостях сообщайте
приватно, см. [SECURITY.md](https://github.com/AndreyKilanov/logfold/blob/main/SECURITY.md).

## Лицензия

MIT, см. [LICENSE](https://github.com/AndreyKilanov/logfold/blob/main/LICENSE). Copyright (c) 2026 Andrey Kilanov.
