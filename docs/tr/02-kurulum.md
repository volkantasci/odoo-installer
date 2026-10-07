# 2. Kurulum

**🇹🇷 Türkçe** · [🇬🇧 English](../en/02-installation.md)

---

## Gereksinimler

| Bileşen | Asgari | Kim denetler |
|---------|--------|--------------|
| **Python** | 3.11+ | kurulumda `pip`/`uv` |
| **İşletim sistemi** | Linux; paket kurulumu pacman ve apt destekler | `oii doctor` |
| **Container runtime** | Podman **veya** Docker, çalışır ve erişilebilir | `oii doctor` (değilse FAIL) |
| **Compose sağlayıcısı** | `docker-compose` / `docker compose` / `podman compose` | `oii doctor` (değilse FAIL) |
| **Git** | güncel herhangi bir sürüm | `oii doctor` (değilse FAIL) |
| **Disk alanı** | stack başına ~7 GB önerilir; 2 GiB altı FAIL | `oii doctor` |
| **GitHub erişimi** | yalnızca OCA keşfi / dal doğrulaması için | `oii doctor` (erişilemezse WARN) |

> 💡 Runtime, `container_runtime` ayar anahtarıyla seçilir (`auto`, önce rootless
> Podman'ı dener, sonra Docker'ı). Dilediğiniz zaman değiştirebilirsiniz —
> bkz. [Yapılandırma](07-yapilandirma.md).

---

## CLI'yi kurun

### PyPI'dan (önerilen)

```bash
pip install odoo-installer
```

### İzole, günlük kullanım kurulumu

Aracı geliştirme virtualenv'lerinizden uzak tutar:

```bash
pipx install odoo-installer
# veya
uv tool install odoo-installer
```

### Bir checkout'tan

```bash
git clone https://github.com/volkantasci/odoo-installer.git
cd odoo-installer
pip install .
```

### Geliştirme için

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
pre-commit install
```

Tam geliştirici akışı için [`DEVELOPMENT.md`](../../DEVELOPMENT.md) dosyasına bakın.

---

## Kurulumu doğrulayın

CLI **üç isme** yanıt verir — bu kılavuzdaki tüm örnekler `oii` kullanır:

| Çağrı | Not |
|-------|-----|
| `oii` | kısa takma ad |
| `odoo-installer` | tam ad |
| `python -m odoo_installer` | console script gerekmez (kısıtlı ortamlar için) |

```bash
oii version        # ör. 0.8.1
oii --version      # aynısı, global bayrakla
oii --help         # Typer tarafından basılan tüm komut grupları
```

Her grubun kendi yardımı da vardır:

```bash
oii instance --help
oii module --help
oii module install --help
```

---

## Kabuk tamamlamayı etkinleştirin

Typer; bash, zsh ve fish için tamamlama sağlar:

```bash
oii --install-completion     # mevcut kabuğa kurar
oii --show-completion        # kurmak yerine betiği yazdırır
```

Ardından kabuğunuzu yeniden başlatın.

---

## Güncelleme

```bash
pip install -U odoo-installer
# veya
pipx upgrade odoo-installer
# veya
uv tool upgrade odoo-installer
```

> 💡 **Sürüm çıktıktan hemen sonra "already satisfied" mi dedi?**
>
> Paket indeksi önbelleği PyPI'ın birkaç dakika gerisinde kalabilir. Tek çalıştırma
> için sürümü sabitleyin:
>
> ```bash
> pip install "odoo-installer==X.Y.Z"
> ```

Güncellemeler yapılandırmanıza, registry'ye ve whitelist'e **dokunmaz** — onlar
`~/.config/odoo-installer/` altında yaşar.

---

## Host'u hazırlayın

CLI'yi kurmak, makineyi henüz stack çalıştırabilir hale getirmez. İki komutla
halledin:

```bash
oii doctor            # 1. teşhis: ne eksik?
oii install --apply   # 2. düzeltilebilir ön gereksinimleri kur
oii doctor            # 3. her şey yeşil mi doğrula
```

### `oii install` tam olarak ne yapar?

| Eksik parça | Kurulan/etkinleştirilen |
|-------------|-------------------------|
| Container runtime | pacman/apt ile `podman` (tercih) veya `docker` |
| Docker servisi | `systemctl enable --now docker` |
| Compose sağlayıcısı | `docker-compose` (Arch) / `docker-compose-plugin` (Debian/Ubuntu) |
| Git | `git` paketi |
| Podman socket | `podman.socket` kullanıcı servisi — compose sağlayıcısı buradan bağlanır |
| Açılışta kalıcılık | `loginctl enable-linger` + `podman-restart.service` |

Notlar:

- Odoo'yu **asla kurmaz** — Odoo, oluşturduğunuz stack'lerde yaşar.
- Plan idempotenttir: hazır bir host
  `✔ all host prerequisites already satisfied` bildirir.
- `--apply` olmadan dry-run'dır.
- Otomatik algılama pacman ve apt destekler. Diğer dağıtımlarda paketleri elle
  kurup `oii doctor` komutunu tekrar çalıştırın.

### Rootful Docker mu, rootless Podman mı?

| | Podman (rootless) | Docker |
|---|---|---|
| İzinler | grup gerekmez — kullanıcınız olarak çalışır | kullanıcı `docker` grubunda olmalı |
| Socket | compose için `podman.socket` kullanıcı servisi gerekir | servis üzerinden `/var/run/docker.sock` |
| Açılış | linger + `podman-restart.service` (eksikse doctor WARN) | `docker` sistem servisi |
| Uzak | `CONTAINER_HOST` geçirilir | `DOCKER_HOST` geçirilir |

`oii doctor` runtime'a duyarlıdır: Podman'da socket, linger ve
`podman-restart.service` denetler; Docker'da grup üyeliğini — her birine tam çözüm
önerisiyle birlikte.

---

## Kaldırma

```bash
pip uninstall odoo-installer     # veya: pipx uninstall odoo-installer
```

CLI'yi kaldırmak başka hiçbir şeyi silmez. Geride kalanlar (tamamen temiz bir sayfa
istiyorsanız elle silin):

| Yol | İçerik |
|-----|--------|
| `~/odoo-instances/` | stack'leriniz (container'lar, veritabanları, filestore, yedekler) |
| `~/.config/odoo-installer/` | yapılandırma, registry, whitelist |
| `~/.local/state/odoo-installer/` | adopte edilmiş stack'lerin test logları |
| `~/.cache/odoo-installer/` | önbellekteki whitelist repo klonu |
| `~/odoo-repos/` | adopte edilmiş stack'lerin OCA klonları |

> ⚠️ Stack dizinini elle silmek container'ları durdurmaz. Bunun yerine
> `oii instance remove <ad> --apply --yes` kullanın.

---

## Sonraki adımlar

- [3. Temel kavramlar](03-kavramlar.md) — araç nasıl düşünür.
- [8. İş akışları](08-is-akislari.md) — ilk uçtan uca senaryo.

---

[⬅️ Önceki: Genel bakış](01-genel-bakis.md) · [Dizin](README.md) · [Sonraki: Temel kavramlar ➡️](03-kavramlar.md)
