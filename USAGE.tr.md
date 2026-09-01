# odoo-installer — Kullanım Kılavuzu

> **0.6.0+ sürümleri içindir** · [English](USAGE.md) olarak da okuyabilirsiniz
>
> Mimari, tasarım kararları ve geliştirme planı [DEVELOPMENT.md](DEVELOPMENT.md)'dedir.

`odoo-installer`, Odoo 19.0 filonuz için tek bir CLI'dır — Docker stack'lerini kurar ve
yönetir, OCA modüllerini doğru daldan ekler, modüller yayına girmeden önce kanıtını
ister ve onayları kullandığınız her makineye yayar. Değiştirdiği her şeyi önce size
gösterir.

---

## İçindekiler

1. [Bir bakışta](#1-bir-bakışta)
2. [Kurulum](#2-kurulum)
3. [Nasıl düşünür](#3-nasıl-düşünür)
4. [Komut başvurusu](#4-komut-başvurusu)
5. [Dosyalar ve yapılandırma](#5-dosyalar-ve-yapılandırma)
6. [Tarifler](#6-tarifler)
7. [Güvenlik ve çıkış kodları](#7-güvenlik-ve-çıkış-kodları)
8. [Sorun giderme](#8-sorun-giderme)

---

## 1. Bir bakışta

| Komut ailesi | Sağladığı şey |
|--------------|---------------|
| `doctor` | Anında host teşhisi — docker, compose, git, disk, portlar, GitHub erişimi |
| `install` | pacman/apt ile host ön gereksinimleri — Odoo'nun kendisi **asla** host'a kurulmaz |
| `config` | Doğrulanmış, atomik genel yapılandırma |
| `instance` | Tam stack yaşam döngüsü: create, mevcut stack'i adopt etme, start/stop, secret, remove |
| `db` | Stack'in kendi postgres konteyneri üzerinden DB işlemleri |
| `module` | OCA depoları ve modülleri: bağımlılık görünümlü add, list, search, install, upgrade, remove, test, approve |
| `test` | Raporlu toplu test süitleri + merkezi whitelist senkronu |

Hem test hem üretim barındıran bir makinede güvenli kullanımı sağlayan üç fikir:

- **Plan-önce** — her mutasyon tam planını yazdırır ve yalnızca `--apply` ile çalışır
  (yıkıcı işlemlerde ayrıca `--yes`). Uygulanan planlar canlı `[i/n]` ilerleme gösterir.
- **Test-edilmiş kurulumlar** — `module install`, gerçek bir testten geçmemiş ya da
  açıkça onaylanmamış modülleri reddeder.
- **Açık veritabanı adları** — CLI hiçbir zaman sizin yerinize veritabanı seçmez.

---

## 2. Kurulum

```bash
pip install odoo-installer            # PyPI'dan
# veya checkout'tan:
pip install .
# veya geliştirme için:
pip install -e ".[dev]"
```

Günlük kullanım için izole kurulum (dev venv ile karıştırmaktan iyidir):

```bash
pipx install odoo-installer           # veya: uv tool install odoo-installer
```

Kabuk tamamlama (bash/zsh/fish): `odoo-installer --install-completion`.

CLI üç isimle çalışar: `odoo-installer`, `oii` ve `python -m odoo_installer`.

> 💡 **Güncelleme:** `pip install -U odoo-installer` (veya `pipx upgrade
> odoo-installer`). Sürüm hemen ardından pip "already satisfied" derse bir çalıştırmalık
> sürümü sabitleyin — `pip install "odoo-installer==X.Y.Z"` — indeks önbelleği PyPI'ın
> birkaç dakika gerisinde kalabilir.

---

## 3. Nasıl düşünür

### 3.1 Instance'lar

Bir **instance**, kendi dizininde duran tek bir Odoo stack'idir (varsayılan kök
`~/odoo-instances/`):

```text
~/odoo-instances/<ad>/
├── docker-compose.yml       # şablonlardan üretilir
├── .env                     # imaj, pg tag, http portu, üretilen sırlar
├── config/odoo.conf         # addons_path, `module add` ile yeniden yazılır
├── addons/local/            # kendi modülleriniz → /mnt/extra-addons
├── repos/<oca-repo>/        # OCA klonları → /mnt/oca/<repo>
├── logs/                    # yakalanan test logları (test-<modül>-<ts>.log)
└── .odoo-installer.json     # instance manifest'i
```

`db` servisi host üzerinde hiç yayınlanmaz — tüm veritabanı erişimi stack üzerinden
(`db` konteynerindeki psql) yapılır.

### 3.2 Plan-önce, canlı ilerlemeyle

Bir şeyi değiştiren komutlar (`install`, `instance create/remove`, `module add/remove`,
`db drop/reset`) tam komut ve dosya yazma listesini numaralı plan olarak yazdırır ve
`--apply` (yıkıcı işlemlerde ayrıca `--yes`) verene kadar **hiçbir şey yapmadan** çıkar.
Yazdırılan plan, uygulanan kod yoluyla birebir aynıdır. Plan çalışırken her adım anında
duyurulur:

```console
$ odoo-installer instance create dev --apply
[1/8] instance dizinini oluştur
  ✔ oluşturuldu
[2/8] docker-compose.yml üret
  ✔ yazıldı
...
[8/8] stack'i başlat (docker compose up -d) ve /web/health'i bekle
  ✔ sağlıklı
✔ instance 'dev' hazır: http://localhost:8069
```

### 3.3 Sahiplenilen (adopted) stack'ler

`instance adopt <dizin>`, **mevcut** bir compose stack'ini (yalnızca konteyner
etiketlerinden tespit edilir) dosyalarını yeniden yazmadan kaydeder. Sahiplenilen
stack'ler **okuma-ağırlıklı** yönetilir:

- `start/stop/restart`, `exec`, `psql` ve log erişimi normal çalışır;
- `start`, `docker compose start` kullanır — stack asla yeniden yaratılmaz;
- dosya değişiklikleri (ör. `module add` ile mount eklemek) açık `--yes` ister ve CLI
  konteynerleri asla yeniden yaratmaz — bunu size bırakır;
- tek mutasyon istisnası `instance remove --apply --yes`'tır: stack'i söker
  (`--remove-data` ile named volume'lerini de siler) ve dizinini kaldırır.

### 3.4 Whitelist — test edilen kurulabilir

`module test` ve `test suite`, her modülü tek kullanımlık bir **scratch
veritabanına** (`oitest_<modül>`, `--keep-db` olmadıkça sonra silinir) kurar,
testlerini konteyner içinde çalıştırır ve her PASS'i whitelist'e
(`~/.config/odoo-installer/tested.toml`) kaydeder. `module install` / `module upgrade`,
whitelist'te olmayan her şeyi `--allow-untested` vermediğiniz sürece reddeder.
Sözleşme budur: **yalnızca kanıtlanmış modüller kurulur.**

Whitelist aynı zamanda **taşınabilirdir** — bkz.
[§4.7](#47-test--toplu-test-ve-merkezi-senkron): küçük bir git reposu onayları her
makineye taşır; `module approve`, çalışan bir stack'te kanıtlanmış modülleri kaydeder.

---

## 4. Komut başvurusu

Genel: `--version` / `-V`, her yerde `--help`; ayrıca yalnızca sürümü basan bir
`version` komutu.

### 4.1 `doctor` — host teşhisi

```bash
odoo-installer doctor [--json]
```

Docker engine, compose eklentisi, docker grubu üyeliği, git, instance kökündeki disk
alanı, yapılandırılan aralıktaki port durumu ve github.com erişilebilirliğini kontrol
eder. Kritik kontrol başarısızsa **4** koduyla çıkar.

### 4.2 `install` — host ön gereksinimleri

```bash
odoo-installer install [--apply]
```

Docker engine, compose eklentisi ve git'i pacman (Arch) veya apt (Debian/Ubuntu) ile
kurar. Odoo'nun kendisini asla kurmaz. Idempotent — karşılanmış host no-op'tur.

### 4.3 `config` — genel yapılandırma

```bash
odoo-installer config show [--json]
odoo-installer config set <anahtar> <değer>
odoo-installer config edit          # $VISUAL/$EDITOR, kaydetmeden önce doğrular
odoo-installer config path
```

| Anahtar | Varsayılan | Anlamı |
|---------|-----------|--------|
| `instances_root` | `~/odoo-instances` | yeni stack'lerin yeri |
| `repo_root` | `~/odoo-repos` | sahiplenilen stack'ler için OCA klonları |
| `default_pg_tag` | `17` | postgres imaj etiketi |
| `port_range_start` / `port_range_end` | `8069` / `8099` | otomatik port aralığı (≥ 1024) |
| `github_token_env` | `GITHUB_TOKEN` | GitHub token'ını tutan ortam değişkeni |
| `tested_repo_url` | *(boş)* | merkezi whitelist reposu (bkz. §4.7) |

Bilinmeyen anahtarlar reddedilir; `set` değerleri doğrular; `edit` sonucu doğrular,
geçersizse hiçbir şey yazmaz.

### 4.4 `instance` — stack yaşam döngüsü

#### Oluşturma

```bash
odoo-installer instance create <ad> [--dir YOL] [--http-port N] [--image ETİKET]
                            [--pg-tag N] [--apply]
```

Stack'i üretir, başlatır, `/web/health`'i bekler, instance'ı kaydeder.

- **Port:** yapılandırılan aralıktaki ilk boş port — *durdurulmuş* bir stack portunu
  rezerve etmez, iki instance aynı portu paylaşabilir; `--http-port` ile sabitleyin.
- **Sırlar:** postgres ve admin şifreleri bir kez üretilip kalıcılaşır. Master
  password `config/odoo.conf`'a (`admin_passwd`) yazılır ve `.env`'de
  (`ADMIN_PASSWD`) saklanır — resmi odoo imajı master password'ü hiçbir ortam
  değişkeniyle sağlamaz ve veritabanı yöneticisi alanı asla ön-doldurmaz.

#### Listele / göster / secret / yaşam döngüsü

```bash
odoo-installer instance list
odoo-installer instance show <ad>
odoo-installer instance secret <ad> [--key ANAHTAR]
odoo-installer instance start|stop|restart <ad>
```

`secret`, instance'ın `.env`'inden tek bir değeri kendi satırında yazdırır
(varsayılan: `ADMIN_PASSWD` — master password; örn. `--key POSTGRES_PASSWORD`).
Olmayan anahtar, uygun anahtarları listeleyen açık bir hatadır.

#### Silme

```bash
odoo-installer instance remove <ad> [--remove-data] [--yes] [--apply]
```

Varsayılan dry-run; yalnızca `--apply --yes` ile çalışır. Volume'ler `--remove-data`
verilmedikçe **korunur** (o durumda compose dosyasında tanımlı named volume'ler yok
edilir). **Sahiplenilen stack'ler için de çalışır** — kaldırma, onlar üzerinde izin
verilen tek açıkça onaylanmış mutasyondur.

#### Mevcut bir stack'i sahiplenme

```bash
odoo-installer instance adopt <dizin> [--name AD] [--db-user odoo] [--apply]
```

### 4.5 `db` — veritabanları

```bash
odoo-installer db list [--instance AD]
odoo-installer db create <db> [--instance AD]           # idempotent
odoo-installer db drop <db> [--instance AD] [--yes] [--apply]
odoo-installer db reset <db> [--instance AD] [--yes] [--apply]
```

Instance'ın `db` konteynerindeki psql ile yürütülür. Veritabanı adları her zaman
açıktır; `postgres`/`template0`/`template1` reddedilir; `drop`/`reset` için
`--apply --yes` gerekir.

### 4.6 `module` — OCA depoları ve modülleri

#### Depo ekleme

```bash
odoo-installer module add <oca-repo> [--modules m1,m2] [--sparse] [--repo YOL]
                         [--fork KULLANICI] [--instance AD] [--yes] [--apply]
```

- Argüman bir **repo**'dur (`web`, `OCA/server-tools`) — modül adı değil. 19.0 dalı
  klonlamadan önce GitHub API ile doğrulanır; yanlışlıkla modül adı verilirse
  sağlayıcı repoyu söyleyen bir ipucu alırsınız.
- `--modules m1,m2` yalnızca bu modülleri kaydeder — ve plan **bağımlılıklarını
  doğrulayıp gösterir** (GitHub raw manifest'lerinden sınıflandırılır):

  ```console
  $ odoo-installer module add web --sparse --modules web_responsive
  ...
  3. → verify dependencies of web_responsive
       (core: base, web, mail, web_tour · already available: —)
  ```

  - **core** — çalışan konteynerin core addons dizini listelenerek doğrulanır;
  - **same-repo** — aynı repodaki kardeş modüller; otomatik olarak sparse klona
    katılırlar, sonraki kurulum "module not found" ile düşemez;
  - **other-repo** — sağlayıcı repo planda yazar; `install --resolve-deps` tarafından
    mount edilir;
  - **already available** — local addons veya başka bir mount'lu repo tarafından
    sağlanıyor.
- `--sparse` **blob-filtreli kısmi klon** yapar
  (`git clone --filter=blob:none --sparse --depth 1`) — yalnızca istenen modüller
  iner.
- `--repo YOL` mevcut checkout'u **olduğu gibi** mount eder — CLI dalını asla
  değiştirmez.
- `--fork KULLANICI` fork'unuzdan klonlar (`origin` = fork, `upstream` = OCA).
- CLI, compose volume'ünü + `addons_path` girdisini ekler (yedekler ve
  `docker compose config` doğrulamasıyla) ve `web`'i **yeniden yaratır** (`up -d` —
  sıradan restart yeni volume mount'unu uygulamaz). Sahiplenilen stack'lerde `--yes`
  gerekir ve yeniden yaratmayı siz yaparsınız.
- Başarı sonrası sıradaki adımları yazar: `module test` → whitelist → `module install`.

#### Listele / ara

```bash
odoo-installer module list [--instance AD] [--db DB] [--json]
odoo-installer module search <sorgu> [--limit N]
```

#### Kur / yükselt

```bash
odoo-installer module install <ad...> --db DB [--instance AD]
                            [--allow-untested] [--resolve-deps]
odoo-installer module upgrade <ad...> --db DB [--instance AD]
                            [--allow-untested] [--resolve-deps]
```

Web konteynerinde
`odoo -d <db> -i/-u <ad> --stop-after-init --http-port=8071` çalıştırır (sunucu
sürecini asla rahatsız etmez). Whitelist'te olmayan modülleri `--allow-untested`
olmadan reddeder; sonrasında `ir_module_module` durumlarını doğrular (bir modül
`installed` değilse 1 koduyla çıkar).

**Bağımlılık çözümleme** — OCA modülleri sıkça başka OCA modüllerine bağımlıdır. CLI
her hedefin `__manifest__.py`'sini okur:

- **Odoo core**'un (web konteynerinin core addons listesiyle doğrulanır) veya
  **mount'lu repoların** sağladığı bağımlılıklar sorunsuz geçer;
- sağlayıcı reposu **mount edilmemiş** bir bağımlılık, sağlayıcı adıyla reddedilir —
  `--resolve-deps` ekleyin; sağlayıcı repolar otomatik mount edilir (whitelist
  kataloğundan) ve bağımlılıklar kurulum listesine eklenir;
- bilinmeyen sağlayıcılar dürüstçe raporlanır, `module search` ipucu verilir.

#### Kaldırma

```bash
odoo-installer module remove <repo> [--db DB] [--purge-repo] [--instance AD]
                             [--yes] [--apply]
```

Unmount eder, `addons_path`'i yeniden yazar; `--db` verildiyse deponun modülleri o
veritabanında `uninstalled` yapılır; `--purge-repo` klonu siler (yalnızca CLI'ın
sahip olduğu klonlar).

#### Tek modül testi

```bash
odoo-installer module test <ad> [--instance AD] [--keep-db]
```

Scratch DB'ye kurar, `--test-enable --test-tags=/<ad>` çalıştırır, logu yakalar,
hata türlerini ayrıştırır, PASS/FAIL basar (başarısızlıkta 3 koduyla çıkar) ve
PASS'leri whitelist'e kaydeder.

#### Zaten kanıtlanmış modülleri onaylama

```bash
odoo-installer module approve <ad...> --db DB [--instance AD]
```

Kalitesi çalışan bir stack'te kanıtlanmış modüller için: `--db`'de `installed`
durumunda olmayan her şeyi reddeder, sonra whitelist'e kaydeder — test logu gerekmez.

### 4.7 `test` — toplu test ve merkezi senkron

```bash
odoo-installer test suite [--instance AD] [--only REPO] [--modules m1,m2]
                          [--output rapor.md] [--output rapor.json] [--keep-db]
odoo-installer test pull [--apply]
```

`suite`, addons_path'teki her modülü sırayla test eder (her birine taze
`oitest_<modül>` scratch DB), PASS'leri whitelist'e işler, tekrarlanabilir
`.md`/`.json` rapor yazdır ve bir şey başarısızsa **3** koduyla çıkar. `--only`
kaynak depoya göre süzer.

`pull`, `tested_repo_url` ile yapılandırılan merkezi repodan whitelist'i senkronlar:
yerel önbellek klonunu tazeler ve repodaki `tested.toml`'u etkin whitelist'e
**birleştirir** — modül adına göre birleşim, daha yeni `tested_at` kazanır. Herhangi
bir yerde yapılan onaylar pull çeken her makineye yayılır; yeni onaylar için CLI'ı
güncellemek gerekmez.

---

## 5. Dosyalar ve yapılandırma

Tüm dosyalar platformdirs konumlarında tutulur; her yazım atomiktir.

| Dosya | Amaç |
|-------|------|
| `~/.config/odoo-installer/config.toml` | genel yapılandırma (§4.3) |
| `~/.config/odoo-installer/registry.toml` | instance kayıt defteri |
| `~/.config/odoo-installer/tested.toml` | kurulabilir-modüller whitelist'i |
| `<stack>/.odoo-installer.json` | instance manifest'i |
| `<stack>/repos/<repo>/` | OCA klonları — dal/commit için doğruluk kaynağı git'tir |
| `<stack>/logs/` · `~/.local/state/odoo-installer/logs/<ad>/` | test logları (oluşturulan / sahiplenilen stack'ler) |

Öncelik: **CLI bayrakları > instance manifest'i > genel config.toml > sabitler.**

GitHub token'ları: `github_token_env`'in adlandırdığı ortam değişkeninden okunur
(varsayılan `GITHUB_TOKEN`); olmadığında keşif zarifçe düşer.

---

## 6. Tarifler

### 6.1 Bir makineyi hazırlama

```bash
odoo-installer doctor && odoo-installer install --apply && odoo-installer doctor
```

### 6.2 Taze dev instance + OCA modülü

```bash
odoo-installer instance create dev --apply
odoo-installer db create odoo --instance dev
odoo-installer module add web --sparse --modules web_responsive --apply
odoo-installer module test web_responsive
odoo-installer module install web_responsive --db odoo
```

### 6.3 Fork'unuzdan çalışma

```bash
odoo-installer module add server-tools --fork myuser --apply
```

### 6.4 Kendi checkout'unuzu mount etme (asla değiştirilmez)

```bash
odoo-installer module add web --repo ~/dev/web-deploy --apply
```

### 6.5 Tam kurulabilirlik raporu

```bash
odoo-installer test suite --output rapor.md --output rapor.json
```

### 6.6 Üretimi sahiplenme, güvenle inceleme

```bash
odoo-installer instance adopt ~/Projects/my-odoo --apply
odoo-installer db list --instance my-odoo
odoo-installer module approve attribute_set pim --db odoo   # kanıtlanmışlar → whitelist
```

### 6.7 Onayları makineler arasında paylaşma

```bash
# 1) kanıtlı stack'te: onayları kaydet
oii module approve attribute_set pim product_attribute_set --db odoo
# 2) whitelist'i merkezi repoya push et (kökünde tested.toml)
# 3) her yerde:
oii config set tested_repo_url https://github.com/<org>/odoo-installer-tested.git
oii test pull --apply
```

### 6.8 Güvenle yükseltme

```bash
oii module test my_module --keep-db          # scratch DB'de kanıtla
oii module upgrade my_module --db odoo       # yalnızca whitelist'tekiler geçer
```

---

## 7. Güvenlik ve çıkış kodları

- Her mutasyonda plan-önce; uygulanırken canlı `[i/n]` ilerleme.
- Idempotent tekrarlar işi yeniden yapmak yerine `already satisfied` raporlar.
- Veritabanı adları her zaman açık.
- Sahiplenilen stack'ler: `--yes` olmadan asla yeniden yazılmaz, CLI tarafından asla
  yeniden yaratılmaz.
- Scratch DB'ler (`oitest_*`) `--keep-db` olmadıkça silinir.

| Kod | Anlamı |
|-----|--------|
| 0 | başarı |
| 1 | çalışma zamanı hatası |
| 2 | kullanım hatası (Typer) |
| 3 | test başarısızlıkları (`module test`, `test suite`) |
| 4 | `doctor` kritik kontrol başarısızlığı |

---

## 8. Sorun giderme

**`doctor` 4 koduyla çıkıyor.** FAIL satırını okuyun — kontrol adı ve düzeltme ipucu
verir. Yaygın nedenler: compose eklentisi eksik, kullanıcı `docker` grubunda değil,
port aralığı dolu.

**"modules not visible to this instance; run 'module add' first".** Modül
addons_path'te değil — reposunu `module add` ile ekleyin (veya `--repo` ile
checkout'unuzu mount edin).

**"not tested yet: ...".** Whitelist'te kayıt yok — `module test <ad>` çalıştırın veya
bilinçli olarak `--allow-untested` verin.

**"branch '19.0' does not exist on OCA/<ad>"** — ipucuyla birlikte. Modül adı verip
repo beklenen bir durumda ipucu, sağlayıcı repoyu ve tam komutu söyler. Değilse
yazımı kontrol edin veya `module search <ad>` çalıştırın.

**"missing OCA dependencies need mounting: ...".** Bağımlılık çözücüsü mount
edilmemiş sağlayıcı repolar buldu. `--resolve-deps` ile tekrar çalıştırın (onaylar
merkezi repodaysa önce `test pull`).

**GitHub rate limit / boş arama sonuçları.** Token tanımlayın (`GITHUB_TOKEN` veya
`github_token_env`'in adlandırdığı değişken).

**Port dolu.** Durdurulmuş bir stack portunu rezerve etmez — iki instance aynı portu
paylaşabilir. Sırayla başlatın, `--http-port` ile sabitleyin veya aralığı genişletin.

**"recreate it with your own tooling".** Sahiplenilen stack'te `module add --yes`
sonrası web servisini kendiniz yeniden yaratın (`docker compose up -d web`) — sıradan
restart yeni volume mount'unu uygulamaz.

**Modül kuruldu ama Odoo kurulu değil diyor.** `module install` `ir_module_module`
durumlarını doğrular ve hatalıları listeleyerek 1 koduyla çıkar — soluk yazılan çıktı
kuyruğuna ve modülün bağımlılıklarına bakın.

**Veritabanı yöneticisi master password soruyor.** O alanı hiçbir şey doldurmaz:
resmi `odoo` imajı master password'ü hiçbir env ile sağlamaz, varsayılan config'de
`admin_passwd` yorum satırıdır. Kendi şifrenizi
`odoo-installer instance secret <ad>` ile okuyun; değiştirmek için `config/odoo.conf`
içindeki `admin_passwd`'i (ve `.env`'i) düzenleyip `instance restart` verin.

**İki instance aynı portu istiyor.** "Port dolu"ya bakın — durdurulmuş stack portu
rezerve etmez.

**Test logları nerede?** Oluşturulan instance'lar: `<stack>/logs/`. Sahiplenilenler:
`~/.local/state/odoo-installer/logs/<ad>/`.
