# 7. Yapılandırma

**🇹🇷 Türkçe** · [🇬🇧 English](../en/07-configuration.md)

---

CLI'nin sakladığı her şey öngörülebilir yerlerde yaşar ve her yazma atomiktir.

**Bu sayfada**

1. [Dosyalar](#1-dosyalar)
2. [Genel yapılandırma anahtarları](#2-genel-yapılandırma-anahtarları)
3. [Yapılandırmayı yönetmek](#3-yapılandırmayı-yönetmek)
4. [Ortam değişkenleri](#4-ortam-değişkenleri)
5. [Instance `.env` dosyası](#5-instance-env-dosyası)
6. [Üretilen `odoo.conf`](#6-üretilen-odooconf)
7. [Merkezi whitelist reposu](#7-merkezi-whitelist-reposu)
8. [Öncelik sırası](#8-öncelik-sırası)

---

## 1. Dosyalar

| Yol | Amacı |
|-----|-------|
| `~/.config/odoo-installer/config.toml` | genel yapılandırma (`oii config`) |
| `~/.config/odoo-installer/registry.toml` | instance registry'si |
| `~/.config/odoo-installer/tested.toml` | kurulabilir-eklentiler whitelist'i |
| `<stack>/.odoo-installer.json` | instance manifest'i (sırsız CLI durumu) |
| `<stack>/.env` | instance sırları (mod `0600`) |
| `<stack>/config/odoo.conf` | üretilen Odoo yapılandırması (mod `0644`) |
| `<stack>/repos/` | oluşturulan instance'ların OCA klonları |
| `<stack>/backups/<ts>/` | sağlama toplamlı `manifest.json` ile yedekler |
| `<stack>/logs/` | oluşturulan instance'ların test logları |
| `~/.local/state/odoo-installer/logs/<ad>/` | adopte edilen instance'ların test logları |
| `~/.cache/odoo-installer/tested-repo/` | merkezi whitelist reposunun önbellek klonu |
| `~/odoo-repos/` | adopte edilmiş stack'lerin OCA klonları (`repo_root`) |

> 💡 Tüm XDG yolları `platformdirs` ile çözülür; standart geçersiz kılmalar
> (`XDG_CONFIG_HOME`, …) dikkate alınır.

---

## 2. Genel yapılandırma anahtarları

Tam liste — `oii config show` çözümlenmiş değerleri basar:

| Anahtar | Varsayılan | Anlamı |
|---------|------------|--------|
| `instances_root` | `~/odoo-instances` | yeni stack dizinlerinin oluşturulduğu yer |
| `repo_root` | `~/odoo-repos` | **adopte edilmiş** stack'ler için OCA klonlarının yeri |
| `default_pg_tag` | `17` | yeni instance'lar için varsayılan PostgreSQL imaj etiketi |
| `port_range_start` | `8069` | port otomatik dağıtım aralığı başlangıcı (≥ 1024) |
| `port_range_end` | `8099` | port otomatik dağıtım aralığı sonu |
| `github_token_env` | `GITHUB_TOKEN` | GitHub token'ını tutan ortam değişkeninin adı |
| `tested_repo_url` | *(boş)* | merkezi whitelist git reposu (`test pull` kullanır) |
| `backup_hook` | *(boş)* | her başarılı yedekten sonra çalışan shell komutu; `OII_BACKUP_DIR` set edilir |
| `container_runtime` | `auto` | `auto`, `podman` veya `docker` |

Doğrulama kuralları:

- bilinmeyen anahtarlar **reddedilir** — yazım hataları sessizce yok sayılmak yerine
  gürültülü biçimde başarısız olur;
- `port_range_start <= port_range_end` ve ikisi de `>= 1024`;
- `container_runtime` üç değerden biri olmalıdır;
- `oii config set` ile verilen değerler yazılmadan önce doğrulanır.

---

## 3. Yapılandırmayı yönetmek

```bash
oii config show            # çözümlenmiş değerler, anahtar = değer
oii config show --json     # makine-okunur
oii config set <anahtar> <değer>
oii config edit            # $VISUAL/$EDITOR; kaydetmeden önce doğrulanır
oii config path            # dosya konumu
```

Notlar:

- `edit` dosyayı önce `$VISUAL`, sonra `$EDITOR`, yoksa `vi` ile açar.
  Düzenlenen metin geçersizse **hiçbir şey kaydedilmez** ve hata gösterilir.
- `set` atomik yazar (geçici dosya + rename) — kesintiye uğrayan bir yazma
  yapılandırmayı asla bozamaz.
- Tek bir dize beklenen yerlerde listeler virgülle ayrılır (örneğin
  `github_token_env` düz bir addır, liste değil).

Sık yapılan değişiklikler:

```bash
oii config set instances_root ~/stacks          # stack'lerin yaşadığı yeri taşı
oii config set container_runtime docker         # Docker'a sabitle
oii config set port_range_start 9000            # daha geniş/başka port aralığı
oii config set port_range_end 9100
oii config set default_pg_tag 16
```

> 💡 `instances_root` değiştirmek mevcut instance'ları **taşımaz** — registry her
> stack'in mutlak dizinini hatırlar.

---

## 4. Ortam değişkenleri

| Değişken | Kullanıldığı yer |
|----------|------------------|
| `GITHUB_TOKEN` (veya `github_token_env`'in adlandırdığı değişken) | GitHub API çağrıları: dal doğrulama, modül taraması, `module search` |
| `VISUAL` / `EDITOR` | `oii config edit` için editör |
| `CONTAINER_HOST` | uzak Podman socket'i — compose'a olduğu gibi geçirilir |
| `DOCKER_HOST` | uzak Docker socket'i — olduğu gibi geçirilir |
| `OII_BACKUP_DIR` | CLI tarafından `backup_hook` için set edilir — taze yedek dizini |
| `NO_COLOR` / `TERM` | Rich çıktısı için standart davranış |

GitHub token'ı hakkında:

- token olmadan da her şey çalışır — dal denetimleri ve arama hız sınırlıdır ve
  geçici olarak başarısız olabilir;
- token ile sınırlar çok daha yüksektir; genel repolar için kapsamsız (public read)
  klasik bir token yeterlidir;
- token yalnızca ortamdan okunur — CLI tarafından asla diske yazılmaz.

---

## 5. Instance `.env` dosyası

Instance başına bir kez üretilir (mod `0600`), her tekrar çalıştırmada yeniden
kullanılır:

| Anahtar | Amacı |
|---------|-------|
| `COMPOSE_PROJECT_NAME` | compose projesi = instance adı |
| `ODOO_IMAGE` | Odoo imaj etiketi |
| `PG_TAG` | PostgreSQL imaj etiketi |
| `HTTP_PORT` | host HTTP portu (ingress modunda `0`) |
| `POSTGRES_PASSWORD` | veritabanı rolü parolası |
| `ADMIN_PASSWD` | Odoo **master parolası** (`admin_passwd`) |
| `ODOO_ADMIN_LOGIN` | uygulama admin girişi |
| `ODOO_ADMIN_PASSWORD` | uygulama admin parolası (`apply` ilk DB kurulumunda uygular) |

Dosyayı açmak yerine değerleri `oii instance secret <ad> --key <ANAHTAR>` ile
okuyun — komut tam olarak tek değeri basar ve yazım hatasında mevcut anahtarları
listeler.

---

## 6. Üretilen `odoo.conf`

`instance create` / `apply`, `config/odoo.conf` dosyasını instance ayarlarından
render eder:

| Ayar | Kaynağı |
|------|---------|
| `admin_passwd` | üretilen sır (master parolası) |
| `db_host`, `db_port`, `db_user`, `db_password` | sabit stack bağlantısı + sır |
| `addons_path` | `/mnt/extra-addons` artı bağlı her repo için bir girdi (`/mnt/oca/<repo>`) — `module add`/`remove` yönetir |
| `data_dir` | `/var/lib/odoo` |
| `list_db` | `[settings].list_db` (varsayılan `True`) |
| `proxy_mode` | ingress modunda örtük `True`, aksi halde `False` |
| `workers` | yalnızca verilirse yazılır (varsayılan: threaded mod) |

> ⚠️ Dosya başlığı *bu instance'ı CLI yönetirken düzenlemeyin* der — CLI
> `addons_path`'i yerinde yeniden yazar ve düzenlemelerinin `.oii-bak` yedeklerini
> tutar. Değerleri araç üzerinden değiştirmek için `--workers`, `--proxy-mode`,
> `[settings]` gibi yolları kullanın.

---

## 7. Merkezi whitelist reposu

Kurulum onaylarını makineler arasında paylaşmak için kökünde `tested.toml` bulunan
küçük bir git reposu barındırın — `module test` ve `module approve` tam bu biçimde
kayıt üretir.

Makine başına bir kez:

```bash
oii config set tested_repo_url https://github.com/<org>/odoo-installer-tested.git
oii test pull --apply
```

Akış:

```bash
# modülü kanıtlayan makinede:
oii module test my_module

# whitelist'i yayınla (herhangi bir git akışı — tested.toml'u commit/push edin):

# diğer tüm makinelerde:
oii test pull --apply
```

Birleştirme kuralı: modül adına göre birleşim; yeni `tested_at` kazanır. Yerel
onaylarla merkezi onaylar bir arada yaşar.

Önbellek klonu `~/.cache/odoo-installer/tested-repo/` altındadır ve her pull'da
sıfırdan klonlanarak tazelenir.

---

## 8. Öncelik sırası

```text
CLI bayrakları  >  instance manifest'i  >  genel config.toml  >  yerleşik sabitler
```

Pratik sonuçlar:

| Değer | Bayrak | Manifest | Config | Sabit |
|-------|--------|----------|--------|-------|
| HTTP portu | `--http-port` | sabitlenmiş port | dağıtım aralığı | `8069` başlangıç |
| Odoo imajı | `--image` | kayıtlı imaj | — | `odoo:19.0` |
| Postgres etiketi | `--pg-tag` | kayıtlı etiket | `default_pg_tag` | `17` |
| Runtime | — | — | `container_runtime` | `auto` |
| Instance dizini | `--dir` | mutlak `dir` | `instances_root` | `~/odoo-instances` |

---

## İlgili sayfalar

- Kavramlar: [3. Temel kavramlar](03-kavramlar.md)
- Yapılandırma komutları: [4. Komutlar — host ve instance](04-komutlar-host-ve-instance.md)
- Whitelist iş akışları: [5. Komutlar — veri, modül ve test](05-komutlar-veri-modul-test.md)

---

[⬅️ Önceki: Yedekleme ve apply](06-komutlar-yedekleme-ve-apply.md) · [Dizin](README.md) · [Sonraki: İş akışları ➡️](08-is-akislari.md)
