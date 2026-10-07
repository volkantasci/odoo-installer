# 5. Komutlar — veri, modül ve test

**🇹🇷 Türkçe** · [🇬🇧 English](../en/05-commands-data-modules-tests.md)

---

Bu sayfa şunları kapsar:

| Komut | Amacı |
|-------|-------|
| [`db`](#db--veritabanları) | veritabanlarını listele, oluştur, düşür, sıfırla |
| [`module`](#module--oca-repoları-ve-modüller) | OCA repolarını, modülleri, testleri ve onayları yönet |
| [`test`](#test--toplu-test-ve-merkezi-senkron) | toplu süitler ve whitelist senkronu |

---

## `db` — veritabanları

```bash
oii db list   [--instance AD] [--json]
oii db create <db> [--instance AD]
oii db drop   <db> [--instance AD] [--yes] [--apply]
oii db reset  <db> [--instance AD] [--yes] [--apply]
```

Tüm komutlar `psql`'i **instance'ın `db` container'ının içinde** çalıştırır —
PostgreSQL host üzerinde hiç açılmaz.

### Kurallar

- Veritabanı adı **her zaman açık bir argümandır** — CLI asla kendisi seçmez.
- Adlar `[a-z][a-z0-9_]{0,62}` kalıbına uymalıdır.
- `postgres`, `template0` ve `template1` korumalıdır: düşürülmeleri reddedilir.
- `create` idempotent ve eklemelidir — `already exists` bildirir.
- `drop` / `reset` plan-öncedir ve yalnızca `--apply --yes` ile çalışır.
- `reset` = düşür + boş olarak yeniden oluştur.

### Örnekler

```bash
oii db list --instance dev
oii db create odoo --instance dev

# dry-run — tam SQL adımlarını gösterir:
oii db drop staging --instance dev
oii db reset staging --instance dev

# çalıştır (yıkıcı):
oii db reset staging --instance dev --apply --yes
```

```console
$ oii db create odoo --instance dev
✔ database 'odoo': created
```

> 💡 Hangi instance? Yalnızca **bir** instance kayıtlıysa `--instance`
> verilmeyebilir. Birden fazlası kayıtlıysa CLI belirtmenizi ister — asla tahmin
> etmez.

---

## `module` — OCA repoları ve modüller

```bash
oii module add | list | search | install | upgrade | upgrade-repos
          | remove | test | approve
```

---

### `module add` — OCA reposu ekle

```bash
oii module add <oca-repo> [--modules m1,m2] [--sparse] [--repo PATH]
                    [--fork KULLANICI] [--instance AD] [--yes] [--apply]
                    [--resolve-deps / --no-resolve-deps]
```

Argüman bir **repodur**, modül değil:

| Kabul edilen biçim | Örnek |
|--------------------|-------|
| kısa ad (sahip `OCA` varsayılır) | `web`, `server-tools` |
| açık sahip | `OCA/server-tools` |

| Seçenek | Anlamı |
|---------|--------|
| `--modules m1,m2` | yalnızca bu modülleri kaydet (sparse kümesine katılırlar) |
| `--sparse` | yalnızca istenen modüllerin blob-filtreli kısmi klonu |
| `--repo PATH` | mevcut yerel checkout'u **olduğu gibi** bağla (asla değiştirilmez; bir dala bağlıysa `19.0` olmalı) |
| `--fork KULLANICI` | fork'unuzdan klonla (`origin` = fork, dal orada doğrulanır) |
| `--instance AD` | hedef instance |
| `--yes` | adopte edilmiş stack'lerde dosya düzenlemesi için gerekli |
| `--resolve-deps` / `--no-resolve-deps` | otomatik repolar-arası sağlamayı aç/kapat (varsayılan: açık) |
| `--apply` | planı çalıştır |

#### Plan aşamasında

1. **Dal doğrulaması** — `origin/19.0` GitHub API'siyle denetlenir. Yanlışlıkla
   modül adı verilirse, sağlayıcı repoyu söyleyen bir ipucu üretilir.
2. **Bağımlılık raporu** — `--modules` ile her modülün `__manifest__.py` dosyası
   GitHub'dan okunur ve tüm bağımlılıklar sınıflandırılır
   (`core` / `same-repo` / `other-repo` / `already available`).
3. **Sağlayıcı planları** — repolar-arası bağımlılıkları sağlayan repolar kendi
   sparse planlarını alır; ayrı `Dependency plan:` bölümleri olarak gösterilir.

#### Uygulama aşamasında

1. önce bağımlılık sağlayıcı planları uygulanır;
2. repo klonlanır/bağlanır (istendiyse sparse);
3. modüller keşfedilir ve istenenlerin varlığı doğrulanır;
4. compose volume satırı + `addons_path` düzenlenir — yedek korumalı, `docker
   compose config` doğrulamalı ve başarısızlıkta otomatik geri almalı;
5. repo manifest'e kaydedilir;
6. tüm yeni mount'ların canlıya geçmesi için `web` servisi **tek kez** yeniden
   oluşturulur (`up -d`).

**Adopte edilmiş stack'lerde** dosyalar yalnızca `--yes` ile düzenlenir, web servisi
CLI tarafından asla yeniden oluşturulmaz ve size kendiniz yapmanız söylenir
(`docker compose up -d web`).

Sonunda sonraki adımlar basılır:

```console
✔ web added
next: `module test <module>` to whitelist it, then `module install <module> --db <db>`
```

#### Örnekler

```bash
# tek modül, sparse, bağımlılık doğrulamalı:
oii module add web --sparse --modules web_responsive

# tüm repo (modüller klondan sonra keşfedilir):
oii module add server-tools

# fork'unuz:
oii module add server-tools --fork kullanici --apply

# mevcut checkout, olduğu gibi bağlanır:
oii module add web --repo ~/dev/web-deploy --apply
```

#### Bağımlılık notları

- Container **kapalıyken** tarama yine çalışır; yalnızca açıklanamayan adlar uyarıyla
  tolere edilir (Odoo kurulum anında yeniden denetler).
- Tüm-repo eklemeleri sağlayıcıları **klondan sonra**, gerçek manifestlerden çözer.
- `--no-resolve-deps` sağlamayı atlar; eksik bir bağımlılık sonraki kurulumu yol
  göstererek durdurur.

---

### `module list` / `module search`

```bash
oii module list [--instance AD] [--db DB] [--json]
oii module search <sorgu> [--limit N]
```

`list`, instance'ın addons yolundaki tüm modülleri gösterir (yerel eklentiler +
bağlı repolar); kaynak repo, commit ve whitelist durumuyla birlikte. `--db` ile o
veritabanındaki `ir_module_module` durumunu da gösterir.

`search`, OCA GitHub organizasyonunda arama yapar:

```console
$ oii module search "responsive"
OCA repos matching 'responsive'
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Repository ┃ Default branch ┃ Description          ┃
...
```

> 💡 GitHub token'ı olmadan keşif zarifçe geriler ama hız sınırlıdır. Sınırları
> yükseltmek için `GITHUB_TOKEN` (veya `github_token_env` ile adlandırdığınız ortam
> değişkeni) tanımlayın.

---

### `module install` / `module upgrade`

```bash
oii module install <ad...> --db DB [--instance AD]
                              [--allow-untested] [--resolve-deps]
oii module upgrade <ad...> --db DB [--instance AD]
                              [--allow-untested] [--resolve-deps]
```

İkisi de web container'ının içinde şunu çalıştırır:

```text
odoo -d <db> -i/-u <ad> --stop-after-init --http-port=8071
```

Alternatif `8071` portu, servis sürecini (`8069`) asla rahatsız etmemelerini
garantiler.

| Seçenek | Anlamı |
|---------|--------|
| `--db DB` | **zorunlu** — hedef veritabanı, her zaman açık |
| `--allow-untested` | whitelist kapısını bilinçli olarak atla |
| `--resolve-deps` | eksik OCA sağlayıcı repolarını otomatik bağla ve bağımlılıkları kuruluma dahil et |
| `--instance AD` | hedef instance |

#### Çalıştırmadan önce uygulanan kapılar

1. **Görünürlük** — modül instance'ın addons yolunda olmalı ya da Odoo **çekirdek**
   modülü olmalı (çalışan container'ın çekirdek eklenti listesi taranarak
   doğrulanır). Görünmüyorsa hata, önce `module add` çalıştırmanızı söyler.
2. **Whitelist** — OCA modülleri test/onay görmüş olmalı; yoksa komut reddeder:
   `not tested yet: <ad> — run 'module test <ad>' first, or pass --allow-untested`.
   Çekirdek modüllere kapı uygulanmaz.
3. **Bağımlılıklar** — aşağıya bakın.

#### Bağımlılık çözümü

- Çekirdek ve hâlihazırda bağlı bağımlılıklar sorunsuz geçer.
- Sağlayıcı reposu **bağlı değilse** → sağlayıcı adıyla reddedilir:
  `missing OCA dependencies need mounting: … — re-run with --resolve-deps`.
  `--resolve-deps` ile sağlayıcı repo bağlanır (önce whitelist kataloğu, sonra
  OCA çapında manifest taraması) ve bağımlılık koşuya dahil edilir.
- Bağlı ama eksik bir **sparse** klon otomatik olarak sparse kümesini genişletir.
- Gerçekten bilinmeyen sağlayıcılar `module search` ipucuyla dürüstçe raporlanır.

#### Koşudan sonra

CLI `ir_module_module` durumlarını doğrular ve `installed` olmayan varsa `1` koduyla
çıkarak suçluları listeler. Başarı şöyle görünür:

```console
$ oii module install web_responsive --db odoo --instance dev
✔ installed: web_responsive
```

Her iki argüman biçimi de çalışır: `module install a b c` ve `module install a,b,c`.

#### Çekirdek modüller

Odoo çekirdek modülleri (`sale`, `account`, `stock`, …) kabul edilir; çalışan
container'a karşı doğrulanır ve asla kapıdan geçmez. Container kapalıysa doğrulama
imkânsızdır ve komut bunu söyler.

---

### `module remove`

```bash
oii module remove <repo> [--db DB] [--purge-repo] [--instance AD]
                         [--yes] [--apply]
```

`module add`'in tersidir:

| Bayrak | Etkisi |
|--------|--------|
| *(yok)* | mount'u kaldırır, `addons_path`'i düzenler, repoyu unutur |
| `--db DB` | ayrıca o veritabanında reponun modüllerini `uninstalled` durumuna çeker |
| `--purge-repo` | klonu da siler — yalnızca CLI'nin sahip olduğu klonları (`repos/` veya `repo_root/` altındakiler) |
| `--yes` | adopte edilmiş stack'lerde dosya düzenlemesi için gerekli |
| `--apply` | planı çalıştır |

> ⚠️ Modül durumlarını sıfırlamak **gerçek bir kaldırma değildir**: veri tabloları
> kalır. Gerçek kaldırma Odoo içinde yapılır; `module remove` yalnızca kurulum
> durumunu temizler.

---

### `module test` — tek modülü kanıtla

```bash
oii module test <ad> [--instance AD] [--keep-db] [--with m1,m2]
```

Sıra:

1. önceki `oitest_<ad>` geçici veritabanını düşürür;
2. modülü bu yepyeni geçici DB'de web container içinde kurar;
3. testlerini çalıştırır (`--test-enable --test-tags=/<ad>`);
4. tam logu yakalar ve hataları sınıflandırır;
5. PASS/FAIL basar;
6. PASS ise modülü whitelist'e kaydeder;
7. geçici DB'yi düşürür (`--keep-db` verilmedikçe).

| Seçenek | Anlamı |
|---------|--------|
| `--keep-db` | hata ayıklama için geçici veritabanını sakla |
| `--with m1,m2` | ek modülleri **önce ayrı bir hazırlık aşamasında** kur |

#### `--with`: iki aşamalı test

Bazı modüller ancak başka modüller kurulduktan sonra var olan veriye ihtiyaç duyar —
özellikle hesap modülleri, bir hesap planı ve günlükler ister. Odoo 19, hesap
şablonlarını modül kurulum döngüsünden **sonra** uygular; bu yüzden tek birleşik
`-i` koşusu, günlükler henüz yokken test eder (yanlış FAIL'ler).

`--with`, ek modülleri önce ayrı bir `--stop-after-init` aşamasında kurar, sonra
hedef modülü kurup test eder:

```bash
oii module test partner_statement --with sale
```

Çalıştırılan testler yine `/<ad>` ile sınırlıdır. Bozuk bir hazırlık aşaması, loguyla
birlikte FAIL olarak raporlanır.

#### Sonucu okumak

```console
$ oii module test web_responsive
✔ PASS web_responsive on scratch db 'oitest_web_responsive' (84s, exit 0)
log: /home/siz/odoo-instances/dev/logs/test-web_responsive-20261007-141530.log
✔ web_responsive recorded as tested/installable (whitelist: ~/.config/odoo-installer/tested.toml)
```

Logdan sınıflandırılan hata türleri: `test_failure`, `import_error`,
`not_installable`, `addons_path`, `manifest`, `traceback`, `exit_code`.

Başarısızlıkta çıkış kodu **3**.

Loglar:

- oluşturulan instance'lar → `<stack>/logs/`
- adopte edilen instance'lar → `~/.local/state/odoo-installer/logs/<ad>/`

---

### `module approve` — zaten kanıtlanmış modüllere güven

```bash
oii module approve <ad...> --db DB [--instance AD]
```

Kalitesi canlı bir stack üzerinde zaten kanıtlanmış modüller için (örneğin üretimde
onaylanmış olanlar):

1. verilen `--db` içinde `installed` durumunda olmayan her şeyi reddeder;
2. whitelist kayıtlarını düşer — test logu gerekmez.

```bash
oii module approve attribute_set pim --db odoo --instance prod
```

---

### `module upgrade-repos` — bağlı repoları tazele

```bash
oii module upgrade-repos [--instance AD] [--apply]
```

Bağlı her repo için:

1. `fetch` + `origin/<dal>` checkout'u (`19.0`'ın ucu);
2. yeni commit'i manifest'e kaydeder;
3. eski ve yeni commit arasında hangi bağlı modüllerin değiştiğini raporlar;
4. bir şey hareket ettiyse web servisini yeniden oluşturur.

**Odoo içindeki** yükseltme açık kalır — basılan komutu kendiniz çalıştırırsınız:

```bash
oii module upgrade <değişen modüller> --db odoo
```

---

## `test` — toplu test ve merkezi senkron

```bash
oii test suite [--instance AD] [--only REPO] [--modules m1,m2]
               [--output rapor.md] [--output rapor.json] [--keep-db]
oii test pull [--apply]
```

### `test suite`

Instance'ın addons yolundaki her modülü **sırayla** test eder (aynı anda tek geçici
DB).

| Seçenek | Anlamı |
|---------|--------|
| `--only REPO` | tek kaynak repoyla sınırla — `web` ve `OCA/web` eşleşir |
| `--modules m1,m2` | her şey yerine açık modül listesi |
| `--output PATH` | rapor yazar; tekrarlanabilir; `.md` ve `.json` desteklenir |
| `--keep-db` | her modülün geçici veritabanını sakla |

- her modül yeni bir `oitest_<modül>` veritabanı alır, sonra düşürülür;
- her PASS whitelist'i besler;
- sonunda özet tablo basılır;
- herhangi biri başarısızsa çıkış kodu **3**.

```console
$ oii test suite --only web --output rapor.md --output rapor.json
[1/3] web_environment_ribbon (OCA/web)
✔ PASS web_environment_ribbon on scratch db 'oitest_web_environment_ribbon' (61s, exit 0)
...
3 modules: 3 passed, 0 failed
✔ report written: rapor.md
✔ report written: rapor.json
```

Markdown raporu özet tabloyu ve loglarla birlikte bir `## Failures` bölümünü içerir;
JSON raporu makine-okunur sonuçları taşır
(`instance`, `generated_at`, `total`, `passed`, `failed`, `results[]`).

### `test pull` — merkezi whitelist senkronu

```bash
oii test pull             # dry-run
oii test pull --apply     # çalıştır
```

`tested_repo_url` ayarlı olmalıdır. Yaptıkları:

1. whitelist reposunun yerel önbellek klonunu tazeler
   (`~/.cache/odoo-installer/tested-repo/`);
2. içindeki `tested.toml` dosyasını etkin whitelist ile **birleştirir** —
   modül adına göre birleşim; yeni `tested_at` kazanır.

```console
$ oii test pull --apply
✔ whitelist synced from https://github.com/org/odoo-installer-tested.git: +42 added, 3 updated (97 approved modules)
```

### Whitelist repo biçimi

Kökünde `tested.toml` bulunan küçük bir git reposu yeterlidir:

```toml
[modules.web_responsive]
name = "web_responsive"
repo = "OCA/web"
branch = "19.0"
commit = "abcdef1234567890"
tested_at = "2026-09-12T14:31:05Z"
db = "oitest_web_responsive"
log_path = ""
deps = ["web"]
```

`module test` / `module approve` yerelde tam bu biçimde kayıt üretir; onayları
dağıtmak için dosyayı merkezi repoya itin.

---

## İlgili sayfalar

- Whitelist ve çözücünün arkasındaki kavramlar:
  [3. Temel kavramlar §4–5](03-kavramlar.md)
- Uçtan uca tarifler: [8. İş akışları](08-is-akislari.md)
- Hatalar ve çözümleri: [9. Güvenlik ve sorun giderme](09-guvenlik-ve-sorun-giderme.md)

---

[⬅️ Önceki: Host ve instance komutları](04-komutlar-host-ve-instance.md) · [Dizin](README.md) · [Sonraki: Yedekleme ve apply ➡️](06-komutlar-yedekleme-ve-apply.md)
