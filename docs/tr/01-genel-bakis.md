# 1. Genel bakış

**🇹🇷 Türkçe** · [🇬🇧 English](../en/01-overview.md)

---

## odoo-installer nedir?

`odoo-installer`, **Odoo 19.0 container stack'lerini kuran, yapılandıran ve
yöneten** bir komut satırı aracıdır.

Tek bir CLI tüm yaşam döngüsünü üstlenir:

- Podman veya Docker üzerinde eksiksiz bir stack (Odoo web + PostgreSQL) oluşturur;
- **OCA** depolarını doğru `19.0` dalından klonlar ve bağlar;
- modülleri güvenmeden önce **geçici veritabanlarında test eder**;
- modülleri Odoo üzerinden kurar, yükseltir ve kaldırır;
- veritabanı **ve** filestore yedeklerini alıp geri yükler;
- tüm bir instance'ı deklaratif bir `odoo-stack.toml` dosyasından hedeflenen duruma
  getirir.

Odoo'yu asla host'a kurmaz. Odoo her zaman container içinde çalışır; tüm Odoo
komutları (`-i`, `-u`, testler) **web container'ının içinde** yürütülür.

---

## Hangi sorunları çözer?

Odoo'yu elle yönetmek, akılda tutulması gereken bir sürü keskin kural demektir:

| Elle yönetimin sıkıntısı | `oii` ne yapar |
|--------------------------|----------------|
| Repo klonlarsınız, sonra `19.0` dalı olmadığını görürsünüz | Dalı klonlamadan **önce** GitHub API'siyle doğrular, asla tahmin etmez |
| Sparse clone'lar daha önce seçilen modülleri sessizce kaybeder | Sparse listesini genişletir (birleşim), asla değiştirmez |
| Modül kurulur ama bir bağımlılık reposu eksik olduğu için çalışmaz | `__manifest__.py` bağımlılıklarını çözer, sağlayıcı repoları otomatik bağlar |
| Test edilmemiş bir topluluk modülünü doğrudan üretime kurmak | Gerçek bir testten geçmemiş hiçbir şeyi kurmaz (whitelist) |
| Mount değişikliğinden sonra unutulan `docker compose up -d` | Web servisini sizin için yeniden oluşturur — düz `restart` yeni volumeleri bağlamaz |
| Compose dosyasının elle bozulması | Düzenlemeler yedeklenir ve `docker compose config` ile doğrulanır |
| Kazara silinen veritabanları | Yalnızca açık adlar; yıkıcı işlemler `--apply --yes` ister |
| "Bu komut neyi değiştirecek?" | Her mutasyon önce tam planını basar; ancak `--apply` ile çalışır |

---

## Öne çıkan özellikler

### 🦭 Önce Podman, Docker uyumlu

Her instance, seçtiğiniz runtime üzerinde bir compose stack'idir
(`container_runtime = auto|podman|docker`).

`auto` **rootless Podman**'ı tercih eder, yoksa Docker'a düşer. Tek bir adaptör iki
motoru da normalize eder; her komut her ikisinde aynı davranır.

### 📄 Deklaratif hedef durum

```bash
oii apply odoo-stack.toml
```

Tek bir TOML dosyası instance'ı uçtan uca tanımlar: stack ayarları, OCA repoları,
veritabanları ve her veritabanında kurulu olması gereken modüller.

`apply` **idempotenttir** — hizalanmış bir spec tekrar çalıştırıldığında her adım
`already satisfied` bildirir. Hosting kontrol düzlemlerinin döngüyle çağırması için
tasarlanmıştır.

### 💾 Yerleşik yedekleme

```bash
oii backup create | list | verify | prune | restore
```

Yedek = tutarlı bir `pg_dump` + filestore + SHA-256 sağlama toplamları.
`restore` plan-önce çalışır ve kapılıdır; bozuk yedekleri kesinlikle reddeder.

### 🌐 Ingress modu

Instance'ları paylaşılan bir reverse-proxy ağına alias ile bağlar — **host portu
yayınlanmaz**; instance bazında kaynak limitleri ve `odoo.conf` ayarları verilebilir.

### 📋 Plan-önce güvenlik

Değişiklik yapan her komut:

1. çalıştırılacak komutların ve dosya yazımlarının numaralı planını basar;
2. **hiçbir şey yapmadan** `0` koduyla çıkar;
3. yalnızca `--apply` ile (yıkıcıysa ayrıca `--yes` ile) çalışır.

Plan uygulanırken ilerleme canlı `[i/n]` satırlarıyla akar.

### 🌿 Doğru OCA dalları

`19.0` dalı her klondan önce GitHub API'siyle doğrulanır. Yanlışlıkla modül adı
verilirse, hataya o modülü sağlayan repo adı ve tam komut eklenir.

### ✅ Yalnızca test edilmiş kurulumlar

`module install`, aşağıdakilerden birini yapmamış hiçbir modülü kabul etmez:

- geçici bir veritabanında gerçek test koşusundan geçmek (`module test`,
  `test suite`), veya
- kanıtlanmış bir stack üzerinde açıkça onaylanmak (`module approve`).

Gerektiğinde `--allow-untested` ile kapıyı bilinçli olarak atlayabilirsiniz.

### 🔗 Bağımlılık çözücü

Her modülün `__manifest__.py` dosyasını okur ve tüm bağımlılıkları sınıflandırır:

- **Odoo çekirdeği** (çalışan container'a karşı doğrulanır);
- aynı repodaki **kardeş** modüller (sparse clone'a otomatik katılır);
- **diğer OCA repoları** (sağlayıcı repolar otomatik bağlanır);
- yerelde ya da başka bir mount'ta **zaten mevcut** olanlar.

### 🗂️ Merkezi onaylar

Whitelist küçük bir git reposunda yaşayabilir (`tested_repo_url`).

`test pull` onu her makineye birleştirir — bir kez onaylanan modül, CLI güncellenmeden
her yerde kurulabilir olur.

### 🔁 Her yerde idempotent

Portlar sabitlenir, sırlar kalıcıdır, tatmin edilmiş adımlar `already satisfied`
bildirir ve adopte edilmiş stack'ler arkanızdan asla yeniden yazılmaz.

---

## Tasarım ilkeleri

Bu kurallar her komutun şeklini belirler:

1. **Önce göster, sonra yap.** Plan dokümantasyon değildir — *çalıştırılan kod
   yolunun ta kendisidir*.
2. **Açık olan, akıllı olandan iyidir.** Veritabanı adı asla varsayılmaz.
3. **Dal asla tahmin edilmez.** OCA desteği doğrulanır, varsayılmaz.
4. **Yalnızca kanıtlanmış modüller kurulur.** Whitelist sözleşmedir.
5. **Adopte edilen stack'ler okuma ağırlıklıdır.** CLI kendi oluşturmadığı
   container'ları yeniden oluşturmaz.
6. **Tekrar çalıştırmak güvenlidir.** Her adım tasarım gereği idempotenttir.

---

## Gereksinimler bir bakışta

| Gereksinim | Ayrıntı |
|------------|---------|
| Python | 3.11 veya üzeri |
| İşletim sistemi | Linux (`install` için pacman ve apt desteklenir) |
| Runtime | Podman (tercih edilen, rootless) **veya** Docker + compose sağlayıcısı |
| Git | OCA klonları için gerekli — `oii doctor` denetler |
| Ağ | OCA keşfi için GitHub erişimi (token opsiyonel, limitleri yükseltir) |
| Disk | Stack başına ~7 GB boş alan sağlıklı bir tabandır |

`oii doctor` tüm bunları doğrular; `oii install --apply` düzeltebileceklerini düzeltir.

---

## Komut aileleri

| Komut ailesi | Sağladığı şey |
|--------------|---------------|
| `doctor` | Anında host teşhisi — runtime, compose, git, disk, portlar, GitHub |
| `install` | pacman/apt ile host ön gereksinimleri — Odoo'nun kendisi **asla** host'a kurulmaz |
| `config` | Doğrulanmış, atomik genel yapılandırma |
| `instance` | Tam stack yaşam döngüsü: oluştur, adopt et, incele, başlat/durdur, sırlar, kaldır |
| `db` | Stack'in kendi PostgreSQL container'ı üzerinden veritabanı işlemleri |
| `module` | OCA repoları ve modülleri: add, list, search, install, upgrade, remove, test, approve |
| `test` | Raporlu toplu test süitleri + merkezi whitelist senkronu |
| `backup` | Tutarlı veritabanı + filestore yedekleri: oluştur, doğrula, buda, geri yükle |
| `apply` | `odoo-stack.toml` ile deklaratif hedef duruma getirme |
| `version` | Kurulu sürümü yazdırır |

Tek satırlık tur:

```bash
oii doctor                                   # bu host Odoo stack'i çalıştırabilir mi?
oii install --apply                          # çalıştırabilir hale getir
oii instance create dev --apply              # stack'i oluştur
oii db create odoo --instance dev            # veritabanını oluştur
oii module add web --sparse \
    --modules web_responsive --apply         # OCA reposunu ekle
oii module test web_responsive               # geçici DB'de kanıtla
oii module install web_responsive \
    --db odoo --instance dev                 # gerçekten kur
oii backup create --instance dev             # yedekle
```

---

## Sırada nereye?

| İstediğim şey… | Okuyun |
|----------------|--------|
| aracı kurmak | [2. Kurulum](02-kurulum.md) |
| nasıl düşündüğünü anlamak | [3. Temel kavramlar](03-kavramlar.md) |
| tek bir komuta bakmak | [4](04-komutlar-host-ve-instance.md) · [5](05-komutlar-veri-modul-test.md) · [6](06-komutlar-yedekleme-ve-apply.md) |
| yapılandırmak | [7. Yapılandırma](07-yapilandirma.md) |
| bir tarif izlemek | [8. İş akışları](08-is-akislari.md) |
| bir hatayı çözmek | [9. Güvenlik ve sorun giderme](09-guvenlik-ve-sorun-giderme.md) |

---

[⬅️ Dizine dön](README.md) · [Sonraki: Kurulum ➡️](02-kurulum.md)
