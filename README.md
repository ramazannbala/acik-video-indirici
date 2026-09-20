# Açık Video İndirici v7.4.1

> **Tek proje belgesi:** Bu dosya; proje özeti, kurulum, kullanım, mimari, geçmiş düzeltmeler, sorun giderme, test/devir notları ve projeyi yeni bir Arena.ai Agent Mode sohbetinde sürdürme adımlarını bir araya getirir.

## 1. Projenin amacı ve güncel durum

Açık Video İndirici, Windows 11 için yerel çalışan iki parçalı bir medya indirme projesidir:

1. **Chrome/Edge Manifest V3 eklentisi**, sayfadaki gerçekten oynayan `<video>` öğesini bulur, sağ üstüne **İndir** düğmesi ekler ve ilgili medya/sayfa bilgisini yerel uygulamaya yollar.
2. **Python masaüstü uygulaması**, `customtkinter`, `yt-dlp`, FFmpeg ve FFprobe ile analiz, kalite seçimi, kuyruk, duraklatma/devam, ayrı ses-altyazı indirme ve MP4/MKV birleştirme işlerini yönetir.

Güncel kaynak ve paket sürümü **7.4.1**'dir. v7.4 ile Format Seçimi sayfasındaki bakım araçlarına **FFmpeg Güncelle** düğmesi eklenmiştir. Düğme Windows Package Manager üzerinden `Gyan.FFmpeg` paketini yükseltir; FFmpeg yoksa kurar, FFprobe'yu birlikte günceller ve yeni sürümü uygulamada yeniden algılar.

**v7.4.1 kurulum düzeltmesi:** `.venv\Scripts\python.exe` bulunduğu halde `pip` modülü eksikse kurucu artık ortamı hazır kabul etmez. Önce `ensurepip` ile onarır; onarım başarısızsa bozuk `.venv` klasörünü temizleyip yeniden oluşturur ve pip'i tekrar doğrular. Python kurulumunda `ensurepip` gerçekten yoksa genel `No module named pip` yerine uygulanabilir Türkçe onarım adımları gösterilir.

**v7.4.1 kurulum paketi (setup.exe):** Aynı sürümle **PyInstaller + Inno Setup** tabanlı Windows kurulum paketi desteği eklenmiştir: `app.py` tek EXE'ye dondurulur, Inno Setup onu profesyonel bir kurulum programı olarak paketler; kullanıcıda Python gerekmez ve dağıtım klasöründe `extension/` klasörü setup'ın yanında taşınır. FFmpeg ve Deno bilinçli olarak pakete konmaz; uygulama içi **FFmpeg Güncelle** ve **YouTube / Deno** düğmeleriyle WinGet üzerinden kurulur, böylece setup küçük kalır.

Sürüm işaretleri şuralarda birlikte tutulur:

- `python_app/app.py` → `APP_VERSION = "7.4.1"`
- `extension/manifest.json` → `"version": "7.4.1"`
- Paket adı → `Acik-Video-Indirici-Windows11-v7.4.1.zip`
- `installer/AcikVideoIndirici.iss` → `MyAppVersion "7.4.1"` ve `Acik-Video-Indirici-Kurulum-7.4.1.exe` çıktı adı (dördü birlikte artırılır)

Bu proje Aloha Browser ile bağlantılı değildir; Aloha'nın uygulama dosyalarını, sayacını veya limitlerini değiştirmez. Yalnız benzer bir kullanıcı akışından esinlenmiş bağımsız bir araçtır.

### Gerçekçi kapsam ve hukuki sınır

- Açık, şifresiz veya kullanıcının indirmeye yetkili olduğu medya hedeflenir.
- MP4, WebM, MOV, TS/M2TS, HLS/M3U8, DASH/MPD, YouTube, X/Twitter ve `yt-dlp` tarafından desteklenen birçok açık kaynakla çalışabilir.
- **“Her site ve her format kesin çalışır” garantisi yoktur.** Site değişiklikleri, kısa ömürlü imzalı URL'ler, oturum, oran sınırı, canlı yayın ve oynatıcı mimarisi sonucu etkiler.
- DRM/EME/Widevine/CENC çözme, anahtar çıkarma veya erişim kontrolünü aşma kapsam dışıdır. Netflix, Disney+, Prime Video gibi DRM kullanan hizmetler için DRM atlatma eklenmemelidir.
- Yalnızca indirme ve saklama hakkınız olan içeriklerde, sitenin koşullarına ve yürürlükteki mevzuata uygun kullanın.

## 2. Proje dizini

```text
aloha-video-downloader/
├─ README.md                                  # Tek proje/devir belgesi
├─ TEST-RAPORU-v7.4.1.txt                     # Son doğrulama özeti
├─ Acik-Video-Indirici-Windows11-v7.4.1.zip   # Dağıtım ve yeni sohbete aktarım paketi
├─ KUR_VE_BASLAT.bat                          # Tek tık kurulum/başlatma (kaynak akışı)
├─ YOUTUBE-DESTEGI-KUR.bat                    # Deno kurulumu
├─ python_app/
│  ├─ app.py                                  # GUI, köprü, analiz, kuyruk, indirme, mux
│  ├─ requirements.txt
│  ├─ install.bat
│  ├─ run.bat
│  └─ TANI.bat
├─ extension/
│  ├─ manifest.json
│  ├─ background.js                           # webRequest, oturum kayıtları ve çerez bağlamı
│  ├─ page-hook.js                            # MAIN-world Fetch/XHR gözlemi ve manifest gövdesi
│  ├─ content.js                              # Sayfa/eklenti dünyaları arasında güvenli aktarım
│  ├─ overlay.js                              # Video eşleştirme ve video üstü İndir düğmesi
│  ├─ popup.html
│  ├─ popup.js
│  └─ popup.css
└─ installer/
   ├─ app.spec                                # PyInstaller: app.py -> tek EXE (onefile)
   ├─ AcikVideoIndirici.iss                   # Inno Setup kurulum betiği (TR/EN)
   ├─ KURULUM-OLUSTUR.bat                     # Tek tıkla setup derleme (yalnız Windows)
   ├─ assets/                                 # app.ico, wizard-left.bmp, wizard-small.bmp
   ├─ tools/make_assets.py                    # Görselleri yeniden üretme betiği (Pillow)
   ├─ .venv/ , build/ , dist/                 # Derleme ara çıktıları (git'e/pakete girmez)
   └─ Output/                                 # setup.exe + extension/ dağıtım klasörü (git'e girmez)
```

Sanal ortam, bağımlılık önbellekleri ve çalışma zamanında oluşan loglar dağıtım paketine eklenmemelidir.

## 3. Gereksinimler

- Windows 11, tercihen 64 bit
- Python **3.10+**; Python 3.11 veya daha yenisi önerilir
- FFmpeg ve FFprobe
- Güncel YouTube/EJS desteği için Deno **2.3+**
- Chrome veya Microsoft Edge **111+**
- İnternet bağlantısı

Python bağımlılıkları `python_app/requirements.txt` içindedir:

```text
customtkinter==5.2.2
tkinterdnd2>=0.4.2
yt-dlp[default,curl-cffi]
```

`yt-dlp[default,curl-cffi]`, güncel yt-dlp bileşenleri, TLS impersonation desteği ve `yt-dlp-ejs` gereksinimini sağlar.

## 4. Windows 11 kurulumu

### 4.1 En kolay yöntem

1. `Acik-Video-Indirici-Windows11-v7.4.1.zip` dosyasına sağ tıklayıp **Tümünü Ayıkla** seçeneğini kullanın.
2. Betikleri ZIP önizlemesinin içinden çalıştırmayın.
3. Ayıklanan ana klasörde `KUR_VE_BASLAT.bat` dosyasına çift tıklayın.
4. Betik uygun Python'u bulur, `python_app/.venv` oluşturur, bağımlılıkları kurar ve uygulamayı başlatır.
5. Sonraki açılışlarda yine aynı dosya veya `python_app/run.bat` kullanılabilir.

Kurulum hataları `python_app/kurulum-log.txt`, uygulama açılış hataları `python_app/uygulama-hata.log` dosyasına yazılır. Ek tanı için `python_app/TANI.bat` çalıştırılabilir; `tani-sonucu.txt` oluşur.

v7.4.1 kurucusu yarım kalmış sanal ortamları otomatik denetler:

- `.venv` Python'u açılmıyorsa ortamı yeniden oluşturur.
- `python.exe -m pip --version` başarısızsa `python.exe -m ensurepip --upgrade --default-pip` çalıştırır.
- pip hâlâ yoksa `.venv` klasörünü silip temiz ortam oluşturur.
- Bozuk klasör kilitli olduğu için silinemezse bunu açıkça bildirir.
- Python kurulumundaki `ensurepip` bileşeni de eksikse Python **Modify/Repair** yönergesini gösterir.

Eski bir pakette `No module named pip` hatasını hemen gidermek için uygulamayı kapatıp yalnız `python_app\.venv` klasörünü silin ve `KUR_VE_BASLAT.bat` dosyasını tekrar çalıştırın. Proje kaynaklarını veya indirilmiş videoları silmeyin.

### 4.2 Python kurulumu

Python yüklü değilse güncel Windows Python 3 sürümünü kurun ve yükleyicide **Add python.exe to PATH** seçeneğini işaretleyin. Doğrulama:

```powershell
py -3 --version
```

### 4.3 FFmpeg kurulumu

```powershell
winget install --id Gyan.FFmpeg -e
ffmpeg -version
ffprobe -version
```

Komutlar bulunmazsa terminali ve uygulamayı kapatıp yeniden açın. Alternatif olarak `ffmpeg.exe` ve `ffprobe.exe` dosyaları `python_app` klasörüne konabilir.

v7.4'ten itibaren uygulama içindeki **Format Seçimi → FFmpeg Güncelle** düğmesi de kullanılabilir. Bu düğme:

1. Etkin indirme veya birleştirme işi varsa dosya kilitlenmesini önlemek için işlemi başlatmaz.
2. Mevcut FFmpeg sürümünü gösterip kullanıcı onayı ister.
3. WinGet yönetimli kurulum varsa `winget upgrade --id Gyan.FFmpeg -e` çalıştırır.
4. FFmpeg yoksa veya mevcut kopya WinGet tarafından yönetilmiyorsa `winget install --id Gyan.FFmpeg -e` fallback'ini kullanır.
5. Yeni WinGet yolunu çalışan uygulamada yeniden tarar ve sürümü üst bileşen bilgisinde gösterir.
6. WinGet yolu bu oturumda görünmezse uygulamanın yeniden başlatılmasını ister.

### 4.4 Deno kurulumu

```powershell
winget install --id DenoLand.Deno -e
deno --version
```

Alternatif olarak `YOUTUBE-DESTEGI-KUR.bat` çalıştırılabilir. Uygulamayı yeniden açınca bileşen bilgisinde `Deno ✓` görülmelidir.

### 4.5 Elle Python kurulumu

```powershell
cd python_app
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

### 4.6 Chrome/Edge eklentisini yükleme veya güncelleme

1. Chrome'da `chrome://extensions`, Edge'de `edge://extensions` açın.
2. **Geliştirici modu**nu etkinleştirin.
3. Eski Açık Video Yakala sürümünü **tamamen kaldırın**.
4. **Paketlenmemiş öğe yükle** ile bu paketteki `extension` klasörünü seçin.
5. İstenen izinleri kabul edin ve eklentiyi araç çubuğuna sabitleyin.
6. Önceden açık video sekmelerini tamamen kapatın; sayfayı yeni sekmede yeniden açın.

Yalnız eklentinin **Yenile** simgesine basmak, açık sekmedeki eski content script'i her zaman değiştirmez. Özellikle v7.3 uzantısız HLS düzeltmesini test ederken sekmeyi kapatıp yeniden açmak zorunludur.

### 4.7 İlk açılış kontrolü

Uygulamada şunlar görünmelidir:

- `yt-dlp <sürüm>`
- `FFmpeg <sürüm> ✓` veya en az `FFmpeg ✓`
- YouTube için `Deno ✓`
- TLS/curl-cffi için `TLS ✓`
- `Tarayıcı köprüsü açık: 127.0.0.1:17852`

### 4.8 Kurulum paketi (setup.exe) ile kurulum

v7.4.1'den itibaren kaynak akışına alternatif olarak tek dosyalık kurulum paketi vardır:

1. `installer/Output/` klasöründeki `Acik-Video-Indirici-Kurulum-7.4.1.exe` dosyasını çalıştırın. Paket imzasız olduğu için Windows SmartScreen uyarısı gösterebilir; **Daha fazla bilgi → Yine de çalıştır** ile devam edin. (Uyarının nedeni kod imzası olmamasıdır; paket yalnız bu repo kaynaklarından derlenir.)
2. Kurulum, uygulamayı ve `extension` klasörünü birlikte `{kurulum}\` altına koyar; Başlat menüsüne uygulama ve **Tarayıcı Eklentisi Klasörü** kısayolları eklenir.
3. Chrome/Edge'de §4.6'daki gibi **Paketlenmemiş öğe yükle** ile kurulum klasöründeki `extension` klasörünü seçin.
4. Uygulamada Python aranmaz; köprü yine `127.0.0.1:17852` üzerinde açılır.
5. FFmpeg ve Deno kurulumda gelmez: ilk açılışta Format Seçimi sayfasındaki **FFmpeg Güncelle** ve **YouTube / Deno** düğmelerini kullanın (WinGet ile kurulur). TLS/curl-cffi EXE ile birlikte gelir.
6. Ayarlar ve geçmiş `%APPDATA%\AcikVideoIndirici` altında kalır; program kaldırma bunları silmez.

Dağıtım klasörü (`installer/Output/`) hem `setup.exe` hem `extension/` klasörünü içerir; `extension`'ı ayrıca elle kopyalamaya gerek yoktur.

## 5. Temel kullanım

### 5.1 Video üstündeki İndir düğmesi

1. Python uygulamasını açık bırakın.
2. Tarayıcıda videoyu oynatın.
3. Görünür ve en az yaklaşık 260×145 piksel olan gerçek video öğesinin sağ üstünde **↓ İndir** düğmesi görünür.
4. Düğmeye basınca o video ile eşleştirilmiş HLS/DASH/doğrudan medya veya gerektiğinde sayfa URL'si yerel uygulamaya gönderilir.
5. Analiz tamamlanınca harici ve küçültülebilir format penceresinde dosya adı, kalite, ayrıntılı format ve çıktı düzeni seçilir.
6. **Kuyruğa Ekle** ile iş indirme yöneticisine aktarılır.

Bir sayfada birden fazla video, reklam veya iframe varsa eşleştirme için `videoKey`, frame, görünürlük, oynatma zamanı, `currentSrc`, sayfa URL'si ve yakın zamanda yakalanan ağ kayıtları birlikte kullanılır.

### 5.2 Eklenti popup'ı

Popup listesinde genel olarak şu türler görünür:

- **HLS:** M3U8 master/video manifesti
- **DASH:** MPD manifesti
- **Dosya:** MP4/WebM/MOV/TS gibi doğrudan medya
- **Blob:** Tarayıcı içi nesne URL'si; tek başına indirilebilir dosya değildir

Aynı videoya ait çok kayıt varsa önce master HLS veya DASH manifestini deneyin. Yalnız `blob:` görünüyorsa videoyu oynatın, ileri/geri sarın veya kalite değiştirip listeyi yenileyin. Gerçek ağ isteği ayrıca yakalanmalıdır.

### 5.3 Uygulamaya URL yapıştırma

1. **Format Seçimi** ekranına geçin.
2. Video sayfası veya medya URL'sini yapıştırın.
3. Çerez seçimini önce **Yok** bırakın.
4. **Analiz Et** düğmesine basın.
5. Sayfadan türetilen çıktı adını kontrol edip gerekiyorsa düzenleyin.
6. Kalite veya ayrıntılı format satırı seçin.
7. Çıktı düzenini belirleyip kuyruğa ekleyin.

Çerez yalnız gerçekten oturum gerektiren, erişmeye yetkili olduğunuz kaynakta kullanılmalıdır. Netscape biçimli `cookies.txt` dosyası oturum anahtarı gibi değerlidir; paylaşmayın.

## 6. Kullanıcı arayüzü

Ana pencere IDM'nin genel iş akışından esinlenmiş fakat özgün bir arayüzdür:

- Yerel Tk menü çubuğu: **Görevler, Ekranlar, Görünüm, Yardım**
- Büyük araç çubuğu
- Tam yükseklikte, kaydırılabilir kategori paneli
- Geniş ve ayrıntılı indirme tablosu
- **İndirmeler, Format Seçimi, Birleştirici** ekranları
- **Açık, Koyu, Sistem** tema seçenekleri

Kategori filtreleri:

- Tüm İndirmeler
- Video
- Ses
- Altyazı
- Birleştirme
- İndiriliyor
- Kuyrukta
- Duraklatılan
- Tamamlanan
- Hata / İptal

İndirme tablosu başlıca şu sütunları içerir:

- Dosya adı
- Tür
- Boyut
- Durum
- İlerleme
- Hız
- Kalan
- Kalite
- Eklendi

Araç çubuğu ile yeni iş, başlat/devam, duraklat, iptal, yeniden adlandır, kayıt/dosya silme ve klasör açma yapılabilir. Aktif ana video satırına çift tıklamak küçük takip penceresini yeniden açar.

Format Seçimi sayfasının alt işlem satırında yan yana üç bakım düğmesi bulunur:

- **yt-dlp Güncelle** — etkin sanal ortamdaki `yt-dlp[default,curl-cffi]` paketini yükseltir.
- **YouTube / Deno** — Deno bulunmuyorsa WinGet ile kurar.
- **FFmpeg Güncelle** — `Gyan.FFmpeg` paketini WinGet ile günceller veya eksikse kurar; FFmpeg ve FFprobe birlikte gelir.

Bakım işlemleri arka plan thread'inde çalışır; arayüz donmaz. FFmpeg güncellemesi sırasında aktif indirme/mux işi bulunmasına izin verilmez. İşlem bittiğinde FFmpeg yolu ve sürümü yeniden taranır.

### Harici format penceresi

- Başlangıç boyutu: yaklaşık 1120×740
- Minimum boyut: yaklaşık 880×580
- Küçültülebilir ve yeniden boyutlandırılabilir
- 18 satırlık geniş format tablosu
- URL, kategori, klasör, düzenlenebilir dosya adı, kalite ve çıktı düzeni aynı pencerededir

### Mini ilerleme penceresi

- URL
- Durum
- İndirilen/toplam veri
- Hız
- Kalan süre
- Fragment sıra/toplam
- İlerleme çubuğu
- Başlat/devam, duraklat ve iptal

Harici HLS ses child işlerinin yüzdesi de ana listedeki ilgili ses satırında gösterilir.

## 7. Desteklenen medya ve yakalama katmanları

Eklenti medya adaylarını birlikte çalışan katmanlardan toplar:

1. `chrome.webRequest` ile URL, istek türü ve yanıt başlıkları
2. DOM içindeki `<video>`, `<audio>`, `<source>` ve `<track>` öğeleri
3. Resource Timing / performance kayıtları
4. MAIN-world `fetch` ve `XMLHttpRequest` kancaları
5. Sınırlı yanıt metni imza incelemesi

Tespit edilen başlıca türler:

- MP4, WebM, MOV, MKV ve benzeri doğrudan dosyalar
- HLS/M3U8
- DASH/MPD
- Gerçek tarayıcı `media` isteği olan bağımsız TS/M2TS
- VTT, SRT, ASS, SSA, TTML ve uzantısız altyazı gövdeleri
- HLS `TYPE=AUDIO` ve `TYPE=SUBTITLES`
- M4A, AAC, MP3, Opus ve ayrı ses kaynakları

HLS oynatıcının XHR ile istediği yüzlerce `.ts` fragment ayrı video olarak listelenmez. Bunları HLS indiricisi birleştirir.

Audio sınıflandırmasında `audio`, `mp4a`, `aac`, `m4a`, `ac-3`, `ec-3`, `eac3` ve `opus` gibi yol/kodek işaretleri kullanılır. Böylece özellikle X/Twitter'daki `/mp4a/32000/*.m3u8` audio rendition'ı ana video sanılmaz.

## 8. Mimari ve veri akışı

```text
Web sayfası
 ├─ webRequest / response headers ──────────────┐
 ├─ video/source/track/performance ─────────────┼─> medya adayları + videoKey/frame eşleştirmesi
 └─ MAIN-world Fetch/XHR + manifest imzası ─────┘
                                                 │
Gerçek <video> üstündeki İndir düğmesi / popup ──┘
                                                 │
                          POST http://127.0.0.1:17852/api/open
                          X-Aloha-Bridge: 1
                                                 │
                                                 v
                              Python customtkinter uygulaması
                              ├─ yt-dlp analizi ve kalite seçimi
                              ├─ 1–20 ortak iş kuyruğu
                              ├─ video child/parent işleri
                              ├─ ayrı audio child işleri
                              ├─ ayrı subtitle child işleri
                              └─ manuel/otomatik mux işleri
                                                 │
                                    FFmpeg + FFprobe + Deno
                                                 │
                             video + korunan MKA/SRT yan dosyaları
                             ve isteğe bağlı final MKV/MP4
```

### Yerel köprü sözleşmesi

- Adres: `127.0.0.1:17852`
- Sağlık: `GET /health`
- Aktarım: `POST /api/open`
- Zorunlu başlık: `X-Aloha-Bridge: 1`
- İstek gövdesi üst sınırı: **2 MiB**
- Yalnız boş origin veya `chrome-extension://` / `edge-extension://` origin kabul edilir.

Payload ihtiyaca göre şu bilgileri taşır:

- `url`, `pageUrl`, `title`, `mediaType`, `captureSources`
- `userAgent`, `referer`, `origin`
- `manifestKind`, `manifestText`
- `externalAudioTracks`, `externalSubtitles`
- `youtubeCookies`, `siteCookies`, `mediaCookies`
- `mediaCookieHeader`, `visitorData`, `primaryLanguage`

Köprü `manifestText` için en fazla **1.000.000 karakter** kabul eder ve yalnız `#EXTM3U`, XML veya `<MPD>` imzasıyla başlayan metni kullanır.

## 9. İş kuyruğu, kalıcılık ve durumlar

`DownloadJob` türleri:

- `video`
- `audio`
- `subtitle`
- `mux`

Tüm türler **aynı global eşzamanlılık havuzuna** girer. Limit 1–20 arasındadır. `concurrency_schema = 2`, eski ayardan ilk v6+ geçişinde varsayılanı bir kez **20** yapar. Bu davranış korunmalıdır.

Başlıca durumlar:

- `queued`
- `downloading`
- `processing`
- `finalizing`
- `pausing`
- `cancelling`
- `paused`
- `completed`
- `cancelled`
- `failed`
- `interrupted`

Ayarlar ve geçmiş Windows'ta şurada tutulur:

```text
%APPDATA%\AcikVideoIndirici\settings.json
%APPDATA%\AcikVideoIndirici\downloads.json
%APPDATA%\AcikVideoIndirici\manifests\*.m3u8
```

En fazla son 500 terminal/geçmiş kaydı saklanır. Uygulama açıkken yarım kalan etkin durumlar yeniden açılışta `interrupted` olur. Cookie değerleri geçmişe yazılmaz. `resume_headers` içinde yalnız gerekli `Referer`, `Origin` ve `User-Agent` korunabilir.

## 10. Ayrı ses ve altyazı paketleri

Varsayılan çıktı düzeni **Ayrı dosyalar (önerilen)** seçeneğidir:

```text
Video Başlığı.mp4
Video Başlığı - Ek Dosyalar/
├─ Ses/
│  ├─ English - Original.mka
│  ├─ Turkce - Turkce Dublaj.mka
│  └─ .parts-<dil>-<hash>/
├─ Altyazi/
│  ├─ Turkce.srt
│  └─ English.srt
└─ NASIL-KULLANILIR.txt
```

İş akışı:

1. Ana video bağımsız tamamlanır.
2. Her harici ses ayrı bir `audio` child işi olur.
3. Her harici altyazı ayrı bir `subtitle` child işi olur.
4. Bir child hata verirse diğer video/ses/altyazı işleri etkilenmez.
5. HLS ses; segment, key ve map kaynaklarını deterministik cache'e indirir.
6. Segmentler 4 paralel işçiyle, `.part` ve HTTP Range devam desteğiyle alınır.
7. Uygulama yeniden açılırsa child geçmişi ve segment cache'i üzerinden devam edebilir.
8. İmzalı URL veya oturum süresi dolmuşsa yeniden analiz gerekir; Cookie diske kaydedilmez.

Yan dosyalar VLC, mpv veya MPC gibi oynatıcılarda elle kullanılabilir ve otomatik mux sonrasında da silinmez.

## 11. Otomatik ve manuel birleştirme

Format seçimindeki çıktı düzenleri:

- `sidecar` → Ayrı dosyalar
- `auto_mkv` → Otomatik MKV
- `auto_mp4` → Otomatik MP4

Otomatik modda bütün beklenen audio/subtitle child işleri tamamlandıktan sonra `_maybe_enqueue_auto_mux(parent_id)` final `mux` işini kuyruğa ekler. Bir child `queued`, `downloading`, `paused`, `failed` veya `cancelled` ise mux bekler. Yan dosyalar korunur.

### Manuel birleştirici

Tek geniş sıralı listede Video, Ses ve Altyazı satırları bulunur. Kullanılabilen işlemler:

- Video Ekle
- Ses Ekle
- Altyazı Ekle
- Ana Video Yap
- Dil / Etiket düzenle
- Seçilenleri çıkar
- Sürükle-bırak

Birden fazla video listelenebilir; yalnız **Ana** işaretli video input 0 olur.

### MKV modu

- Video: `-c:v copy`
- Ses: mümkün olduğunda kayıpsız stream copy
- Metin altyazıları: SRT stream
- Harici subtitle map: `N:0`
- İlk altyazı: `default`
- Dil ve title metadata yazılır
- Final subtitle/audio sayısı FFprobe ile doğrulanır

### MP4 modu

- Video: copy
- Ses: AAC 192k
- Metin altyazıları: `mov_text`
- `faststart`

Video codec'i MP4 ile uyumsuzsa MKV seçilmelidir. Final dosyada beklenen altyazı sayısı eksikse iş **Tamamlandı** sayılmaz. Kaynak video, MKA ve altyazı dosyaları hiçbir zaman otomatik silinmez.

## 12. Duraklatma, devam ve hata kurtarma

- yt-dlp `.part` / `.ytdl` dosyaları mümkün olduğunda korunur.
- Harici HLS audio segmentleri kendi `.part` cache'i üzerinden devam eder.
- Sunucu HTTP Range desteklemiyorsa son parça yeniden başlayabilir.
- FFmpeg'in final mux aşamasını güvenli biçimde ortada duraklatmak her zaman mümkün değildir.
- Aynı etkin `URL + kalite` işi ikinci kez kuyruğa eklenmez.

### WinError 32 finalization

Tamamlanmış `.part` dosyası Windows'ta kilitlenirse:

1. `os.replace` 12 kez denenir.
2. Gerekirse copy-finalize fallback uygulanır.
3. FFprobe ile video stream doğrulanır.
4. Hatalı iş tekrar **Başlat** seçilirse yeniden indirmeden önce mevcut `.part` dosyası finalize edilmeye çalışılır.

### HLS sahte boyut

İlk fragmentten türetilen yanıltıcı 80+ GiB `total_bytes_estimate` kullanılmaz. HLS ilerlemesi `fragment_index / fragment_count` ile gösterilir ve tekrar eden sahte GiB logları bastırılır.

### Windows dosya yolu

- Oynatıcı hata metni başlık kabul edilmez.
- Başlıkta sayfa meta verisi ve URL slug'ı tercih edilir.
- Uzun generic/base64 kimliği kaldırılır.
- Kısa 10 karakter URL hash'i kullanılır.
- Dinamik başlık yaklaşık 48–110 karaktere sınırlandırılır.
- yt-dlp `trim_file_name=140` kullanır.

## 13. Siteye özel davranışlar

### YouTube

- Eklenti kısa ömürlü `googlevideo` URL'si yerine YouTube izleme sayfasını yollar.
- Kullanıcı **İndir (oturumla)** düğmesine bastığında yalnız ilgili YouTube profil bağlamı, cookie objeleri ve Visitor Data bellekte aktarılır.
- Deno güncel JS/EJS sınamalarında kullanılır.
- `yt-dlp-ejs` bağımlılığı kurulur.
- Kalite seçimi zorunludur; kullanıcı seçim yapmadan indirme başlamaz.
- Aynı dilde yinelenen otomatik altyazılar azaltılır.
- Bir altyazı 403/429 verirse yalnız o altyazı atlanır; ana video devam eder.
- Uygulama YouTube oran sınırını, bot doğrulamasını veya PO Token gereksinimini atlatmaz.

### X/Twitter

- X/Twitter status sayfası, kısa ömürlü codec CDN URL'si yerine yt-dlp'nin site çıkarıcısına yönlendirilir.
- `/mp4a/`, AAC, AC-3, E-AC-3 ve Opus HLS yolları audio sayılır.
- `.x.com` ve `.twitter.com` ile ilişkili etkin oturum cookie'leri yalnız bellekte kullanılabilir.
- CDN 403 verirse video sekmesini açık tutup yeniden yakalamak veya sayfa URL'sini yeniden analiz etmek gerekir.

### Standalone TS/M2TS

Gerçek tarayıcı `media` isteği olan TS/M2TS yakalanır. HLS XHR fragment seli ise ayrı medya olarak gösterilmez.

## 14. v7.3 uzantısız / `.txt` HLS düzeltmesi

Sorun örneği:

```text
https://imagestoo.com/cdn/hls/<kimlik>/master.txt
```

Eski davranışta eklenti yanıt gövdesinden bunun HLS olduğunu anlayabiliyor, fakat Python URL'yi yeniden istediğinde CDN bağlamı/TLS fingerprint/token nedeniyle playlist'i alamıyordu. yt-dlp generic extractor URL'yi doğrudan dosya sanıp şu hatayı veriyordu:

```text
URL could be a direct video link
No video formats found
```

v7.3 akışı:

1. `page-hook.js`, yalnız gerçekten `#EXTM3U` ile başlayan ve 1 MB altında olan Fetch/XHR gövdesini `manifestText` olarak yakalar.
2. `content.js` bu metadata'yı aktarır.
3. `background.js` aynı medya kaydında oturum süresince korur.
4. `overlay.js`, seçilen medya payload'ına ekler.
5. Yerel köprü magic ve boyut doğrulaması yapar.
6. Python önce tarayıcının yakaladığı metni kullanır; CDN'ye ikinci istek yapmaz.
7. Relative variant, segment, key ve map URI'leri özgün response URL'sine göre mutlaklaştırılır.
8. `%APPDATA%\AcikVideoIndirici\manifests\<20-karakter-sha1>.m3u8` yazılır.
9. yt-dlp `enable_file_urls=True` ile local manifesti analiz eder.
10. Hazırlanan URL, indirme seçeneklerinde `_app_download_url` ile worker'a taşınır.
11. Tarayıcı gövdesi yoksa curl-cffi refetch eski fallback olarak kalır.

Beklenen log:

```text
Uzantısız HLS tarayıcı yanıt gövdesinden yerel M3U8 olarak hazırlandı: <hash>.m3u8
[generic] Extracting URL: file:///.../<hash>.m3u8
Downloading m3u8 information
```

### Henüz kullanıcı ortamında doğrulanması gereken aktif konu

v7.4.1 paketi v7.3 manifest fallback'ini korur ve kaynak/statik testleri geçmiştir; ancak aşağıdaki gerçek Imagestoo akışları için yeni paketin Windows kullanıcı testi henüz alınmamıştır:

```text
https://imagestoo.com/cdn/hls/a42e71edb979cddae99730dd476078e1/master.txt
https://imagestoo.com/cdn/hls/f304f1c7276fff25d540873222c64991/master.txt
```

Bu adresler kısa ömürlü olabilir. Testte öncelikle yukarıdaki **“tarayıcı yanıt gövdesinden yerel M3U8”** satırı aranmalıdır.

Satır yoksa olası nedenler:

- Eski extension hâlâ yüklüdür.
- Açık sekmede eski content script çalışıyordur.
- Response opaque veya service worker üzerinden geldiği için gövde klonlanamamıştır.
- `manifestText`, page hook → content → background → overlay zincirinde kaybolmuştur.
- Gövde 1 MB sınırını aşmıştır.
- Bridge payload'ı 2 MiB sınırına takılmıştır.

İlk işlem: eski eklentiyi kaldırın, v7.4.1 `extension` klasörünü yeniden yükleyin, video sekmesini tamamen kapatıp tekrar açın. Sorun sürerse geçici tanı logları şu noktalara eklenmelidir:

- page hook'ta manifest karakter/byte sayısı ve `manifestKind`
- content aktarımında URL + body uzunluğu
- background storage kaydında body var/yok
- overlay seçilen öğede `mediaType`, `manifestKind`, kaynaklar ve body uzunluğu
- bridge kabul/reddet nedeni
- Python `context["manifestText"]` uzunluğu

Beklenen satır var ama yt-dlp yine başarısızsa AppData altındaki oluşturulmuş `.m3u8` incelenmeli; nested variant URI'leri, key/map URI'leri, gerekli header/cookie ve content-type davranışı kontrol edilmelidir.

## 15. Cookie, gizlilik ve güvenlik

- Eklenti uzak telemetri servisine veri göndermez.
- Uygulama bağlantısı yalnız loopback `127.0.0.1:17852` üzerindedir.
- İmzalı query değerleri logda gösterilmez; URL etiketi host + path olarak redakte edilir.
- YouTube/site/CDN cookie'leri structured objelerden veya gerektiğinde Cookie header'dan **bellek içi Netscape CookieJar**'a çevrilir.
- Cookie doğrudan yt-dlp `http_headers` içine eklenmez; böylece `Passing cookies as a header` deprecation/security hatası önlenir.
- Cookie değerleri `settings.json`, `downloads.json` veya proje dosyalarına yazılmaz.
- Geçmiş kaydındaki external track metadata'sından `cookieHeader` çıkarılır.
- Kullanıcı uygulamayı kapattığında bellek cookie'leri kaybolur.
- İmzalı URL/cookie süresi dolarsa kaynak yeniden analiz edilmelidir.

Chrome/Edge/Brave cookie SQLite dosyası kilitliyse uygulama tarayıcı-cookie seçimini kaldırıp çerezsiz yeniden deneyebilir. Gerekirse Firefox veya kullanıcının kendi Netscape `cookies.txt` dosyası seçilebilir.

## 16. Sorun giderme özeti

### `.venv\Scripts\python.exe: No module named pip`

Bu hata Python 3.13'ün desteklenmemesi anlamına gelmez. `.venv\Scripts\python.exe` oluşmuş, ancak o sanal ortamın içine pip yerleşmemiş veya önceki kurulum yarım kalmıştır. Eski kurucu yalnız `python.exe` dosyasının varlığına baktığı için bu eksik ortamı yanlışlıkla hazır kabul ediyordu.

Çözüm sırası:

1. v7.4.1 paketini normal klasöre tamamen çıkarın ve `KUR_VE_BASLAT.bat` çalıştırın; otomatik onarım uygulanır.
2. Eski klasörde devam edecekseniz uygulamayı kapatın, yalnız `python_app\.venv` klasörünü silin ve ana klasördeki `KUR_VE_BASLAT.bat` dosyasını yeniden çalıştırın.
3. Hata hâlâ sürerse Python yükleyicisinde **Modify/Repair** açıp `pip` ve `venv` bileşenlerini onarın.

Elle onarım gerekirse:

```bat
cd /d "C:\uygulama-yolu\python_app"
rmdir /s /q .venv
py -3 -m venv .venv
.venv\Scripts\python.exe -m ensurepip --upgrade --default-pip
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### FFmpeg bulunamadı

```powershell
where.exe ffmpeg
ffmpeg -version
ffprobe -version
```

Önce Format Seçimi sayfasındaki **FFmpeg Güncelle** düğmesini kullanın. WinGet yoksa PATH'i düzeltin veya iki EXE'yi `python_app` içine koyup uygulamayı yeniden başlatın.

### `FFmpeg güncellenemedi: winget bulunamadı`

Microsoft Store/Windows üzerinden **App Installer** bileşenini güncelleyin ve yeni PowerShell'de `winget --version` komutunu doğrulayın. Ardından düğmeyi yeniden kullanın veya elle çalıştırın:

```powershell
winget install --id Gyan.FFmpeg -e --source winget
```

Aktif indirme/birleştirme varsa güncelleme bilinçli olarak engellenir. Önce etkin işin tamamlanmasını bekleyin. WinGet tamamlandığı halde uygulama yeni yolu görmüyorsa uygulamayı kapatıp yeniden açın.

### YouTube formatları yok / JS runtime uyarısı

Deno 2.3+ kurun, `deno --version` ile doğrulayın, uygulamayı yeniden açın ve **yt-dlp Güncelle** seçeneğini kullanın.

### YouTube 429 / “Sign in to confirm you're not a bot”

Giriş yapılmış Chrome profilinde sayfayı yenileyin ve video üstündeki **İndir (oturumla)** düğmesini kullanın. Logda cookie sayısı, Visitor Data ve `giriş yapılmış profil` aranmalıdır. Buna rağmen 429 sürerse peş peşe denemeyin; hesap/IP geçici oran sınırında olabilir. Bu proje oran sınırı veya bot doğrulaması atlatmaz.

### Yerel uygulama kapalı

`python_app/run.bat` çalıştırın. Portu kontrol edin:

```powershell
netstat -ano | findstr :17852
```

Aynı uygulamanın ikinci örneğini kapatın.

### 401/403

Sayfa URL'sini deneyin, gerekli ve yetkili oturum bağlamını seçin, sekmeyi açık bırakın, süresi dolmamış akışı yeniden yakalayın ve tarayıcı/Python'un farklı VPN çıkışları kullanmadığını kontrol edin.

### Eklenti hiçbir şey yakalamıyor

Eklenti yüklendikten sonra sekmeyi yeniden açın, videoyu gerçekten oynatıp ileri/geri sarın ve kalite değiştirin. `chrome://`, Web Store ve bazı korumalı sayfalarda content script çalışmaz. Yalnız DRM şifreli segment varsa desteklenmez.

### `Option reconnect not found` ve yerel playlist

HTTP `reconnect` seçenekleri local `.m3u8` input'una verilmemelidir. Yalnız uzak HTTP playlist FFmpeg'e doğrudan verildiğinde uygulanır.

### `.jpg is not in allowed_segment_extensions`

Bazı CDN'ler HLS ses segmentini `.jpg` gibi gösterir. Localized playlist ve FFmpeg tarafında `-allowed_extensions ALL`, `-allowed_segment_extensions ALL`, `-extension_picky 0` korunmalıdır; segment içeriğinden probe edilir.

### `fextaudio*.m4a` / `Invalid data found when processing input`

Harici ses URL'si sahte `.m4a` adıyla kaydedilmemelidir. FFmpeg yalnız `a:0` stream'ini MKA'ya normalize etmeli, FFprobe doğrulamasından sonra mux'a eklemelidir. Eski sürümden kalan çok küçük `fextaudio-*.m4a` dosyaları hatalı olabilir.

### WinError 32

Explorer önizlemesini/oynatıcıyı kapatın. Güncel kod 12 rename denemesi, copy-finalize ve FFprobe kurtarması uygular; başarısız işi tekrar başlatmak önce mevcut `.part` dosyasını finalize etmeyi dener.

### HLS 80–90 GiB sahte boyut

Gerçek boyut değildir. Fragment oranı kullanılmalıdır; eski byte estimate loguna göre yeniden indirme başlatmayın.

### Uzun dosya adı / `.ytdl` Errno 2

Kaynak başlığı sınırlandıran, token/base64 kimliğini kaldıran ve `trim_file_name=140` kullanan mevcut yol mantığını koruyun. Çıktı klasörünü de gereksiz uzun seçmeyin.

### Altyazı SSL EOF / 403 / 429

Harici altyazı ana video worker'ını bloklamaz; ayrı subtitle child işidir. Yalnız ilgili satır hata vermeli, video ve ses devam etmelidir.

### Harici HLS'de yalnız ses

Audio rendition ana video adayı olmamalıdır. Format tablosunda `Yalnızca ses` yerine `Video + ses` veya `Video (+ en iyi ses)` satırını seçin. Eski eklentiyi kaldırıp güncel sürümü yükleyin.

### Harici İngilizce/orijinal ses görünmüyor

Oynatıcıda her ses seçeneğini bir kez seçip birkaç saniye oynatın. HLS `TYPE=AUDIO`, doğrudan M4A/MP3/Opus ve etiketli ayrı kaynaklar yakalanır. Erken primary-language filtresi geri getirilmemelidir; bütün benzersiz track'ler doğrulanmalıdır.

### Harici altyazı görünmüyor

Altyazıyı oynatıcıdan etkinleştirin. `<track>`, VTT/SRT/ASS/TTML, uzantısız WEBVTT/SRT/TTML ve HLS `TYPE=SUBTITLES` tespiti korunmalıdır.

### `no impersonate target is available`

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade "yt-dlp[default,curl-cffi]"
```

### Canlı yayın

İş yayın bitene veya kullanıcı iptal edene kadar sürebilir. Yeterli disk alanı ayırın; bazı ağ çağrılarının iptali birkaç saniye gecikebilir.

## 17. Tarihsel geliştirme özeti

| Sürüm dönemi | Temel değişiklik |
|---|---|
| v2.2 | YouTube oturum/Visitor Data aktarımı, zorunlu kalite, altyazı 403/429 dayanıklılığı |
| v3.0 | IDM benzeri kuyruk yöneticisi, çoklu iş, duraklat/devam, geçmiş |
| v3.1–3.6 | Harici HLS video/audio sınıflandırması, çoklu ses/altyazı, MKA normalizasyonu, İngilizce ses doğrulaması, `.jpg` segment ve local-HLS reconnect düzeltmeleri |
| v4.0–4.4 | Ayrı dosya paketi, ayrı audio/subtitle child kuyrukları, kalıcı HLS segment cache'i, X/Twitter yönlendirmesi, TS/M2TS, WinError 32, sahte boyut ve uzun yol düzeltmeleri |
| v5.0 | Düzenlenebilir çıktı adı ve sürükle-bırak manuel MKV/MP4 birleştirici |
| v6.0 | Global 20 iş havuzu, otomatik MKV/MP4 coordinator ve yan dosyaları koruma |
| v7.0 | Referans görsellere göre menü/toolbar/kategori/list UI, tema, harici format ve mini takip pencereleri, subtitle mux doğrulaması |
| v7.1 | Birleşik sıralı mux listesi, tam yükseklik kategori paneli, geniş ekran düzeni |
| v7.2 | Daha büyük format tablosu, Python refetch ile extensionless/text HLS, memory CookieJar |
| v7.3 | Tarayıcıdan `manifestText` aktarımı; CDN'ye ikinci istek olmadan local M3U8 hazırlama |
| v7.4 | Format Seçimi sayfasında WinGet tabanlı FFmpeg/FFprobe güncelleme-kurma düğmesi, aktif iş güvenlik kontrolü, WinGet yolu yeniden keşfi ve sürüm göstergesi |
| v7.4.1 | Eksik pip içeren yarım `.venv` ortamını `ensurepip` ile onarma, gerekirse temiz yeniden oluşturma ve açıklayıcı Python Repair yönlendirmesi; PyInstaller + Inno Setup ile tek EXE ve setup.exe kurulum paketi (dağıtım klasöründe `extension/`, FFmpeg/Deno paketsiz, TR/EN sihirbaz, ikon/wizard görselleri); dondurulmuş sürümde yt-dlp düğmesi bilgilendirme modu ve EXE yanında FFmpeg/FFprobe keşfi |

## 18. Geliştirme sırasında korunacak mimari kurallar

Yeni bir değişiklik yapılırken aşağıdakiler regresyona uğratılmamalıdır:

1. `APP_VERSION`, extension version ve paket adı birlikte artırılmalı.
2. Video, audio, subtitle ve mux işleri aynı 1–20 global havuzda kalmalı.
3. İlk eski-ayar migrasyonunda varsayılan 20 davranışı korunmalı.
4. Audio ve subtitle bağımsız child işler olmalı; ana video bunları beklemeden tamamlanmalı.
5. Yan MKA/SRT/VTT dosyaları otomatik mux sonrasında silinmemeli.
6. Otomatik mux yalnız beklenen bütün child işler başarıyla tamamlanınca kuyruğa girmeli.
7. Cookie, Cookie header veya oturum token'ı ayarlara/geçmişe/loga yazılmamalı.
8. İmzalı URL query değerleri logda açık gösterilmemeli.
9. Audio-only HLS ana video olarak seçilmemeli.
10. HLS TS XHR fragmentleri tek tek video adayı yapılmamalı.
11. Extensionless HLS'de önce browser-captured `manifestText`, sonra refetch fallback kullanılmalı.
12. Local M3U8'e geçersiz HTTP reconnect seçeneği verilmemeli.
13. `.jpg` görünen HLS segment desteği korunmalı.
14. HLS ilerlemesinde yanıltıcı byte estimate yerine fragment oranı kullanılmalı.
15. WinError 32 kurtarma ve tekrar başlatmada önce finalization davranışı korunmalı.
16. MKV/MP4 final çıktıda subtitle sayısı FFprobe ile doğrulanmalı.
17. Manuel mux girdileri ve sidecar kaynakları hiçbir zaman otomatik silinmemeli.
18. DRM kırma, anahtar çıkarma veya erişim kontrolü atlatma eklenmemeli.
19. Kullanıcıya “her site kesin desteklenir” sözü verilmemeli.
20. Arayüz değişikliği ana büyük indirme listesini küçültmemeli; harici format ve takip pencereleri küçültülebilir kalmalı.
21. FFmpeg güncelleyici yalnız kullanıcı onayıyla ve aktif medya işi yokken çalışmalı; `Gyan.FFmpeg` WinGet yükseltme/kurma fallback'i, hata mesajları ve yeniden yol/sürüm algılama korunmalı.
22. Windows kurucusu yalnız `.venv\Scripts\python.exe` varlığına güvenmemeli; pip'i ayrıca doğrulamalı, `ensurepip` onarımı ve tek seferlik temiz `.venv` yeniden oluşturma fallback'ini korumalı.
23. Setup paketi FFmpeg, Deno veya Python içermemeli; bunlar uygulama içi bakım düğmeleriyle (WinGet) kurulmalı. `extension/` klasörü hem `{app}\extension` altına kurulmalı hem dağıtım klasöründe setup'ın yanında taşınmalı. `APP_VERSION`, extension manifest ve `.iss` `MyAppVersion` birlikte artırılmalı.
24. Dondurulmuş (setup) sürümde `yt-dlp Güncelle` pip çalıştırmamalı, kullanıcıya yeni kurulum paketini önermeli; `IS_FROZEN` koruması ve dondurulmuş EXE'de kurulum klasörünü tarayan FFmpeg/FFprobe keşfi korunmalı.

## 19. Geliştirici doğrulama ve paketleme

### 19.1 Linux/Arena çalışma alanında ortam

Workspace snapshot'ları `.venv` klasörünü saklamayabilir. Gerektiğinde yeniden oluşturun:

```bash
cd /home/user/aloha-video-downloader
python -m venv python_app/.venv
python_app/.venv/bin/python -m pip install -r python_app/requirements.txt
```

### 19.2 Hızlı statik kontroller

```bash
cd /home/user/aloha-video-downloader
python -m py_compile python_app/app.py
python -m json.tool extension/manifest.json >/dev/null
for f in extension/*.js; do node --check "$f"; done
```

Sürüm eşleşmesi ayrıca kontrol edilmelidir:

```bash
grep -n 'APP_VERSION' python_app/app.py
grep -n '"version"' extension/manifest.json
```

### 19.3 Regresyon kontrol listesi

- Uygulama açılıyor ve bridge 17852'yi dinliyor.
- Extension yükleniyor; manifest ve JavaScript syntax hatasız.
- `install.bat` ve `run.bat` CRLF satır sonlarını koruyor; bütün `goto` hedefleri tanımlı.
- Python 3.13 ile `venv --without-pip` ortamı oluşturulup kurucunun kullandığı `ensurepip --upgrade --default-pip` komutuyla pip'in gerçekten geri geldiği doğrulanıyor.
- Eksik pip senaryosunda kurucu önce `ensurepip`, sonra en fazla bir temiz `.venv` yeniden oluşturma yoluna gidiyor; sonsuz döngü oluşturmuyor.
- `run.bat`, bağımlılık kontrolünden önce `python -m pip --version` ile yarım ortamı kurucuya yönlendiriyor.
- Format Seçimi satırında yt-dlp, Deno ve FFmpeg bakım düğmeleri yan yana görünüyor.
- FFmpeg updater mock testlerinde ilk kurulum, normal yükseltme, yönetilmeyen kopyadan install fallback'i, zaten güncel ve hata yolları doğru event üretiyor.
- Windows gerçek testinde aktif iş varken FFmpeg güncellemesi engelleniyor; boşta WinGet işlemi ve sürüm/yol yenilemesi çalışıyor.
- Doğrudan MP4/WebM yakalanıyor.
- Standart M3U8 ve MPD analiz ediliyor.
- `.txt`/uzantısız HLS için browser body local M3U8'e dönüşüyor.
- Relative variant/segment/key/map URI'leri doğru mutlaklaşıyor.
- Cookie deprecation görünmüyor.
- 20 global iş ayarı ve eski ayar migrasyonu çalışıyor.
- Pause/resume `.part` dosyasını koruyor.
- Audio/subtitle child satırları ayrı ilerliyor.
- Otomatik MKV/MP4 yalnız tüm child işler bittikten sonra oluşuyor.
- Manuel mux'ta dil/etiket, ana video ve drag/drop çalışıyor.
- MKV/MP4 subtitle stream sayısı FFprobe ile doğrulanıyor.
- YouTube sayfa URL'si, Deno ve oturum bağlamı yolu bozulmamış.
- X/Twitter `/mp4a/` kaydı ana video seçilmiyor.
- Cookie değerleri `downloads.json` veya loglarda yok.

### 19.4 Test sınırı

Linux sandbox'ta ekran/Xvfb yoksa tam Windows `customtkinter` görsel smoke test'i yapılamaz. Windows CMD olmadığı için `.bat` akışı gerçek `cmd.exe` altında çalıştırılamaz; CRLF, label/goto grafiği ve komut sırası statik olarak doğrulanır. WinGet de Linux'ta gerçek paket yükseltmesiyle çalıştırılamaz; updater dalları mock `CompletedProcess` sonuçlarıyla regresyon testinden geçirilir. Syntax, yardımcı fonksiyon ve paket testleri geçse bile Windows'ta gerçek kurulum, GUI, WinGet, Chrome/Edge eklentisi, FFmpeg ve örnek medya ile son kullanıcı testi yapılmalıdır.

### 19.5 ZIP paketleme kuralları

Dağıtım ZIP'inde yalnız şunlar bulunmalıdır:

- `README.md`
- `TEST-RAPORU-v7.4.1.txt`
- `KUR_VE_BASLAT.bat`
- `YOUTUBE-DESTEGI-KUR.bat`
- `python_app/` içindeki kaynak/bat/requirements dosyaları
- `extension/` içindeki kaynak dosyaları
- `installer/` içindeki kaynak dosyalar: `app.spec`, `AcikVideoIndirici.iss`, `KURULUM-OLUSTUR.bat`, `assets/`, `tools/make_assets.py`

Şunlar dahil edilmemelidir:

- `.venv`, `installer/.venv`
- `__pycache__`
- `node_modules`
- `installer/build`, `installer/dist`, `installer/Output`
- kurulum/uygulama logları
- kullanıcı ayarları/geçmişi
- cookie dosyaları
- indirilmiş medya veya segment cache'i
- eski sürüm belgeleri ve eski ZIP'ler

Paket sonrası:

```bash
unzip -t Acik-Video-Indirici-Windows11-v7.4.1.zip
sha256sum Acik-Video-Indirici-Windows11-v7.4.1.zip
```

### 19.6 Setup derleme (PyInstaller + Inno Setup)

Kurulum paketi yalnız **Windows** üzerinde derlenir (PyInstaller hedef işletim sistemi EXE'si üretir; Linux/Arena ortamı kaynak ve statik doğrulama içindir).

1. `installer/KURULUM-OLUSTUR.bat` çalıştırılır. Betik sırayla:
   - Python 3.10+ bulur ve `installer/.venv` oluşturur; `requirements.txt` + `pyinstaller` kurar.
   - `app.spec` ile `app.py`'yi **tek EXE** (`installer/dist/AcikVideoIndirici.exe`, penceresiz, ikonlu) olarak dondurur.
   - Inno Setup 6'yı arar; yoksa onayla `winget install --id JRSoftware.InnoSetup -e` kurar.
   - `AcikVideoIndirici.iss` derleyerek `installer/Output/Acik-Video-Indirici-Kurulum-7.4.1.exe` üretir.
   - `extension/` klasörünü `installer/Output/extension` altına kopyalar ve SHA-256 yazdırır.
2. `app.spec` şunları EXE'ye gömer: `customtkinter` temaları, `tkinterdnd2` (tkdnd Tcl paketi + dll), `curl_cffi` yerel kütüphaneleri (TLS impersonation), `certifi` CA paketi, `yt-dlp[default,curl-cffi]` + `yt_dlp_ejs` modülleri. UPX kapalıdır (tk/curl dll'lerini bozabilir).
3. **Bilinçli kapsam:** FFmpeg, Deno ve Python pakete konmaz; boyut küçük kalır. Kurulumdan sonra uygulama içi bakım düğmeleri bunları WinGet ile kurar. Dondurulmuş sürümde **yt-dlp Güncelle** pip çalıştırmaz, yeni setup paketini önerir (`IS_FROZEN` koruması).
4. **Onefile notu:** İlk açılışta geçici klasöre açılım nedeniyle birkaç saniyelik gecikme normaldir; SmartScreen/antivirüs imzasız EXE'de uyarı verebilir. Kod imzası istenirse `codesign_identity` spec'e eklenebilir.
5. Sürüm artırırken `APP_VERSION`, `manifest.json`, `.iss` içindeki `MyAppVersion` ve bu README'deki paket/setup adları birlikte güncellenir.

Derleme sonrası kontrol listesi:

- `installer/Output/` içinde hem setup.exe hem `extension/` vardır.
- Kurulum sonrası `{app}\AcikVideoIndirici.exe` açılır, köprü 17852'yi dinler.
- `{app}\extension` Chrome/Edge'de yüklenir; manifest sürümü uygulama sürümüyle aynıdır.
- `ffmpeg -version` gerekmeden önce uygulama **FFmpeg Güncelle** ile kurabilir.

## 20. Projeyi yeni Arena.ai Agent Mode sohbetine aktarma

Yeni sohbet önceki sohbetin belleğine veya mevcut workspace yoluna otomatik olarak güvenmemelidir. En güvenli aktarım bir **kaynak ZIP'i + bu README** üzerinden yapılır.

### Adım adım

1. Bu sohbetten `Acik-Video-Indirici-Windows11-v7.4.1.zip` dosyasını bilgisayarınıza indirin.
2. Yeni bir Arena.ai sohbeti açın ve **Agent Mode** seçin.
3. Mesaj ekindeki dosya yükleme alanından ZIP'i yeni sohbete ekleyin. Yalnız `/home/user/...` yolu yazmak yeterli değildir; yeni sohbet aynı workspace'i görmeyebilir.
4. Aşağıdaki hazır devir istemini yapıştırın.
5. Son hata logunu metin olarak, varsa ekran görüntülerini ayrıca ekleyin.
6. Yapılacak yeni özelliği veya hatayı tek bir net görev olarak yazın.
7. Agent'tan yalnız açıklama değil; kaynak değişikliği, test, yeni sürüm numarası, bütünlük kontrolü ve indirilebilir güncel ZIP isteyin.

### Yeni sohbet için hazır devir istemi

Aşağıdaki metni kopyalayıp `[YENİ GÖREV]` bölümünü değiştirin:

```text
Ekte Açık Video İndirici Windows 11 projesinin güncel kaynak paketi var.

1. ZIP'i workspace içinde /home/user/aloha-video-downloader klasörüne çıkar.
2. Önce README.md dosyasının tamamını oku; bu dosya proje mimarisi, değişmez kurallar, güncel sorun, test ve paketleme bilgisinin tek kaynağıdır.
3. Sonra python_app/app.py, extension/manifest.json ve ilgili extension JavaScript dosyalarını doğrudan inceleyerek README ile kaynak kodu doğrula.
4. Güncel başlangıç sürümü v7.4.1'dir. Mevcut özellikleri ve README'deki “Geliştirme sırasında korunacak mimari kurallar” bölümünü bozma.
5. DRM/Widevine/CENC atlatma yapma ve her site için garanti verme. Yalnız açık/şifresiz veya kullanıcının indirmeye yetkili olduğu medya kapsamında çalış.
6. Cookie/token değerlerini loga, ayarlara, geçmişe veya pakete yazma.
7. Değişiklikten sonra Python/JSON/JavaScript kontrollerini, ilgili regresyon testlerini ve ZIP bütünlük testini çalıştır.
8. APP_VERSION, extension manifest sürümü ve paket adını birlikte artır.
9. README.md içindeki güncel durum/devir notunu yeni değişikliğe göre güncelle; yeni dağınık MD dosyaları oluşturma.
10. Sonuçta kaynakları workspace'te bırak, güncel Windows ZIP paketini üret, SHA-256 değerini bildir ve ZIP'i bana aç/present et.
11. Yalnız genel öneri verme; kök nedeni logdan teşhis et ve somut kod düzeltmesi yap.

[YENİ GÖREV]
Buraya yeni hata logunu, beklenen davranışı veya istenen özelliği yazacağım.
```

### Yeni sohbete özellikle iletilmesi gereken aktif test

Yeni görev v7.3 Imagestoo HLS testi ise isteme şunu da ekleyin:

```text
Önce yeni logda şu satırın bulunup bulunmadığını kontrol et:
“Uzantısız HLS tarayıcı yanıt gövdesinden yerel M3U8 olarak hazırlandı”

Satır yoksa page-hook → content → background → overlay → bridge → Python zincirinde manifestText uzunluğunu geçici, gizlilik güvenli tanı loglarıyla izle. Satır varsa AppData/manifests altındaki local M3U8'in relative/nested URI ve header davranışını incele. Eski extension veya açık sekmede eski content script olasılığını önce ele.
```

### Her geliştirme turunun sonunda saklanacaklar

- Güncel kaynak ZIP'i
- ZIP SHA-256 değeri
- Yeni sürüm numarası
- Kısa değişiklik listesi
- Çalıştırılan testler ve geçmeyen testler
- Hâlâ kullanıcı ortamında doğrulanması gereken noktalar
- Hata varsa tam, redakte edilmiş log

Bu yöntemle eski sohbet geçmişine ihtiyaç duymadan proje tekrar yüklenebilir ve geliştirme aynı mimari üzerinden sürdürülebilir.
