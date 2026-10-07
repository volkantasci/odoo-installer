# 8. İş akışları ve tarifler

**🇹🇷 Türkçe** · [🇬🇧 English](../en/08-workflows.md)

---

Kopyala-yapıştır senaryolar: boş makineden büyümüş filoya.

**Bu sayfada**

1. [Yeni makineyi kurmak](#1-yeni-makineyi-kurmak)
2. [OCA modüllü yeni bir geliştirme instance'ı](#2-oca-modüllü-yeni-bir-geliştirme-instanceı)
3. [Repolar-arası bağımlılığı olan modül kurmak](#3-repolar-arası-bağımlılığı-olan-modül-kurmak)
4. [Hesap planı gerektiren bir modülü test etmek](#4-hesap-planı-gerektiren-bir-modülü-test-etmek)
5. [Fork'unuzdan çalışmak](#5-forkunuzdan-çalışmak)
6. [Kendi checkout'unuzu bağlamak (asla değiştirilmez)](#6-kendi-checkoutunuzu-bağlamak-asla-değiştirilmez)
7. [Tam kurulabilirlik raporu](#7-tam-kurulabilirlik-raporu)
8. [Üretimi adopte edip güvenle incelemek](#8-üretimi-adopte-edip-güvenle-incelemek)
9. [Onayları makineler arasında paylaşmak](#9-onayları-makineler-arasında-paylaşmak)
10. [Güvenle yükseltmek](#10-güvenle-yükseltmek)
11. [Reverse proxy arkasında ingress](#11-reverse-proxy-arkasında-ingress)
12. [Spec dosyasından deklaratif instance](#12-spec-dosyasından-deklaratif-instance)
13. [Offsite hook ile zamanlanmış yedekler](#13-offsite-hook-ile-zamanlanmış-yedekler)

---

## 1. Yeni makineyi kurmak

```bash
# CLI'yi kur (izole):
pipx install odoo-installer

# host'u stack çalıştırabilir hale getir:
oii doctor
oii install --apply
oii doctor        # her şey yeşil mi? hazırsınız
```

Opsiyonel ama önerilir:

```bash
oii --install-completion
export GITHUB_TOKEN=ghp_...   # daha yüksek GitHub API limitleri
```

---

## 2. OCA modüllü yeni bir geliştirme instance'ı

Klasik uçtan uca akış — her mutasyon `--apply` gelene kadar dry-run'dır:

```bash
# 1. stack'i oluştur (compose/.env/odoo.conf render edilir, başlar, sağlık beklenir)
oii instance create dev --apply

# 2. veritabanını oluştur
oii db create odoo --instance dev

# 3. modülü sağlayan OCA reposunu bul
oii module search "responsive"

# 4. yalnızca ihtiyacınız olan modülle sparse repo klonla
oii module add web --sparse --modules web_responsive --apply

# 5. geçici veritabanında kanıtla
oii module test web_responsive

# 6. kendi veritabanınıza kur
oii module install web_responsive --db odoo --instance dev

# 7. giriş yapın:
#    http://localhost:8069
#    - uygulama admin'i: düz `admin` kullanıcısı (parolayı Ayarlar'dan değiştirin)
#    - master parolası (veritabanı yöneticisi): `oii instance secret dev`
```

> 💡 Repoyu zaten biliyorsanız 3–4. adımlar opsiyoneldir. 5. adım, bilinçli olarak
> `--allow-untested` vermedikçe zorunludur.
>
> 💡 `oii apply` ile başlatılan veritabanlarına ayrıca ilk kurulumda üretilen
> `ODOO_ADMIN_PASSWORD` uygulanır — bkz.
> [12. tarif](#12-spec-dosyasından-deklaratif-instance).

---

## 3. Repolar-arası bağımlılığı olan modül kurmak

`module add`, repolar-arası sağlayıcıları otomatik çözer ve sağlar:

```console
$ oii module add account-financial-report --modules account_financial_report --apply
...
resolving dependency OCA/server-ux (provides date_range)
...
resolving dependency OCA/reporting-engine (provides report_xlsx)
...
✔ account-financial-report added
```

Doğrudan kurar da bağımlılığın sağlayıcı reposu eksikse hata size ne yapacağınızı
söyler:

```console
$ oii module install account_financial_report --db odoo
Error: missing OCA dependencies need mounting: date_range <- OCA/server-ux (provides date_range) — re-run with --resolve-deps to mount them automatically
```

```bash
# kurucunun sağlayıcıları bağlamasına ve bağımlılıkları dahil etmesine izin ver:
oii module install account_financial_report --db odoo --resolve-deps
```

---

## 4. Hesap planı gerektiren bir modülü test etmek

Hesap modülleri tek başına kurulduğunda, günlükler henüz olmadığı için testleri
sıkça başarısız olur. **İki aşamalı** test kullanın:

```bash
oii module test partner_statement --with sale
```

`--with`, ek modülleri test koşusundan **önce** ayrı bir hazırlık aşamasında kurar;
testler yine `partner_statement` ile sınırlı kalır.

Hatayı etkileşimli incelemek için geçici veritabanını saklayın:

```bash
oii module test partner_statement --with sale --keep-db
oii db list --instance dev          # oitest_partner_statement hâlâ orada
```

---

## 5. Fork'unuzdan çalışmak

```bash
oii module add server-tools --fork kullanici --apply
```

- `origin` fork'unuzu, `upstream` OCA'yı gösterir;
- dal, klonlamadan önce fork üzerinde doğrulanır;
- değişikliklerinizi fork'a itin; `module upgrade-repos` ucuna tazeler.

---

## 6. Kendi checkout'unuzu bağlamak (asla değiştirilmez)

Aktif geliştirme için mükemmel: yerel çalışma ağacınızı olduğu gibi bağlayın.

```bash
cd ~/dev/web-deploy
git checkout 19.0

oii module add web --repo ~/dev/web-deploy --apply
```

Kurallar:

- checkout `19.0` üzerinde olmalıdır (bir dala bağlıysa) — aksi halde CLI reddeder
  ve kendiniz geçmenizi söyler;
- CLI onu asla fetch etmez, checkout yapmaz, düzenlemez;
- `module remove` mount'u kaldırır ama `--purge-repo` onu **silmez**
  (yalnızca CLI'nin sahip olduğu klonlar temizlenebilir).

Kod düzenledikten sonra container'ın görmesi için servisi yeniden oluşturun:

```bash
oii instance restart dev        # veya: docker compose up -d web
```

---

## 7. Tam kurulabilirlik raporu

Instance'ın addons yolundaki her şeyi sırayla test edin, raporlarla:

```bash
oii test suite --instance dev --output rapor.md --output rapor.json
```

- modül başına yepyeni bir geçici DB;
- PASS'ler whitelist'i besler;
- bir şey başarısızsa çıkış kodu `3` — CI'da kullanılabilir.

```bash
# repoya göre ya da açık listeyle filtrele:
oii test suite --only web
oii test suite --modules web_responsive,web_environment_ribbon
```

---

## 8. Üretimi adopte edip güvenle incelemek

```bash
# mevcut stack'i kaydet (hiçbir dosya yeniden yazılmaz):
oii instance adopt ~/Projects/my-odoo --apply

# hiçbir şeye dokunmadan incele:
oii instance show my-odoo
oii db list --instance my-odoo
oii module list --instance my-odoo --db odoo
oii instance logs my-odoo --tail 100

# zaten kanıtlanmış modülleri whitelist'e kaydet:
oii module approve attribute_set pim product_attribute_set --db odoo --instance my-odoo
```

Adopte edilmiş stack'ler aynen çalışmaya devam eder — CLI container'larını asla
yeniden oluşturmaz. Bkz. [3. Temel kavramlar §6](03-kavramlar.md#6-adopte-edilmiş-stackler).

---

## 9. Onayları makineler arasında paylaşmak

```bash
# her makinede tek seferlik kurulum:
oii config set tested_repo_url https://github.com/<org>/odoo-installer-tested.git

# modülleri kanıtlayan makinede:
oii module test my_module
# (veya canlı bir stack'te zaten kanıtlanmışsa:)
oii module approve my_module --db odoo

# ~/.config/odoo-installer/tested.toml dosyasını merkezi repoya kopyalayıp itin.
# ardından her yerde:
oii test pull --apply
```

Yeni onaylar artık CLI güncellenmeden yayılır.

---

## 10. Güvenle yükseltmek

```bash
# 1. repo klonlarını dallarının ucuna tazele (değişen modülleri raporlar):
oii module upgrade-repos --instance dev --apply

# 2. modülü önce geçici DB'de kanıtla:
oii module test my_module --keep-db

# 3. Odoo içinde yükselt — yalnızca whitelist'teki modüller geçer:
oii module upgrade my_module --db odoo --instance dev
```

Araç iki fazı bilinçli olarak ayrı tutar: **kodu tazele**, sonra basılan listeyle
**Odoo içinde yükselt**.

---

## 11. Reverse proxy arkasında ingress

```bash
oii instance create acme \
    --ingress-network violetear-ingress \
    --ingress-alias acme \
    --memory 2g --cpus 1.5 --workers 4 \
    --apply
```

- harici ağ yoksa önce oluşturun
  (`docker network create violetear-ingress` / `podman network create …`);
- web servisi ona `acme` alias'ıyla katılır; host portu yayınlanmaz;
- proxy'nizi ağ içindeki `acme:8069` adresine yönlendirin;
- sağlık denetimleri container healthcheck'i üzerinden çalışmaya devam eder.

Deklaratif olarak:

```toml
name = "acme"

[ingress]
network = "violetear-ingress"
alias = "acme"

[resources]
memory = "2g"
cpus = 2.0

[settings]
workers = 4
```

```bash
oii apply acme.toml --apply
```

---

## 12. Spec dosyasından deklaratif instance

Hedef durumu bir kez yazın, dilediğiniz kadar hizalayın:

```toml
# acme.toml
name = "acme"
pg_tag = 17
http_port = 8070
admin_login = "admin"

[[repos]]
url = "OCA/web"
modules = ["web_environment_ribbon"]

[[repos]]
url = "OCA/server-tools"
modules = ["base_technical_features"]

[databases.acme]
install = ["base", "sale", "web_environment_ribbon", "base_technical_features"]
allow_untested = false
```

```bash
# tam olarak neyin değişeceğini gör:
oii apply acme.toml

# hizala:
oii apply acme.toml --apply

# tekrar hizala — her adım "already satisfied" bildirir:
oii apply acme.toml --apply
```

> ⚠️ Tested-only kapısı yine geçerlidir: modüller test/onay görmüş olmalıdır (ya da
> veritabanının `allow_untested = true` değeri). Spec yeni modüller içeriyorsa önce
> `module test` veya `test pull` çalıştırın.

---

## 13. Offsite hook ile zamanlanmış yedekler

```bash
# her taze yedeği offsite'a gönder (her oluşturmadan sonra çalışır):
oii config set backup_hook 'rclone copy "$OII_BACKUP_DIR" remote:odoo-backups/$(basename "$OII_BACKUP_DIR")'

# elle anlık görüntü:
oii backup create --instance prod

# en yeni 14 tanesini sakla:
oii backup prune --instance prod --keep 14 --apply
```

Gece anlık görüntüsü için bir cron girdisi:

```cron
# dk saat gün ay hafta  komut
  30 3  *   *   *      oii backup create --instance prod >> ~/.local/state/odoo-backups.log 2>&1
  30 3  *   *   *      oii backup prune --instance prod --keep 14 --apply >> ~/.local/state/odoo-backups.log 2>&1
```

Notlar:

- `backup create`, Odoo hizmet verirken güvenlidir (MVCC tutarlı dump);
- başarısız hook komutu başarısız kılar, ama yerel yedek diskte kalır;
- arada bir doğrulayın: `oii backup verify --instance prod`.

---

## İlgili sayfalar

- Komutların arkasındaki kavramlar: [3. Temel kavramlar](03-kavramlar.md)
- Tüm seçenek listeleri: [4](04-komutlar-host-ve-instance.md) ·
  [5](05-komutlar-veri-modul-test.md) · [6](06-komutlar-yedekleme-ve-apply.md)

---

[⬅️ Önceki: Yapılandırma](07-yapilandirma.md) · [Dizin](README.md) · [Sonraki: Güvenlik ve sorun giderme ➡️](09-guvenlik-ve-sorun-giderme.md)
