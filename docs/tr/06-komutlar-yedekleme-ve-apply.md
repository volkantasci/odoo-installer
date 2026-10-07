# 6. Komutlar — yedekleme ve apply

**🇹🇷 Türkçe** · [🇬🇧 English](../en/06-commands-backups-and-apply.md)

---

Bu sayfa şunları kapsar:

| Komut | Amacı |
|-------|-------|
| [`backup`](#backup--veritabanı--filestore-anlık-görüntüleri) | tutarlı anlık görüntüler, doğrulama, budama, geri yükleme |
| [`apply`](#apply--deklaratif-hedef-durum) | instance'ı `odoo-stack.toml`'dan hedefine getirme |

---

## `backup` — veritabanı + filestore anlık görüntüleri

```bash
oii backup create  [--instance AD] [--db DB]
oii backup list    [--instance AD] [--json]
oii backup verify  [--instance AD] [--backup TS]
oii backup prune   [--instance AD] [--keep N] [--apply]
oii backup restore <TS> [--instance AD] [--apply] [--yes]
```

### Bir yedeğin içeriği

Her yedek `<stack>/backups/<zaman>/` altında yaşar:

| Dosya | İçerik |
|-------|--------|
| `db.dump` | `pg_dump -Fc` (custom format dump) |
| `filestore.tar` | web container'ının `/var/lib/odoo` dizini (ekler vb.) |
| `manifest.json` | meta veri + iki dosya için **SHA-256 sağlama toplamları** |

Zaman damgaları saniye altı hassasiyet taşır
(`YYYYMMDDTHHMMSSffffff`), böylece zamanlanmış ve elle alınan yedekler çakışmaz.

Her şey container ile host arasında runtime'ın kendi stdio'su (`compose exec -T`)
üzerinden akar — container uid'sine ait filestore baytları için host tarafında izin
düzeltmesi gerekmez.

---

### `backup create`

```bash
oii backup create [--instance AD] [--db DB]
```

- **Doğrudan** çalışır — eklemelidir ve güvenlidir.
- `pg_dump` MVCC tutarlıdır: Odoo yedek sırasında hizmet vermeye devam edebilir.
- Veritabanı varsayılanı: instance'ın **tek** Odoo veritabanı. Hiç yoksa ya da birden
  fazlaysa `--db` vermek zorundasınız (veya önce bir veritabanı oluşturun).

```console
$ oii backup create --instance dev
✔ backup 20261007T141530123456 of 'odoo': db 25165824 bytes + filestore 7340032 bytes (32505856 total) in /home/siz/odoo-instances/dev/backups/20261007T141530123456
```

`backup_hook` ayarlıysa her başarılı oluşturmadan sonra çalışır;
`OII_BACKUP_DIR` taze yedek dizinini gösterir — `rclone`, `rsync` veya bir depo
betiği için idealdir:

```bash
oii config set backup_hook 'rclone copy "$OII_BACKUP_DIR" remote:odoo-backups/$(basename "$OII_BACKUP_DIR")'
```

Başarısız bir hook komutu başarısız kılar (yedek diskte kalır).

---

### `backup list` / `backup verify`

```bash
oii backup list [--instance AD] [--json]
oii backup verify [--instance AD] [--backup TS]
```

`list`, en yenisi en sonda olacak şekilde her yedeği tek satırda basar.

`verify`, SHA-256 sağlama toplamlarını `manifest.json`'a karşı yeniden hesaplar:

- `--backup` yok → **tüm** yedekleri doğrular;
- herhangi bir uyuşmazlıkta (eksik dosya veya bozulmuş baytlar) `1` koduyla çıkar.

```console
$ oii backup verify --instance dev
✔ 20261007T141530123456: checksums match
```

---

### `backup prune`

```bash
oii backup prune [--instance AD] [--keep N] [--apply]
```

En yeni `--keep` yedek dışındakileri siler (varsayılan `3`). Plan-öncedir:

```console
$ oii backup prune --instance dev --keep 2
Backup prune plan: dev (keep 2)
   1. → delete backup 20260901T030000000000 (odoo, 31000000 bytes)
dry run — re-run with --apply to execute
```

Silinecek kadar eski bir şey yoksa `✔ nothing to prune` der.

---

### `backup restore`

```bash
oii backup restore <TS> [--instance AD] [--apply] [--yes]
```

Yıkıcı ve plan-öncedir; yalnızca `--apply --yes` ile çalışır.

Planlamadan önce yedek **doğrulanır** — bozuk ya da eksik bir yedek doğrudan
reddedilir.

Plan, sırasıyla:

1. web servisini durdurur (geri yükleme sırasında Odoo yazmamalıdır);
2. veritabanını düşürüp yeniden oluşturur;
3. dump'ı `pg_restore` ile içine yükler;
4. filestore'u tek kullanımlık bir container üzerinden değiştirir;
5. web servisini başlatır;
6. container sağlıklı olana kadar bekler.

```console
$ oii backup restore 20261007T141530123456 --instance dev
Backup restore plan: dev <- 20261007T141530123456
   1. → stop the web service (Odoo must not write during restore)
   2. → drop and recreate database 'odoo'
   3. → restore database from .../db.dump
   4. → replace the filestore from .../filestore.tar
   5. → start the web service
   6. → wait for the web container to become healthy
This replaces database 'odoo' and the filestore with the state from 20261007T141530123456.
add --yes to confirm the restore
```

> 🔥 **Restore veriyi bütünüyle değiştirir.** Geri yükleme öncesi durum otomatik
> saklanmaz — önemliyse önce `oii backup create` çalıştırın.

---

## `apply` — deklaratif hedef durum

```bash
oii apply <odoo-stack.toml> [--apply] [--json]
```

Tek bir TOML dosyası **tek bir instance'ı uçtan uca** tanımlar:

```toml
name = "acme"                    # instance adı (compose projesi de budur)
# dir = "~/stacks/acme"          # opsiyonel: stack dizini
image = "odoo:19.0"              # opsiyonel (varsayılan)
pg_tag = 17                      # opsiyonel (config varsayılanı)
http_port = 8069                 # VEYA bir [ingress] bloğu — ikisi birden olamaz
admin_login = "admin"            # Odoo admin girişi (parola .env'e üretilir)

[ingress]                        # reverse-proxy modu: host portu yayınlanmaz
network = "violetear-ingress"    # harici compose ağı
alias = "acme"                   # ağ alias'ı (varsayılan: ad)

[resources]
memory = "2g"                    # compose mem_limit
cpus = 2.0                       # compose cpus

[settings]                       # odoo.conf ayarları
proxy_mode = true                # [ingress] ile örtük olarak açılır
list_db = false
workers = 4

[[repos]]                        # OCA repoları (dal her zaman 19.0)
url = "https://github.com/OCA/web.git"
modules = ["web_environment_ribbon"]   # sparse klon listesi (verilmezse: tüm repo)

[[repos]]
url = "OCA/server-tools"         # sahip/repo kısa yazımı da olur

[databases.acme]                 # her veritabanı bir tablo alır
install = ["base", "sale", "web_environment_ribbon"]
allow_untested = false           # tested-only kapısı için kaçış yolu
```

### `apply` neyi hizalar?

`apply`, etkileşimli komutların kullandığı **aynı idempotent planları** bir araya
getirir:

| Alan | Davranış |
|------|----------|
| Stack | yoksa oluşturulur — compose, `.env`, `odoo.conf`, registry, manifest |
| Repolar | manifest'e karşı karşılaştırılır: yeni URL'ler eklenir (`modules` verilmişse sparse); çıkarılan repolar unmount edilir ve klonları temizlenir |
| Veritabanları | her `[databases.<ad>]` tablosu veritabanının var olmasını sağlar |
| Modüller | `module install` ile aynı kapılarla kurulur — görünürlük + tested-only whitelist (`allow_untested` veritabanı bazında) |

### Bilinmesi gereken anlamlar

- **İdempotent.** Hizalanmış bir spec tekrar çalıştırıldığında her adım
  `already satisfied` bildirir. Döngüye sokmak güvenlidir — hosting kontrol
  düzlemlerinin kullandığı ilkel budur.
- **`http_port` bir istektir.** Kablo üzerinde boş ve başka bir kayıtlı instance
  tarafından rezerve edilmemiş olmalıdır; instance'ın kendi portuyla tekrar
  çalıştırmak sorunsuzdur.
- **Yeni stack'ler iki fazda hizalanır.** Repo/veritabanı/modül planları instance
  manifest'inden kurulur; manifest ancak stack var olduktan sonra doğar. Bu yüzden
  dry-run geri kalanı tek bir dürüst hizalama adımı olarak gösterir; uygulama anında
  tam ayrıntısıyla planlanır ve canlı `[i/n]` ilerlemesiyle yürütülür.
- **İlk kurulumda admin bilgileri uygulanır.** Bir veritabanı ilk kez
  başlatıldığında üretilen `ODOO_ADMIN_PASSWORD`, Odoo'nun ORM'i üzerinden uygulanır
  (ham SQL yazımı parola hash'lemesini atlardı). Sonraki apply'lar parolaya bir daha
  dokunmaz.
- **`[ingress]` ile `http_port` birbirini dışlar** — ingress host portu yayınlamaz.
- Repolar `https://github.com/sahip/repo[.git]`, `git@github.com:sahip/repo` veya
  `sahip/repo` kabul eder; çıplak `repo` varsayılan olarak `OCA` sahibini alır. Dal
  her zaman `19.0`'dır.

### Dry-run ve planı inceleme

```console
$ oii apply odoo-stack.toml
Apply plan: acme (existing instance)
   1. → render docker-compose.yml
   2. → render .env (contains secrets, mode 0600)
   ...
   7. → ensure database 'acme' exists
   8. → install modules base, sale, web_environment_ribbon into db 'acme' (visibility and whitelist verified at run time)
dry run — re-run with --apply to execute
```

CI/kontrol düzlemleri için makine-okunur plan:

```bash
oii apply odoo-stack.toml --json
```

```json
{
  "instance": "acme",
  "stack_dir": "/home/siz/odoo-instances/acme",
  "created": false,
  "steps": [
    {
      "index": 1,
      "description": "render docker-compose.yml",
      "already_satisfied": true
    }
  ]
}
```

Yürütmeyle birleştirin:

```bash
oii apply odoo-stack.toml --json --apply     # planı basar, sonra hizalar
```

### Kontrol düzlemi döngüsü

```bash
#!/usr/bin/env bash
set -euo pipefail

# her spec dosyalanmış bir instance'tır; hepsini hizala, iki kez çalışmak zararsız
for spec in /etc/odoo-fleet/*.toml; do
    oii apply "$spec" --json --apply
done
```

---

## İlgili sayfalar

- İki komutu kullanan uçtan uca tarifler: [8. İş akışları](08-is-akislari.md)
- Yapılandırma anahtarları (`backup_hook`, `tested_repo_url`, …):
  [7. Yapılandırma](07-yapilandirma.md)

---

[⬅️ Önceki: Veri, modül ve test](05-komutlar-veri-modul-test.md) · [Dizin](README.md) · [Sonraki: Yapılandırma ➡️](07-yapilandirma.md)
