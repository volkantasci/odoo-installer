# 9. Güvenlik ve sorun giderme

**🇹🇷 Türkçe** · [🇬🇧 English](../en/09-safety-and-troubleshooting.md)

---

**Bu sayfada**

1. [Güvenlik kuralları bir bakışta](#1-güvenlik-kuralları-bir-bakışta)
2. [Çıkış kodları](#2-çıkış-kodları)
3. [Sorun giderme](#3-sorun-giderme)
4. [SSS](#4-sss)
5. [Yardım almak](#5-yardım-almak)

---

## 1. Güvenlik kuralları bir bakışta

| Kural | Kendini nasıl gösterir |
|-------|------------------------|
| Plan-önce | her mutasyon numaralı plan basar ve `--apply` gelene kadar hiçbir şey yapmaz |
| Yıkıcı işlemler çift kapılı | `db drop/reset`, `instance remove --remove-data`, `backup restore` `--apply --yes` ister |
| İdempotent tekrarlar | tatmin edilen adımlar `already satisfied` bildirir; sırlar/portlar kalıcıdır |
| Açık veritabanı adları | CLI sizin için asla veritabanı seçmez |
| Açık instance adları | belirsiz registry `--instance` ister, rastgele seçim asla yapılmaz |
| Adopte edilen stack'ler okuma ağırlıklı | `--yes` olmadan dosya yeniden yazımı yok; container'ları CLI asla yeniden oluşturmaz |
| Dosya düzenlemeleri yedek korumalı | `.oii-bak` kopyaları; compose düzenlemeleri `docker compose config` ile doğrulanır, bozulursa geri alınır |
| Geçici veritabanları tek kullanımlık | `oitest_*` DB'leri testlerden sonra düşürülür (`--keep-db` hariç) |
| Bozuk yedekler reddedilir | `backup restore` planlamadan önce sağlama toplamlarını doğrular |
| Token yönetimi | GitHub token'ları ortamdan okunur, asla diske yazılmaz |

Korumalı veritabanı adları: `postgres`, `template0`, `template1`.

`remove` komutu, CLI manifest'i taşımayan dizinleri reddeder — kendi oluşturmadığı
bir şeyi asla silmez (adopte edilen stack'ler `--apply --yes` arkasındaki bilinçli
istisnadır).

---

## 2. Çıkış kodları

| Kod | Anlamı | Tipik komutlar |
|-----|--------|----------------|
| `0` | başarı (dry-run'lar dahil) | hepsi |
| `1` | çalışma zamanı hatası | bir OdooInstallerError ile başarısız olan her komut (eksik instance, sağlıksız stack, reddedilen işlem) |
| `2` | kullanım hatası | Typer — bilinmeyen seçenek/komut |
| `3` | test başarısızlıkları | `module test`, `test suite` |
| `4` | kritik host denetimi başarısız | `doctor` |

Betik örneği:

```bash
oii doctor || exit 4
oii test suite --only web --output rapor.md
case $? in
    0) echo "her şey yolunda" ;;
    3) echo "testler başarısız — rapor.md'ye bakın" ;;
    *) echo "beklenmedik hata" ;;
esac
```

Çoğu okuma komutu kararlı makine çıktısı için `--json` da destekler:
`doctor`, `instance list/show/health`, `db list`, `module list`, `backup list`,
`test suite --output rapor.json`, `config show`, `apply --json`.

---

## 3. Sorun giderme

### `doctor` `4` koduyla çıkıyor

FAIL satırını okuyun — denetimi adıyla söyler. Sık nedenler ve çözümleri:

| FAIL | Çözüm |
|------|-------|
| container runtime | kurun/başlatın: `oii install --apply` |
| compose | sağlayıcıyı kurun (`docker-compose` / `docker-compose-plugin`) |
| compose (podman) | `systemctl --user enable --now podman.socket` |
| runtime permissions | `sudo usermod -aG docker $USER`, sonra yeniden oturum açın |
| git | `git` kurun |
| disk space | yer açın; bir stack yaklaşık 7 GB ister |

WARN satırları engellemez; bozulmuş davranışı açıklar (linger, dolu portlar, GitHub
erişilemezliği).

### "branch '19.0' does not exist on OCA/&lt;ad&gt;"

Dal denetimi herhangi bir klondan önce başarısız oldu.

- `module add` komutuna **modül** adı vermiş olabilirsiniz — whitelist biliyorsa
  hata, sağlayıcı repoyu ve tam komutu söyler.
- Değilse yazımı kontrol edin veya repoyu `oii module search <ad>` ile bulun.

### "not tested yet: …"

`module install`/`upgrade` test edilmemiş bir modülü reddetti.

```bash
oii module test <ad>          # kanıtla → whitelist
oii module install <ad> --db odoo

# veya bilinçli olarak:
oii module install <ad> --db odoo --allow-untested
```

Onaylarınız merkezi repoda yaşıyorsa önce `oii test pull --apply` çalıştırın.

### "missing OCA dependencies need mounting: …"

Çözücü, bağlı olmayan sağlayıcı repoları buldu:

```bash
oii module install <ad> --db odoo --resolve-deps
```

Sağlayıcılar var olmalı ve çözülebilmelidir; bağımlılık kataloğun açıklayamadığı bir
repoda yaşıyorsa `module search` onu bulur.

### "modules not visible to this instance"

Modül addons yolunda değil:

```bash
oii module add <repo> --apply          # onu sağlayan OCA reposu
oii module add <repo> --repo ~/benim/checkout --apply   # veya kendi checkout'unuz
```

Hata *"cannot verify Odoo core either — is the stack running?"* ekiyle geliyorsa
container kapalıdır; ne çekirdek ne OCA görünürlüğü doğrulanamaz: stack'i başlatın
(`oii instance start <ad>`).

### GitHub hız sınırı / boş arama sonuçları

Bir token tanımlayın:

```bash
export GITHUB_TOKEN=ghp_...
# veya CLI'yi başka bir değişkene yönlendirin:
oii config set github_token_env MY_GH_TOKEN
```

### Port zaten alınmış

- **Durmuş** bir stack socket tutmaz — iki instance aynı portu gösterebilir; birer
  birer başlatın ya da farklı `--http-port` değerleri sabitleyin;
- ilgisiz bir sürecin kullandığı port açıkça bildirilir;
- aralık tükendiyse genişletin:

```bash
oii config set port_range_start 9000
oii config set port_range_end 9100
```

### Yeni bir create geride container/volume bıraktı

Yeni oluşturmalar aynı adlı kalıntıları otomatik temizler (`compose down -v`) çünkü
PostgreSQL mevcut bir veri dizinini asla yeniden başlatmaz. Manifest bulunan
tekrarlarda temizlik asla yapılmaz — bu veriyi yok ederdi.

Bir oluşturma yarıda öldüyse ve manifest duruyorsa, kaldırıp yeniden oluşturun:

```bash
oii instance remove <ad> --apply --yes --remove-data   # verisini yok eder
oii instance create <ad> --apply
```

### "recreate it with your own tooling" (adopte edilmiş stack'ler)

Adopte edilmiş bir stack'te `module add --yes` sonrası CLI dosyaları düzenlemiştir
ama çalışan container'lara bilinçli olarak dokunmamıştır:

```bash
cd <stack-dizini>
docker compose up -d web     # veya: podman compose up -d web
```

### Modül kuruldu ama Odoo onu kurulu göstermiyor

`module install` sonrasında `ir_module_module` durumlarını doğrular ve `1` koduyla
listeyi verir. Çıktının sonunu ve modülün bağımlılıklarını inceleyin:

```bash
oii module list --instance dev --db odoo
oii instance logs dev --tail 200
```

### Veritabanı yöneticisi master parolasını soruyor

O alan tasarım gereği önceden doldurulmaz. Üretilen master parolasını okuyun:

```bash
oii instance secret dev
```

Kendinizinkini koymak için: `config/odoo.conf` içindeki `admin_passwd` **ve** `.env`
(`ADMIN_PASSWD`) değerlerini düzenleyin, sonra `oii instance restart dev`.

### Test logları nerede?

| Instance türü | Konum |
|---------------|-------|
| oluşturulan | `<stack>/logs/test-<modül>-<zaman>.log` |
| adopte edilen | `~/.local/state/odoo-installer/logs/<ad>/` |

`module test`, log yazıldıysa yolunu da basar.

### "cannot identify the web/db services" / adopt başarısız

Adoption yalnızca container etiketlerinden çalışır. Koşullar:

- stack en az bir kez çalışmış olmalı (`compose ps` container'larını görür);
- bir servis **postgres** imajlı olmalı (db);
- bir servis **odoo** imajlı olmalı ya da host `8069` portunu yayınlamalı (web);
- web servisi `8069` container portunu host üzerinde yayınlamalı.

Host portu yayınlamayan ingress stack'leri adopte edilemez — CLI onlara HTTP ile
ulaşamaz.

### Backup hook başarısız oldu

Hook komutu yedek yazıldıktan sonra, `OII_BACKUP_DIR` set edilerek çalışır. Sıfır
olmayan çıkış komutu başarısız kılar ve stderr'i basar — yedek diskte kalır. Hook'u
elle test edin:

```bash
OII_BACKUP_DIR=/path/to/backup bash -c '<hook komutunuz>'
```

### Restore yedeğimi reddediyor

`backup restore` önce SHA-256 sağlama toplamlarını doğrular. Hangi dosyanın
eksik/bozuk olduğunu görmek için
`oii backup verify --instance <ad> --backup <TS>` çalıştırın. Restore yalnızca
eksiksiz yedeklerle yapılır; yarım bir dizin asla kullanılmaz.

### Yeni bir stack'te `apply` tek büyük bir adım gösteriyor

Bu beklenen bir durumdur: repo/veritabanı/modül planları instance manifest'inden
kurulur; manifest ancak stack oluşturulduktan sonra doğar. Dry-run dürüstçe tek bir
hizalama adımı gösterir; yürütme sırasında tam ayrıntısıyla planlanır ve canlı
`[i/n]` çıktısı verir.

---

## 4. SSS

**Docker mı Podman mı — hangisini seçmeliyim?**
İkisi de çalışır. `auto`, varsa rootless Podman'ı tercih eder. Tercihi açıkça
belirtin: `oii config set container_runtime podman|docker`.

**CLI, Odoo'yu host'a kurar mı?**
Asla. `oii install` yalnızca host runtime'ını hazırlar; Odoo her zaman stack içinde
çalışır.

**Birden fazla instance yönetebilir miyim?**
Evet — her biri kendi dizininde, kendi portu ve sırlarıyla bir arada yaşar. Birden
fazlası kayıtlıysa `--instance` verin.

**Komutları tekrar çalıştırmak verimi bozar mı?**
Hayır. Tekrarlar idempotenttir. Veri yalnızca açık yıkıcı komutlarla
(`db drop/reset`, `instance remove --remove-data`, `backup restore`) ve
`--apply --yes` arkasında yok edilir.

**19.0 dışında Odoo sürümleri kullanabilir miyim?**
OCA doğrulaması için dal mantığı `19.0`'a sabittir. `--image` başka bir etiketi
gösterebilir ama OCA dal denetimleri `19.0`'da kalır.

**Filestore'um nerede?**
Stack içindeki isimli compose volume'unda; `oii backup create` onu `filestore.tar`
olarak yedekler. Veritabanı volume'u (`pgdata`) db container'ı tarafından yönetilir.

**GitHub token'ı gerekli mi?**
Yalnızca yoğun keşif/tarama için. Tokensız da her şey çalışır, yalnızca hız
sınırları düşer.

**CI'da çalıştırabilir miyim?**
Evet — `doctor --json`, `apply --json`, raporlar ve çıkış kodları betikleme için
tasarlanmıştır. Testlerin kendisi container runtime'ı bulunan çalışan bir stack
gerektirir.

**OCA kodunu nasıl güncellerim?**
`oii module upgrade-repos --apply` klonları tazeler; ardından basılan
`module upgrade <değişenler> --db <db>` komutunu Odoo içinde çalıştırın.

**CLI'yi nasıl kaldırırım?**
`pip uninstall odoo-installer` (veya `pipx uninstall odoo-installer`). Stack'leriniz,
yapılandırmanız ve whitelist'iniz kalır; bkz.
[2. Kurulum §Kaldırma](02-kurulum.md).

---

## 5. Yardım almak

- `oii <komut> --help` her zaman en güncel başvurudur.
- [`USAGE.tr.md`](../../USAGE.tr.md) — tek sayfalık kılavuz (Türkçe).
- [`USAGE.md`](../../USAGE.md) — tek sayfalık kılavuz (English).
- [`DEVELOPMENT.md`](../../DEVELOPMENT.md) — mimari ve kararlar.
- Hata ve öneriler:
  <https://github.com/volkantasci/odoo-installer/issues>

Sorun bildirirken şunları ekleyin:

```bash
oii version
oii doctor --json
oii config show --json
```

…artı çalıştırdığınız tam komut ve tüm çıktısı.

---

[⬅️ Önceki: İş akışları](08-is-akislari.md) · [Dizin](README.md) · [🇬🇧 English](../en/09-safety-and-troubleshooting.md)
