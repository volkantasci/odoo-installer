# odoo-installer — Kılavuz

**🇹🇷 Türkçe** · [🇬🇧 English](../en/README.md)

> **`odoo-installer` 0.8.x için yazılmıştır** (güncel sürüm: 0.8.1).
> Mimari ve tasarım kararlarının kaynağı:
> [`DEVELOPMENT.md`](../../DEVELOPMENT.md).

`odoo-installer` (kısaca `oii`), bir Odoo 19.0 kurulumunun tüm yaşam döngüsü için
tek bir komut satırı aracıdır:

> container stack'lerini oluştur, OCA depolarını doğru daldan ekle, modülleri
> gerçek testlerle kanıtla, güvenle kur, veriyi yedekle ve geri yükle, her şeyi
> deklaratif bir spec dosyasından yönet — üstelik **her değişikliği olmadan önce**
> göstererek.

---

## Bu kılavuzu nasıl okumalısınız?

Bölümler birbirinin üzerine kurulur ama her sayfa kendi başına da okunabilir.

Yeniyseniz önce **1 → 3 → 4** sırasını izleyin; gerisine ihtiyaç doğdukça dönün.

| # | Bölüm | Ne öğrenirsiniz |
|---|-------|-----------------|
| 1 | [Genel bakış](01-genel-bakis.md) | Araç ne yapar, özellikleri ve tasarım ilkeleri |
| 2 | [Kurulum](02-kurulum.md) | Kurulum, güncelleme ve kabuk tamamlama |
| 3 | [Temel kavramlar](03-kavramlar.md) | Instance, plan, whitelist, bağımlılık çözümü, ingress |
| 4 | [Komutlar — host ve instance](04-komutlar-host-ve-instance.md) | `doctor`, `install`, `config`, `instance` |
| 5 | [Komutlar — veri, modül ve test](05-komutlar-veri-modul-test.md) | `db`, `module`, `test` |
| 6 | [Komutlar — yedekleme ve apply](06-komutlar-yedekleme-ve-apply.md) | `backup`, `apply` ve desired-state spec'i |
| 7 | [Yapılandırma](07-yapilandirma.md) | Tüm ayar anahtarları, dosyalar ve ortam değişkenleri |
| 8 | [İş akışları ve tarifler](08-is-akislari.md) | Kopyala-yapıştır senaryolar |
| 9 | [Güvenlik ve sorun giderme](09-guvenlik-ve-sorun-giderme.md) | Güvenlik kuralları, çıkış kodları, sık hatalar, SSS |

---

## Tüm sayfalarda geçerli kurallar

- Örnekler kısa takma adı **`oii`** kullanır. Aynı CLI `odoo-installer` ve
  `python -m odoo_installer` ile de çalışır.
- Blok başındaki `$`, *çalıştırılacak shell komutunu* gösterir; `$` olmayan
  bloklar **çıktıdır**.
- Değişiklik yapan komutlar **varsayılan olarak dry-run**'dır; örneklerde gerçekten
  çalıştırmak için `--apply` (yıkıcı işlemlerde ayrıca `--yes`) eklenir.
- `✔` adımın başarıyla tamamlandığını, `already satisfied` ise yapılacak bir şey
  kalmadığını gösterir.
- Yer tutucular `<ad>`, `<db>` ya da `X.Y.Z` gibi yazılır.

---

## Aradığınız başka bir şey miydi?

- Hızlı genel bakış: [proje README'si](../../README.md).
- Tek sayfalık kullanım kılavuzu: [USAGE.tr.md](../../USAGE.tr.md) ·
  [English](../../USAGE.md).
- Mimari ve geliştirici dokümanı: [DEVELOPMENT.md](../../DEVELOPMENT.md).
- Sürüm geçmişi: [CHANGELOG.md](../../CHANGELOG.md).

---

[Sonraki: Genel bakış ➡️](01-genel-bakis.md)
