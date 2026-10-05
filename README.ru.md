<p align="center"><a href="README.md">English</a> · <b>Русский</b></p>

<p align="center">
  <img src="docs/assets/logo.png" alt="logfold" width="240">
</p>

<h3 align="center">Превращает миллион строк лога в десяток шаблонов и точно показывает, что изменилось между двумя запусками.</h3>

<p align="center">
  <a href="https://github.com/AndreyKilanov/logfold/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/AndreyKilanov/logfold/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/logfold/"><img alt="PyPI" src="https://img.shields.io/pypi/v/logfold"></a>
  <a href="https://pypi.org/project/logfold/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/logfold"></a>
  <a href="https://github.com/AndreyKilanov/logfold/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/github/license/AndreyKilanov/logfold"></a>
  <a href="https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md"><img alt="Rust core" src="https://img.shields.io/badge/core-Rust-orange"></a>
</p>

---

После деплоя сервис ведёт себя странно. Лог — 2 ГБ одинаковых на вид строк, а `grep` находит только то, что вы и так
подозревали. **logfold** превращает этот шум в короткий список шаблонов сообщений со счётчиками, уровнями важности и
примерами, а ещё **сравнивает два запуска** и показывает, что появилось, что пропало и что вдруг стало встречаться
намного чаще. Всё работает офлайн, на вашей машине и за секунды: не нужно разворачивать платформу и выгружать данные.

```
$ logfold diff before.log after.log --out diff.html --fail-on-new
before.log -> after.log: 1,265,631 -> 1,246,573 records, 2 new (2 WARN+), 1 disappeared, 3 changed, 9 unchanged, native engine, 3.41s

New templates (2)
    before      after    change  level  template
         0     44,102       new  ERROR  circuit breaker opened for upstream <IP>
         0     44,310       new  WARN   queue depth <NUM> exceeds limit on worker-<NUM>
```

## За что его полюбят

| | |
|---|---|
| **Миллион строк — десяток шаблонов** | `user alice failed login from 10.0.0.7` и миллион таких же строк превращаются в одну: `user <*> failed login from <IP>`, со счётчиком, временем первого и последнего появления, уровнем и примером. Группировка совпадает с [Drain3](https://github.com/logpai/Drain3) на Loghub-2k. |
| **Видно, что изменил деплой** | `diff` сравнивает два запуска: новые, пропавшие и изменившиеся шаблоны, с поправкой на размер лога, поэтому более длинный лог не выглядит как регрессия. Одинаковые входы дают пустой diff. |
| **Проверка для CI** | `--fail-on-new-alerts` завершает команду с кодом 2, если появился новый шаблон уровня WARN, ERROR или FATAL. Одна строка превращает лог в тест. |
| **Быстро даже на ноутбуке** | Ядро на Rust читает файл потоком, а память не растёт с его размером. Все ядра заняты: 100 МБ за 0,4 с, лог HDFS на 1,6 ГБ примерно за секунду, результат не зависит от числа потоков. |
| **Отчёты, которые хочется открыть** | Самодостаточная HTML-страница (без сети, со строгим CSP), JSON с версионируемой схемой, Markdown, CSV и обычный текст. |
| **Приватность по умолчанию** | Всё выполняется локально. Значения вроде UUID, IP и чисел маскируются, а `--examples masked` или `none` не пускает сырые строки в отчёт, которым вы делитесь. |
| **Прежде всего Python-библиотека** | `analyze()` и `diff()` возвращают простые неизменяемые dataclass-объекты; командная строка — тонкий слой над тем же API. |
| **Расширяется под вас** | Форматы логов, отчёты и сопоставления для diff — плагины. `logfold plugins` показывает и ставит новые, а для своих хватит папки с `.py`-файлами. |

## Установка

```
pip install "logfold[cli]"
```

Готовые колёса для Linux, macOS и Windows (Python 3.10+): на вашей машине ничего не компилируется. Без `[cli]`
устанавливается только библиотека.

## Три сценария для начала

**1. Разобраться в логе.**

```
logfold analyze app.log --top 30 --out report.html
```

Формат определяется сам (nginx, apache, syslog, journald, Kubernetes, JSON-строки, logfmt и другие), gzip-файлы
читаются как есть, `-` читает стандартный ввод, а строки стек-трейса с отступом присоединяются к записи, с которой они
начались.

**2. Сравнить до и после деплоя.**

```
logfold diff before.log after.log --out diff.html --fail-on-new-alerts
```

Откройте `diff.html`, чтобы увидеть таблицы, либо пусть CI смотрит на код выхода (`0` — всё хорошо, `2` — появилось
что-то новое и плохое, `1` — ошибка).

**3. Сравнивать потом, без самих логов** (*новое в 0.3.0*).

```
logfold analyze before.log --out before.json
logfold analyze after.log  --out after.json
logfold diff before.json after.json --matcher token_subset
```

Храните маленькие JSON-отчёты вместо гигабайтов логов и сравнивайте любые два из них, когда захотите.

## Из Python

```python
from logfold import analyze, diff, load_analysis

result = analyze("app.log")  # формат определяется сам
for template in result.top(10):
    print(template.count, template.level, template.text)
result.to_html("report.html")

comparison = diff("before.log", "after.log")
comparison.new_templates
comparison.new_alerts  # новые шаблоны уровня WARN/ERROR/FATAL
comparison.to_html("diff.html")

# новое в 0.3.0: сравнение сохранённых результатов
diff(load_analysis("before.json"), load_analysis("after.json"))
```

## Что он умеет

| | |
|---|---|
| **Форматы** | `nginx`, `apache`, `nginx-error`, `syslog`, `journald`, Kubernetes (`k8s`), JSON-строки, `app` (`<время> УРОВЕНЬ сообщение`), `logfmt`, Serilog CLEF, `plain` или собственный `regex:<шаблон>`. `--format auto` смотрит на образец файла и честно говорит, если не уверен. |
| **Входы** | Файлы, gzip, стандартный ввод, несколько файлов как один запуск. Многострочные записи (стек-трейсы) с `--multiline`. |
| **Маскирование** | UUID, время, IP, hex, пути и числа превращаются в `<UUID>`, `<IP>`, `<NUM>` и так далее; правила можно менять. |
| **Трудные данные** | `--high-cardinality` для логов, где почти каждая строка уникальна: ограниченная память и заметно быстрее (на файле в 10 МБ с 2,0 с до 0,14 с). |
| **Отчёты** | HTML, JSON, текст, Markdown и CSV; `--report ИМЯ` (*0.3.0*) выбирает любой отчёт, в том числе ваш. |
| **Сравнение** | Новые, пропавшие и изменившиеся шаблоны; пороги под вашим контролем; сопоставления (`exact`, `token_subset`, `jaccard`), которые связывают переформулированное сообщение с его прежней версией. |
| **Плагины** | `logfold plugins list`, `check`, `install`, `new`; точки входа или просто папка с `.py`-файлами. |
| **Скрипты** | Стабильные коды выхода, `--json` в stdout, документированная JSON-схема. |

## Как быстро

Замеры на одной машине (8 ядер, Windows 11), протокол зафиксирован до запусков. Подробности —
в [`bench/RESULTS.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/RESULTS.md).

| | logfold, 16 потоков | [Drain3](https://github.com/logpai/Drain3) (Python) |
|---|---:|---:|
| лог доступа nginx, 100 МБ | **0,38 с** | 5,26 с |
| лог приложения, 100 МБ | **0,41 с** | 9,03 с |
| лог доступа nginx с маскированием значений | **0,45 с** | 26,82 с |
| HDFS, 1,57 ГБ, настоящий лог | **0,94 с** | не измерялось |
| `diff` двух логов по 100 МБ | **0,7 с** | `diff` нет |

На настоящих логах от 0,7 до 1,6 ГБ память достигает примерно 45 МБ с одним потоком и 110 МБ с 16 потоками.

## Чем отличается от других

| | logfold | [Drain3](https://github.com/logpai/Drain3) | [logdrain](https://github.com/vnvo/logdrain) | [logdelta](https://github.com/antonsoo/logdelta) |
|---|---|---|---|---|
| Язык | ядро на Rust, Python API и CLI | Python | Rust | Rust |
| Качество шаблонов | совпадает с Drain3 на Loghub-2k | эталон | Drain | на основе Drain |
| Сравнение двух запусков | да (`diff`, доли нормируются, пересчёт) | нет | нет (онлайн-сигнал «создан шаблон») | да (`diff`, несколько baseline, блоки) |
| Python API | да | да | нет | нет |
| Многопоточный разбор одного большого файла | да, детерминированно | нет | для CLI не описано | не описано |
| Отчёты | JSON, HTML, текст, Markdown, CSV | - | текст, JSON, CSV | терминал, JSON, Markdown |

Качество шаблонов: `python eval/quality.py` (точность группировки на 16 наборах Loghub-2k).

## Документация

Документация написана на английском.

- [Руководство](https://github.com/AndreyKilanov/logfold/blob/main/docs/guide.md): форматы, параметры, плагины, движки.
- [Справочник командной строки](https://github.com/AndreyKilanov/logfold/blob/main/docs/cli.md): все команды, опции и
  коды выхода.
- [Плагины](https://github.com/AndreyKilanov/logfold/blob/main/docs/plugins.md): как использовать и писать форматы,
  отчёты и сопоставления для diff; готовый пример пакета —
  [`examples/logfold-example-plugin`](https://github.com/AndreyKilanov/logfold/tree/main/examples/logfold-example-plugin).
- [Справочник Python API](https://github.com/AndreyKilanov/logfold/blob/main/docs/api.md): `analyze`, `diff`, результаты,
  настройки, ошибки, отчёты и точки расширения.
- [Алгоритм](https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md), [JSON-схемы](https://github.com/AndreyKilanov/logfold/tree/main/docs/schema)
  и [история изменений](https://github.com/AndreyKilanov/logfold/blob/main/CHANGELOG.md).

## Устройство

Слоями: чистое ядро предметной области (маскирование, токенизатор, Drain-совместимое дерево, слияние) без ввода-вывода,
адаптеры для файлов и форматов, слой выполнения, тонкая прослойка PyO3 и сверху Python-пакет. Алгоритм описан в
[`docs/ALGORITHM.md`](https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md); эталонный движок на чистом
Python реализует ту же спецификацию, а движок на Rust проверяется против него на точное равенство.

## Участие

Issues и pull request приветствуются, см.
[CONTRIBUTING.md](https://github.com/AndreyKilanov/logfold/blob/main/CONTRIBUTING.md) (ветки, коммиты, issues, критерии
готовности). Об уязвимостях сообщайте приватно, см.
[SECURITY.md](https://github.com/AndreyKilanov/logfold/blob/main/SECURITY.md).

## Лицензия

MIT, см. [LICENSE](https://github.com/AndreyKilanov/logfold/blob/main/LICENSE). Copyright (c) 2026 Andrey Kilanov.
