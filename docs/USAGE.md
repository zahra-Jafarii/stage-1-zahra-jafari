# راهنمای استفاده از پکیج کارخانه‌ی داده (مرحله ۱) در مراحل بعد

این پکیج یک **کتابخانه** است. مرحله‌های ۲ و ۳ آن را نصب و صدا می‌زنند و **هیچ‌وقت کد مرحله ۱ را ویرایش نمی‌کنند**.
هر مرحله کانفیگ، contract و دیتاست مخصوص خودش را در پروژه‌ی خودش نگه می‌دارد.

## ۱. نصب در پروژه‌ی مرحله‌ی بعد

```bash
pip install -e ../stage-1-zahra-jafarii
pip install SQLAlchemy psycopg2-binary   # فقط اگر مقصد دیتابیس است
```

بعد از نصب، در پروژه‌ی مرحله‌ی بعد می‌شود نوشت `from nyc311_factory.pipeline import run_pipeline`.

## ۲. یک ورودی اصلی: `run_pipeline`

برای کار عادی لازم نیست فایل‌ها را جدا جدا صدا بزنی. یک تابع کل زنجیره را اجرا می‌کند:

```python
from nyc311_factory.config import Config
from nyc311_factory.pipeline import run_pipeline

manifest = run_pipeline(config, dataset=MY_DATASET)
```

چیزی که تو می‌دهی: `config` (کجا بخوان، کجا بنویس، آستانه‌ی قرنطینه) و `dataset` (contract تو).
چیزی که پکیج انجام می‌دهد: خواندن، اعتبارسنجی، قرنطینه، پاکسازی، نوشتن در مقصد، گزارش کیفیت و manifest.

## ۳. چه فایل‌هایی لازم‌اند و چه فایل‌هایی اختیاری

| بخش | فایل‌ها | وضعیت |
|---|---|---|
| هسته | `pipeline`، `contract`، `dataset`، `validator`، `transformer`، `manifest`، `quality_report`، `config`، `exceptions`، `files`، `parsing` | همیشه کار می‌کنند و لازم‌اند |
| ورودی | `sources` (فایل csv و jsonl) | یکی‌شان به‌کار می‌رود |
| مقصد | `sinks` (csv و database) | یکی یا هر دو |
| اختیاری | `rules` (قوانین آماده)، `enrichers` (اتصال جدول مرجع) | اگر نیاز نداری، import نمی‌شوند |
| فقط NYC | `api_source`، `fetcher`، `http_client`، `reference`، `aggregate`، `analysis`، `datasets/` | مرحله‌های دیگر لازم ندارند |

پوشه‌ی `datasets/` فقط دیتاست NYC و ثبت‌نام آن را نگه می‌دارد. اگر `run_pipeline` را با `dataset=` صدا بزنی، این پوشه اصلاً import نمی‌شود.

## ۴. ترتیب اجرا و جای هر فایل

۱. `config`: خواندن و اعتبارسنجی کانفیگ.

۲. `dataset` و `contract`: ساخت contract.

۳. `sources`: ساخت منبع (فقط برای API مرحله‌ی دانلود دارد).

۴. هر دسته از داده:
   - `validator`: چک نوع ستون‌ها، اعتبارسنجی و ساخت دلیل قرنطینه
   - `transformer`: تکراری‌ها و پاکسازی
   - تابع `derive` دیتاست: ستون‌های مشتق
   - `enrichers`: اتصال جدول مرجع (اگر تعریف کرده باشی)
   - `quality_report`: آمار هر ستون
   - `sinks`: نوشتن (موقت)

۵. بعد از آخرین دسته: چک ستون‌های اجباری، چک آستانه‌ی قرنطینه، انتشار مقصدها.

۶. `quality_report.json` و آخر از همه `manifest_run.json`.

## ۴.۱ فایل‌هایی که ساخته می‌شوند

در `curated_dir`: `cases.csv`، `quarantine.csv` (اگر مقصد csv باشد)، `quality_report.json` و `manifest_run.json`.
در مقصد دیتابیس: جدول داده و جدول قرنطینه.

## ۵. مرحله‌ی ۲: بارگذاری خروجی مرحله‌ی ۱ در دیتابیس

دو حالت داری، با کلید `database_load_mode`:

| حالت | رفتار |
|---|---|
| `replace` | پکیج خودش جدول را می‌سازد و جایگزین می‌کند |
| `existing` | جدول‌هایی که خودت ساخته‌ای (کلید، ایندکس، view) می‌مانند و فقط ردیف‌ها دوباره پر می‌شوند |

برای جدول‌های ساخته‌شده‌ی خودت `existing` را بگذار. اسم ستون‌های جدول باید با ستون‌های خروجی بخواند.

```json
{
  "dataset": "nyc311",
  "source_type": "api",
  "api_url": "...",
  "start_date": "2024-01-01",
  "end_date": "2025-07-01",
  "destinations": ["database"],
  "database_schema": "نام_schema",
  "database_cases_table": "نام_جدول",
  "database_quarantine_table": "نام_جدول_قرنطینه",
  "database_load_mode": "existing",
  "quarantine_threshold": 0.05,
  "curated_dir": "data/curated"
}
```

```bash
export DATABASE_URL="postgresql+psycopg2://user:pass@localhost:5432/dbname"
nyc311-factory process --destinations database
```

رمز دیتابیس هیچ‌وقت داخل کانفیگ نمی‌رود؛ فقط از متغیر محیطی `DATABASE_URL` خوانده می‌شود.

## ۶. مرحله‌ی ۳: دیتاست و ورودی فایل خودت

سه فایل در پروژه‌ی خودت بنویس (نمونه‌ی کامل و اجراشده در `examples/new_dataset/`):

۱. `my_dataset.py`: یک `Contract` و یک `Dataset`.
۲. `config.json`: کانفیگ کوچک خودت.
۳. `run.py`: صدا زدن `run_pipeline`.

```python
from nyc311_factory.contract import Column, Contract
from nyc311_factory.dataset import Dataset

CONTRACT = Contract(
    name="my_data",
    source_columns=(Column("id", "str", nullable=False), ...),
    derived_columns=(),
    key_column="id",
    content_columns=("...",),
    required_columns=("id",),
)
DATASET = Dataset(name="my_data", build_contract=lambda config: CONTRACT)
```

```python
config = load_config("config.json")
manifest = run_pipeline(config, dataset=DATASET)
```

انواع ستون (`dtype`): `str`، `int`، `float`، `datetime`، `zip5`، `bool`.
هر ستون می‌تواند `nullable`، `allowed`، `min_value`، `max_value`، `fill_value` و کد دلیل مخصوص قرنطینه داشته باشد.
قوانین بین‌ستونی با `row_rules` اضافه می‌شوند (مثلاً `not_before_rule`).


## ۶.۱ ریختن خروجی مرحله‌ی ۳ در دیتابیس مرحله‌ی ۲

لازم نیست در مرحله‌ی ۲ چیزی برای مرحله‌ی ۳ طراحی کنی. «همان Database» یعنی همان دیتابیس، نه همان جدول.
حالت `replace` جدول را خودش از روی contract می‌سازد (نوع ستون‌ها از `dtype` هر ستون می‌آید). کانفیگ مرحله‌ی ۳:

```json
{
  "quarantine_threshold": 0.05,
  "curated_dir": "data/curated",
  "source_type": "csv",
  "input_path": "data/raw/file.csv",
  "destinations": ["database"],
  "database_schema": "stage3",
  "database_load_mode": "replace"
}
```

```bash
export DATABASE_URL="همان آدرس دیتابیس مرحله ۲"
python run.py
```

نام جدول‌ها اگر ننویسی از اسم contract ساخته می‌شود: `<name>` و `<name>_quarantine`.
با این کار جدول‌های مرحله‌ی ۲ و ۳ با هم قاطی نمی‌شوند.

حواست باشد: در حالت `replace` هر اجرا جدول را از نو می‌سازد، پس ایندکسی که خودت روی آن زده باشی می‌پرد.
اگر ایندکس و کلید می‌خواهی، جدول را یک‌بار خودت بساز و `"database_load_mode": "existing"` بگذار.
هیچ‌وقت `replace` را روی اسم جدولی که در مرحله‌ی ۲ ساخته‌ای نزن.

بعد از اجرا، نوتبوک مرحله‌ی ۳ با SQLAlchemy از همین جدول‌ها می‌خواند.

## ۶.۲ `Dataset` چیست و کانفیگ چه قالبی دارد

`Dataset` فقط یک ظرف ساده است که مشخصات یک دیتاست را به `run_pipeline` می‌دهد: چطور contract ساخته شود و
اختیاری‌ها (ستون مشتق، جدول مرجع، آماده‌سازی). import کردنش چیزی اجرا نمی‌کند.

کانفیگ یک فایل JSON است که کلیدهایش دقیقاً نام فیلدهای کلاس `Config` در `config.py` پکیج است.
`load_config` همین کلیدها را می‌خواند. کلید ناشناس یا نبودن یکی از دو کلید اجباری (`quarantine_threshold` و `curated_dir`) خطای `ConfigError` می‌دهد.
اسم و جای فایل با خودت است. اگر تنظیم دیگری برای پروژه‌ی خودت داری، آن را در یک فایل جدا بگذار، نه داخل این JSON.
می‌توانی به‌جای JSON هم مستقیم `Config(...)` را در پایتون بسازی.

| کلید | معنی |
|---|---|
| `quarantine_threshold`، `curated_dir` | اجباری |
| `source_type` | `csv` یا `jsonl` یا `api` |
| `input_path` | مسیر فایل ورودی |
| `destinations` | لیستی از `csv` و `database` |
| `database_schema` | نام schema |
| `database_cases_table`، `database_quarantine_table` | اسم جدول‌ها (اختیاری) |
| `database_load_mode` | `replace` یا `existing` |
| `database_url_env` | نام متغیر محیطی آدرس دیتابیس (پیش‌فرض `DATABASE_URL`) |

## ۷. اگر جدول مرجع یا ستون مشتق نداری

لازم نیست چیزی بنویسی. `Dataset` بدون `build_enrichers` و `derive` بدون جدول مرجع و بدون ستون مشتق اجرا می‌شود.

## ۸. اگر جدول مرجع داری

در دیتاست خودت یک `ReferenceJoin` بساز و تابع ساخت آن را بده:

```python
from nyc311_factory.enrichers import ReferenceJoin, load_reference_table

def build_enrichers(config):
    table = load_reference_table(
        "data/reference/regions.csv", key_column="region_code",
        columns={"population": "population"}, key_cleaner=str.strip,
        numeric=("population",))
    return [ReferenceJoin("regions", table, join_column="region_code")]

DATASET = Dataset(name="my_data", build_contract=..., build_enrichers=build_enrichers)
```

ستون‌های اضافه‌شده باید در `derived_columns` contract هم باشند. تعداد ردیف قبل و بعد اتصال در `manifest["joins"]` ثبت می‌شود.
برای مقایسه‌ی یک ستون با مرجع، `compare=(ستون_داده, ستون_مرجع)` را هم بده؛ نتیجه در `manifest["reference_checks"]` می‌آید.

## ۹. ستون مشتق

ستون را در `derived_columns` contract تعریف کن و یک تابع بنویس که دسته‌ی تمیزشده را بگیرد و ستون‌ها را اضافه کند:

```python
def derive(frame):
    frame["total"] = frame["price"] * frame["count"]
    return frame

DATASET = Dataset(name="my_data", build_contract=..., derive=derive)
```

## ۱۰. استفاده‌ی تکه‌ای (اگر لازم شد)

تابع‌ها مستقل از هم قابل import هستند، مثلاً فقط اعتبارسنجی:

```python
from nyc311_factory.validator import split_valid
valid, rejected = split_valid(records, CONTRACT)
```

ولی راه اصولی `run_pipeline` است، چون قرنطینه، آستانه، manifest و نوشتن اتمیک را یک‌جا و بدون تکرار کد می‌دهد.

## ۱۱. خطاها و کد خروج

| کد | خطا |
|---|---|
| ۲ | تنظیمات (`ConfigError`) |
| ۳ | شبکه (`NetworkError`) |
| ۴ | اعتبارسنجی داده (`DataValidationError`) |
| ۵ | تغییر ساختار منبع (`SchemaDriftError`) |
| ۶ | بالا رفتن نسبت قرنطینه (`QuarantineThresholdError`) |
| ۷ | خطای مقصد، مثل دیتابیس (`DestinationError`) |

## ۱۲. ردیابی نسخه

در `manifest_run.json`، کلید `package_version` نسخه‌ی پکیج و کلید `code_version` کامیت پروژه‌ای است که اجرا را انجام داده.
هر وقت پکیج را تغییر دادی، نسخه‌ی `pyproject.toml` را بالا ببر و یک تگ گیت بزن.
