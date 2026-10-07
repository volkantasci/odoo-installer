# 3. Temel kavramlar

**🇹🇷 Türkçe** · [🇬🇧 English](../en/03-concepts.md)

---

Bu bölüm her komutun arkasındaki zihinsel modeli anlatır. Bir kez okuyun — sonrası
kendiliğinden oturur.

**Bu sayfada**

1. [Instance'lar](#1-instancelar)
2. [Plan-önce çalışma](#2-plan-önce-çalışma)
3. [Sırlar ve portlar](#3-sırlar-ve-portlar)
4. [Whitelist](#4-whitelist)
5. [OCA repoları ve bağımlılık çözücü](#5-oca-repoları-ve-bağımlılık-çözücü)
6. [Adopte edilmiş stack'ler](#6-adopte-edilmiş-stackler)
7. [Ingress modu](#7-ingress-modu)
8. [Container runtime](#8-container-runtime)
9. [Durumun yaşadığı yerler](#9-durumun-yaşadığı-yerler)
10. [Öncelik sırası](#10-öncelik-sırası)

---

## 1. Instance'lar

Bir **instance**, kendi dizininde yaşayan tek bir Odoo stack'idir.

Oluşturulan instance'lar varsayılan olarak `~/odoo-instances/<ad>/` altındadır:

```text
~/odoo-instances/dev/
├── docker-compose.yml       # şablonlardan üretilir
├── .env                     # imaj, pg tag, port, üretilen sırlar (mod 0600)
├── config/
│   └── odoo.conf            # addons_path vb. — `module add` ile yeniden yazılır (mod 0644)
├── addons/
│   └── local/               # kendi modülleriniz → /mnt/extra-addons'a bağlanır
├── repos/
│   └── oca-web/             # OCA klonları → /mnt/oca/web'e bağlanır
├── logs/                    # yakalanan test logları (test-<modül>-<zaman>.log)
├── backups/                 # `oii backup create` ile oluşur
│   └── <zaman>/
│       ├── db.dump
│       ├── filestore.tar
│       └── manifest.json
└── .odoo-installer.json     # instance manifest'i (CLI durumu — sırsız)
```

Stack'i iki servis oluşturur:

| Servis | İmaj | Host'ta yayınlanır mı? |
|--------|------|-------------------------|
| `web` | `odoo:19.0` (değiştirilebilir) | evet — ayrılan HTTP portu (ingress modu hariç) |
| `db` | `postgres:<tag>` (varsayılan `17`) | **asla** — tüm DB erişimi stack üzerinden |

Her veritabanı işlemi (`db …`, test geçici DB'leri, modül durum sorguları) `psql`
ile **`db` container'ının içinde** çalışır. PostgreSQL hiçbir zaman dışarı açılmaz.

---

## 2. Plan-önce çalışma

Değişiklik yapan komutlar tek bir kurala uyar: **planı göster, istenene kadar
hiçbir şey yapma.**

```console
$ oii instance create dev
Instance create plan: dev (http port 8069)
   1. → create directory structure under /home/siz/odoo-instances/dev
   2. → render docker-compose.yml
   3. → render .env (contains secrets, mode 0600)
   4. → render config/odoo.conf (readable by the container, mode 0644)
   5. → register instance 'dev' in the registry
   6. → write .odoo-installer.json
   7. → clear containers/volumes from any earlier 'dev' stack (compose down -v; …)
   8. → start the stack (docker compose up -d, project 'dev')
   9. → wait for web container dev-web-1 to become healthy
dry run — re-run with --apply to execute
```

Basılan plan **çalıştırılan kod yolunun ta kendisidir** — ondan sapamaz.

### İki anahtar

| Anahtar | Anlamı |
|---------|--------|
| `--apply` | planı çalıştır |
| `--yes` | buna ek olarak **yıkıcı** ya da adopte-stack işlemini onayla |

Pratik kurallar:

- Salt-okunur komutlar (`list`, `show`, `search`, `health`, `logs`, `secret`,
  `doctor`, `backup list/verify`) doğrudan çalışır — anahtar gerekmez.
- Ekleme yapan komutlar (`db create`, `backup create`) da doğrudan çalışır; mevcut
  veriyi yok edemezler.
- Diğer her şey `--apply` gelene kadar dry-run'dır.
- Yıkıcı komutlar (`db drop/reset`, `instance remove`, `backup restore`)
  `--apply --yes` ister.

### Canlı ilerleme ve idempotentlik

Uygulanan bir plan sırasında her adım olduğu anda duyurulur:

```console
$ oii instance create dev --apply
[1/9] create directory structure under /home/siz/odoo-instances/dev
  ✔ directories ready
[2/9] render docker-compose.yml
  ✔ written (623 bytes)
...
[9/9] wait for web container dev-web-1 to become healthy
  ✔ healthy
✔ instance 'dev' ready at http://localhost:8069
```

Tekrar çalıştırmak güvenlidir:

- değişmeyen dosyalar `already satisfied` olarak bildirilir;
- port mevcut manifest tarafından sabitlenir;
- sırlar `.env`'den yeniden kullanılır;
- çalışan bir stack'e dokunulmaz.

---

## 3. Sırlar ve portlar

### Üretilen sırlar

İlk oluşturmada üç kimlik bilgisi üretilir ve **kalıcılaştırılır** (yeniden
çalıştırmalar onları asla döndürmez):

| `.env` anahtarı | Amacı |
|-----------------|-------|
| `POSTGRES_PASSWORD` | PostgreSQL `odoo` rolünün parolası |
| `ADMIN_PASSWD` | Odoo **master parolası** (`config/odoo.conf` içindeki `admin_passwd`) |
| `ODOO_ADMIN_LOGIN` / `ODOO_ADMIN_PASSWORD` | `oii apply`'ın bir veritabanının ilk kurulumunda uyguladığı uygulama admin bilgileri |

İstediğiniz zaman geri okuyun:

```bash
oii instance secret dev                                  # master parolası
oii instance secret dev --key POSTGRES_PASSWORD
oii instance secret dev --key ODOO_ADMIN_PASSWORD
```

`secret` asla tahmin etmez: olmayan anahtar, mevcut anahtarları listeleyen kesin bir
hatadır.

### Portlar

- Oluşturmada `port_range_start`–`port_range_end` (varsayılan **8069–8099**)
  aralığındaki ilk boş port ayrılır.
- **Durmuş bir stack socket tutmaz** — kaydı registry tutar ve otomatik dağıtım,
  kayıtlı herhangi bir instance'ın rezerve ettiği portları atlar.
- Portu `--http-port` ile sabitleyin; kablo üzerinde boş ve başka bir instance
  tarafından rezerve edilmemiş olmalıdır.
- Bir instance'ta `create` tekrar çalıştırılırsa, stack çalışıyor olsa bile sabit
  portu korunur.
- Ingress modundaki instance'lar host portu **yayınlamaz** (içeride `http_port = 0`).

---

## 4. Whitelist

Merkezi güvenlik sözleşmesi: **bir modül, kendini kanıtladıktan sonra kurulabilir.**

### Bir modül nasıl güvenilir hale gelir?

```text
oii module test <ad>
        │
        ├─ yepyeni bir geçici veritabanı açar    →  oitest_<ad>
        ├─ modülü web container'ı içinde kurar
        ├─ testlerini çalıştırır                 →  --test-enable --test-tags=/<ad>
        ├─ logu ayrıştırır, PASS/FAIL basar
        └─ PASS ise ~/.config/odoo-installer/tested.toml dosyasına kayıt düşer
```

```text
oii module install <ad> --db <db>
        │
        ├─ OCA modülü whitelist'te yok mu?  →  reddedilir
        │      (--allow-untested verilmedikçe)
        └─ Odoo çekirdek modülleri          →  her zaman serbest
```

Whitelist dosyası (`tested.toml`) her modül için şunları saklar: ad, repo, dal,
commit, test zamanı, veritabanı, log yolu ve bağımlılıklar.

### `module approve` — zaten kanıtlanmış modüllere güvenmek

Canlı bir stack üzerinde sağlıklı olduğu belli olan modüller için:

```bash
oii module approve my_module --db odoo
```

Verilen veritabanında `installed` durumunda olmayan hiçbir şeyi onaylamaz; ardından
whitelist kaydını düşer — test logu gerekmez.

### Taşınabilir onaylar

Kısa süre sonra aynı onayları her makinede istersiniz. CLI'yi, kökünde `tested.toml`
bulunan küçük bir git reposuna yönlendirin:

```bash
oii config set tested_repo_url https://github.com/<org>/odoo-installer-tested.git
oii test pull --apply
```

`test pull`, repodaki `tested.toml` dosyasını yerel whitelist ile birleştirir —
**modül adına göre birleşim; yeni `tested_at` kazanır**. Yeni onaylar için CLI'nin
güncellenmesine hiç gerek yoktur.

### Geçici veritabanları

Test koşuları `oitest_<modül>` adlı geçici veritabanlarını kullanır:

- koşudan sonra düşürülür (`--keep-db` verilmedikçe);
- gerçek veritabanlarınıza asla dokunmaz;
- yaşadıkları sürece `db list` çıktısında görünür.

---

## 5. OCA repoları ve bağımlılık çözücü

### Modül adı değil, repo

`module add` bir **repo** adı bekler:

```bash
oii module add web                    # OCA/web
oii module add OCA/server-tools       # açık sahip
```

Yanlışlıkla modül adı verirseniz hata, o modülü sağlayan repoyu söyler.

Her klondan önce `19.0` dalı GitHub API'siyle doğrulanır. Dal yoksa hiçbir şey
klonlanmaz ve hata, denemeniz gereken tam komutu gösterir.

### Sparse clone'lar

```bash
oii module add web --sparse --modules web_responsive
```

`--sparse`, blob-filtreli kısmi bir klon yapar:
`git clone --filter=blob:none --sparse --depth 1`.

Yalnızca istenen modüllerin dosyaları iner. Sonradan başka bir modül eklemek
sparse kümesini **genişletir**, değiştirmez.

### Bağımlılık raporu

`--modules` verdiğinizde plan, her modülün bağımlılıklarını GitHub'daki
`__manifest__.py` dosyalarından okuyup *göstererek* doğrular:

```console
3. → verify dependencies of web_responsive
     (core: base, web, mail, web_tour · already available: —)
```

Her bağımlılık sınıflandırılır:

| Kova | Anlamı | CLI ne yapar |
|------|--------|--------------|
| **core** | Odoo'nun kendisi sağlar | çalışan web container'a karşı doğrulanır |
| **same-repo** | aynı GitHub reposunda | sparse clone'a otomatik katılır |
| **other-repo** | başka bir OCA reposunda | sağlayıcı repo otomatik bağlanır (aşağıya bakın) |
| **already available** | yerel eklentilerde veya başka mount'ta | yapılacak bir şey yok |
| **unknown** | sağlayıcı belirlenemiyor | dürüstçe raporlanır; container kapalıyken tolere edilir |

### Otomatik repolar-arası sağlama

`module add`, repolar-arası bağımlılıkları varsayılan olarak çözer:

1. önce whitelist kataloğuna sorulur;
2. açıklanamayanlar OCA organizasyonunda taranır (ham manifestler, geçişli);
3. her sağlayıcı repo `19.0`'da sparse klonlanır, **ana repodan önce** bağlanır ve
   kaydedilir;
4. web servisi **tek kez**, en sonda yeniden oluşturulur.

```console
$ oii module add account-financial-report --modules account_financial_report
Module add plan: OCA/account-financial-report
   ...
Dependency plan: OCA/server-ux (provides date_range)
   ...
Dependency plan: OCA/reporting-engine (provides report_xlsx)
   ...
```

`--no-resolve-deps` sağlamayı kapatır — repo olduğu gibi eklenir ve karşılanmayan
bir bağımlılık sonraki kurulumu yol göstererek durdurur.

Tüm repoyu eklerken (`--modules` verilmeden) modül kümesi klondan önce bilinemez;
sağlayıcılar klon yerleştirildikten hemen sonra bir geç fazda çözülür.

### Mount'lar nasıl canlıya geçer?

Repo eklemek/kaldırmak iki dosyayı düzenler:

- `docker-compose.yml` — volume satırı; `docker compose config` ile doğrulanır ve
  düzenleme dosyayı bozarsa geri alınır (`.oii-bak` yedeği bırakılır);
- `config/odoo.conf` — `addons_path` girdisi.

Ardından `web` servisi `compose up -d` ile **yeniden oluşturulur** — düz `restart`
yeni volumeyi bağlamaz.

---

## 6. Adopte edilmiş stack'ler

`instance adopt`, **mevcut** bir compose stack'ini kaydeder — örneğin zaten çalışan
bir üretim kurulumunu — tek bir dosyayı bile yeniden yazmadan.

Algılama yalnızca **container etiketleriyle** yapılır; compose dosyası hiç parse
edilmez. CLI; `web` servisini (Odoo imajı veya yayınlanmış `8069` portu), `db`
servisini (postgres imajı), proje adını ve host portunu bulur.

Adopte edilen stack'ler bundan sonra **okuma ağırlıklı** yönetilir:

| İşlem | Adopte edilmiş stack'lerde davranış |
|-------|--------------------------------------|
| `start` | `compose start` — yalnızca mevcut container'lar, asla yeniden oluşturulmaz |
| `stop` / `restart` | normal compose işlemleri |
| `show` / `logs` / `health` / `db …` / `module list` | normal çalışır |
| `module add` / `module remove` | dosya düzenlemesi `--yes` ister; ardından stack'i kendiniz yeniden oluşturmanız söylenir |
| `instance remove` | çalışır — izin verilen tek, açıkça onaylanmış yıkıcı mutasyon |

Adopte edilmiş stack'lerin test logları
`~/.local/state/odoo-installer/logs/<ad>/` altına yazılır (CLI adopte edilmiş bir
stack dizinine asla yazmaz).

> ⚠️ Adoption için web servisinin host üzerinde `8069` container portunu
> yayınlaması gerekir — CLI'nin HTTP ile ulaşamadığı bir stack adopte edilemez.

---

## 7. Ingress modu

Reverse proxy arkasındaki filolar için (Caddy, nginx, Traefik…), instance'ları
**host portu yayınlamadan** oluşturun:

```bash
oii instance create acme \
    --ingress-network violetear-ingress \
    --ingress-alias acme
```

Ne değişir:

- `web` servisi `violetear-ingress` **harici** ağına alias'ıyla (`acme`) katılır;
- hiçbir `ports:` girdisi yoktur — proxy, ağ içinden `acme:8069` adresine yönlenir;
- `proxy_mode` otomatik olarak `true` olur;
- `db` servisi ingress ağına asla katılmaz.

Kaynak limitleri ve `odoo.conf` ayarlarıyla birleştirin:

```bash
oii instance create acme \
    --ingress-network violetear-ingress \
    --memory 2g --cpus 1.5 --workers 4
```

Sağlık denetimleri uyum sağlar: port yayınlayan stack'ler HTTP (`/web/health`) ile,
ingress instance'ları container healthcheck'i ile yoklanır.

Aynısı deklaratif olarak da ifade edilebilir — bkz.
[6. Yedekleme ve apply](06-komutlar-yedekleme-ve-apply.md).

---

## 8. Container runtime

| Ayar değeri | Davranış |
|-------------|----------|
| `auto` (varsayılan) | `podman` kurulu **ve** yanıt veriyorsa onu, yoksa `docker`'ı seçer |
| `podman` | podman binary'si PATH'te olmalı |
| `docker` | docker binary'si PATH'te olmalı |

- İki motor da **compose specification** konuşur; her komut ikisinde de çalışır.
- Rootless Podman'da compose sağlayıcısı `podman.socket` (kullanıcı servisi)
  üzerinden konuşur — socket dinlemiyorsa `oii doctor` compose denetimini tam çözüm
  önerisiyle FAIL eder.
- `CONTAINER_HOST` / `DOCKER_HOST` ortam değişkenleri uzak socket'ler için
  olduğu gibi geçirilir.

---

## 9. Durumun yaşadığı yerler

| Yol | İçerik |
|-----|--------|
| `~/.config/odoo-installer/config.toml` | genel yapılandırma |
| `~/.config/odoo-installer/registry.toml` | instance registry'si |
| `~/.config/odoo-installer/tested.toml` | kurulabilir-eklentiler whitelist'i |
| `<stack>/.odoo-installer.json` | instance manifest'i (sırsız) |
| `<stack>/.env` | instance sırları (mod 0600) |
| `<stack>/repos/<repo>/` | OCA klonları — **gerçek kaynak git durumudur** |
| `<stack>/backups/<ts>/` | sağlama toplamlı `manifest.json` ile yedekler |
| `<stack>/logs/` | test logları (oluşturulan instance'lar) |
| `~/.local/state/odoo-installer/logs/<ad>/` | test logları (adopte edilen instance'lar) |
| `~/.cache/odoo-installer/tested-repo/` | merkezi whitelist reposunun önbellek klonu |

Manifest; instance'ın servislerini, repolarını, portlarını ve render ayarlarını
kaydeder; kasten **sırsızdır**. Sırlar yalnızca `.env` ve `config/odoo.conf` içinde
yaşar.

---

## 10. Öncelik sırası

Değerler çakıştığında şu sıra kazanır:

```text
CLI bayrakları  >  instance manifest'i  >  genel config.toml  >  yerleşik sabitler
```

Bunun pratik sonuçları:

- `--http-port`, manifest'in sabitlediği portu yener (ancak manifest'in kendi portu
  meşgulken bile kabul edilir);
- açık oluşturma seçenekleri (`--image`, `--workers`, `--memory`…) instance'ın o an
  kullandığını geçersiz kılar — onları vermemek kayıtlı değerleri asla değiştirmez;
- `config set` değerleri, bayrakların ve manifestlerin belirtmediği her şeyi
  tamamlar.

---

[⬅️ Önceki: Kurulum](02-kurulum.md) · [Dizin](README.md) · [Sonraki: Host ve instance komutları ➡️](04-komutlar-host-ve-instance.md)
