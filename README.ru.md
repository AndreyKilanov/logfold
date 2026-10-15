<p align="center"><a href="https://github.com/AndreyKilanov/logfold/blob/main/README.md">English</a> · <b>Русский</b></p>

<p align="center">
  <img src="https://raw.githubusercontent.com/AndreyKilanov/logfold/main/docs/assets/logo.png" alt="logfold" width="240">
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
$ logfold diff before.log after.log --fail-on-new-alerts
before.log -> after.log: 364 -> 600 records, 1 new (1 WARN+), 0 disappeared, 1 changed, 2 unchanged, native engine, 0.01s

New templates (1)
    before       after    change  level  template
         0         180       new  ERROR  db connection timeout after <*> <*>

Changed templates (1)
    before       after    change       p  level  template
         4          60     x9.10  <0.001  WARN   retry <NUM> for order <NUM>
$ echo $?
2
```

## Попробовать за минуту

```
pip install "logfold[cli]"
logfold analyze app.log --out report.html                 # шаблоны одного лога со счётчиками и примерами
logfold diff before.log after.log --out diff.html         # что новое, пропало или изменилось между двумя запусками
```

Отчёт — один HTML-файл: без сетевых запросов, со строгой политикой безопасности содержимого, и каждое значение из лога
экранируется.

<p align="center">
  <img src="https://raw.githubusercontent.com/AndreyKilanov/logfold/main/docs/assets/report-diff.png" alt="HTML-отчёт logfold diff: новые, изменившиеся и пропавшие шаблоны и значения, которые различаются" width="820">
</p>

## Что вы хотите сделать

### Остановить задание в CI на новой ошибке

```yaml
      - uses: AndreyKilanov/logfold@v0.5.0
        with:
          log: current.log
```

Действие сравнивает лог запуска с последним хорошим, пишет сводку задания и завершает его с ошибкой, если появился новый
шаблон уровня WARN, ERROR или FATAL. Без GitHub: `logfold diff good.log current.log --fail-on-new-alerts` (код выхода 2) или
сохранённая модель: `logfold learn good.log --state model.json` и `logfold check current.log --state model.json`. Рецепты для GitHub Actions
и GitLab CI: [logfold в CI](https://github.com/AndreyKilanov/logfold/blob/main/docs/ci.md).

### Найти, что изменилось при инциденте

```
logfold diff app.log --split-at 2026-10-06T12:00           # лог до времени против лога после него
logfold diff before.log after.log --new-values             # значения, которые есть только в одном запуске
logfold diff docker:web-old docker:web-new                 # читать прямо из docker, kubectl или journalctl
```

[Что изменилось при инциденте](https://github.com/AndreyKilanov/logfold/blob/main/docs/incident.md) идёт по шагам и объясняет,
как читать результат.

### Безопасно поделиться логом или отчётом

```
logfold analyze app.log --masks all --examples none --out report.html
```

Наборы масок прячут ключи, токены, пароли, адреса почты, телефоны, номера карт и IBAN до того, как лог разобран, а
`--examples none` убирает примеры строк. Они снижают риск, но не убирают его: имена и слова сообщений остаются.
[Как безопасно поделиться логом или отчётом](https://github.com/AndreyKilanov/logfold/blob/main/docs/share-a-log.md) говорит, что
скрывает каждая опция и как проверить файл перед отправкой.

### Пользоваться из Python

```python
from logfold import analyze, check, diff

result = analyze("app.log")  # формат определяется сам
for template in result.top(10):
    print(template.count, template.level, template.text)

comparison = diff("before.log", "after.log")
comparison.new_alerts  # новые шаблоны WARN, ERROR и FATAL
comparison.to_html("diff.html")

analyze("good.log", save_state="model.json")  # модель: шаблоны и счётчики, примеров строк в ней нет
check("model.json", "today.log").passed
```

Результаты — неизменяемые датаклассы. [logfold в программе на Python](https://github.com/AndreyKilanov/logfold/blob/main/docs/python.md)
говорит, какой вызов за что отвечает, и ведёт к справочнику.

### Держать модель, проверять лог, следить за потоком

```
logfold learn good.log --state model.json                  # сохранить, как выглядит хороший запуск
logfold check today.log --state model.json                 # код выхода 2, если в логе есть то, чего модель не знает
logfold match model.json today.log                         # сколько записей не подошло ни к одному шаблону
tail -F app.log | logfold stream -f app                    # печатать каждый новый шаблон при первом появлении
```

В Python то же делает `logfold.Miner`: он принимает записи пачками и говорит, к какому шаблону подходит запись.

### Переходите с Drain3

Какие вызовы и настройки соответствуют друг другу и чем результат отличается, написано в
[переходе с Drain3](https://github.com/AndreyKilanov/logfold/blob/main/docs/migrating-from-drain3.md).

## Что делает

- **Шаблоны.** `user alice failed login from 10.0.0.7` и остальные такие же строки сводятся к одной записи
  `user <*> failed login from <IP>`. Алгоритм совместим с Drain3: на 16 наборах Loghub-2k средняя точность группировки
  0,7658 в последовательном режиме (как у Drain3) и 0,7643 в параллельном.
- **Сравнение двух запусков.** Доли шаблонов считаются от числа записей в каждом запуске, поэтому разный размер логов не
  мешает. Шаблон считается изменившимся, если его доля выросла или упала не меньше чем в 2 раза и хотя бы в одном из
  запусков у него не меньше 10 записей (оба порога настраиваются) и G-тест показывает, что изменение вряд ли случайно
  (`--significance`, по умолчанию 0,01); самые значимые изменения идут первыми. Одинаковые входы дают пустой результат.
- **Один лог и несколько baseline.** `diff app.log --split-at ВРЕМЯ` сравнивает часть одного лога до времени с частью
  после него (`--since` и `--until` ограничивают любую команду диапазоном времени). `--baseline` (повторяемый) объединяет
  несколько хороших запусков: шаблон считается новым, только если его нет ни в одном из них, и редкие сообщения не шумят.
- **Значения.** `analyze --values` считает значения на переменных позициях (частые значения и перцентили чисел);
  `diff --new-values` показывает значения, которые есть только в одном из двух запусков, для шаблонов, которые есть в обоих.
- **Код выхода для CI.** `--fail-on-new` завершает команду с кодом 2, если появились новые шаблоны,
  `--fail-on-new-alerts` — если среди них есть WARN, ERROR или FATAL. Переформулированное сообщение, которое
  сопоставление по умолчанию связало со старым, считается изменённым, а не новым; `--matcher exact` делает проверку строгой.
  `--out ФАЙЛ --append` дописывает текстовый или Markdown-отчёт в конец файла, а не заменяет его: так несколько шагов
  задания пишут одну сводку (`$GITHUB_STEP_SUMMARY`).
- **Можно делиться.** Наборы масок (`secrets`, `pii`, `credentials`, `payment`, `all`, ваши файлы) прячут значения до того, как
  они попадут в шаблон, сохранённую модель или отчёт; `--examples masked` или `none` решает судьбу примеров строк. HTML-отчёт
  экранирует всё.
- **Входы.** Файлы, gzip, стандартный ввод, несколько файлов как один запуск, а также `docker:ИМЯ`, `kubectl:NAMESPACE/POD` и
  `journalctl:UNIT`: чтение через ваши собственные программы, только для чтения и с ограничениями. Файл читается потоком,
  расход памяти не зависит от его размера.
- **Параллельность.** Большой файл режется на куски (по умолчанию 64 МиБ), деревья кусков сливаются по порядку. При
  фиксированном размере куска результат не зависит от числа потоков. Стратегия выбирается автоматически: большой файл
  обрабатывается параллельно, а последовательно, если первый кусок показывает, что почти каждая строка — новое сообщение
  (`--strategy auto`, по умолчанию).
- **Отчёты.** HTML, JSON с версионируемой схемой, текст, Markdown, CSV; для конвейеров `github-summary`, `junit`,
  `chat-message` и `prometheus`.
- **Настройки и расширения.** `logfold.toml` хранит параметры, которые вы повторяете. Форматы логов, отчёты, сопоставления
  шаблонов, наборы масок и источники подключаются плагинами через точки входа или из папки с `.py`-файлами.

## Установка

```
pip install "logfold[cli]"
```

Нужен Python 3.11 или новее. Для Linux (x86_64, aarch64, musl), macOS (x86_64, arm64) и Windows (x86_64) на PyPI лежат
уже собранные пакеты, поэтому pip ничего не компилирует и Rust устанавливать не нужно. На других системах pip соберёт
пакет из исходников, для этого понадобится компилятор Rust. Без `[cli]` ставится только библиотека.

## Форматы и на чём каждый проверен

`logfold formats` показывает список форматов. `--format auto` (по умолчанию) выбирает формат по образцу файла: nginx, apache,
syslog, journald, Kubernetes, JSON lines, logfmt и другие; если не уверен, перечисляет кандидатов и просит указать
`--format`. `logfold inspect app.log` показывает, как читается файл: формат, первые записи, уровни. Строки стека с отступом
присоединяются к записи, которая их начала.

Каждый формат сравнивали с чем-то вне этого проекта, и таблица говорит, с чем. Проверка не обещает, что формат читает любой
лог этой программы: настройки программы, которые не пробовали, и найденные пределы перечислены в
[таблице руководства](https://github.com/AndreyKilanov/logfold/blob/main/docs/guide.md#what-each-format-was-checked-on)
и в `logfold plugins info ИМЯ`.

<!-- format-checks:start -->
| Проверено на | Форматы |
|---|---|
| Настоящая программа, каждая запись сверена с тем, что она записала (HAProxy 2.8–3.2, PostgreSQL 13–17, log4j2, logback и log4j 1.x, Docker 28) | `haproxy`, `postgresql`, `postgresql-csv`, `log4j`, `docker-json` |
| Журналы заданий собственных запусков GitHub Actions этого проекта | `github-actions` |
| Образцы и логи других проектов (Filebeat, Fluent Bit, Loki, Loghub) и сгенерированные логи | `nginx`, `apache`, `nginx-error`, `syslog`, `k8s`, `jsonl`, `logfmt`, `app` |
| Только повреждённые логи (fuzzing); настоящей программы и образцов пока нет | `plain`, `journald`, `serilog-clef` |
<!-- format-checks:end -->

Свой формат: `--format regex:<шаблон>` или `log4j:<шаблон>`. Лог другой программы со временем и уровнем в тех же местах читает
`app` (`<время> УРОВЕНЬ сообщение`).

## Параметры

| | |
|---|---|
| Многострочные записи | `--multiline`; с `--format auto` включается сам, если найдены строки с отступом. |
| Свёртка | `--depth` (4), `--sim-th` (0,4), `--max-children` (100), `--max-templates` (100000), `--on-full evict` (при пределе вытеснять давно не использованные шаблоны вместо складывания новых в общие), `--delimiters` (символы-разделители токенов). Значения по умолчанию те же, что в Drain3. |
| Выполнение | `--strategy auto` (по умолчанию; параллельные куски, последовательно для логов из уникальных сообщений), `sequential`, `chunked`; `--threads`, `--chunk-mb`; `--warm-start` (по желанию, только chunked: заметно меньше лишних шаблонов ценой того, что первый кусок обрабатывается отдельно). |
| Логи из почти уникальных строк | `--high-cardinality`: не более 5000 шаблонов, остальное уходит в общие шаблоны, работает последовательно. |
| Маски | маски по умолчанию заменяют UUID, время, IP, hex, пути и числа; `--masks secrets,pii`, `--masks all`, `--masks-file ФАЙЛ` добавляют наборы, которые идут первыми (`logfold masks list`). |
| Значения | `analyze --values`, `diff --new-values` (`--values-templates N`); `logfold params ШАБЛОН СООБЩЕНИЕ` (Python: `logfold.extract_parameters`) даёт значения одного сообщения на переменных местах шаблона. |
| Диапазон времени | `--since`, `--until`; `diff --split-at ВРЕМЯ`. |
| Уровни | `--level ERROR` оставляет шаблоны, у которых наибольший уровень не ниже указанного; `--only-alerts` — то же, что `--level WARN`. |
| Сохранённые результаты | `logfold analyze before.log --out before.json`, затем `logfold diff before.json after.json` сравнивает их без повторного чтения логов. |
| Модели и потоки | `learn`, `check`, `match`, `stream`; `--save-state` и `--load-state` продолжают запуск с сохранённой модели, в том числе параллельно. |
| Отчёты | суффикс `--out` выбирает формат (`.html`, `.json`, `.txt`, `.md`, `.csv`, `.xml` для JUnit, `.prom`), `--report ИМЯ` выбирает явно, в том числе из плагина. |
| Сопоставления для `diff` | `jaccard` (по умолчанию), `jaccard-idf`, `overlap`, `rules:ФАЙЛ` (ваши пары), `token_subset`, `exact`: они связывают переформулированное сообщение с прежним, чтобы оно не считалось и новым, и пропавшим. |
| Плагины | `logfold plugins list` (встроенные, установленные, доступные), `info ИМЯ`, `check`, `install ИМЯ`, `new`; неизвестное имя формата, отчёта или сопоставления получает подсказку с ближайшим именем или командой установки. |
| Скрипты | `--json` печатает JSON в стандартный вывод, коды выхода стабильны (`0`, `1`, `2` для находки `--fail-on-*`), формат JSON описан схемой в `docs/schema`. |

Все команды и опции: [справочник командной строки](https://github.com/AndreyKilanov/logfold/blob/main/docs/cli.md).

## Скорость

Измерено на одной машине (8 ядер, Windows 11) на этой версии; протокол — в
[`bench/PROTOCOL.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/PROTOCOL.md), сравнение с другими инструментами — в
[`bench/RESULTS.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/RESULTS.md).

| | 1 поток | 16 потоков |
|---|---:|---:|
| `analyze`, access-лог nginx, 100 МБ | 0,93 с | 0,45 с |
| `analyze`, лог приложения, 100 МБ | 0,83 с | 0,45 с |
| `diff` двух логов по 100 МБ | 2,55 с | 0,69 с |

Пиковая память: 46 МБ в один поток и 97–110 МБ в 16 потоков на файлах по 100 МБ, с размером файла она не растёт. Наборы масок
добавляют 5–15% (`secrets` и `pii`) или 11–24% (`all`); `--values` работает в три–четыре раза дольше `analyze`, а
`diff --new-values` — в 1,5–3 раза дольше `diff`.

## Ограничения

> **Предупреждение.** Помните об этом, прежде чем запускать logfold на больших логах и сравнивать результаты.
>
> - Скорость измерена только на Windows 11; на Linux и macOS проверяется корректность, а скорость нет.
> - Параллельный режим строит дерево на каждый кусок и сливает их, поэтому на логах без масок он может вернуть больше
>   шаблонов, чем последовательный (HDFS без масок: 341 против 43; `--warm-start` снижает до 45 ценой отдельного первого
>   куска). На логах с очень большим числом разных сообщений стратегия `auto` по умолчанию замечает это после первого куска и
>   переходит на последовательный режим; `--high-cardinality` делает его ещё быстрее.
> - Сохранённые результаты сравниваются без пересчёта по общему дереву шаблонов, поэтому одно и то же событие может попасть
>   и в новые, и в пропавшие; для этого и нужно сопоставление (по умолчанию `jaccard`).
> - Наборы масок снижают риск, когда вы делитесь логом, но не убирают его, а формат проверен на том, что сказано в таблице
>   выше, а не на всех настройках программы.

## Замеры и сообщения об ошибках

logfold измеряли на одной машине (Windows 11, 8 ядер). Если вы можете запустить его на другом железе (Linux, macOS, ARM,
более медленный диск, больше ядер) или на своих логах, мы будем рады цифрам. Нам также нужны сообщения о неверных
результатах, падениях, плохо сгруппированных шаблонах и запусках, которые медленны или съедают слишком много памяти.

- **Замеры.** Запустите бенчмарк, как описано в [`bench/README.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/README.md) (протокол —
  в [`bench/PROTOCOL.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/PROTOCOL.md)), или засеките свою команду и создайте
  [issue о производительности](https://github.com/AndreyKilanov/logfold/issues/new?template=performance.yml). Укажите время выполнения, скорость и пиковую
  память, команду, размер и формат входа, процессор и число ядер, объём памяти, тип диска, ОС, версию logfold и число
  потоков.
- **Ошибки.** Создайте [issue об ошибке](https://github.com/AndreyKilanov/logfold/issues/new?template=bug_report.yml): что ожидали и что получилось, команда или
  фрагмент на Python, который воспроизводит проблему, вывод `logfold --version` и `logfold info`, несколько строк входа
  без секретов.
- **Лог читается неверно.** Потерялись строки или запись разрезана не там, поле попало не туда, `-f auto` выбрал не тот
  формат: заполните [форму о формате](https://github.com/AndreyKilanov/logfold/issues/new?template=format_problem.yml). Укажите программу и её версию, изменённые настройки журнала, вывод
  `logfold inspect FILE` и около 20 настоящих строк без секретов. Форматы проверены на настоящих программах и на логах
  других проектов, но не на всех настройках; эта форма — способ найти остальное.

Все формы собраны на [странице создания issue](https://github.com/AndreyKilanov/logfold/issues/new/choose); как оформлять issues, описано в
[CONTRIBUTING.md](https://github.com/AndreyKilanov/logfold/blob/main/CONTRIBUTING.md#issues). Issues принимаются на английском.

## Документация

Документация написана на английском.

- [Руководство](https://github.com/AndreyKilanov/logfold/blob/main/docs/guide.md): типичные задачи, форматы, параметры, плагины, движки.
- [logfold в CI](https://github.com/AndreyKilanov/logfold/blob/main/docs/ci.md): GitHub Actions и GitLab CI, сводка
  задачи, проверки, откуда брать baseline.
- [Что изменилось при инциденте](https://github.com/AndreyKilanov/logfold/blob/main/docs/incident.md): сравнить два лога или две части одного, прочитать результат, заглянуть в шаблон.
- [Как безопасно поделиться логом или отчётом](https://github.com/AndreyKilanov/logfold/blob/main/docs/share-a-log.md): наборы масок, примеры, что остаётся в отчёте, как проверить.
- [logfold в программе на Python](https://github.com/AndreyKilanov/logfold/blob/main/docs/python.md): какой вызов за что отвечает, со ссылками на справочник API.
- [Справочник командной строки](https://github.com/AndreyKilanov/logfold/blob/main/docs/cli.md): команды, опции, коды
  выхода.
- [Файл настроек](https://github.com/AndreyKilanov/logfold/blob/main/docs/config.md): `logfold.toml`.
- [Плагины](https://github.com/AndreyKilanov/logfold/blob/main/docs/plugins.md): использование и написание форматов,
  отчётов и сопоставлений; пример пакета —
  [`examples/logfold-example-plugin`](https://github.com/AndreyKilanov/logfold/tree/main/examples/logfold-example-plugin).
- [Справочник Python API](https://github.com/AndreyKilanov/logfold/blob/main/docs/api.md).
- [Переход с Drain3](https://github.com/AndreyKilanov/logfold/blob/main/docs/migrating-from-drain3.md): какие вызовы и
  настройки соответствуют, чем отличается результат, чего в logfold нет.
- [Алгоритм](https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md),
  [JSON-схемы](https://github.com/AndreyKilanov/logfold/tree/main/docs/schema) и
  [история изменений](https://github.com/AndreyKilanov/logfold/blob/main/CHANGELOG.md).

## Устройство

Чистое ядро (маскирование, токенизатор, Drain-совместимое дерево, слияние) без ввода-вывода, адаптеры файлов и
форматов, слой выполнения, тонкая прослойка PyO3 и Python-пакет сверху. Алгоритм описан в
[`docs/ALGORITHM.md`](https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md). Движок на Rust —
единственная реализация; эталонные результаты, property-тесты и сравнение с Drain3 на Loghub удерживают его в рамках спецификации.

## Разработка

Правила веток, коммитов и критерии готовности — в
[CONTRIBUTING.md](https://github.com/AndreyKilanov/logfold/blob/main/CONTRIBUTING.md). Об уязвимостях сообщайте
приватно, см. [SECURITY.md](https://github.com/AndreyKilanov/logfold/blob/main/SECURITY.md).

## Лицензия

MIT, см. [LICENSE](https://github.com/AndreyKilanov/logfold/blob/main/LICENSE). Copyright (c) 2026 Andrey Kilanov.
