# 4. Komutlar — host ve instance

**🇹🇷 Türkçe** · [🇬🇧 English](../en/04-commands-host-and-instance.md)

---

Bu sayfa şunları kapsar:

| Komut | Amacı |
|-------|-------|
| [`version`](#version) | kurulu sürümü yazdırır |
| [`doctor`](#doctor--host-teşhisi) | host teşhisi |
| [`install`](#install--host-ön-gereksinimleri) | host ön gereksinimleri (plan-önce) |
| [`config`](#config--genel-yapılandırma) | genel yapılandırma |
| [`instance`](#instance--stack-yaşam-döngüsü) | stack oluşturma, inceleme ve yönetim |

Her komut ayrıca `--help` kabul eder.

---

## `version`

```bash
oii version
```

Sade sürümü yazdırır — betikler için idealdir:

```console
$ oii version
0.8.1
```

Global bayrak `oii --version` / `oii -V` aynı bilgiyi araç adıyla birlikte basar.

---

## `doctor` — host teşhisi

```bash
oii doctor [--json]
```

Yedi denetim (Podman'da dokuz) çalıştırır ve bir tablo basar:

| Denetim | Notlar |
|---------|--------|
| container runtime | motor sürümü ve mevcut kullanıcı için kullanılabilirliği |
| compose | sağlayıcı sürümü; Podman'da ayrıca rootless socket yoklanır |
| runtime permissions | docker grup üyeliği (Docker) veya rootless kullanılabilirlik (Podman) |
| git | PATH'te bulunma |
| disk space | instances kökünde boş GiB — 2 GiB altı FAIL, 5 GiB altı WARN |
| ports | yapılandırılmış aralığın doluluğu — bazıları doluysa WARN |
| github api | erişilebilirlik — yalnızca WARN (keşif zarifçe geriler) |
| linger (yalnızca Podman) | açılışta kalıcılık — kapalıysa WARN |
| podman boot restart (yalnızca Podman) | `podman-restart.service` — kapalıysa WARN |

Her satır, çalıştırılacak tam komutu söyleyen bir `fix_hint` taşır.

Çıkış kodları:

| Kod | Anlamı |
|-----|--------|
| 0 | FAIL satırı yok |
| 4 | en az bir kritik denetim başarısız |

Örnekler:

```bash
oii doctor                # okunabilir tablo
oii doctor --json         # CI/izleme için makine-okunur çıktı
oii doctor || echo "ilgi gerekiyor"
```

```console
$ oii doctor
odoo-installer doctor
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Check              ┃ Status ┃ Detail                     ┃ Fix hint    ┃
...
7 checks: 7 ok, 0 warn, 0 fail
```

---

## `install` — host ön gereksinimleri

```bash
oii install [--apply]
```

Eksik host parçalarını **pacman** (Arch) veya **apt** (Debian/Ubuntu) ile kurar:

- container runtime (`container_runtime` ayarına göre);
- compose sağlayıcısı;
- git;
- Podman'da ayrıca: `podman.socket`, linger, `podman-restart.service`.

Odoo'nun kendisini **asla kurmaz** — Odoo stack'lerin içinde çalışır.

```bash
oii install               # dry-run: adımları göster
oii install --apply       # çalıştır
```

Hazır bir host için komut etkisizdir:

```console
$ oii install
✔ all host prerequisites already satisfied
```

---

## `config` — genel yapılandırma

```bash
oii config show [--json]
oii config set <anahtar> <değer>
oii config edit
oii config path
```

| Alt komut | Davranış |
|-----------|----------|
| `show` | **çözümlenmiş** yapılandırmayı basar (varsayılanlar dahil) |
| `set` | tek değeri doğrulayıp atomik yazar; bilinmeyen anahtar ve hatalı değer reddedilir |
| `edit` | dosyayı `$VISUAL`/`$EDITOR` (yoksa `vi`) ile açar; sonuç **kaydetmeden önce** doğrulanır |
| `path` | yapılandırma dosyasının yolunu basar |

Örnekler:

```bash
oii config show
oii config show --json
oii config set instances_root ~/stacks
oii config set container_runtime podman
oii config set tested_repo_url https://github.com/org/odoo-installer-tested.git
oii config path
```

```console
$ oii config set default_pg_tag 16
✔ default_pg_tag = 16
```

Tüm anahtarlar ve varsayılanları
[7. Yapılandırma](07-yapilandirma.md) sayfasındadır.

---

## `instance` — stack yaşam döngüsü

```bash
oii instance create | adopt | list | show | health | logs | secret
                 | start | stop | restart | remove
```

İstediğiniz an `oii instance --help` hepsini listeler.

---

### `instance create`

```bash
oii instance create <ad> [seçenekler] [--apply]
```

Eksiksiz bir stack oluşturur: `docker-compose.yml`, `.env` ve `config/odoo.conf`
render edilir, stack başlatılır, `/web/health` beklenir ve instance kaydedilir.

| Seçenek | Anlamı |
|---------|--------|
| `--dir PATH` | stack dizini (varsayılan: `<instances_root>/<ad>`) |
| `--http-port N` | host HTTP portu (varsayılan: aralıktaki ilk boş port) |
| `--image TAG` | Odoo imajı (varsayılan `odoo:19.0`) |
| `--pg-tag N` | PostgreSQL imaj etiketi (varsayılan config'ten, `17`) |
| `--ingress-network AD` | web'i bu harici ağa bağlar, host portu **yayınlamaz** |
| `--ingress-alias SLUG` | ağ alias'ı (varsayılan: instance adı) |
| `--memory 2g` | web servisinde compose `mem_limit` |
| `--cpus 1.5` | web servisinde compose `cpus` |
| `--proxy-mode / --no-proxy-mode` | `odoo.conf` `proxy_mode` (ingress'te varsayılan açık) |
| `--workers N` | `odoo.conf` `workers` (varsayılan: threaded) |
| `--apply` | planı çalıştır |

Instance adları `[a-z0-9][a-z0-9-]{0,31}` kalıbına uymalıdır — küçük harf, rakam
ve tire.

Plan sırasıyla şunları yapar:

1. dizin yapısını oluşturur (`config/`, `addons/local/`, `logs/`);
2. `docker-compose.yml` dosyasını render eder;
3. üretilen sırlarla `.env` dosyasını yazar (mod `0600`);
4. `config/odoo.conf` dosyasını yazar (mod `0644`);
5. instance'ı registry'ye kaydeder;
6. manifest'i yazar;
7. **yalnızca ilk oluşturmada:** aynı adlı eski bir stack'in kalan
   container/volume'larını temizler (`compose down -v`) — PostgreSQL eski bir veri
   dizinini asla yeniden başlatmaz; bayat volumeler yeni stack'i bozardı;
8. `compose up -d`;
9. web container'ı sağlıklı olana kadar bekler.

Tekrar çalıştırmalar idempotenttir: değişmeyen dosyalar `already satisfied` bildirir,
sırlar ve portlar kalıcıdır ve manifest varsa temizlik asla yapılmaz
(bu veriyi yok ederdi).

```console
$ oii instance create dev --apply
...
✔ instance 'dev' ready at http://localhost:8069
```

Ingress modunda son satır, port yerine ağı ve alias'ı bildirir.
**Adopte edilmiş** bir instance'ın bulunduğu dizinde `create` reddedilir.

---

### `instance list` / `show`

```bash
oii instance list [--json]
oii instance show <ad> [--json]
```

`list`, registry'yi basar (ad, HTTP portu, dizin, adopted bayrağı).

`show`, manifest'i ve canlı container durumlarını basar:

```console
$ oii instance show dev
dev — Odoo 19.0 (odoo:19.0), postgres 17
  directory: /home/siz/odoo-instances/dev
  http port: 8069
  adopted:   no
  web: running (odoo:19.0)
  db: running (postgres:17)
```

---

### `instance health` / `logs`

```bash
oii instance health <ad> [--wait N] [--json]
oii instance logs <ad> [--tail N]
```

`health`:

- port yayınlayan stack'ler → HTTP `GET /web/health`;
- ingress stack'leri → container healthcheck'i;
- sağlıksızsa `1` koduyla çıkar; `--wait N` en fazla N saniye yoklar.

`logs`, birleşik compose loglarını basar (varsayılan `--tail 80`).

```bash
oii instance health dev --wait 60
oii instance logs dev --tail 200
```

---

### `instance secret`

```bash
oii instance secret <ad> [--key ANAHTAR]
```

Instance'ın `.env` dosyasından **tek** bir değeri kendi satırında basar
(varsayılan `--key ADMIN_PASSWD` — Odoo master parolası).

```bash
oii instance secret dev
oii instance secret dev --key POSTGRES_PASSWORD
oii instance secret dev --key ODOO_ADMIN_PASSWORD
```

Olmayan anahtar, mevcut anahtarları listeleyen kesin bir hatadır — komut asla tahmin
etmez ve başka bir dosyaya düşmez.

---

### `instance start` / `stop` / `restart`

```bash
oii instance start <ad>
oii instance stop <ad>
oii instance restart <ad>
```

Doğrudan, geri alınabilir yaşam döngüsü işlemleri (plan gerekmez).

| İşlem | Oluşturulan instance'lar | Adopte edilmiş stack'ler |
|-------|--------------------------|--------------------------|
| `start` | `compose up -d` | `compose start` — yalnızca mevcut container'lar, asla yeniden oluşturulmaz |
| `stop` | `compose stop` | aynı |
| `restart` | `compose restart` | aynı |

---

### `instance remove`

```bash
oii instance remove <ad> [--remove-data] [--yes] [--apply]
```

Varsayılan dry-run; yalnızca `--apply --yes` ile çalışır.

| Bayrak | Etkisi |
|--------|--------|
| *(yok)* | container'ları durdurup kaldırır, stack dizinini siler, kaydı düşer |
| `--remove-data` | ayrıca stack'in **isimli volume'larını** yok eder (`compose down -v`) — veritabanı ve filestore |
| `--yes` | gerekli onay |
| `--apply` | planı çalıştır |

**Adopte edilmiş stack'lerde de** çalışır — orada izin verilen tek onaylı mutasyon
budur.

> 🔥 `--remove-data` geri alınamaz. Veri önemliyse önce yedekleyin
> (`oii backup create`).

```console
$ oii instance remove dev --apply --yes
[1/3] stop and remove the instance's containers (volumes kept)
  ✔ removed
[2/3] delete the instance directory /home/siz/odoo-instances/dev
  ✔ deleted
[3/3] remove instance 'dev' from the registry
  ✔ removed
✔ instance 'dev' removed
```

`remove`, CLI manifest'i olmayan dizinleri reddeder — kendi oluşturmadığı bir şeyi
silmez.

---

### `instance adopt`

```bash
oii instance adopt <dizin> [--name AD] [--db-user odoo] [--apply]
```

Mevcut bir compose stack'ini, dosyalarını yeniden yazmadan kaydeder. CLI, planlamadan
önce ne algıladığını basar.

```console
$ oii instance adopt ~/Projects/my-odoo
detected: project my-odoo, web service web (odoo:19.0) on port 8069, db service db (postgres:17)
Instance adopt plan: my-odoo
   1. → write .odoo-installer.json into /home/siz/Projects/my-odoo (adopted, read-mostly)
   2. → register instance 'my-odoo' in the registry (adopted)
dry run — re-run with --apply to execute
```

| Koşul | Ayrıntı |
|-------|---------|
| Algılama | tamamen **container etiketlerinden** — compose dosyası parse edilmez |
| Web servisi | Odoo imajı ya da `8069` container portuna eşlenen yayınlanmış host portu |
| DB servisi | bir postgres imajı |
| Benzersiz ad | compose proje adı alınmışsa/geçersizse `--name` |
| `--db-user` | db container'ındaki postgres rolü (varsayılan `odoo`) |

Adopte edilmiş stack'lerin davranış kuralları
[3. Temel kavramlar §6](03-kavramlar.md#6-adopte-edilmiş-stackler) bölümündedir.

---

## İlgili sayfalar

- Tüm yapılandırma anahtarları: [7. Yapılandırma](07-yapilandirma.md)
- Diğer alanlar: [5. Veri, modül ve test](05-komutlar-veri-modul-test.md)
  · [6. Yedekleme ve apply](06-komutlar-yedekleme-ve-apply.md)

---

[⬅️ Önceki: Temel kavramlar](03-kavramlar.md) · [Dizin](README.md) · [Sonraki: Veri, modül ve test ➡️](05-komutlar-veri-modul-test.md)
