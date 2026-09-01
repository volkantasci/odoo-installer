# odoo-installer — Kullanım Kılavuzu

`odoo-installer` ile **Odoo 19.0 Docker stack'lerini** kurmak, yapılandırmak ve
yönetmek için ayrıntılı, pratik bir rehber — doğru-dallı OCA modül yönetimi ve otomatik
kurulabilirlik testleri dahil.

Mimari, tasarım kararları ve geliştirme planı için bkz.
[DEVELOPMENT.md](DEVELOPMENT.md). Bu kılavuz, komutları v0.1.x'teki gerçek
davranışlarıyla anlatır.

---

## İçindekiler

1. [Araç ne yapar, ne yapmaz](#1-araç-ne-yapar-ne-yapmaz)
2. [Kurulum](#2-kurulum)
3. [Temel kavramlar](#3-temel-kavramlar)
4. [Komut başvurusu](#4-komut-başvurusu)
5. [Yapılandırma dosyaları ve durum](#5-yapılandırma-dosyaları-ve-durum)
6. [Yaygın iş akışları](#6-yaygın-iş-akışları)
7. [Güvenlik kuralları ve çıkış kodları](#7-güvenlik-kuralları-ve-çıkış-kodları)
8. [Sorun giderme](#8-sorun-giderme)

---

## 1. Araç ne yapar, ne yapmaz

`odoo-installer`, Odoo 19.0'ı **yalnızca Docker üzerinden** yönetir. Odoo'yu asla
host'a yerel (native) kurmaz: her instance, CLI tarafından üretilen, başlatılan ve
yönetilen bir `docker compose` stack'idir (bir `web` + bir `db` servisi). Üzerine şunları
ekler:

- **OCA modül yönetimi** — OCA depolarını doğrulanmış `origin/19.0` dalında klonlar,
  stack'e mount eder ve `addons_path`'i sizin için yeniden yazar.
- **Kurulabilirlik testi** — her modülü tek kullanımlık (scratch) bir veritabanına
  kurar, testlerini konteyner içinde çalıştırır, logu ayrıştırır ve PASS sonuçlarını
  kurulabilir-modüller beyaz listesine kaydeder. `module install` test edilmemiş
  modülleri reddeder.
- **Plan-önce güvenliği** — her yıkıcı veya sistemi değiştiren komut, tam olarak ne
  yapacağını yazdırır ve `--apply` vermediğiniz sürece (yıkıcı onaylar için ayrıca
  `--yes`) hiçbir şey yapmadan çıkar. Tekrar çalıştırmalar idempotenttir.

**Kapsam dışı (v1):** yerel (Docker'sız) Odoo, başka Odoo sürümleri, GUI/TUI,
veritabanı yedekleme/geri yükleme, SMTP sihirbazı, reverse-proxy/TLS üretimi.

### Gereksinimler

- Python ≥ 3.11
- Docker engine + `compose` eklentisi
- `git`
- Linux host (referans platform Arch Linux; Debian/Ubuntu paket adaptörleri mevcut
  ancak daha az denenmiş durumda)

Host'unuzu doğrulamak için `odoo-installer doctor` çalıştırın.

---

## 2. Kurulum

```bash
pip install odoo-installer            # PyPI'dan (0.1.1+)
# veya checkout'tan:
pip install .
# veya geliştirme için:
pip install -e ".[dev]"
```

Kabuk tamamlamayı etkinleştirin (bash/zsh/fish):

```bash
odoo-installer --install-completion
```

CLI ayrıca `oii` kısa adıyla ve `python -m odoo_installer` ile kullanılabilir.

---

## 3. Temel kavramlar

### 3.1 Instance'lar

Bir **instance**, kendi dizininde duran tek bir Odoo stack'idir (varsayılan kök:
`~/odoo-instances/`). Her instance şunları içerir:

```text
~/odoo-instances/<ad>/
├── docker-compose.yml       # şablonlardan üretilir
├── .env                     # imaj, pg tag, http portu, üretilen sırlar
├── config/odoo.conf         # addons_path, `module add` ile yeniden yazılır
├── addons/local/            # kendi modülleriniz (/mnt/extra-addons olarak mount edilir)
├── repos/<oca-repo>/        # OCA klonları (her biri /mnt/oca/<repo> olarak mount edilir)
├── logs/                    # yakalanan test logları (test-<modül>-<ts>.log)
└── .odoo-installer.json     # instance manifest'i
```

`db` servisi host üzerinde **yayınlanmaz** — tüm veritabanı erişimi stack üzerinden
(`db` konteynerindeki psql) yapılır.

### 3.2 Plan-önce (varsayılan dry-run)

Bir şeyi değiştiren komutlar (`install`, `instance create/remove`, `module add/remove`,
`db drop/reset`) tam komut ve dosya yazma listesini numaralı bir plan olarak yazdırır ve
`--apply` verene kadar **hiçbir şey uygulamadan** 0 koduyla çıkar. Yıkıcı işlemler
ayrıca `--yes` ister. Yazdırılan plan, uygulanan kod yoluyla birebir aynıdır — dry-run
tasarım gereği kusursuzdur. Plan uygulandığında her adım canlı olarak
`[i/n] açıklama` biçiminde ve ardından sonucuyla duyurulur; hangi aşamada olduğunuz her
zaman görünür:

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

`instance adopt <dizin>` komutu, **mevcut** bir compose stack'ini (ör. aracı kullanmadan
önce elle kurduğunuz bir stack) dosyalarını yeniden yazmadan kaydeder. Sahiplenilen
stack'ler **okuma-ağırlıklı** yönetilir:

- `start/stop/restart`, `exec`, `psql` ve log erişimi normal çalışır.
- `start`, `docker compose start` kullanır — stack asla yeniden oluşturulmaz.
- Dosya değişiklikleri (ör. `module add` ile mount eklemek) açık `--yes` gerektirir ve
  CLI sahiplenilen stack'i **asla yeniden yaratmaz** — konteynerleri kendiniz
  yeniden yaratmanızı (`docker compose up -d web`) söyler.
- Tek mutasyon istisnası `instance remove --apply --yes`'tır: stack'i söker ve
  dizinini siler (bkz. §4.4).

### 3.4 Test edilmiş modüller beyaz listesi

`module test` ve `test suite`, her PASS'i
`~/.config/odoo-installer/tested.toml` dosyasına kaydeder (modül → repo, dal, commit,
veritabanı, log yolu). `module install`/`module upgrade`, beyaz listede kaydı olmayan
her modülü `--allow-untested` vermediğiniz sürece **reddeder**. Bu, aracın sözleşmesidir:
yalnızca test edilen modüller kurulabilir.

### 3.5 Scratch veritabanları

`module test` ve `test suite` gerçek veritabanlarınıza asla dokunmaz. Her modül,
`oitest_<modül>` adlı tek kullanımlık bir veritabanında test edilir; `--keep-db`
vermediğiniz sürece test sonunda silinir. Veritabanı adları **her zaman açık** CLI
argümanıdır — varsayılan veritabanı diye bir şey yoktur.

---

## 4. Komut başvurusu

Genel seçenekler: `--version` / `-V` (sürümü göster ve çık), her yerde `--help`.
Ayrıca yalnızca sürüm numarasını basan bir `version` komutu vardır.

### 4.1 `doctor` — host teşhisi

```bash
odoo-installer doctor [--json]
```

Kontroller: docker engine, compose eklentisi, docker grubu üyeliği, git, instance
kökündeki disk alanı, yapılandırılan aralıktaki (8069–8099) port durumu ve github.com
erişilebilirliği. Tablo (veya JSON) basar; kritik bir kontrol başarısızsa **4 koduyla**
çıkar.

```console
$ odoo-installer doctor --json | head
```

### 4.2 `install` — host ön gereksinimleri

```bash
odoo-installer install [--apply]
```

**Yalnızca host ön gereksinimlerini** kurar — docker engine, compose eklentisi ve git —
pacman (Arch) veya apt (Debian/Ubuntu) üzerinden. Odoo'nun kendisini asla kurmaz; onun
için stack'ler var. `--apply` olmadan planı yazdırır; `--apply` ile uygular. Gereksinimler
karşılanmışsa "yapılacak bir şey yok" der (tekrar çalıştırmalar no-op'tur).

### 4.3 `config` — genel yapılandırma

```bash
odoo-installer config show [--json]        # çözümlenmiş yapılandırma
odoo-installer config set <anahtar> <değer>  # tek anahtar ata (doğrulanır)
odoo-installer config edit                 # $VISUAL/$EDITOR ile yerinde düzenle, doğrulanır
odoo-installer config path                 # yapılandırma dosyası yolunu yazdır
```

Anahtarlar ve varsayılanlar (tam tablo §5.1'de):

| Anahtar | Varsayılan | Anlamı |
|---------|-----------|--------|
| `instances_root` | `~/odoo-instances` | yeni stack'lerin oluşturulacağı yer |
| `repo_root` | `~/odoo-repos` | sahiplenilen stack'ler için OCA klonlarının yeri |
| `default_pg_tag` | `17` | postgres imaj etiketi |
| `port_range_start` / `port_range_end` | `8069` / `8099` | otomatik port atama aralığı (≥ 1024 olmalı) |
| `github_token_env` | `GITHUB_TOKEN` | GitHub token'ını tutan ortam değişkeni adı |

Bilinmeyen anahtarlar reddedilir — `config.toml`'daki yazım hataları sessizce
yutulmaz, yüksek sesle hata verir. `set` değerleri pydantic ile dönüştürüp doğrular;
`edit` kaydetmeden önce sonucu doğrular, geçersizse hiçbir şey yazmaz.

```bash
odoo-installer config set port_range_end 8095
odoo-installer config set github_token_env GH_TOKEN
```

### 4.4 `instance` — stack yaşam döngüsü

#### Oluşturma

```bash
odoo-installer instance create <ad> [--dir YOL] [--http-port N] [--image ETIKET]
                            [--pg-tag N] [--apply]
```

Eksiksiz stack'i üretir (`docker-compose.yml`, `.env`, `config/odoo.conf`),
`docker compose up -d` ile başlatır, `/web/health`'i bekler ve instance'ı kaydeder.

- **Port:** `--http-port` verilmezse yapılandırılan aralıktaki (8069–8099) ilk boş port.
  Atanan port manifest'e sabitlenir, tekrar çalıştırmalar aynı portu korur.
- **Sırlar:** postgres ve admin şifreleri ilk çalıştırmada üretilir ve `.env`'de
  saklanır — tekrar çalıştırmalar onları asla değiştirmez.
- **Idempotency:** var olan sağlıklı bir instance için `create` yeniden çalıştırılırsa
  no-op'tur.
- Varsayılan imaj `odoo:19.0`; `--image` ile değiştirilebilir (manifest'e kaydedilir).

```console
$ odoo-installer instance create dev            # dry-run: planı yazdırır
$ odoo-installer instance create dev --apply    # uygular
✔ instance 'dev' hazır: http://localhost:8069
```

#### Listele / göster / secret / yaşam döngüsü

```bash
odoo-installer instance list
odoo-installer instance show <ad>        # manifest ayrıntıları + docker compose ps
odoo-installer instance secret <ad> [--key ANAHTAR]   # .env'den bir sır yazdırır
odoo-installer instance start <ad>       # oluşturulan: up -d · sahiplenilen: compose start
odoo-installer instance stop <ad>        # docker compose stop
odoo-installer instance restart <ad>     # docker compose restart
```

`secret`, instance'ın `.env`'inden tek bir değeri kendi satırında (düz metin, pipe'a
uygun) yazdırır. Varsayılan anahtar `ADMIN_PASSWD` — Odoo master password'ü;
`POSTGRES_PASSWORD` gibi diğer anahtarlar `--key` ile okunur. Olmayan anahtar, uygun
anahtarları listeleyen açık bir hatadır.

#### Silme

```bash
odoo-installer instance remove <ad> [--remove-data] [--yes] [--apply]
```

Varsayılan dry-run; yalnızca `--apply --yes` ile uygulanır. Varsayılan olarak stack'in
data volume'leri (ve onlarla birlikte veritabanlarınız) **korunur**; `--remove-data`,
compose dosyasında tanımlı named volume'leri yok eder (`docker compose down -v`);
bind-mount edilmiş veriler stack diziniyle birlikte gider. **Sahiplenilen stack'ler için
de çalışır** — kaldırma, onlar üzerinde izin verilen tek açıkça onaylanmış yıkıcı
işlemdir. Instance'ı yeniden oluşturduğunuzda, açıkça istemediyseniz verileriniz
yerinde kalır.

#### Mevcut bir stack'i sahiplenme

```bash
odoo-installer instance adopt <dizin> [--name AD] [--db-user odoo] [--apply]
```

Stack'i yalnızca konteyner etiketlerinden tespit eder (compose projesi, web/db
servisleri, imajlar, yayınlanan port), yalnızca odoo-installer manifest'ini ve registry
kaydını yazar; stack dosyalarını asla yeniden yazmaz. Okuma-ağırlıklı kurallar için bkz.
§3.3.

```console
$ odoo-installer instance adopt ~/Projects/my-odoo --apply
tespit edildi: proje my-odoo, web servisi web (odoo:19.0) port 8069, ...
✔ instance 'my-odoo' sahiplenildi (okuma-ağırlıklı)
```

### 4.5 `db` — veritabanları

Tüm veritabanı işlemleri instance'ın `db` konteynerindeki psql üzerinden yürütülür.
Veritabanı adı **her zaman** açık pozisyonel argümandır.

```bash
odoo-installer db list [--instance AD]                    # adlar + boyutlar
odoo-installer db create <db> [--instance AD]             # idempotent
odoo-installer db drop <db> [--instance AD] [--yes] [--apply]
odoo-installer db reset <db> [--instance AD] [--yes] [--apply]
```

- `create`, veritabanı zaten varsa `already exists` der.
- `drop`/`reset` plan-öncedir; yalnızca `--apply --yes` ile uygulanır. Dry-run'da kırmızı
  uyarı yazdırır.
- `reset` = sil + yeniden oluştur (boş veritabanı).
- Korunan `postgres`, `template0` ve `template1` veritabanları reddedilir.
- `--instance`, tek kayıtlı instance varsa varsayılandır; birden fazla kayıtlı
  instance varsa verilmesi zorunludur.

```console
$ odoo-installer db create odoo --instance dev
✔ veritabanı 'odoo': oluşturuldu
```

### 4.6 `module` — OCA depoları ve modüller

#### Depo ekleme

```bash
odoo-installer module add <oca-repo> [--modules m1,m2] [--sparse] [--repo YOL]
                         [--fork KULLANICI] [--instance AD] [--yes] [--apply]
```

- `<oca-repo>`, `server-tools` veya `OCA/server-tools` biçiminde olabilir.
- **19.0 dalı klonlamadan önce GitHub API üzerinden doğrulanır** — `19.0` dalı olmayan
  bir depo açık bir hatadır. Araç asla tahmin etmez, `master`'a düşmez.
- Klonlar sığ ve tek dallıdır (`--depth 1 --branch 19.0`).
- `--modules m1,m2`: yalnızca bu modülleri kaydet (depo yine de tam mount edilir —
  `--sparse` kullanılmadıkça).
- `--sparse`: git sparse-checkout yalnızca istenen modüllerle sınırlı — büyük depoları
  (ör. OCA/web) küçük tutar.
- `--repo YOL`: klonlamak yerine **mevcut yerel checkout'u** mount et. CLI, sahibi
  olmadığı bir checkout'ta asla dal değiştirmez veya dosya değiştirmez.
- `--fork KULLANICI`: fork'unuzdan klonlar (`origin` = fork'unuz, `upstream` = OCA).
- Sonrasında CLI, compose volume'ünü + `addons_path` girdisini ekler (otomatik
  yedekler ve `docker compose config` doğrulamasıyla) ve oluşturduğu stack'lerde
  `web`'i **yeniden yaratır** (`docker compose up -d` — sıradan bir restart yeni
  volume mount'unu uygulamaz). Sahiplenilen stack'lerde `--yes` ister ve yeniden
  yaratmayı size bırakır.

```console
$ odoo-installer module add web --sparse --modules web_responsive --apply
repo web, dal 19.0 -> ~/odoo-instances/dev/repos/web:/mnt/oca/web
✔ web eklendi
```

#### Listele / ara

```bash
odoo-installer module list [--instance AD] [--db DB] [--json]
odoo-installer module search <sorgu> [--limit N]
```

`list`, dosya sistemi keşfini `ir_module_module` durumuyla birleştirir: her modül için
kaynak depo, kayıtlı commit ve — `--db` verildiyse — o veritabanındaki kurulum durumu,
artı beyaz listeden Tested sütununu gösterir. `search`, OCA GitHub organizasyonunda
arama yapar.

#### Kur / yükselt

```bash
odoo-installer module install <ad...> --db DB [--instance AD] [--allow-untested]
odoo-installer module upgrade <ad...> --db DB [--instance AD] [--allow-untested]
```

- `web` konteynerinin içinde çalışır:
  `odoo -d <db> -i/-u <ad> --stop-after-init --http-port=8071` (alternatif port, 8069'daki
  sunucu sürecini asla rahatsız etmez).
- `--db` **zorunludur** — varsayılan veritabanı yoktur. Denemeler için scratch adlarını
  (`oitest_*`) kullanın.
- tested.toml kaydı olmayan modülleri `--allow-untested` vermediğiniz sürece reddeder.
- Sonrasında `ir_module_module` durumlarını doğrular; `installed` durumunda olmayan
  modül varsa 1 koduyla çıkar.

```console
$ odoo-installer module install web_responsive --db oitest_deneme
✔ kuruldu: web_responsive
```

#### Kaldırma

```bash
odoo-installer module remove <repo> [--db DB] [--purge-repo] [--instance AD]
                           [--yes] [--apply]
```

Depoyu unmount eder ve `addons_path`'i (yedeklerle) yeniden yazar. `--db` verildiyse
önce o veritabanında deponun modülleri `uninstalled` durumuna sıfırlanır. `--purge-repo`
klon dizinini de siler. Sahiplenilen stack'ler `--apply` ile birlikte `--yes` ister.

#### Tek modül testi

```bash
odoo-installer module test <ad> [--instance AD] [--keep-db]
```

Beyaz liste akışının kalbi:

1. varsa eski `oitest_<ad>` scratch veritabanını temizler,
2. modülü oraya kurar,
3. web konteynerinde `odoo --test-enable --test-tags=/<ad>` çalıştırır,
4. tam logu `logs/test-<ad>-<ts>.log` dosyasına yakalar,
5. logu hata türlerine ayrıştırır (test hatası, import hatası, "not installable",
   eksik manifest, addons_path uyarısı, yalın çıkış kodu),
6. PASS/FAIL basar, başarısızlıkta 3 koduyla çıkar,
7. PASS'te modülü `tested.toml`'a kaydeder (repo, dal, commit, log yolu).

```console
$ odoo-installer module test web_responsive
PASS web_responsive (3.2s) — log: .../logs/test-web_responsive-20260901.log
✔ web_responsive test edildi/kurulabilir olarak kaydedildi (beyaz liste: .../tested.toml)
```

#### Zaten kanıtlanmış modülleri onaylama

```bash
odoo-installer module approve <ad...> --db DB [--instance AD]
```

Modülleri **testleri yeniden çalıştırmadan** beyaz listeye kaydeder — kanıt, modülün
açık bir veritabanındaki `installed` durumudur (yazmadan önce doğrulanır; başka durumda
olanlar reddedilir). Modülün bir stack'te üretimde zaten çalıştığı ve her makinenin onu
kurulabilir saymasını istediğiniz durumlarda kullanın.

### 4.7 `test suite` — toplu test

```bash
odoo-installer test suite [--instance AD] [--only REPO] [--modules m1,m2]
                          [--output rapor.md] [--output rapor.json] [--keep-db]
```

Instance'ın addons_path'indeki **tüm modülleri** sırayla test eder (Odoo kısıtı: aynı
anda tek scratch veritabanı), her modül için taze `oitest_<modül>` scratch DB'si
kullanır. PASS'ler beyaz listeye işlenir. `--only` tek kaynak depoyla sınırlar (`web`
veya `OCA/web`); `--modules` açık liste sabitler. `--output` tekrarlanabilir; Markdown
ve/veya JSON raporu yazar. Herhangi bir modül başarısız olursa **3** koduyla çıkar.

#### Merkezi whitelist reposu (`test pull`)

`tested_repo_url`'ı kökünde `tested.toml` tutan küçük bir git reposuna yönlendirin, sonra:

```bash
odoo-installer config set tested_repo_url https://github.com/<org>/odoo-installer-tested.git
odoo-installer test pull --apply
```

Pull, yerel önbellek klonunu tazeler ve repodaki girdileri etkin whitelist'e
**birleştirir**: modül adına göre birleşim, çakışmada daha yeni `tested_at` kazanır.
Herhangi bir makinede yapılan onaylar (test PASS'i veya `module approve`) pull çeken
her makineye yayılır — yeni onaylar için CLI'ı güncellemek gerekmez, yalnızca repo'yu
güncellemek yeterlidir.

```console
$ odoo-installer test suite --only web --output rapor.md --output rapor.json
[1/12] web_responsive (web)
PASS web_responsive (3.1s)
...
12 modül: 11 geçti, 1 başarısız   → çıkış 3
✔ rapor yazıldı: rapor.md
✔ rapor yazıldı: rapor.json
```

---

## 5. Yapılandırma dosyaları ve durum

Tüm dosyalar XDG yapılandırma dizininde (`~/.config/odoo-installer/`) tutulur; tüm
yazımlar atomiktir (geçici dosya + rename).

| Dosya | Amaç |
|-------|------|
| `config.toml` | genel kullanıcı yapılandırması (tablo §4.3'te) |
| `registry.toml` | instance kaydı: `ad → {dir, http_port, created_at, adopted}` |
| `tested.toml` | kurulabilir-modüller beyaz listesi: `modül → {repo, branch, commit, db, log_path}` |
| `<stack>/.odoo-installer.json` | instance manifest'i: şema sürümü, odoo sürümü, imaj, pg tag, eklenen depolar `{repo, url, branch, commit, modules, mount}`, adopted bayrağı |
| `<stack>/repos/<repo>/` | OCA klonları — dal/commit için doğruluk kaynağı git durumudur |

Yapılandırma önceliği: **CLI bayrakları > instance manifest'i > genel config.toml >
sabitler.**

GitHub erişimi: CLI, token'ı `github_token_env` anahtarının adlandırdığı ortam
değişkeninden (varsayılan `GITHUB_TOKEN`) okur; token yoksa çevrimdışı keşfe zarifçe
düşer.

---

## 6. Yaygın iş akışları

### 6.1 Yeni bir makineyi hazırlama

```bash
odoo-installer doctor                # host'u doğrula (4 kodu = önce düzelt)
odoo-installer install               # dry-run: neler kurulacak?
odoo-installer install --apply       # docker engine, compose eklentisi, git
odoo-installer doctor                # artık hepsi yeşil olmalı
```

### 6.2 Sıfırdan dev instance + OCA modülü, adım adım

```bash
odoo-installer instance create dev --apply
odoo-installer db create odoo --instance dev

odoo-installer module search "responsive"
odoo-installer module add web --sparse --modules web_responsive --apply
odoo-installer module test web_responsive      # scratch DB, PASS → beyaz liste
odoo-installer module install web_responsive --db odoo
```

Her adım ayrıştırılabilir ve idempotenttir — bir şey ters giderse düzeltip yalnızca o
adımı yeniden çalıştırırsınız.

### 6.3 Bir OCA deposundaki fork'unuzla çalışma

```bash
odoo-installer module add server-tools --fork myuser --apply
# origin = https://github.com/myuser/server-tools.git, upstream = OCA
```

### 6.4 Mevcut yerel checkout'unuzu kullanma (worktree deseni)

```bash
odoo-installer module add web --repo ~/dev/web-deploy --apply
# checkout'u olduğu gibi mount eder; CLI dalını asla değiştirmez
```

### 6.5 Bir stack için tam kurulabilirlik raporu

```bash
odoo-installer test suite --output rapor.md --output rapor.json
# herhangi bir modül başarısız olursa çıkış 3; PASS'ler beyaz listeye işlenir
```

### 6.6 Üretim stack'ini sahiplenme ve güvenle inceleme

```bash
odoo-installer instance adopt ~/Projects/my-odoo --apply
odoo-installer db list --instance my-odoo         # psql -l ile eşleşmeli
odoo-installer module list --instance my-odoo --db odoo
odoo-installer module test web_responsive         # yalnızca scratch DB, asla odoo DB değil
```

Yalnızca okuma komutları + scratch-DB testleri — sahiplenilen stack'in dosyalarına ve
üretim `odoo` veritabanına açık, korumalı eylemler olmadan asla dokunulmaz.

### 6.7 Modülleri güvenle yükseltme

```bash
odoo-installer module test my_module --keep-db          # önce scratch DB'de doğrula
odoo-installer module upgrade my_module --db odoo       # yalnızca beyaz listeden geçtiyse
```

---

## 7. Güvenlik kuralları ve çıkış kodları

- **Plan-önce:** `install`, `instance create/remove`, `module add/remove`,
  `db drop/reset` numaralı plan yazdırır; uygulama için `--apply` (yıkıcı onaylar için
  ayrıca `--yes`) gerekir.
- **Idempotency:** her adım önce mevcut durumu kontrol eder (paket kurulu mu? depo
  doğru commit'te mi? addons_path girdisi zaten var mı?) ve işi tekrarlamak yerine
  `already satisfied` raporlar.
- **Açık veritabanı adları:** CLI asla kendiliğinden bir veritabanı adı uydurmaz.
- **Sahiplenilen stack'ler:** `--yes` olmadan asla yeniden yazılmaz, CLI tarafından
  asla yeniden yaratılmaz (tek istisna: açık `instance remove --apply --yes`).
- **Scratch DB'ler:** `oitest_*` adları, `--keep-db` verilmedikçe kullanımdan sonra
  silinir.

Çıkış kodları:

| Kod | Anlamı |
|-----|--------|
| 0 | başarı |
| 1 | çalışma zamanı hatası (ör. modül kurulamadı, plan adımı başarısız) |
| 2 | kullanım hatası (Typer varsayılanı) |
| 3 | test başarısızlıkları (`module test`, `test suite`) |
| 4 | `doctor` kritik bir kontrol başarısızlığı buldu |

Script'ler bu kodlara güvenebilir; ör. `odoo-installer doctor || exit 1` benzeri
kapılar veya 3 kodunu "modülü düzelt" olarak yorumlamak.

---

## 8. Sorun giderme

**`doctor` 4 koduyla çıkıyor.**
FAIL satırını okuyun — kontrolün adını ve düzeltme ipucunu verir. Yaygın nedenler:
compose eklentisi eksik, kullanıcı `docker` grubunda değil, port aralığı dolu.

**"module ... not visible to this instance; run 'module add' first".**
Modül instance'ın addons_path'inde değil. Repoyu `module add` ile ekleyin (veya
checkout'unuzu `--repo` ile mount edin).

**"not tested yet: ... — run 'module test <name>' first".**
tested.toml beyaz listesinde modülün kaydı yok. `module test <ad>` (veya `test suite`)
çalıştırın; bilinçli olarak `--allow-untested` ile atlayabilirsiniz.

**"repo ... has no 19.0 branch".**
OCA deposunda 19.0 dalı yok. Ya dalın gelmesini bekleyin ya da kendi hazırladığınız
checkout'u `--repo` ile gösterin.

**GitHub rate limit / boş arama sonuçları.**
Token tanımlayın: `export GITHUB_TOKEN=ghp_...` (veya `github_token_env`
yapılandırmanızdaki ortam değişkeni adı) ve tekrar deneyin. Token olmadan çevrimdışı
keşif yine de çalışır.

**Port dolu.**
`instance create` 8069–8099 aralığındaki ilk boş portu seçer — ama *durdurulmuş* bir
stack portunu rezerve etmez, bu yüzden iki instance aynı porta kaydolabilir. Onları
sırayla başlatın, `--http-port` ile sabitleyin veya `config set port_range_end ...`
ile aralığı genişletin.

**Sahiplenilen stack "recreate it with your own tooling" diyor.**
Sahiplenilen stack'te `module add --yes` sonrası CLI dosyaları günceller ama
konteynerleri asla yeniden yaratmaz — yeni mount'ın uygulanması için web servisini
kendiniz yeniden yaratın (`docker compose up -d web`; sıradan bir restart yeni
volume mount'unu uygulamaz).

**Modül kuruldu ama Odoo onu kurulu değil gösteriyor.**
`module install`, `ir_module_module` durumlarını doğrular ve hatalıları listeleyerek 1
koduyla çıkar — yakalanan çıktının son satırlarına (soluk yazdırılır) ve modülün
bağımlılıklarına bakın.

**Veritabanı yöneticisi master password soruyor — şifre nerede?**
Hiçbir şey bu alanı sizin yerinize doldurmaz: resmi `odoo` imajı master password'ü
**hiçbir ortam değişkeniyle** sağlamaz (entrypoint'i yalnızca DB bağlantı
değişkenlerini ayarlar, imajın varsayılan config'inde `admin_passwd` yorum satırıdır)
ve Odoo formu sunucu tarafında asla ön-doldurmaz. Dolu görünen alan, tarayıcınızın
kaydettiği şifrenin autofill'idir. `instance create` rastgele bir master password
üretir ve `<stack>/.env` (`ADMIN_PASSWD=...`) ile `<stack>/config/odoo.conf`
(`admin_passwd = ...`) dosyalarına yazar. CLI ile okuyun:
`odoo-installer instance secret <ad>` (DB şifresi için `--key POSTGRES_PASSWORD`).
Kendi şifrenizi belirlemek için `config/odoo.conf` içindeki `admin_passwd`'i
(tutarlılık için `.env`'i de) düzenleyip `odoo-installer instance restart <ad>`
çalıştırın.

**İki instance aynı portu (8069) istiyor.**
Otomatik port atama, *o an* boş olan ilk portu seçer — durdurulmuş bir stack portunu
rezerve etmez. İki kayıtlı instance aynı portu paylaşıyorsa onları sırayla başlatın ya
da birini başka portta yeniden oluşturun (ör. `instance create <ad> --http-port 8070`).

**Test logları nerede?**
Oluşturulan instance'lar: `<stack>/logs/test-<modül>-<ts>.log`. Sahiplenilen
instance'lar: `~/.local/state/odoo-installer/logs/<ad>/` (XDG state dizini — CLI
sahiplenilen stack'lere asla yazmaz).
