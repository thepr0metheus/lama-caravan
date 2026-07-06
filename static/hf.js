/* HuggingFace Browser — split layout with favorites & badges */
// $ and escapeHtml come from the shared utils module (note: that escapeHtml
// also escapes single quotes — a strict superset of the old local copy).
import { $, escapeHtml } from "/js/utils.js";

function hfToast(message) {
  let el = document.getElementById("hfToast");
  if (!el) {
    el = document.createElement("div");
    el.id = "hfToast";
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(hfToast._t);
  hfToast._t = setTimeout(() => el.classList.remove("show"), 4000);
}

// ── page strings (en+ru; the big i18n-data dict is deliberately NOT loaded
// here — /hf stays lightweight, so it keeps its own tiny table; language code
// is shared with the main app via localStorage) ─────────────────────────────
const HFS = {
  en: {
    treeQuants: "Quantized versions",
    treeSiblings: "Other quants of {base}",
    tokenNotSet: "not set — gated models unavailable",
    tokenChangeTitle: "Change HF token?", tokenChangeOk: "Change",
    tokenClearTitle: "Clear HF token?", tokenClearOk: "Clear",
    favRemove: "Remove from favorites", favAdd: "Add to favorites",
    searchToBrowse: "Search to browse repositories",
    noFilterMatches: "No matches for the filter",
    selectRepo: "← Select a repository",
    searching: "Searching…", noResults: "No results", errorWord: "Error",
    showBench: "Show benchmarks", loading: "Loading…",
    noGguf: "No GGUF files found",
    selectForDownload: "Select for download",
    deleteLocalTitle: "Delete local file", deleteLocalConfirm: "Delete local file?", deleteWord: "Delete",
    deleteFailed: "Failed to delete: {err}",
    benchLoading: "Loading data from Artificial Analysis…",
    onDiskTitle: "Manage downloaded models",
  },
  ru: {
    treeQuants: "Квантованные версии",
    treeSiblings: "Другие кванты {base}",
    tokenNotSet: "не задан — закрытые модели недоступны",
    tokenChangeTitle: "Сменить HF-токен?", tokenChangeOk: "Сменить",
    tokenClearTitle: "Убрать HF-токен?", tokenClearOk: "Убрать",
    favRemove: "Убрать из избранного", favAdd: "В избранное",
    searchToBrowse: "Ищите, чтобы посмотреть репозитории",
    noFilterMatches: "Ничего не подходит под фильтр",
    selectRepo: "← Выберите репозиторий",
    searching: "Ищу…", noResults: "Ничего не найдено", errorWord: "Ошибка",
    showBench: "Показать бенчмарки", loading: "Загрузка…",
    noGguf: "GGUF-файлов не найдено",
    selectForDownload: "Выбрать для загрузки",
    deleteLocalTitle: "Удалить локальный файл", deleteLocalConfirm: "Удалить локальный файл?", deleteWord: "Удалить",
    deleteFailed: "Не удалось удалить: {err}",
    benchLoading: "Загружаю данные Artificial Analysis…",
    onDiskTitle: "Скачанные модели",
  },
  zh: {
    treeQuants: "量化版本",
    treeSiblings: "{base} 的其他量化版本",
    tokenNotSet: "未设置 — 无法访问受限模型",
    tokenChangeTitle: "更换 HF 令牌？",
    tokenChangeOk: "更换",
    tokenClearTitle: "清除 HF 令牌？",
    tokenClearOk: "清除",
    favRemove: "从收藏中移除",
    favAdd: "加入收藏",
    searchToBrowse: "搜索以浏览仓库",
    noFilterMatches: "没有符合筛选的结果",
    selectRepo: "← 选择一个仓库",
    searching: "搜索中…",
    noResults: "无结果",
    errorWord: "错误",
    showBench: "显示基准测试",
    loading: "加载中…",
    noGguf: "未找到 GGUF 文件",
    selectForDownload: "选择以下载",
    deleteLocalTitle: "删除本地文件",
    deleteLocalConfirm: "删除本地文件？",
    deleteWord: "删除",
    deleteFailed: "删除失败：{err}",
    benchLoading: "正在加载 Artificial Analysis 数据…",
    onDiskTitle: "管理已下载的模型",
  },
  hi: {
    treeQuants: "क्वांटाइज़्ड संस्करण",
    treeSiblings: "{base} के अन्य क्वांट",
    tokenNotSet: "सेट नहीं — गेटेड मॉडल अनुपलब्ध",
    tokenChangeTitle: "HF टोकन बदलें?",
    tokenChangeOk: "बदलें",
    tokenClearTitle: "HF टोकन हटाएं?",
    tokenClearOk: "हटाएं",
    favRemove: "पसंदीदा से हटाएं",
    favAdd: "पसंदीदा में जोड़ें",
    searchToBrowse: "रिपॉज़िटरी ब्राउज़ करने के लिए खोजें",
    noFilterMatches: "फ़िल्टर से कोई मेल नहीं",
    selectRepo: "← एक रिपॉज़िटरी चुनें",
    searching: "खोज रहा है…",
    noResults: "कोई परिणाम नहीं",
    errorWord: "त्रुटि",
    showBench: "बेंचमार्क दिखाएं",
    loading: "लोड हो रहा है…",
    noGguf: "कोई GGUF फ़ाइलें नहीं मिलीं",
    selectForDownload: "डाउनलोड के लिए चुनें",
    deleteLocalTitle: "स्थानीय फ़ाइल हटाएं",
    deleteLocalConfirm: "स्थानीय फ़ाइल हटाएं?",
    deleteWord: "हटाएं",
    deleteFailed: "हटाना विफल: {err}",
    benchLoading: "Artificial Analysis से डेटा लोड हो रहा है…",
    onDiskTitle: "डाउनलोड किए मॉडल प्रबंधित करें",
  },
  es: {
    treeQuants: "Versiones cuantizadas",
    treeSiblings: "Otras cuantizaciones de {base}",
    tokenNotSet: "no definido — modelos con acceso restringido no disponibles",
    tokenChangeTitle: "¿Cambiar el token HF?",
    tokenChangeOk: "Cambiar",
    tokenClearTitle: "¿Borrar el token HF?",
    tokenClearOk: "Borrar",
    favRemove: "Quitar de favoritos",
    favAdd: "Añadir a favoritos",
    searchToBrowse: "Busca para explorar repositorios",
    noFilterMatches: "Nada coincide con el filtro",
    selectRepo: "← Selecciona un repositorio",
    searching: "Buscando…",
    noResults: "Sin resultados",
    errorWord: "Error",
    showBench: "Mostrar benchmarks",
    loading: "Cargando…",
    noGguf: "No se encontraron archivos GGUF",
    selectForDownload: "Seleccionar para descargar",
    deleteLocalTitle: "Eliminar archivo local",
    deleteLocalConfirm: "¿Eliminar archivo local?",
    deleteWord: "Eliminar",
    deleteFailed: "Fallo al eliminar: {err}",
    benchLoading: "Cargando datos de Artificial Analysis…",
    onDiskTitle: "Gestionar modelos descargados",
  },
  fr: {
    treeQuants: "Versions quantifiées",
    treeSiblings: "Autres quantifications de {base}",
    tokenNotSet: "non défini — modèles à accès restreint indisponibles",
    tokenChangeTitle: "Changer le token HF ?",
    tokenChangeOk: "Changer",
    tokenClearTitle: "Effacer le token HF ?",
    tokenClearOk: "Effacer",
    favRemove: "Retirer des favoris",
    favAdd: "Ajouter aux favoris",
    searchToBrowse: "Recherchez pour parcourir les dépôts",
    noFilterMatches: "Aucun résultat pour ce filtre",
    selectRepo: "← Sélectionnez un dépôt",
    searching: "Recherche…",
    noResults: "Aucun résultat",
    errorWord: "Erreur",
    showBench: "Afficher les benchmarks",
    loading: "Chargement…",
    noGguf: "Aucun fichier GGUF trouvé",
    selectForDownload: "Sélectionner pour téléchargement",
    deleteLocalTitle: "Supprimer le fichier local",
    deleteLocalConfirm: "Supprimer le fichier local ?",
    deleteWord: "Supprimer",
    deleteFailed: "Échec de la suppression : {err}",
    benchLoading: "Chargement des données d'Artificial Analysis…",
    onDiskTitle: "Gérer les modèles téléchargés",
  },
  ar: {
    treeQuants: "إصدارات مكمّمة",
    treeSiblings: "تكميمات أخرى لـ {base}",
    tokenNotSet: "غير مضبوط — النماذج المقيدة غير متاحة",
    tokenChangeTitle: "تغيير رمز HF؟",
    tokenChangeOk: "تغيير",
    tokenClearTitle: "مسح رمز HF؟",
    tokenClearOk: "مسح",
    favRemove: "إزالة من المفضلة",
    favAdd: "إضافة إلى المفضلة",
    searchToBrowse: "ابحث لتصفح المستودعات",
    noFilterMatches: "لا نتائج مطابقة للتصفية",
    selectRepo: "← اختر مستودعًا",
    searching: "جارٍ البحث…",
    noResults: "لا نتائج",
    errorWord: "خطأ",
    showBench: "عرض المعايير",
    loading: "جارٍ التحميل…",
    noGguf: "لم يُعثر على ملفات GGUF",
    selectForDownload: "تحديد للتنزيل",
    deleteLocalTitle: "حذف الملف المحلي",
    deleteLocalConfirm: "حذف الملف المحلي؟",
    deleteWord: "حذف",
    deleteFailed: "فشل الحذف: {err}",
    benchLoading: "جارٍ تحميل بيانات Artificial Analysis…",
    onDiskTitle: "إدارة النماذج المنزّلة",
  },
  bn: {
    treeQuants: "কোয়ান্টাইজড সংস্করণ",
    treeSiblings: "{base}-এর অন্যান্য কোয়ান্ট",
    tokenNotSet: "সেট করা নেই — গেটেড মডেল অনুপলব্ধ",
    tokenChangeTitle: "HF টোকেন বদলাবেন?",
    tokenChangeOk: "বদলান",
    tokenClearTitle: "HF টোকেন মুছবেন?",
    tokenClearOk: "মুছুন",
    favRemove: "প্রিয় থেকে সরান",
    favAdd: "প্রিয়তে যোগ করুন",
    searchToBrowse: "রিপোজিটরি ব্রাউজ করতে অনুসন্ধান করুন",
    noFilterMatches: "ফিল্টারের সাথে কিছু মেলেনি",
    selectRepo: "← একটি রিপোজিটরি নির্বাচন করুন",
    searching: "অনুসন্ধান চলছে…",
    noResults: "কোনো ফলাফল নেই",
    errorWord: "ত্রুটি",
    showBench: "বেঞ্চমার্ক দেখান",
    loading: "লোড হচ্ছে…",
    noGguf: "কোনো GGUF ফাইল পাওয়া যায়নি",
    selectForDownload: "ডাউনলোডের জন্য নির্বাচন করুন",
    deleteLocalTitle: "স্থানীয় ফাইল মুছুন",
    deleteLocalConfirm: "স্থানীয় ফাইল মুছবেন?",
    deleteWord: "মুছুন",
    deleteFailed: "মুছতে ব্যর্থ: {err}",
    benchLoading: "Artificial Analysis থেকে ডেটা লোড হচ্ছে…",
    onDiskTitle: "ডাউনলোড করা মডেল পরিচালনা",
  },
  pt: {
    treeQuants: "Versões quantizadas",
    treeSiblings: "Outras quantizações de {base}",
    tokenNotSet: "não definido — modelos restritos indisponíveis",
    tokenChangeTitle: "Alterar o token HF?",
    tokenChangeOk: "Alterar",
    tokenClearTitle: "Remover o token HF?",
    tokenClearOk: "Remover",
    favRemove: "Remover dos favoritos",
    favAdd: "Adicionar aos favoritos",
    searchToBrowse: "Pesquise para navegar pelos repositórios",
    noFilterMatches: "Nada corresponde ao filtro",
    selectRepo: "← Selecione um repositório",
    searching: "Pesquisando…",
    noResults: "Sem resultados",
    errorWord: "Erro",
    showBench: "Mostrar benchmarks",
    loading: "Carregando…",
    noGguf: "Nenhum arquivo GGUF encontrado",
    selectForDownload: "Selecionar para baixar",
    deleteLocalTitle: "Excluir arquivo local",
    deleteLocalConfirm: "Excluir o arquivo local?",
    deleteWord: "Excluir",
    deleteFailed: "Falha ao excluir: {err}",
    benchLoading: "Carregando dados do Artificial Analysis…",
    onDiskTitle: "Gerenciar modelos baixados",
  },
  ja: {
    treeQuants: "量子化バージョン",
    treeSiblings: "{base} の他の量子化版",
    tokenNotSet: "未設定 — ゲート付きモデルは利用できません",
    tokenChangeTitle: "HF トークンを変更しますか？",
    tokenChangeOk: "変更",
    tokenClearTitle: "HF トークンを削除しますか？",
    tokenClearOk: "削除",
    favRemove: "お気に入りから削除",
    favAdd: "お気に入りに追加",
    searchToBrowse: "検索してリポジトリを表示",
    noFilterMatches: "フィルターに一致するものがありません",
    selectRepo: "← リポジトリを選択",
    searching: "検索中…",
    noResults: "結果なし",
    errorWord: "エラー",
    showBench: "ベンチマークを表示",
    loading: "読み込み中…",
    noGguf: "GGUF ファイルが見つかりません",
    selectForDownload: "ダウンロード対象に選択",
    deleteLocalTitle: "ローカルファイルを削除",
    deleteLocalConfirm: "ローカルファイルを削除しますか？",
    deleteWord: "削除",
    deleteFailed: "削除に失敗しました：{err}",
    benchLoading: "Artificial Analysis からデータを読み込み中…",
    onDiskTitle: "ダウンロード済みモデルの管理",
  },
  de: {
    treeQuants: "Quantisierte Versionen",
    treeSiblings: "Weitere Quantisierungen von {base}",
    tokenNotSet: "nicht gesetzt — zugangsbeschränkte Modelle nicht verfügbar",
    tokenChangeTitle: "HF-Token ändern?",
    tokenChangeOk: "Ändern",
    tokenClearTitle: "HF-Token entfernen?",
    tokenClearOk: "Entfernen",
    favRemove: "Aus Favoriten entfernen",
    favAdd: "Zu Favoriten hinzufügen",
    searchToBrowse: "Suchen, um Repositories zu durchstöbern",
    noFilterMatches: "Keine Treffer für den Filter",
    selectRepo: "← Repository auswählen",
    searching: "Suche läuft…",
    noResults: "Keine Ergebnisse",
    errorWord: "Fehler",
    showBench: "Benchmarks anzeigen",
    loading: "Lädt…",
    noGguf: "Keine GGUF-Dateien gefunden",
    selectForDownload: "Zum Herunterladen auswählen",
    deleteLocalTitle: "Lokale Datei löschen",
    deleteLocalConfirm: "Lokale Datei löschen?",
    deleteWord: "Löschen",
    deleteFailed: "Löschen fehlgeschlagen: {err}",
    benchLoading: "Daten von Artificial Analysis werden geladen…",
    onDiskTitle: "Heruntergeladene Modelle verwalten",
  },
  id: {
    treeQuants: "Versi terkuantisasi",
    treeSiblings: "Kuantisasi lain dari {base}",
    tokenNotSet: "belum disetel — model tertutup tidak tersedia",
    tokenChangeTitle: "Ganti token HF?",
    tokenChangeOk: "Ganti",
    tokenClearTitle: "Hapus token HF?",
    tokenClearOk: "Hapus",
    favRemove: "Hapus dari favorit",
    favAdd: "Tambah ke favorit",
    searchToBrowse: "Cari untuk menjelajahi repositori",
    noFilterMatches: "Tidak ada yang cocok dengan filter",
    selectRepo: "← Pilih repositori",
    searching: "Mencari…",
    noResults: "Tidak ada hasil",
    errorWord: "Kesalahan",
    showBench: "Tampilkan benchmark",
    loading: "Memuat…",
    noGguf: "Tidak ada berkas GGUF ditemukan",
    selectForDownload: "Pilih untuk diunduh",
    deleteLocalTitle: "Hapus berkas lokal",
    deleteLocalConfirm: "Hapus berkas lokal?",
    deleteWord: "Hapus",
    deleteFailed: "Gagal menghapus: {err}",
    benchLoading: "Memuat data dari Artificial Analysis…",
    onDiskTitle: "Kelola model terunduh",
  },
  ur: {
    treeQuants: "کوانٹائزڈ ورژن",
    treeSiblings: "{base} کے دیگر کوانٹس",
    tokenNotSet: "سیٹ نہیں — گیٹڈ ماڈلز دستیاب نہیں",
    tokenChangeTitle: "HF ٹوکن تبدیل کریں؟",
    tokenChangeOk: "تبدیل کریں",
    tokenClearTitle: "HF ٹوکن ہٹائیں؟",
    tokenClearOk: "ہٹائیں",
    favRemove: "پسندیدہ سے ہٹائیں",
    favAdd: "پسندیدہ میں شامل کریں",
    searchToBrowse: "ریپوزٹریز دیکھنے کے لیے تلاش کریں",
    noFilterMatches: "فلٹر سے کچھ میل نہیں کھاتا",
    selectRepo: "← ایک ریپوزٹری منتخب کریں",
    searching: "تلاش ہو رہی ہے…",
    noResults: "کوئی نتائج نہیں",
    errorWord: "خرابی",
    showBench: "بینچ مارکس دکھائیں",
    loading: "لوڈ ہو رہا ہے…",
    noGguf: "کوئی GGUF فائلیں نہیں ملیں",
    selectForDownload: "ڈاؤن لوڈ کے لیے منتخب کریں",
    deleteLocalTitle: "مقامی فائل حذف کریں",
    deleteLocalConfirm: "مقامی فائل حذف کریں؟",
    deleteWord: "حذف کریں",
    deleteFailed: "حذف کرنا ناکام: {err}",
    benchLoading: "Artificial Analysis سے ڈیٹا لوڈ ہو رہا ہے…",
    onDiskTitle: "ڈاؤن لوڈ شدہ ماڈلز منظم کریں",
  },
  tr: {
    treeQuants: "Nicemlenmiş sürümler",
    treeSiblings: "{base} için diğer nicemlemeler",
    tokenNotSet: "ayarlanmadı — kısıtlı modeller kullanılamaz",
    tokenChangeTitle: "HF token'ı değiştirilsin mi?",
    tokenChangeOk: "Değiştir",
    tokenClearTitle: "HF token'ı temizlensin mi?",
    tokenClearOk: "Temizle",
    favRemove: "Favorilerden kaldır",
    favAdd: "Favorilere ekle",
    searchToBrowse: "Depolara göz atmak için arayın",
    noFilterMatches: "Filtreyle eşleşen yok",
    selectRepo: "← Bir depo seçin",
    searching: "Aranıyor…",
    noResults: "Sonuç yok",
    errorWord: "Hata",
    showBench: "Karşılaştırmaları göster",
    loading: "Yükleniyor…",
    noGguf: "GGUF dosyası bulunamadı",
    selectForDownload: "İndirmek için seç",
    deleteLocalTitle: "Yerel dosyayı sil",
    deleteLocalConfirm: "Yerel dosya silinsin mi?",
    deleteWord: "Sil",
    deleteFailed: "Silme başarısız: {err}",
    benchLoading: "Artificial Analysis'ten veri yükleniyor…",
    onDiskTitle: "İndirilen modelleri yönet",
  },
  ko: {
    treeQuants: "양자화 버전",
    treeSiblings: "{base}의 다른 양자화 버전",
    tokenNotSet: "설정 안 됨 — 게이트된 모델 사용 불가",
    tokenChangeTitle: "HF 토큰을 변경할까요?",
    tokenChangeOk: "변경",
    tokenClearTitle: "HF 토큰을 지울까요?",
    tokenClearOk: "지우기",
    favRemove: "즐겨찾기에서 제거",
    favAdd: "즐겨찾기에 추가",
    searchToBrowse: "저장소를 보려면 검색하세요",
    noFilterMatches: "필터와 일치하는 항목 없음",
    selectRepo: "← 저장소를 선택하세요",
    searching: "검색 중…",
    noResults: "결과 없음",
    errorWord: "오류",
    showBench: "벤치마크 표시",
    loading: "로딩 중…",
    noGguf: "GGUF 파일을 찾지 못함",
    selectForDownload: "다운로드 대상으로 선택",
    deleteLocalTitle: "로컬 파일 삭제",
    deleteLocalConfirm: "로컬 파일을 삭제할까요?",
    deleteWord: "삭제",
    deleteFailed: "삭제 실패: {err}",
    benchLoading: "Artificial Analysis 데이터 로딩 중…",
    onDiskTitle: "다운로드한 모델 관리",
  },
  vi: {
    treeQuants: "Phiên bản lượng tử hóa",
    treeSiblings: "Các bản lượng tử hóa khác của {base}",
    tokenNotSet: "chưa đặt — không dùng được các mô hình bị khóa",
    tokenChangeTitle: "Đổi token HF?",
    tokenChangeOk: "Đổi",
    tokenClearTitle: "Xóa token HF?",
    tokenClearOk: "Xóa",
    favRemove: "Bỏ khỏi yêu thích",
    favAdd: "Thêm vào yêu thích",
    searchToBrowse: "Tìm kiếm để duyệt các kho",
    noFilterMatches: "Không có kết quả khớp bộ lọc",
    selectRepo: "← Chọn một kho",
    searching: "Đang tìm…",
    noResults: "Không có kết quả",
    errorWord: "Lỗi",
    showBench: "Hiện benchmark",
    loading: "Đang tải…",
    noGguf: "Không tìm thấy tệp GGUF",
    selectForDownload: "Chọn để tải xuống",
    deleteLocalTitle: "Xóa tệp cục bộ",
    deleteLocalConfirm: "Xóa tệp cục bộ?",
    deleteWord: "Xóa",
    deleteFailed: "Xóa thất bại: {err}",
    benchLoading: "Đang tải dữ liệu từ Artificial Analysis…",
    onDiskTitle: "Quản lý mô hình đã tải",
  },
  it: {
    treeQuants: "Versioni quantizzate",
    treeSiblings: "Altre quantizzazioni di {base}",
    tokenNotSet: "non impostato — modelli gated non disponibili",
    tokenChangeTitle: "Cambiare il token HF?",
    tokenChangeOk: "Cambia",
    tokenClearTitle: "Rimuovere il token HF?",
    tokenClearOk: "Rimuovi",
    favRemove: "Rimuovi dai preferiti",
    favAdd: "Aggiungi ai preferiti",
    searchToBrowse: "Cerca per sfogliare i repository",
    noFilterMatches: "Nessuna corrispondenza per il filtro",
    selectRepo: "← Seleziona un repository",
    searching: "Ricerca…",
    noResults: "Nessun risultato",
    errorWord: "Errore",
    showBench: "Mostra benchmark",
    loading: "Caricamento…",
    noGguf: "Nessun file GGUF trovato",
    selectForDownload: "Seleziona per il download",
    deleteLocalTitle: "Elimina file locale",
    deleteLocalConfirm: "Eliminare il file locale?",
    deleteWord: "Elimina",
    deleteFailed: "Eliminazione non riuscita: {err}",
    benchLoading: "Caricamento dati da Artificial Analysis…",
    onDiskTitle: "Gestisci i modelli scaricati",
  },
  te: {
    treeQuants: "క్వాంటైజ్డ్ వెర్షన్లు",
    treeSiblings: "{base} ఇతర క్వాంట్లు",
    tokenNotSet: "సెట్ కాలేదు — గేటెడ్ మోడల్‌లు అందుబాటులో లేవు",
    tokenChangeTitle: "HF టోకెన్‌ను మార్చాలా?",
    tokenChangeOk: "మార్చండి",
    tokenClearTitle: "HF టోకెన్‌ను క్లియర్ చేయాలా?",
    tokenClearOk: "క్లియర్ చేయండి",
    favRemove: "ఇష్టమైనవాటి నుండి తీసివేయండి",
    favAdd: "ఇష్టమైనవాటికి జోడించండి",
    searchToBrowse: "రిపోజిటరీలను బ్రౌజ్ చేయడానికి వెతకండి",
    noFilterMatches: "ఫిల్టర్‌కు సరిపోలేవి లేవు",
    selectRepo: "← రిపోజిటరీని ఎంచుకోండి",
    searching: "వెతుకుతోంది…",
    noResults: "ఫలితాలు లేవు",
    errorWord: "లోపం",
    showBench: "బెంచ్‌మార్క్‌లను చూపించండి",
    loading: "లోడ్ అవుతోంది…",
    noGguf: "GGUF ఫైళ్లు కనుగొనబడలేదు",
    selectForDownload: "డౌన్‌లోడ్ కోసం ఎంచుకోండి",
    deleteLocalTitle: "లోకల్ ఫైల్‌ను తొలగించండి",
    deleteLocalConfirm: "లోకల్ ఫైల్‌ను తొలగించాలా?",
    deleteWord: "తొలగించండి",
    deleteFailed: "తొలగించడం విఫలమైంది: {err}",
    benchLoading: "Artificial Analysis నుండి డేటా లోడ్ అవుతోంది…",
    onDiskTitle: "డౌన్‌లోడ్ చేసిన మోడల్‌లను నిర్వహించండి",
  },
  mr: {
    treeQuants: "क्वांटाइज्ड आवृत्त्या",
    treeSiblings: "{base} च्या इतर क्वांट आवृत्त्या",
    tokenNotSet: "सेट केलेले नाही — गेटेड मॉडेल्स अनुपलब्ध",
    tokenChangeTitle: "HF टोकन बदलायचे?",
    tokenChangeOk: "बदला",
    tokenClearTitle: "HF टोकन काढायचे?",
    tokenClearOk: "काढा",
    favRemove: "आवडत्यांमधून काढा",
    favAdd: "आवडत्यांमध्ये जोडा",
    searchToBrowse: "रिपॉझिटरी ब्राउझ करण्यासाठी शोधा",
    noFilterMatches: "फिल्टरसाठी काहीही जुळत नाही",
    selectRepo: "← रिपॉझिटरी निवडा",
    searching: "शोधत आहे…",
    noResults: "काही निकाल नाही",
    errorWord: "त्रुटी",
    showBench: "बेंचमार्क दाखवा",
    loading: "लोड होत आहे…",
    noGguf: "कोणत्याही GGUF फाइल्स सापडल्या नाहीत",
    selectForDownload: "डाउनलोडसाठी निवडा",
    deleteLocalTitle: "स्थानिक फाइल हटवा",
    deleteLocalConfirm: "स्थानिक फाइल हटवायची?",
    deleteWord: "हटवा",
    deleteFailed: "हटवणे अयशस्वी: {err}",
    benchLoading: "Artificial Analysis कडून डेटा लोड होत आहे…",
    onDiskTitle: "डाउनलोड केलेली मॉडेल्स व्यवस्थापित करा",
  },
  ta: {
    treeQuants: "குவாண்டைஸ் பதிப்புகள்",
    treeSiblings: "{base} இன் பிற குவாண்ட்கள்",
    tokenNotSet: "அமைக்கப்படவில்லை — கேட் செய்யப்பட்ட மாதிரிகள் கிடைக்காது",
    tokenChangeTitle: "HF டோக்கனை மாற்றவா?",
    tokenChangeOk: "மாற்று",
    tokenClearTitle: "HF டோக்கனை அழிக்கவா?",
    tokenClearOk: "அழி",
    favRemove: "பிடித்தவைகளிலிருந்து அகற்று",
    favAdd: "பிடித்தவைகளில் சேர்",
    searchToBrowse: "களஞ்சியங்களை உலாவ தேடவும்",
    noFilterMatches: "வடிகட்டிக்கு பொருத்தங்கள் இல்லை",
    selectRepo: "← ஒரு களஞ்சியத்தைத் தேர்வுசெய்",
    searching: "தேடுகிறது…",
    noResults: "முடிவுகள் இல்லை",
    errorWord: "பிழை",
    showBench: "பென்ச்மார்க்குகளைக் காட்டு",
    loading: "ஏற்றுகிறது…",
    noGguf: "GGUF கோப்புகள் எதுவும் கிடைக்கவில்லை",
    selectForDownload: "பதிவிறக்கத்திற்குத் தேர்வுசெய்",
    deleteLocalTitle: "உள்ளூர் கோப்பை நீக்கு",
    deleteLocalConfirm: "உள்ளூர் கோப்பை நீக்கவா?",
    deleteWord: "நீக்கு",
    deleteFailed: "நீக்குவது தோல்வியுற்றது: {err}",
    benchLoading: "Artificial Analysis இலிருந்து தரவு ஏற்றப்படுகிறது…",
    onDiskTitle: "பதிவிறக்கிய மாதிரிகளை நிர்வகி",
  },
};
function hfT(key, vars = {}) {
  const lang = localStorage.getItem("llamacppAdminLang") || "en";
  let text = (HFS[lang] || HFS.en)[key] || HFS.en[key] || key;
  Object.entries(vars).forEach(([n, v]) => { text = text.replace(`{${n}}`, v); });
  return text;
}
document.addEventListener("DOMContentLoaded", () => {
  const od = document.getElementById("hfOnDiskBtn");
  if (od) od.title = hfT("onDiskTitle");
});

function hfConfirm(title, body, okLabel = "Delete", danger = true) {
  return new Promise(resolve => {
    const overlay = document.createElement("div");
    overlay.className = "hf-confirm-overlay";
    overlay.innerHTML =
      `<div class="hf-confirm-box">` +
        `<div class="hf-confirm-title">${escapeHtml(title)}</div>` +
        (body ? `<div class="hf-confirm-body">${escapeHtml(body)}</div>` : "") +
        `<div class="hf-confirm-actions">` +
          `<button class="hf-confirm-cancel">Cancel</button>` +
          `<button class="hf-confirm-ok ${danger ? "danger" : "primary"}">${escapeHtml(okLabel)}</button>` +
        `</div>` +
      `</div>`;
    const close = (val) => { overlay.remove(); resolve(val); };
    overlay.addEventListener("click", e => { if (e.target === overlay) close(false); });
    overlay.querySelector(".hf-confirm-cancel").addEventListener("click", () => close(false));
    overlay.querySelector(".hf-confirm-ok").addEventListener("click", () => close(true));
    document.body.appendChild(overlay);
    overlay.querySelector(".hf-confirm-ok").focus();
  });
}

const searchInput   = $("hfSearchInput");
const searchBtn     = $("hfSearchBtn");
const limitSelect   = $("hfLimitSelect");
const repoCol       = $("hfRepoCol");
const fileCol       = $("hfFileCol");
const dlPanel       = $("hfDownloadPanel");

// ── token ─────────────────────────────────────────────────────────────────────

const tokenStatus   = $("hfTokenStatus");
const tokenInput    = $("hfTokenInput");
const tokenSaveBtn  = $("hfTokenSaveBtn");
const tokenEditBtn  = $("hfTokenEditBtn");
const tokenClearBtn = $("hfTokenClearBtn");

function renderTokenState(data) {
  if (data.set) {
    tokenStatus.textContent = data.masked;
    tokenStatus.className = "hf-token-status is-set";
    tokenClearBtn.hidden = false;
  } else {
    tokenStatus.textContent = hfT("tokenNotSet");
    tokenStatus.className = "hf-token-status";
    tokenClearBtn.hidden = true;
  }
  tokenStatus.hidden = false;
  tokenInput.hidden = true;
  tokenSaveBtn.hidden = true;
  tokenEditBtn.hidden = false;
  tokenInput.value = "";
}

async function loadTokenStatus() {
  try {
    const data = await fetch("/api/hf/token").then(r => r.json());
    renderTokenState(data);
  } catch (_) {}
}

tokenEditBtn.addEventListener("click", async () => {
  if (!(await hfConfirm(hfT("tokenChangeTitle"), "", hfT("tokenChangeOk"), false))) return;
  tokenStatus.hidden = true;
  tokenEditBtn.hidden = true;
  tokenInput.hidden = false;
  tokenSaveBtn.hidden = false;
  tokenInput.focus();
});
tokenSaveBtn.addEventListener("click", saveToken);
tokenInput.addEventListener("keydown", e => {
  if (e.key === "Enter") saveToken();
  if (e.key === "Escape") loadTokenStatus();
});

async function saveToken() {
  const val = tokenInput.value.trim();
  tokenSaveBtn.disabled = true;
  try {
    const data = await fetch("/api/hf/token", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token: val}),
    }).then(r => r.json());
    renderTokenState(data);
  } catch (e) {
    hfToast(e.message);
  } finally {
    tokenSaveBtn.disabled = false;
  }
}

tokenClearBtn.addEventListener("click", async () => {
  if (!(await hfConfirm(hfT("tokenClearTitle"), "", hfT("tokenClearOk")))) return;
  await fetch("/api/hf/token", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({token: ""}),
  });
  await loadTokenStatus();
});

// ── favorites ─────────────────────────────────────────────────────────────────

let favRepos = [];
// [{id, downloads, likes}, ...]

// ── filter / sort state ───────────────────────────────────────────────────────

let filterParamRange = 'all';   // 'all'|'0-9'|'10-19'|'20-29'|'30-39'|'40-74'|'75+'
let filterTypes = new Set();    // активные типы ('it','mmproj','mtp')
let filterMask = '';            // подстрока по имени репо
let sortKey = 'downloads';      // 'downloads'|'likes'|'params'|'date'|'aa'|'olb'
let sortDir = 'desc';
let searchResults = [];         // repos из последнего поиска
let discoveredTypes = new Set(); // типы найденные при загрузке файлов
let _filesLoadDone = 0, _filesLoadTotal = 0;
let _benchLoadDone = 0, _benchLoadTotal = 0;

function isFav(repoId) { return favRepos.some(r => r.id === repoId); }

async function saveFavs() {
  try {
    await fetch("/api/hf/favorites", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({favorites: favRepos}),
    });
  } catch (_) {}
}

async function loadFavs() {
  try {
    const data = await fetch("/api/hf/favorites").then(r => r.json());
    if (data.ok && Array.isArray(data.favorites)) {
      favRepos = data.favorites;
      renderAll();
      loadAllFilesBg(favRepos);
      loadAllBenchmarksBg(favRepos);
    }
  } catch (_) {}
}

function toggleFavorite(repo) {
  if (isFav(repo.id)) {
    favRepos = favRepos.filter(r => r.id !== repo.id);
  } else {
    favRepos = [repo, ...favRepos];
  }
  saveFavs();
  renderAll();
  refreshStarButtons(repo.id);
}

function refreshStarButtons(repoId) {
  const starred = isFav(repoId);
  for (const btn of document.querySelectorAll(`.hf-repo-row[data-repo-id] .hf-star-btn`)) {
    const row = btn.closest(".hf-repo-row");
    if (row?.dataset.repoId === repoId) setStarBtn(btn, starred);
  }
}

function setStarBtn(btn, starred) {
  btn.textContent = starred ? "★" : "☆";
  btn.title = starred ? hfT("favRemove") : hfT("favAdd");
  btn.classList.toggle("is-starred", starred);
}

// ── left panel structure ──────────────────────────────────────────────────────

const favSection  = document.createElement("div");
favSection.className = "hf-fav-section";
favSection.hidden = true;

const resultsList = document.createElement("div");
resultsList.className = "hf-results-list";
resultsList.innerHTML = `<div class="hf-file-empty" style="padding:20px;text-align:center;color:var(--muted)">${hfT("searchToBrowse")}</div>`;

repoCol.appendChild(buildFilterBar());
repoCol.appendChild(favSection);
repoCol.appendChild(resultsList);

let favExpanded = true;

// ── helper functions ──────────────────────────────────────────────────────────

function extractParamsNum(repoId) {
  const m = repoId.split("/").pop().match(/(?:^|[-_])(\d+(?:\.\d+)?)[Bb](?:[-_]|$)/);
  return m ? parseFloat(m[1]) : null;
}

function passesAllFilters(repo) {
  // param range
  if (filterParamRange !== 'all') {
    const n = extractParamsNum(repo.id);
    if (n !== null) {
      const ranges = {'0-9':[0,9],'10-19':[10,19],'20-29':[20,29],'30-39':[30,39],'40-74':[40,74],'75+':[75,Infinity]};
      const [lo, hi] = ranges[filterParamRange] || [0, Infinity];
      if (n < lo || n > hi) return false;
    }
  }
  // type filter
  if (filterTypes.size > 0) {
    const files = filesCache.get(repo.id);
    const kinds = files ? new Set(files.map(f => f.kind)) : new Set();
    if (inferIt(repo.id)) kinds.add('it');
    if (inferVision(repo.id, kinds)) kinds.add('vision');
    if (inferAudio(repo.id)) kinds.add('audio');
    if (inferUncensored(repo.id)) kinds.add('uncensored');
    const hasAny = [...filterTypes].some(t => kinds.has(t));
    if (!hasAny && files) return false; // exclude only when files loaded
  }
  // mask
  if (filterMask && !repo.id.toLowerCase().includes(filterMask.toLowerCase())) return false;
  return true;
}

function sortRepos(repos) {
  return [...repos].sort((a, b) => {
    let va, vb;
    switch(sortKey) {
      case 'downloads': va = a.downloads||0; vb = b.downloads||0; break;
      case 'likes':     va = a.likes||0;     vb = b.likes||0;     break;
      case 'params':    va = extractParamsNum(a.id)??-1; vb = extractParamsNum(b.id)??-1; break;
      case 'date':      va = a.createdAt||''; vb = b.createdAt||''; break;
      case 'aa':        va = benchCache.get(a.id)?.scores?.aa_intelligence??-1; vb = benchCache.get(b.id)?.scores?.aa_intelligence??-1; break;
      case 'olb':       va = benchCache.get(a.id)?.scores?.open_llm_avg??-1;   vb = benchCache.get(b.id)?.scores?.open_llm_avg??-1;   break;
      default: return 0;
    }
    if (sortDir==='desc') return vb>va?1:vb<va?-1:0;
    return va>vb?1:va<vb?-1:0;
  });
}

// ── renderAll ─────────────────────────────────────────────────────────────────

function renderAll() {
  const filtFavs    = sortRepos(favRepos.filter(passesAllFilters));
  const filtResults = sortRepos(searchResults.filter(passesAllFilters));
  renderFavSection(filtFavs);
  renderResultsSection(filtResults);
}

// ── renderFavSection ──────────────────────────────────────────────────────────

function renderFavSection(filteredFavs) {
  if (!filteredFavs) filteredFavs = sortRepos(favRepos.filter(passesAllFilters));
  if (!favRepos.length) { favSection.hidden = true; return; }
  favSection.hidden = false;

  const label = document.createElement("div");
  label.className = "hf-section-header hf-fav-header";
  label.innerHTML =
    `<span>★ FAVORITES (${filteredFavs.length} of ${favRepos.length})</span>` +
    `<span class="hf-fav-chevron">${favExpanded ? "▲" : "▼"}</span>`;
  label.addEventListener("click", () => {
    favExpanded = !favExpanded;
    renderFavSection();
  });

  favSection.innerHTML = "";
  favSection.appendChild(label);

  if (favExpanded) {
    for (const repo of filteredFavs) favSection.appendChild(buildRepoRow(repo));
  }
  favSection.insertAdjacentHTML("beforeend", `<div class="hf-section-divider"></div>`);
}

// ── renderResultsSection ──────────────────────────────────────────────────────

function renderResultsSection(repos) {
  resultsList.innerHTML = '';
  if (!searchResults.length) {
    resultsList.innerHTML = `<div class="hf-file-empty" style="padding:20px;text-align:center;color:var(--muted)">${hfT("searchToBrowse")}</div>`;
    return;
  }
  const hdr = document.createElement('div');
  hdr.className = 'hf-section-header hf-results-header';
  hdr.innerHTML = `<span>🔍 Results ${repos.length < searchResults.length ? repos.length + ' of ' + searchResults.length : repos.length}</span>`;
  resultsList.appendChild(hdr);
  if (!repos.length) {
    const el = document.createElement('div');
    el.className = 'hf-status'; el.style.padding = '12px';
    el.textContent = hfT("noFilterMatches");
    resultsList.appendChild(el);
    return;
  }
  for (const repo of repos) resultsList.appendChild(buildRepoRow(repo));
}

// ── badge helpers ─────────────────────────────────────────────────────────────

function inferIt(repoId) {
  return /[-_]it[-_\/]|[-_]it-gguf|[-_]it$/i.test(repoId);
}

function inferUncensored(repoId) {
  return /uncensored|heretic|abliterat|unfiltered|unrestricted/i.test(repoId);
}

// Input modalities from the HF model record (pipeline_tag + tags). These are
// authoritative for what the model accepts: "image-text-to-text" → vision,
// "audio-text-to-text" → audio, "any-to-any" → both. A loaded mmproj file is a
// secondary signal for vision (covers repos with no modality tags).
function _modalityTokens(repoId) {
  const m = repoModality.get(repoId) || {};
  const toks = [String(m.pipelineTag || ""), ...(m.tags || [])];
  return toks.join(" ").toLowerCase();
}
function inferVision(repoId, extraKinds) {
  if (extraKinds?.has("mmproj")) return true;
  return /image-text-to-text|any-to-any|\bvision\b|\bvlm\b|multimodal/.test(_modalityTokens(repoId));
}
function inferAudio(repoId) {
  return /audio-text-to-text|any-to-any|automatic-speech-recognition|\baudio\b/.test(_modalityTokens(repoId));
}

const TYPE_LABELS = {
  it: '🤖 it', mmproj: '📷 mmproj', mtp: '⚡ mtp',
  vision: '👁 vision', audio: '🎙 audio', uncensored: '🔞 uncensored',
};

function mbadge(type, text) {
  return `<span class="mbadge mbadge-${type}">${text}</span>`;
}

// Artifact format of a repo, best-effort: HF tags (search results carry them),
// then the loaded file panel, then the repo name. "" when unknown.
function repoFormatLabel(repoId) {
  const tags = ((repoModality.get(repoId) || {}).tags || []).map((x) => String(x).toLowerCase());
  if (tags.includes("gguf")) return "GGUF";
  const st = repoMetaCache.get(repoId)?.safetensors;
  if (st?.format) return "⚡ " + st.format;
  if (tags.includes("mlx")) return "MLX";
  const up = repoId.toUpperCase();
  if (up.endsWith("-GGUF") || up.includes("-GGUF-")) return "GGUF";
  for (const hint of ["NVFP4", "MXFP4", "AWQ", "GPTQ", "AUTOROUND", "FP8", "W4A16", "BNB"]) {
    if (up.includes(hint) || tags.includes(hint.toLowerCase())) return "⚡ " + hint;
  }
  if (tags.includes("safetensors")) return "⚡ ST";
  return "";
}

function buildBadgesHtml(repoId, extraKinds) {
  const badges = [];
  const fmt = repoFormatLabel(repoId);
  if (fmt) badges.push(mbadge("fmt", fmt));
  if (inferIt(repoId))            badges.push(mbadge("it", "🤖 it"));
  if (inferVision(repoId, extraKinds)) badges.push(mbadge("vision", "👁 vision"));
  if (inferAudio(repoId))         badges.push(mbadge("audio", "🎙 audio"));
  if (extraKinds?.has("mmproj"))  badges.push(mbadge("mmproj", "📷 mmproj"));
  if (extraKinds?.has("mtp"))     badges.push(mbadge("mtp", "⚡ mtp"));
  if (inferUncensored(repoId))    badges.push(mbadge("uncensored", "🔞 uncensored"));
  return badges.join("");
}

function updateRepoBadges(repoId) {
  const files = filesCache.get(repoId) || [];
  const kinds = new Set(files.map(f => f.kind));
  for (const row of document.querySelectorAll(`.hf-repo-row[data-repo-id="${CSS.escape(repoId)}"]`)) {
    const container = row.querySelector(".hf-repo-badges");
    if (container) container.innerHTML = buildBadgesHtml(repoId, kinds);
  }
}

// ── state ─────────────────────────────────────────────────────────────────────

let activeRepoId = null;
const filesCache  = new Map();
const repoMetaCache = new Map(); // repoId → { lastModified }
const treeCache = new Map(); // repoId → {quantizations, base, siblings} | null while in flight
const repoModality = new Map(); // repoId → { pipelineTag, tags:[] } from HF
const checkedMap  = new Map();
const localCache  = new Map(); // repoId → Set of local filenames

function getChecked(repoId) {
  if (!checkedMap.has(repoId)) checkedMap.set(repoId, new Set());
  return checkedMap.get(repoId);
}

// ── search ────────────────────────────────────────────────────────────────────

searchBtn.addEventListener("click", doSearch);
searchInput.addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });

async function doSearch() {
  const q = searchInput.value.trim();
  if (!q) return;

  resultsList.innerHTML = `<div class="hf-status">${hfT("searching")}</div>`;
  fileCol.innerHTML = `<div class="hf-file-empty">${hfT("selectRepo")}</div>`;
  activeRepoId = null;
  filesCache.clear();
  checkedMap.clear();
  refreshDownloadPanel(); // clears selection rows but keeps active download progress
  searchBtn.disabled = true;
  searchResults = [];

  const limit = limitSelect?.value || "20";

  try {
    const data = await fetch(`/api/hf/search?q=${encodeURIComponent(q)}&limit=${limit}`).then(r => r.json());
    if (!data.ok) { resultsList.innerHTML = `<div class="hf-error">${escapeHtml(data.error || hfT("errorWord"))}</div>`; return; }
    if (!data.repos.length) { resultsList.innerHTML = `<div class="hf-status">${hfT("noResults")}</div>`; return; }

    searchResults = data.repos;
    for (const r of data.repos) {
      if (r.pipelineTag || (r.tags && r.tags.length))
        repoModality.set(r.id, {pipelineTag: r.pipelineTag || "", tags: r.tags || []});
    }
    renderAll();

    if (q.includes("/") && data.repos.length === 1) {
      selectRepo(data.repos[0].id);
    }

    // deduplicate by id
    const allRepos = [...favRepos, ...searchResults].filter(
      (r, i, arr) => arr.findIndex(x => x.id === r.id) === i
    );
    loadAllFilesBg(allRepos);
    loadAllBenchmarksBg(allRepos);
  } catch (e) {
    resultsList.innerHTML = `<div class="hf-error">${escapeHtml(e.message)}</div>`;
  } finally {
    searchBtn.disabled = false;
  }
}

// ── background loaders ────────────────────────────────────────────────────────

async function loadAllFilesBg(repos) {
  const toLoad = repos.filter(r => !filesCache.has(r.id));
  _filesLoadTotal = toLoad.length;
  _filesLoadDone = 0;
  if (!toLoad.length) { updateProgress(); return; }
  updateProgress();
  const CONCURRENCY = 5;
  const queue = [...toLoad];
  async function worker() {
    while (queue.length) {
      const repo = queue.shift();
      if (!repo) break;
      try {
        const data = await fetch(`/api/hf/files?repo=${encodeURIComponent(repo.id)}`).then(r => r.json());
        if (data.ok) {
          const ORDER = {model:0,mmproj:1,mtp:2,vocab:3};
          filesCache.set(repo.id, data.files.sort((a,b) => {
            const d = (ORDER[a.kind]??9) - (ORDER[b.kind]??9);
            return d !== 0 ? d : a.quant < b.quant ? -1 : 1;
          }));
          repoMetaCache.set(repo.id, {lastModified: data.lastModified||'',
                                      safetensors: data.safetensors || null,
                                      otherFiles: data.otherFiles || []});
          // update discovered types
          for (const f of data.files) {
            if (['mmproj','mtp','vision'].includes(f.kind)) discoveredTypes.add(f.kind);
          }
          const _kinds = new Set(data.files.map(f => f.kind));
          if (inferIt(repo.id)) discoveredTypes.add('it');
          if (inferVision(repo.id, _kinds)) discoveredTypes.add('vision');
          if (inferAudio(repo.id)) discoveredTypes.add('audio');
          if (inferUncensored(repo.id)) discoveredTypes.add('uncensored');
          updateRepoBadges(repo.id);
          refreshRepoRowDate(repo.id);
          updateTypeChips();
        }
      } catch (_) {}
      _filesLoadDone++;
      updateProgress();
    }
  }
  await Promise.all(Array.from({length: CONCURRENCY}, worker));
  updateProgress();
}

async function loadAllBenchmarksBg(repos) {
  const toLoad = repos.filter(r => !benchCache.has(r.id));
  _benchLoadTotal = toLoad.length;
  _benchLoadDone = 0;
  if (!toLoad.length) { updateProgress(); return; }
  updateProgress();
  for (const repo of toLoad) {
    try { await loadBenchmarks(repo.id); } catch(_) {}
    _benchLoadDone++;
    updateProgress();
    renderAll();
    await new Promise(r => setTimeout(r, 80));
  }
  updateProgress();
}

// ── progress & type chips ─────────────────────────────────────────────────────

function updateProgress() {
  const bar  = $('hfLoadProgress');
  const fill = $('hfLoadFill');
  const text = $('hfLoadText');
  if (!bar) return;
  const filesRunning = _filesLoadTotal > 0 && _filesLoadDone < _filesLoadTotal;
  const benchRunning = _benchLoadTotal > 0 && _benchLoadDone < _benchLoadTotal;
  if (!filesRunning && !benchRunning) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  if (filesRunning) {
    const pct = _filesLoadTotal ? (_filesLoadDone / _filesLoadTotal * 100) : 0;
    fill.style.width = pct + '%';
    text.textContent = `files ${_filesLoadDone}/${_filesLoadTotal}`;
  } else {
    const pct = _benchLoadTotal ? (_benchLoadDone / _benchLoadTotal * 100) : 0;
    fill.style.width = pct + '%';
    text.textContent = `benchmarks ${_benchLoadDone}/${_benchLoadTotal}`;
  }
}

function updateTypeChips() {
  const container = $('hfTypeChips');
  const row = $('hfTypeFilterRow');
  if (!container || !row) return;
  if (discoveredTypes.size === 0) { row.style.display = 'none'; return; }
  row.style.display = '';
  container.innerHTML = [...discoveredTypes].sort().map(t =>
    `<button class="hf-chip${filterTypes.has(t) ? ' is-active' : ''}" data-type="${escapeHtml(t)}">${escapeHtml(TYPE_LABELS[t] || t)}</button>`
  ).join('');
  container.querySelectorAll('.hf-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const t = btn.dataset.type;
      filterTypes.has(t) ? filterTypes.delete(t) : filterTypes.add(t);
      renderAll(); updateTypeChips();
    });
  });
}

// ── filter bar ────────────────────────────────────────────────────────────────

function buildFilterBar() {
  const bar = document.createElement('div');
  bar.className = 'hf-filter-bar';
  bar.id = 'hfFilterBar';
  bar.innerHTML = `
    <div class="hf-filter-row">
      <span class="hf-filter-label">Size:</span>
      <div class="hf-chips" id="hfParamChips">
        <button class="hf-chip is-active" data-range="all">All</button>
        <button class="hf-chip" data-range="0-9">≤9B</button>
        <button class="hf-chip" data-range="10-19">10–19B</button>
        <button class="hf-chip" data-range="20-29">20–29B</button>
        <button class="hf-chip" data-range="30-39">30–39B</button>
        <button class="hf-chip" data-range="40-74">40–74B</button>
        <button class="hf-chip" data-range="75+">75B+</button>
      </div>
    </div>
    <div class="hf-filter-row" id="hfTypeFilterRow" style="display:none">
      <span class="hf-filter-label">Type:</span>
      <div class="hf-chips" id="hfTypeChips"></div>
    </div>
    <div class="hf-filter-row">
      <input class="hf-mask-input" id="hfMaskInput" placeholder="filter by name…" type="text">
      <select class="hf-sort-select" id="hfSortSelect">
        <option value="downloads-desc">↓ Downloads</option>
        <option value="downloads-asc">↑ Downloads</option>
        <option value="likes-desc">↓ Likes</option>
        <option value="likes-asc">↑ Likes</option>
        <option value="params-desc">↓ Size</option>
        <option value="params-asc">↑ Size</option>
        <option value="date-desc">↓ Date</option>
        <option value="date-asc">↑ Date</option>
        <option value="aa-desc">↓ AA Score</option>
        <option value="olb-desc">↓ Open LLM</option>
      </select>
    </div>
    <div class="hf-load-progress" id="hfLoadProgress" style="display:none">
      <div class="hf-load-bar-track"><div class="hf-load-bar-fill" id="hfLoadFill"></div></div>
      <span class="hf-load-text" id="hfLoadText"></span>
    </div>
  `;
  // wire up param chips
  bar.querySelectorAll('#hfParamChips .hf-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      bar.querySelectorAll('#hfParamChips .hf-chip').forEach(b => b.classList.remove('is-active'));
      btn.classList.add('is-active');
      filterParamRange = btn.dataset.range;
      renderAll();
    });
  });
  // wire up mask input
  bar.querySelector('#hfMaskInput').addEventListener('input', e => {
    filterMask = e.target.value;
    renderAll();
  });
  // wire up sort select
  bar.querySelector('#hfSortSelect').addEventListener('change', e => {
    const [k, d] = e.target.value.split('-');
    sortKey = k; sortDir = d;
    renderAll();
  });
  return bar;
}

// ── prefetchBadges (kept for compatibility, not called directly) ──────────────

async function prefetchBadges(repos) {
  // Replaced by loadAllFilesBg — kept as no-op to avoid reference errors
}

function _repoDateHtml(repoId, createdAt) {
  const iso = createdAt || repoMetaCache.get(repoId)?.lastModified || "";
  if (!iso) return "";
  return ` · <span class="hf-repo-date" title="${escapeHtml(iso)}">${escapeHtml(fmtDate(iso))}</span>`;
}

function refreshRepoRowDate(repoId) {
  for (const row of document.querySelectorAll(`.hf-repo-row[data-repo-id="${CSS.escape(repoId)}"]`)) {
    const slot = row.querySelector(".hf-repo-date-slot");
    if (slot) slot.innerHTML = _repoDateHtml(repoId, null);
  }
}

// ── repo row (left panel) ─────────────────────────────────────────────────────

function buildRepoRow(repo) {
  const div = document.createElement("div");
  div.className = "hf-repo-row";
  div.dataset.repoId = repo.id;

  const starred = isFav(repo.id);
  div.innerHTML =
    `<div class="hf-repo-row-top">` +
      `<span class="hf-repo-row-id">${escapeHtml(repo.id)}</span>` +
      `<button class="hf-star-btn${starred ? " is-starred" : ""}" title="${starred ? hfT("favRemove") : hfT("favAdd")}">${starred ? "★" : "☆"}</button>` +
    `</div>` +
    `<div class="hf-repo-row-bottom">` +
      `<span class="hf-repo-row-meta">↓ ${fmtNum(repo.downloads)} · ♥ ${fmtNum(repo.likes)}${extractParams(repo.id) ? ` · <span class="hf-repo-params">${extractParams(repo.id)}</span>` : ""}<span class="hf-repo-date-slot">${_repoDateHtml(repo.id, repo.createdAt)}</span></span>` +
      `<div class="hf-repo-badges">${buildBadgesHtml(repo.id, filesCache.get(repo.id) ? new Set(filesCache.get(repo.id).map(f=>f.kind)) : null)}</div>` +
      `<button class="hf-bench-toggle" title="${hfT("showBench")}">📊</button>` +
    `</div>` +
    `<div class="hf-bench-inline"></div>`;

  div.querySelector(".hf-star-btn").addEventListener("click", e => {
    e.stopPropagation();
    toggleFavorite(repo);
  });

  const benchBtn = div.querySelector(".hf-bench-toggle");
  benchBtn.addEventListener("click", e => {
    e.stopPropagation();
    toggleBenchPanel(repo.id, benchBtn);
  });

  // If benchmarks are already cached, fill inline chips directly on this element
  const bdata = benchCache.get(repo.id);
  if (bdata && bdata.scores) _applyBenchInline(div, bdata);

  div.addEventListener("click", () => selectRepo(repo.id));
  return div;
}

// ── select repo → load files into right panel ─────────────────────────────────

function ensureModelTree(repoId) {
  if (treeCache.has(repoId)) return; // loaded or in flight
  treeCache.set(repoId, null);
  fetch(`/api/hf/model-tree?repo=${encodeURIComponent(repoId)}`)
    .then(r => r.json())
    .then(d => {
      if (!d?.ok) { treeCache.delete(repoId); return; }
      treeCache.set(repoId, d);
      if (activeRepoId === repoId) renderFilePanel(repoId);
    })
    .catch(() => treeCache.delete(repoId));
}

async function selectRepo(repoId) {
  activeRepoId = repoId;
  ensureModelTree(repoId);

  document.querySelectorAll(".hf-repo-row").forEach(el =>
    el.classList.toggle("is-active", el.dataset.repoId === repoId)
  );

  if (filesCache.has(repoId)) {
    renderFilePanel(repoId);
    // Refresh local markers in the background without re-fetching the file list.
    fetch(`/api/hf/local-check?repo=${encodeURIComponent(repoId)}`)
      .then(r => r.json()).then(d => {
        if (d?.ok) { localCache.set(repoId, new Set(d.localNames)); renderFilePanel(repoId); }
      }).catch(() => {});
    return;
  }

  fileCol.innerHTML =
    `<div class="hf-file-col-header"><span class="hf-file-col-title">${escapeHtml(repoId)}</span></div>` +
    `<div class="hf-status">${hfT("loading")}</div>`;

  try {
    const [filesData, localData] = await Promise.all([
      fetch(`/api/hf/files?repo=${encodeURIComponent(repoId)}`).then(r => r.json()),
      fetch(`/api/hf/local-check?repo=${encodeURIComponent(repoId)}`).then(r => r.json()).catch(() => null),
    ]);

    if (localData?.ok) localCache.set(repoId, new Set(localData.localNames));

    if (!filesData.ok) {
      fileCol.innerHTML =
        `<div class="hf-file-col-header"><span class="hf-file-col-title">${escapeHtml(repoId)}</span></div>` +
        `<div class="hf-error" style="margin:12px">${escapeHtml(filesData.error || hfT("errorWord"))}</div>`;
      return;
    }
    const ORDER = { model: 0, mmproj: 1, mtp: 2, vocab: 3 };
    filesCache.set(repoId, filesData.files.sort((a, b) => {
      const d = (ORDER[a.kind] ?? 9) - (ORDER[b.kind] ?? 9);
      return d !== 0 ? d : a.quant < b.quant ? -1 : 1;
    }));
    repoMetaCache.set(repoId, { lastModified: filesData.lastModified || "",
                                safetensors: filesData.safetensors || null,
                                otherFiles: filesData.otherFiles || [] });
    updateRepoBadges(repoId);
    refreshRepoRowDate(repoId);
    renderFilePanel(repoId);
  } catch (e) {
    fileCol.innerHTML =
      `<div class="hf-file-col-header"><span class="hf-file-col-title">${escapeHtml(repoId)}</span></div>` +
      `<div class="hf-error" style="margin:12px">${escapeHtml(e.message)}</div>`;
  }
}

// ── file panel (right column) ─────────────────────────────────────────────────

const LOW_QUANT_RE = /\b(IQ[123]_|Q[23]_)/i;

function isLowQuant(quant) {
  return !!quant && LOW_QUANT_RE.test(quant);
}

function renderFilePanel(repoId) {
  const files   = filesCache.get(repoId) || [];
  const checked = getChecked(repoId);

  fileCol.innerHTML = "";

  const meta = repoMetaCache.get(repoId) || {};
  const header = document.createElement("div");
  header.className = "hf-file-col-header";
  header.innerHTML =
    `<span class="hf-file-col-title">${escapeHtml(repoId)}</span>` +
    (meta.lastModified
      ? `<span class="hf-repo-last-modified" title="Last modified: ${escapeHtml(meta.lastModified)}">updated ${escapeHtml(fmtDate(meta.lastModified))}</span>`
      : "");
  fileCol.appendChild(header);

  // safetensors checkpoint: ONE artifact row — the whole repo downloads into
  // <model>/<author>/<FORMAT>/… exactly like a gguf quant folder. No new
  // translatable words: format token, counts and sizes only.
  const st = meta.safetensors;
  if (st && st.files?.length) {
    const gb = (st.totalSize / 1e9).toFixed(2);
    const row = document.createElement("div");
    row.className = "hf-file hf-file-st";
    row.innerHTML =
      `<span class="hf-file-badge hf-badge-st">${escapeHtml(st.format)}</span>` +
      `<span class="hf-file-name">safetensors · ${st.files.length} × 📄</span>` +
      `<span class="hf-file-size">${gb} GB</span>` +
      `<button class="hf-file-dl" title="⬇ ${escapeHtml(st.format)}">⬇</button>`;
    row.querySelector(".hf-file-dl").addEventListener("click", () => downloadSafetensors(repoId, st));
    fileCol.appendChild(row);
  }

  // HF model tree, the actionable part: quantized descendants of this repo,
  // and — when the repo is itself a quant — the other quants of its base.
  // Rows are one click away from the same file panel (selectRepo).
  const renderModelTree = () => {
    const tree = treeCache.get(repoId);
    if (!tree) return;
    const sections = [
      { items: tree.quantizations || [], label: hfT("treeQuants"), open: true },
      { items: tree.siblings || [], label: hfT("treeSiblings", { base: tree.base }),
        open: !(tree.quantizations || []).length },
    ];
    for (const s of sections) {
      if (!s.items.length) continue;
      const det = document.createElement("details");
      det.className = "hf-model-tree";
      det.open = s.open;
      det.innerHTML =
        `<summary>🧬 ${escapeHtml(s.label)} · ${s.items.length}</summary>` +
        s.items.map(it =>
          `<div class="hf-tree-row" data-repo="${escapeHtml(it.id)}" title="${escapeHtml(it.id)}">` +
          `<span class="hf-file-badge hf-badge-st">${escapeHtml(it.format || "?")}</span>` +
          `<span class="hf-tree-id">${escapeHtml(it.id)}</span>` +
          `<span class="hf-tree-meta">⬇ ${fmtNum(it.downloads)}${it.likes ? " · ♥ " + fmtNum(it.likes) : ""}</span>` +
          `</div>`).join("");
      det.querySelectorAll(".hf-tree-row").forEach(rowEl =>
        rowEl.addEventListener("click", () => selectRepo(rowEl.dataset.repo)));
      fileCol.appendChild(det);
    }
  };

  // Everything the caravan cannot launch still deserves to be SEEN: a grey,
  // collapsed list at the bottom (README, onnx, tf, misc) — numbers only, no
  // download buttons.
  const renderOtherFiles = () => {
    const others = meta.otherFiles || [];
    if (!others.length) return;
    const bytes = others.reduce((a, f) => a + (f.size || 0), 0);
    const sizeLabel = bytes >= 1e9 ? (bytes / 1e9).toFixed(2) + " GB"
                    : bytes >= 1e6 ? Math.round(bytes / 1e6) + " MB"
                    : bytes > 0 ? Math.max(1, Math.round(bytes / 1e3)) + " KB" : "";
    const det = document.createElement("details");
    det.className = "hf-other-files";
    det.innerHTML =
      `<summary>… ${others.length} × 📄${sizeLabel ? " · " + sizeLabel : ""}</summary>` +
      others.map((f) => `<div class="hf-other-file"><span class="hf-file-name">${escapeHtml(f.name)}</span>` +
        `<span class="hf-file-size">${f.size ? (f.size >= 1e9 ? (f.size / 1e9).toFixed(2) + " GB" : Math.max(1, Math.round(f.size / 1e6)) + " MB") : ""}</span></div>`).join("");
    fileCol.appendChild(det);
  };

  if (!files.length) {
    if (!st) fileCol.insertAdjacentHTML("beforeend", `<div class="hf-status">${hfT("noGguf")}</div>`);
    renderModelTree();
    renderOtherFiles();
    return;
  }

  const list = document.createElement("div");
  list.className = "hf-file-list";

  const localNames = localCache.get(repoId) || new Set();

  for (const f of files) {
    const isLocal = localNames.has(f.name);
    let cls = "hf-file";
    if (f.kind === "model" && isLowQuant(f.quant)) cls += " is-low-quant";
    if (isLocal) cls += " is-local";
    const row = document.createElement("div");
    row.className = cls;
    row._fileData = f;

    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.className = "hf-file-check";
    chk.checked = checked.has(f.path);
    chk.title = hfT("selectForDownload");

    chk.addEventListener("change", () => {
      if (chk.checked) checked.add(f.path);
      else checked.delete(f.path);
      refreshDownloadPanel();
      updateRecommendations(repoId);
    });

    row.appendChild(chk);
    row.insertAdjacentHTML("beforeend",
      `<span class="hf-file-local">${isLocal ? "✓" : ""}</span>` +
      `<span class="hf-file-kind hf-kind-${f.kind}">${f.kind}</span>` +
      `<span class="hf-file-name" title="${escapeHtml(f.path)}">${escapeHtml(f.name)}</span>` +
      `<span class="hf-file-quant">${escapeHtml(f.quant)}</span>` +
      `<span class="hf-file-size">${fmtBytes(f.size)}</span>` +
      `<span class="hf-file-date"${f.date ? ` title="${escapeHtml(f.date)}"` : ""}>${f.date ? escapeHtml(fmtDate(f.date)) : ""}</span>` +
      `<span class="hf-file-rec" hidden></span>` +
      (isLocal ? `<button class="hf-file-del" title="${hfT("deleteLocalTitle")}">🗑</button>` : `<span class="hf-file-del"></span>`)
    );

    if (isLocal) {
      const delBtn = row.querySelector(".hf-file-del");
      delBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!await hfConfirm(hfT("deleteLocalConfirm"), f.name, hfT("deleteWord"))) return;
        delBtn.disabled = true;
        delBtn.textContent = "…";
        const res = await fetch(
          `/api/hf/local-file?repo=${encodeURIComponent(repoId)}&name=${encodeURIComponent(f.name)}`,
          { method: "DELETE" }
        ).then(r => r.json()).catch(() => ({ ok: false, error: "network error" }));
        if (res.ok) {
          localCache.get(repoId)?.delete(f.name);
          renderFilePanel(repoId);
        } else {
          delBtn.disabled = false;
          delBtn.textContent = "🗑";
          hfToast(hfT("deleteFailed", { err: res.error }));
        }
      });
    }

    list.appendChild(row);
  }

  fileCol.appendChild(list);
  renderModelTree();
  renderOtherFiles();
}

// ── recommendations ───────────────────────────────────────────────────────────

const QUANT_RANK = {
  'IQ1_S':0.5,'IQ1_M':0.6,
  'IQ2_XXS':1,'IQ2_XS':1.2,'IQ2_S':1.4,'IQ2_M':1.6,
  'Q2_K':2,'Q2_K_S':2,'Q2_K_L':2.1,'Q2_K_XL':2.2,'Q2_K_XXL':2.3,
  'IQ3_XXS':2.5,'IQ3_XS':2.6,'IQ3_S':2.8,'IQ3_M':3,
  'Q3_K_S':3,'Q3_K_M':3.3,'Q3_K_L':3.6,'Q3_K_XL':3.8,'Q3_K_XXL':3.9,
  'IQ4_XS':3.8,'IQ4_NL':4,
  'Q4_0':4,'Q4_1':4.1,'Q4_K_S':4.2,'Q4_K_M':4.5,'Q4_K_L':4.8,'Q4_K_XL':4.9,'Q4_K_XXL':4.95,
  'Q5_0':5,'Q5_1':5.1,'Q5_K_S':5,'Q5_K_M':5.3,'Q5_K_L':5.6,'Q5_K_XL':5.8,'Q5_K_XXL':5.9,
  'Q6_K':6,'Q6_K_L':6.3,'Q6_K_XL':6.5,
  'Q8_0':8,
  'F16':15,'BF16':16,'F32':32,
};

function quantRank(q) {
  if (!q) return 5; // unknown → above threshold, show by default
  const v = QUANT_RANK[q];
  if (v !== undefined) return v;
  // pattern fallback for unlisted variants
  const u = q.toUpperCase();
  if (/^IQ1_/.test(u)) return 0.6;
  if (/^IQ2_/.test(u)) return 1.5;
  if (/^IQ3_/.test(u)) return 2.8;
  if (/^Q2_/.test(u))  return 2;
  if (/^Q3_/.test(u))  return 3.5;
  if (/^IQ4_/.test(u)) return 3.9;
  return 5; // anything else → show
}

function updateRecommendations(repoId) {
  const files   = filesCache.get(repoId) || [];
  const checked = getChecked(repoId);

  let modelRank = null;
  for (const f of files) {
    if (f.kind === "model" && checked.has(f.path)) {
      const r = quantRank(f.quant);
      if (modelRank === null || r > modelRank) modelRank = r;
    }
  }

  let recMtpPath = null;
  if (modelRank !== null) {
    let best = Infinity;
    for (const f of files) {
      if (f.kind !== "mtp") continue;
      const diff = Math.abs(quantRank(f.quant) - modelRank);
      if (diff < best) { best = diff; recMtpPath = f.path; }
    }
  }

  for (const row of fileCol.querySelectorAll(".hf-file")) {
    const f = row._fileData;
    if (!f) continue;
    const rec = row.querySelector(".hf-file-rec");
    if (!rec) continue;
    let label = null;
    if (modelRank !== null) {
      if (f.kind === "mtp" && f.path === recMtpPath) label = "rec";
      if (f.kind === "mmproj") label = "rec";
    }
    row.classList.toggle("is-recommended", label !== null);
    rec.hidden = label === null;
    rec.textContent = label || "";
  }
}

// ── download panel ────────────────────────────────────────────────────────────

// Active downloads — decoupled from the DOM so the panel can always re-render,
// and an array so several can run/render at once. Each entry is
// { uid, jobId, title, totalFiles, pct, labelText, labelCls, cancelled }.
let dlJobs = [];
let dlJobSeq = 0;

// Persist active downloads to localStorage so a page reload can re-attach to
// jobs still running on the server (their download threads outlive the page).
// Only live jobs are stored; done / error / cancelled ones are dropped.
const DL_STORE_KEY = "hfDlJobs";
function saveDlJobs() {
  try {
    const live = dlJobs
      .filter(j => j.jobId && !j.cancelled && j.labelCls !== "hf-dl-done" && j.labelCls !== "hf-dl-error")
      .map(j => ({ jobId: j.jobId, title: j.title, totalFiles: j.totalFiles }));
    localStorage.setItem(DL_STORE_KEY, JSON.stringify(live));
  } catch (_) { /* storage unavailable — skip */ }
}
async function restoreDlJobs() {
  // Prefer the server-side registry — it's shared across devices and survives a
  // hard reload. Fall back to localStorage if the endpoint isn't reachable.
  let jobs = null;
  try {
    const r = await fetch("/api/hf/download/jobs").then(x => x.json());
    if (r && r.ok && Array.isArray(r.jobs)) {
      jobs = r.jobs.map(j => ({ jobId: j.jobId, title: j.title, totalFiles: j.total_files }));
    }
  } catch (_) {}
  if (!jobs) {
    try { jobs = JSON.parse(localStorage.getItem(DL_STORE_KEY) || "[]"); } catch (_) { jobs = []; }
  }
  if (!Array.isArray(jobs)) return;
  for (const st of jobs) {
    if (!st || !st.jobId || dlJobs.some(j => j.jobId === st.jobId)) continue;
    const job = {
      uid: "dlj" + (++dlJobSeq), jobId: st.jobId, title: st.title || "",
      totalFiles: st.totalFiles || 1, pct: 0, labelText: "Resuming…", labelCls: "", cancelled: false,
    };
    dlJobs.push(job);
    pollDownload(job);
  }
  refreshDownloadPanel();
}

function refreshDownloadPanel() {
  saveDlJobs();
  const allFiles = [];
  for (const [repoId, paths] of checkedMap) {
    if (!paths.size) continue;
    for (const f of (filesCache.get(repoId) || [])) {
      if (paths.has(f.path)) allFiles.push({ repoId, file: f });
    }
  }

  const hasSelection = allFiles.length > 0;
  const hasJobs = dlJobs.length > 0;

  if (!hasSelection && !hasJobs) { dlPanel.hidden = true; dlPanel.innerHTML = ""; return; }

  // ── active job progress sections (one row per concurrent download) ──
  let progressHTML = "";
  for (const job of dlJobs) {
    const pct      = job.pct || 0;
    const labelCls = job.labelCls ? ` ${job.labelCls}` : "";
    const isTerminal = job.labelCls === "hf-dl-done" || job.labelCls === "hf-dl-error";
    const cancelBtn  = (!isTerminal && !job.cancelled)
      ? `<button class="hf-dl-btn hf-dl-btn-cancel" data-action="cancel-job" data-job="${job.uid}">Cancel</button>` : "";
    const titleHTML  = job.title
      ? `<div class="hf-dl-job-title" style="font-size:12px;opacity:.75;margin-bottom:2px">${escapeHtml(job.title)}</div>` : "";
    progressHTML +=
      `<div class="hf-dl-progress-row" style="display:flex;align-items:center;gap:10px;padding:8px 18px 4px">` +
        `<div style="flex:1;min-width:0">` +
          titleHTML +
          `<div class="hf-progress-bar"><div class="hf-progress-fill" style="width:${pct}%"></div></div>` +
          `<div class="hf-progress-label${labelCls}" style="margin-top:3px">${escapeHtml(job.labelText || "Starting…")}</div>` +
        `</div>` +
        cancelBtn +
      `</div>`;
  }

  // ── new selection section ──
  let selectionHTML = "";
  if (hasSelection) {
    const totalSize  = allFiles.reduce((s, { file: f }) => s + (f.size || 0), 0);
    const n          = allFiles.length;
    const lines      = allFiles.map(({ repoId, file: f }) => {
      const dir = computeDestDir(repoId, f);
      return `<div class="hf-dl-file">` +
        `<span class="hf-file-kind hf-kind-${f.kind}">${f.kind}</span>` +
        `<span class="hf-dl-dest">${escapeHtml(dir)}/<b>${escapeHtml(f.name)}</b></span>` +
        `<span class="hf-file-size">${fmtBytes(f.size)}</span>` +
        `</div>`;
    }).join("");
    const wasExpanded = dlPanel.querySelector(".hf-dl-body") && !dlPanel.querySelector(".hf-dl-body[hidden]");
    selectionHTML =
      `<div class="hf-dl-bar"${hasJobs ? ' style="border-top:1px solid var(--line)"' : ""}>` +
        `<span class="hf-dl-bar-label">↓ ${n} file${n !== 1 ? "s" : ""} selected — ${fmtBytes(totalSize)}</span>` +
        `<button class="hf-dl-toggle" data-expand>${wasExpanded ? "▲ hide" : "▼ details"}</button>` +
        `<button class="hf-dl-btn" data-action="start">↓ Download ${n} file${n !== 1 ? "s" : ""}</button>` +
      `</div>` +
      `<div class="hf-dl-body"${wasExpanded ? "" : " hidden"}>` +
        `<div class="hf-dl-preview">${lines}</div>` +
      `</div>`;
  }

  dlPanel.innerHTML = progressHTML + selectionHTML;
  dlPanel.hidden = false;

  dlPanel.querySelector("[data-expand]")?.addEventListener("click", () => {
    const body = dlPanel.querySelector(".hf-dl-body");
    const btn  = dlPanel.querySelector("[data-expand]");
    body.hidden = !body.hidden;
    btn.textContent = body.hidden ? "▼ details" : "▲ hide";
  });

  dlPanel.querySelectorAll("[data-action=cancel-job]").forEach(btn => {
    btn.addEventListener("click", () => {
      const job = dlJobs.find(j => j.uid === btn.getAttribute("data-job"));
      if (job) {
        job.cancelled = true;
        job.labelText = "Cancelled (current file will finish)";
        setTimeout(() => { dlJobs = dlJobs.filter(j => j !== job); refreshDownloadPanel(); }, 4000);
      }
      refreshDownloadPanel();
    });
  });

  if (hasSelection) {
    // One job per repo: the download endpoint takes a single repo id, so a
    // mixed-repo selection must not send other repos' paths under it (they
    // would 404 on the wrong repo URL and fail the whole job).
    dlPanel.querySelector("[data-action=start]").addEventListener("click", () => {
      const byRepo = new Map();
      for (const { repoId, file } of allFiles) {
        if (!byRepo.has(repoId)) byRepo.set(repoId, []);
        byRepo.get(repoId).push(file);
      }
      for (const [rid, files] of byRepo) {
        const payload = files.map(f => ({
          path: f.path, name: f.name, size: f.size, destDir: computeDestDir(rid, f),
        }));
        startDownload(rid, files, payload);
      }
    });
  }
}

// ── models-disk headroom: header badge + pre-download fit check ─────────────
let _diskInfo = null;
async function refreshDiskInfo() {
  try {
    _diskInfo = await fetch("/api/models/disk").then(r => r.json());
  } catch (_) { _diskInfo = null; }
  const el = document.getElementById("hfDiskBadge");
  if (!el) return;
  if (!_diskInfo || !_diskInfo.ok) { el.hidden = true; return; }
  const free = _diskInfo.freeGb;
  el.hidden = false;
  el.textContent = `disk: ${free} GB free`;
  el.title = `${_diskInfo.path} — ${free} GB free of ${_diskInfo.totalGb} GB`;
  el.classList.toggle("low", free < 50);
  el.classList.toggle("critical", free < 15);
}

// Returns true when the download should proceed. Blocks with a confirm()
// when the selection clearly does not fit (sizes are known from the file
// list; +5 GB slack for the .tmp copy during multi-part assembly).
function diskFitCheck(files) {
  if (!_diskInfo || !_diskInfo.ok) return true;
  const needGb = files.reduce((a, f) => a + (Number(f.size) || 0), 0) / 2 ** 30 + 5;
  const freeGb = Number(_diskInfo.freeGb) || 0;
  if (needGb <= freeGb) return true;
  return confirm(
    `This download needs ~${needGb.toFixed(1)} GB but the models disk has only `
    + `${freeGb} GB free (${_diskInfo.path}).\n\nFree up space first (or press OK to try anyway).`);
}

async function startDownload(repoId, files, payload) {
  if (!diskFitCheck(files)) return;
  const job = {
    // Full repo id, not just the model name — concurrent jobs for the same
    // model from different authors must be distinguishable in the panel.
    uid: "dlj" + (++dlJobSeq), jobId: null, title: repoId,
    totalFiles: files.length, pct: 0, labelText: "Starting…", labelCls: "", cancelled: false,
  };
  dlJobs.push(job);
  refreshDownloadPanel();

  try {
    const data = await fetch("/api/hf/download", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ repo: repoId, files: payload }),
    }).then(r => r.json());

    if (!data.ok) {
      job.labelText = "Error: " + (data.error || "unknown"); job.labelCls = "hf-dl-error";
      refreshDownloadPanel();
      return;
    }
    job.jobId = data.jobId;
    // The files now belong to the job — drop them from the selection so the
    // Download button can't start a duplicate job for the same destinations.
    const startedPaths = new Set(payload.map(p => p.path));
    const checked = checkedMap.get(repoId);
    if (checked) startedPaths.forEach(p => checked.delete(p));
    document.querySelectorAll(".hf-file-list .hf-file").forEach(row => {
      if (activeRepoId === repoId && row._fileData && startedPaths.has(row._fileData.path)) {
        const chk = row.querySelector(".hf-file-check");
        if (chk) chk.checked = false;
      }
    });
    saveDlJobs();
    pollDownload(job);
  } catch (e) {
    job.labelText = "Error: " + e.message; job.labelCls = "hf-dl-error";
    refreshDownloadPanel();
  }
}

function pollDownload(job) {
  async function tick() {
    if (!dlJobs.includes(job) || job.cancelled) return;
    try {
      const s = await fetch(`/api/hf/download/status?job=${encodeURIComponent(job.jobId)}`).then(r => r.json());
      if (!dlJobs.includes(job) || job.cancelled) return;
      if (!s.ok) { dlJobs = dlJobs.filter(j => j !== job); refreshDownloadPanel(); return; }

      const pct = s.total_bytes > 0
        ? Math.round((s.total_bytes_done / s.total_bytes) * 100)
        : s.total_files > 0 ? Math.round((s.current_idx / s.total_files) * 100) : 0;
      job.pct = pct;

      if (s.status === "running") {
        const fileNum = Math.min(s.current_idx + 1, job.totalFiles);
        const filePct = s.file_bytes_total > 0
          ? Math.round((s.file_bytes_done / s.file_bytes_total) * 100) : 0;
        // Smoothed transfer speed from poll-to-poll byte deltas.
        const now = performance.now();
        if (job._pBytes != null && now > job._pTime) {
          const inst = (s.total_bytes_done - job._pBytes) / ((now - job._pTime) / 1000);
          if (inst >= 0) job._speed = job._speed ? job._speed * 0.7 + inst * 0.3 : inst;
        }
        job._pBytes = s.total_bytes_done; job._pTime = now;
        const speedTxt = job._speed > 0 ? ` — ${(job._speed / 1048576).toFixed(1)} MB/s` : "";
        job.labelText = `File ${fileNum}/${job.totalFiles} — ${s.current_file} (${filePct}%)${speedTxt}`;
        refreshDownloadPanel();
        setTimeout(tick, 600);
      } else if (s.status === "done") {
        job.pct = 100;
        job.labelText = `Done — ${job.totalFiles} file${job.totalFiles !== 1 ? "s" : ""} downloaded`;
        job.labelCls = "hf-dl-done";
        refreshDownloadPanel();
        // The files are on disk now — refresh the ✓ local markers for the repo.
        if (s.repo) {
          fetch(`/api/hf/local-check?repo=${encodeURIComponent(s.repo)}`)
            .then(r => r.json()).then(d => {
              if (d?.ok) {
                localCache.set(s.repo, new Set(d.localNames));
                if (activeRepoId === s.repo) renderFilePanel(s.repo);
              }
            }).catch(() => {});
        }
        setTimeout(() => { dlJobs = dlJobs.filter(j => j !== job); refreshDownloadPanel(); }, 4000);
      } else if (s.status === "error") {
        job.labelText = "Error: " + (s.error || "unknown");
        job.labelCls = "hf-dl-error";
        refreshDownloadPanel();
      }
    } catch (e) {
      if (dlJobs.includes(job)) { job.labelText = "Poll error: " + e.message; refreshDownloadPanel(); }
    }
  }
  tick();
}

// ── path helpers ──────────────────────────────────────────────────────────────

function deriveModelName(repoId) {
  return repoId.includes("/") ? repoId.split("/").pop() : repoId;
}

async function downloadSafetensors(repoId, st) {
  const author = repoId.includes("/") ? repoId.split("/")[0] : "unknown";
  const modelName = deriveModelName(repoId);
  const destDir = `${modelName}/${author}/${st.format}`;
  const payload = st.files.map((f) => ({ path: f.path, name: f.name, size: f.size, destDir }));
  const totalGb = (st.totalSize / 1e9).toFixed(2);
  if (!await hfConfirm(`⬇ ${st.format} · ${totalGb} GB`, `${repoId} → ${destDir}/`, "⬇", false)) return;
  const job = {
    repoId, jobId: null,
    totalBytes: st.totalSize, doneBytes: 0, fileName: st.files[0]?.name || "",
    totalFiles: payload.length, pct: 0, labelText: "Starting…", labelCls: "", cancelled: false,
  };
  dlJobs.push(job);
  refreshDownloadPanel();
  try {
    const data = await fetch("/api/hf/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo: repoId, files: payload }),
    }).then((r) => r.json());
    if (!data.ok) {
      job.labelText = "Error: " + (data.error || "unknown"); job.labelCls = "hf-dl-error";
      refreshDownloadPanel();
      return;
    }
    job.jobId = data.jobId;
    saveDlJobs();
    pollDownload(job);
  } catch (e) {
    job.labelText = "Error: " + e.message; job.labelCls = "hf-dl-error";
    refreshDownloadPanel();
  }
}

function computeDestDir(repoId, file) {
  const author    = repoId.includes("/") ? repoId.split("/")[0] : "unknown";
  const modelName = deriveModelName(repoId);
  const quant     = file.quant || "default";
  return `${modelName}/${author}/${quant}`;
}

// ── benchmarks ───────────────────────────────────────────────────────────────

const benchCache = new Map();   // repoId → data | null
const benchExpanded = new Set(); // repoIds with panel open

async function loadBenchmarks(repoId, force = false) {
  if (!force && benchCache.has(repoId)) return benchCache.get(repoId);
  benchCache.set(repoId, null); // mark as loading
  try {
    const url = `/api/hf/benchmarks?repo=${encodeURIComponent(repoId)}${force ? "&force=1" : ""}`;
    const data = await fetch(url).then(r => r.json());
    benchCache.set(repoId, data.ok ? data : null);
    return benchCache.get(repoId);
  } catch (_) {
    benchCache.set(repoId, null);
    return null;
  }
}

function _benchBarPct(key, val) {
  if (key === "arena_elo") return Math.min(100, Math.max(0, Math.round((val - 800) / 6)));
  if (key === "mt_bench")  return Math.round((val / 10) * 100);
  return Math.min(100, Math.max(0, Math.round(val)));
}

function _buildBenchPanel(repoId, data, onRefresh) {
  const panel = document.createElement("div");
  panel.className = "hf-bench-panel";

  if (!data || !data.scores || !Object.keys(data.scores).length) {
    // Header with refresh even when empty
    const hdr = document.createElement("div");
    hdr.className = "hf-bench-panel-header";
    hdr.innerHTML = `<span class="hf-bench-data-from">No benchmark data</span>`;
    const ref = _buildRefreshBtn(onRefresh, data?.from_cache);
    hdr.appendChild(ref);
    panel.appendChild(hdr);
    return panel;
  }

  const { scores, groups, meta, data_from, repo, from_cache } = data;

  // Header: source note + refresh button
  const hdr = document.createElement("div");
  hdr.className = "hf-bench-panel-header";
  const showSource = data_from && data_from !== repo;
  hdr.innerHTML = showSource
    ? `<span class="hf-bench-data-from">📌 data for: <strong>${escapeHtml(data_from)}</strong></span>`
    : `<span class="hf-bench-data-from">${from_cache ? "cached" : "fresh data"}</span>`;
  hdr.appendChild(_buildRefreshBtn(onRefresh, from_cache));
  panel.appendChild(hdr);

  for (const g of (groups || [])) {
    if (!g.keys || !g.keys.length) continue;
    const grpDiv = document.createElement("div");
    grpDiv.className = "hf-bench-group";
    grpDiv.innerHTML = `<div class="hf-bench-group-label">${escapeHtml(g.label)}</div>`;
    for (const key of g.keys) {
      const val = scores[key];
      if (val === undefined) continue;
      const m = (meta || {})[key] || [key, "", "0–100 %", "", ""];
      const [engName, ruDesc, scale, , url] = m;
      const pct = _benchBarPct(key, val);
      const isElo = key === "arena_elo";
      const displayVal = key === "mt_bench" ? val.toFixed(1) + "/10" : val + (scale.includes("%") ? " %" : "");
      const nameHtml = url
        ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(engName)}</a>`
        : escapeHtml(engName);
      const row = document.createElement("div");
      row.className = "hf-bench-row" + (isElo ? " is-elo" : "");
      row.innerHTML =
        `<span class="hf-bench-row-name" title="${escapeHtml(engName)}">${nameHtml}</span>` +
        `<span class="hf-bench-row-desc" title="${escapeHtml(ruDesc)}">${escapeHtml(ruDesc)}</span>` +
        `<div class="hf-bench-bar-wrap"><div class="hf-bench-bar-fill" style="width:${pct}%"></div></div>` +
        `<span class="hf-bench-row-val">${escapeHtml(String(displayVal))}</span>`;
      grpDiv.appendChild(row);
    }
    panel.appendChild(grpDiv);
  }
  return panel;
}

function _buildRefreshBtn(onRefresh, fromCache) {
  const btn = document.createElement("button");
  btn.className = "hf-bench-refresh";
  btn.title = "Refresh from the server";
  btn.innerHTML = fromCache ? "🔄 refresh" : "🔄";
  btn.addEventListener("click", e => { e.stopPropagation(); onRefresh && onRefresh(); });
  return btn;
}

function _onRefresh(repoId) {
  benchCache.delete(repoId);
  // Show loading in existing panel
  for (const row of document.querySelectorAll(`.hf-repo-row[data-repo-id="${CSS.escape(repoId)}"]`)) {
    const p = row.querySelector(".hf-bench-panel");
    if (p) p.innerHTML = `<div class="hf-bench-loading">Refreshing…</div>`;
  }
  loadBenchmarks(repoId, true).then(() => {
    if (benchExpanded.has(repoId)) _refreshBenchUI(repoId);
  });
}

function _applyBenchInline(rowEl, data) {
  const inlineEl = rowEl.querySelector(".hf-bench-inline");
  if (!inlineEl || !data || !data.scores) return;
  const inline = data.inline || [];
  if (!inline.length) { inlineEl.innerHTML = ""; return; }
  inlineEl.innerHTML = inline.map(key => {
    const val = data.scores[key];
    if (val === undefined) return "";
    const m = (data.meta || {})[key] || [key, "", "0–100 %", "", ""];
    const engName = m[0];
    const scale = m[2] || "";
    const displayVal = key === "mt_bench" ? val.toFixed(1) : val;
    const isElo = key === "arena_elo";
    return `<span class="hf-bench-chip${isElo ? " is-elo" : ""}">` +
      `<span class="hf-bench-chip-name">${escapeHtml(engName)}</span>` +
      `<span class="hf-bench-chip-val">${escapeHtml(String(displayVal))}${scale.includes("%") && key !== "arena_elo" ? "%" : ""}</span>` +
      `</span>`;
  }).join("");
}

function _refreshBenchUI(repoId) {
  const data = benchCache.get(repoId);
  const rows = document.querySelectorAll(`.hf-repo-row[data-repo-id="${CSS.escape(repoId)}"]`);
  for (const row of rows) {
    _applyBenchInline(row, data);
    // Update panel if expanded
    if (benchExpanded.has(repoId)) {
      const existing = row.querySelector(".hf-bench-panel");
      const newPanel = _buildBenchPanel(repoId, data, () => _onRefresh(repoId));
      if (existing) existing.replaceWith(newPanel);
      else row.appendChild(newPanel);
    }
  }
}

async function toggleBenchPanel(repoId, toggleBtn) {
  const isOpen = benchExpanded.has(repoId);
  if (isOpen) {
    benchExpanded.delete(repoId);
    toggleBtn.textContent = "📊";
    toggleBtn.classList.remove("is-active");
    for (const row of document.querySelectorAll(`.hf-repo-row[data-repo-id="${CSS.escape(repoId)}"]`)) {
      row.querySelector(".hf-bench-panel")?.remove();
    }
    return;
  }

  benchExpanded.add(repoId);
  toggleBtn.textContent = "📊▲";
  toggleBtn.classList.add("is-active");

  // Show loading placeholder
  for (const row of document.querySelectorAll(`.hf-repo-row[data-repo-id="${CSS.escape(repoId)}"]`)) {
    if (!row.querySelector(".hf-bench-panel")) {
      const ph = document.createElement("div");
      ph.className = "hf-bench-panel";
      ph.innerHTML = `<div class="hf-bench-loading">Loading benchmarks…</div>`;
      row.appendChild(ph);
    }
  }

  const data = await loadBenchmarks(repoId);
  if (benchExpanded.has(repoId)) {
    _refreshBenchUI(repoId);
  }
}

// ── helpers ───────────────────────────────────────────────────────────────────

function extractParams(repoId) {
  const name = repoId.split("/").pop();
  // Match e.g. 8B, 70B, 1.5B, 0.5B, 405B — as a dash/underscore-delimited token
  const m = name.match(/(?:^|[-_])(\d+(?:\.\d+)?)[Bb](?:[-_]|$)/);
  if (!m) return "";
  const n = parseFloat(m[1]);
  if (n < 0.1 || n > 10000) return "";
  return n + "B";
}

function fmtNum(n) {
  if (!n) return "0";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const now = new Date();
  const diffDays = Math.floor((now - d) / 86400000);
  if (diffDays === 0) return "today";
  if (diffDays === 1) return "yesterday";
  if (diffDays < 30) return `${diffDays}d ago`;
  if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo ago`;
  return `${Math.floor(diffDays / 365)}y ago`;
}

function fmtBytes(b) {
  if (!b) return "—";
  if (b >= 1073741824) return (b / 1073741824).toFixed(1) + " GB";
  return Math.round(b / 1048576) + " MB";
}

// ── frontier reference panel ──────────────────────────────────────────────────

const refSection = document.createElement("div");
refSection.className = "hf-ref-section";
repoCol.appendChild(refSection);

let refExpanded = false;
let _refData = null;

const ORG_COLOR = {
  Google: "#4285f4", OpenAI: "#10a37f", Anthropic: "#d97757",
  Meta: "#0064e0", DeepSeek: "#5b6cf9", Qwen: "#ff6b00", Mistral: "#fa5252",
};

function renderRefSection() {
  refSection.innerHTML = "";
  const hdr = document.createElement("div");
  hdr.className = "hf-section-header hf-ref-header";
  hdr.innerHTML =
    `<span>📊 Reference models (frontier)</span>` +
    `<span class="hf-fav-chevron">${refExpanded ? "▲" : "▼"}</span>`;
  hdr.addEventListener("click", () => {
    refExpanded = !refExpanded;
    if (refExpanded && !_refData) loadRefModels();
    else renderRefSection();
  });
  refSection.appendChild(hdr);

  if (!refExpanded) return;

  if (!_refData) {
    const loading = document.createElement("div");
    loading.className = "hf-status"; loading.style.padding = "12px";
    loading.textContent = hfT("benchLoading");
    refSection.appendChild(loading);
    return;
  }

  const table = document.createElement("div");
  table.className = "hf-ref-table";

  const maxAA = Math.max(..._refData.filter(m => m.aa != null).map(m => m.aa));

  for (const m of _refData) {
    const row = document.createElement("div");
    row.className = "hf-ref-row";
    const orgColor = ORG_COLOR[m.org] || "#888";
    const pct = m.aa != null ? Math.round((m.aa / (maxAA || 100)) * 100) : 0;
    row.innerHTML =
      `<span class="hf-ref-org" style="color:${escapeHtml(orgColor)}">${escapeHtml(m.org)}</span>` +
      `<span class="hf-ref-name">${escapeHtml(m.name)}</span>` +
      `<div class="hf-ref-bar-wrap"><div class="hf-ref-bar-fill" style="width:${pct}%;background:${escapeHtml(orgColor)}40;border-right:2px solid ${escapeHtml(orgColor)}"></div></div>` +
      `<span class="hf-ref-val">${m.aa != null ? m.aa : "—"}</span>`;
    table.appendChild(row);
  }

  const footer = document.createElement("div");
  footer.className = "hf-ref-footer";
  const isDefault = !_refData || _refData.every(m => !m._live);
  footer.innerHTML =
    `AA Intelligence Index · <a href="https://artificialanalysis.ai/leaderboards/models" target="_blank" rel="noopener">artificialanalysis.ai</a>` +
    (isDefault ? ` · <span title="Data snapshot from June 2026">~Jun 2026</span>` : "") +
    `<button class="hf-bench-refresh" id="hfRefRefresh" title="Fetch fresh data from AA">🔄</button>`;
  footer.querySelector("#hfRefRefresh").addEventListener("click", () => {
    _refData = null;
    renderRefSection();
    loadRefModels(true);
  });

  refSection.appendChild(table);
  refSection.appendChild(footer);
}

async function loadRefModels(force = false) {
  try {
    const url = `/api/hf/reference-models${force ? "?force=1" : ""}`;
    const data = await fetch(url).then(r => r.json());
    if (data.ok) {
      _refData = data.models.filter(m => m.aa != null).sort((a, b) => (b.aa || 0) - (a.aa || 0));
      renderRefSection();
    }
  } catch (_) {}
}

// ── init ──────────────────────────────────────────────────────────────────────

const _initLoads = [loadTokenStatus(), loadFavs(), restoreDlJobs()];
refreshDiskInfo();
setInterval(refreshDiskInfo, 60_000);
renderRefSection();
// Пиксельный лоадер (inline в hf.html) прячем, когда стартовые данные пришли.
Promise.allSettled(_initLoads).then(() => window.__plHide?.());

const _urlQ = new URLSearchParams(location.search).get("q");
if (_urlQ) {
  searchInput.value = _urlQ;
  doSearch();
} else {
  searchInput.focus();
}


// "on disk" → the dedicated /models page (tree, owners, cleanup).
document.getElementById("hfOnDiskBtn")?.addEventListener("click", () => { window.location.href = "/models"; });

// ── onboarding tour (?) ───────────────────────────────────────────────────────
// The engine is dependency-free; strings live here so this page keeps NOT
// importing the big i18n dictionary. All 20 app languages; the language
// follows the main app's localStorage key.
import { autoStartOnce, createTour, initTourButtons } from "/js/onboarding.js";

const HF_TOUR = {
  en: {
    btn: "How to use this page",
    label: "Tour",
    langPick: "Language",
    next: "Next →", back: "← Back", done: "Done", skip: "Close",
    steps: [
      [null, "HuggingFace model browser",
       "Search HuggingFace for <b>GGUF</b> models and download them straight to the controller's models directory — they become available to every llama server cell.<br><br>Navigate with <b>→</b>/<b>←</b>, close with <b>Esc</b>."],
      [".hf-search", "Search",
       "Type a repo name (<code>bartowski/Qwen3-…-GGUF</code>) or free words. Only GGUF repositories are shown."],
      ["#hfRepoCol", "Repositories",
       "Pick a repository — stars, downloads and benchmark badges help choose. ★ favorites stay on top."],
      ["#hfFileCol", "Files & quants",
       "Every GGUF in the repo with its size. Pick a quantization that fits your VRAM (the board's editor shows a fit estimate) and press download; multi-part files are handled automatically. Files land as <code>&lt;model&gt;/&lt;author&gt;/&lt;quant&gt;/file.gguf</code> — use the same layout when adding models by hand."],
      [".hf-token-row", "HF token",
       "Needed only for gated or private repos. Stored on the controller, never in the browser."],
    ],
  },
  ru: {
    btn: "Как пользоваться этой страницей",
    label: "Тур",
    langPick: "Язык",
    next: "Дальше →", back: "← Назад", done: "Готово", skip: "Закрыть",
    steps: [
      [null, "Браузер моделей HuggingFace",
       "Ищите на HuggingFace <b>GGUF</b>-модели и скачивайте их прямо в каталог моделей контроллера — они станут доступны всем llama-ячейкам.<br><br>Навигация: <b>→</b>/<b>←</b>, закрыть — <b>Esc</b>."],
      [".hf-search", "Поиск",
       "Введите имя репозитория (<code>bartowski/Qwen3-…-GGUF</code>) или просто слова. Показываются только GGUF-репозитории."],
      ["#hfRepoCol", "Репозитории",
       "Выберите репозиторий — помогут звёзды, загрузки и бейджи бенчмарков. ★ избранное всегда сверху."],
      ["#hfFileCol", "Файлы и кванты",
       "Все GGUF репозитория с размерами. Выберите квант под вашу VRAM (оценку «влезет ли» покажет редактор на доске) и жмите download; многочастные файлы склеиваются сами. Файлы ложатся как <code>&lt;модель&gt;/&lt;автор&gt;/&lt;квант&gt;/файл.gguf</code> — кладите руками в ту же структуру."],
      [".hf-token-row", "HF-токен",
       "Нужен только для gated/приватных репозиториев. Хранится на контроллере, не в браузере."],
    ],
  },
  zh: {
    btn: "如何使用此页面",
    label: "导览",
    langPick: "语言",
    next: "下一步 →", back: "← 上一步", done: "完成", skip: "关闭",
    steps: [
      [null, "HuggingFace 模型浏览器",
       "在 HuggingFace 搜索 <b>GGUF</b> 模型并直接下载到控制器的模型目录 — 所有 llama 服务器单元都能使用。<br><br>用 <b>→</b>/<b>←</b> 导航，<b>Esc</b> 关闭。"],
      [".hf-search", "搜索",
       "输入仓库名（<code>bartowski/Qwen3-…-GGUF</code>）或任意关键词。只显示 GGUF 仓库。"],
      ["#hfRepoCol", "仓库",
       "选择一个仓库 — 星标、下载量和基准徽章帮你挑选。★ 收藏始终置顶。"],
      ["#hfFileCol", "文件与量化",
       "仓库中所有 GGUF 及其大小。选择适合你 VRAM 的量化（看板编辑器会估算能否放下）并点击下载；多分卷文件自动处理。文件按 <code>&lt;模型&gt;/&lt;作者&gt;/&lt;量化&gt;/file.gguf</code> 存放 — 手动添加模型请沿用同一结构。"],
      [".hf-token-row", "HF 令牌",
       "仅 gated/私有仓库需要。保存在控制器上，绝不留在浏览器里。"],
    ],
  },
  hi: {
    btn: "इस पेज का उपयोग कैसे करें",
    label: "टूर",
    langPick: "भाषा",
    next: "आगे →", back: "← पीछे", done: "हो गया", skip: "बंद करें",
    steps: [
      [null, "HuggingFace मॉडल ब्राउज़र",
       "HuggingFace पर <b>GGUF</b> मॉडल खोजें और सीधे कंट्रोलर की मॉडल डायरेक्टरी में डाउनलोड करें — वे हर llama सर्वर सेल को उपलब्ध हो जाते हैं।<br><br><b>→</b>/<b>←</b> से चलें, <b>Esc</b> से बंद करें।"],
      [".hf-search", "खोज",
       "रेपो का नाम लिखें (<code>bartowski/Qwen3-…-GGUF</code>) या कोई भी शब्द। केवल GGUF रिपॉज़िटरी दिखती हैं।"],
      ["#hfRepoCol", "रिपॉज़िटरी",
       "एक रिपॉज़िटरी चुनें — स्टार, डाउनलोड और बेंचमार्क बैज चुनने में मदद करते हैं। ★ पसंदीदा हमेशा ऊपर रहते हैं।"],
      ["#hfFileCol", "फ़ाइलें और क्वांट",
       "रेपो के सभी GGUF अपने आकार के साथ। अपनी VRAM में समाने वाला क्वांटाइज़ेशन चुनें (बोर्ड का एडिटर फ़िट का अनुमान दिखाता है) और डाउनलोड दबाएँ; बहु-भाग फ़ाइलें अपने आप संभल जाती हैं। फ़ाइलें <code>&lt;मॉडल&gt;/&lt;लेखक&gt;/&lt;क्वांट&gt;/file.gguf</code> के रूप में रखी जाती हैं — हाथ से मॉडल जोड़ते समय भी यही संरचना रखें।"],
      [".hf-token-row", "HF टोकन",
       "केवल gated या निजी रेपो के लिए चाहिए। कंट्रोलर पर संग्रहीत, ब्राउज़र में कभी नहीं।"],
    ],
  },
  es: {
    btn: "Cómo usar esta página",
    label: "Guía",
    langPick: "Idioma",
    next: "Siguiente →", back: "← Atrás", done: "Listo", skip: "Cerrar",
    steps: [
      [null, "Navegador de modelos de HuggingFace",
       "Busca modelos <b>GGUF</b> en HuggingFace y descárgalos directo al directorio de modelos del controlador — quedan disponibles para todas las celdas de servidor llama.<br><br>Navega con <b>→</b>/<b>←</b>, cierra con <b>Esc</b>."],
      [".hf-search", "Búsqueda",
       "Escribe el nombre de un repo (<code>bartowski/Qwen3-…-GGUF</code>) o palabras sueltas. Solo se muestran repositorios GGUF."],
      ["#hfRepoCol", "Repositorios",
       "Elige un repositorio — estrellas, descargas e insignias de benchmarks ayudan a decidir. Los favoritos ★ quedan arriba."],
      ["#hfFileCol", "Archivos y cuantizaciones",
       "Todos los GGUF del repo con su tamaño. Elige una cuantización que quepa en tu VRAM (el editor del tablero estima si cabe) y pulsa descargar; los archivos multiparte se manejan solos. Los archivos quedan como <code>&lt;modelo&gt;/&lt;autor&gt;/&lt;cuant&gt;/file.gguf</code> — usa la misma estructura al añadir modelos a mano."],
      [".hf-token-row", "Token de HF",
       "Solo hace falta para repos gated o privados. Se guarda en el controlador, nunca en el navegador."],
    ],
  },
  fr: {
    btn: "Comment utiliser cette page",
    label: "Visite",
    langPick: "Langue",
    next: "Suivant →", back: "← Retour", done: "Terminé", skip: "Fermer",
    steps: [
      [null, "Navigateur de modèles HuggingFace",
       "Cherchez des modèles <b>GGUF</b> sur HuggingFace et téléchargez-les droit dans le répertoire de modèles du contrôleur — ils deviennent disponibles pour toutes les cellules de serveur llama.<br><br>Naviguez avec <b>→</b>/<b>←</b>, fermez avec <b>Esc</b>."],
      [".hf-search", "Recherche",
       "Tapez un nom de dépôt (<code>bartowski/Qwen3-…-GGUF</code>) ou des mots libres. Seuls les dépôts GGUF s'affichent."],
      ["#hfRepoCol", "Dépôts",
       "Choisissez un dépôt — étoiles, téléchargements et badges de benchmarks aident à trancher. Les favoris ★ restent en haut."],
      ["#hfFileCol", "Fichiers et quantifications",
       "Tous les GGUF du dépôt avec leur taille. Choisissez une quantification qui tient dans votre VRAM (l'éditeur du tableau estime si ça rentre) et lancez le téléchargement ; les fichiers multi-parties sont gérés automatiquement. Les fichiers arrivent en <code>&lt;modèle&gt;/&lt;auteur&gt;/&lt;quant&gt;/file.gguf</code> — gardez la même structure pour vos ajouts manuels."],
      [".hf-token-row", "Jeton HF",
       "Nécessaire seulement pour les dépôts gated ou privés. Stocké sur le contrôleur, jamais dans le navigateur."],
    ],
  },
  ar: {
    btn: "كيف تستخدم هذه الصفحة",
    label: "جولة",
    langPick: "اللغة",
    next: "التالي ←", back: "→ رجوع", done: "تم", skip: "إغلاق",
    steps: [
      [null, "متصفح نماذج HuggingFace",
       "ابحث في HuggingFace عن نماذج <b>GGUF</b> ونزّلها مباشرة إلى مجلد النماذج في وحدة التحكم — فتصبح متاحة لكل خلايا خوادم llama.<br><br>تنقّل بـ <b>→</b>/<b>←</b>، وأغلق بـ <b>Esc</b>."],
      [".hf-search", "البحث",
       "اكتب اسم المستودع (<code>bartowski/Qwen3-…-GGUF</code>) أو كلمات حرة. تُعرض مستودعات GGUF فقط."],
      ["#hfRepoCol", "المستودعات",
       "اختر مستودعًا — تساعدك النجوم والتنزيلات وشارات الاختبارات في الاختيار. المفضلة ★ تبقى في الأعلى."],
      ["#hfFileCol", "الملفات والتكميمات",
       "كل ملفات GGUF في المستودع مع أحجامها. اختر تكميمًا يناسب ذاكرة VRAM لديك (محرر اللوحة يقدّر إن كان يتسع) واضغط تنزيل؛ الملفات متعددة الأجزاء تُعالج تلقائيًا. تُحفظ الملفات بالشكل <code>&lt;النموذج&gt;/&lt;المؤلف&gt;/&lt;التكميم&gt;/file.gguf</code> — التزم بالبنية نفسها عند إضافة النماذج يدويًا."],
      [".hf-token-row", "رمز HF",
       "مطلوب فقط للمستودعات المقيدة أو الخاصة. يُخزن على وحدة التحكم، ولا يبقى في المتصفح أبدًا."],
    ],
  },
  bn: {
    btn: "এই পেজটি কীভাবে ব্যবহার করবেন",
    label: "ট্যুর",
    langPick: "ভাষা",
    next: "পরবর্তী →", back: "← পিছনে", done: "সম্পন্ন", skip: "বন্ধ করুন",
    steps: [
      [null, "HuggingFace মডেল ব্রাউজার",
       "HuggingFace-এ <b>GGUF</b> মডেল খুঁজুন এবং সরাসরি কন্ট্রোলারের মডেল ডিরেক্টরিতে নামান — সেগুলি প্রতিটি llama সার্ভার সেলের জন্য উপলব্ধ হয়ে যায়।<br><br><b>→</b>/<b>←</b> দিয়ে চলুন, <b>Esc</b> দিয়ে বন্ধ করুন।"],
      [".hf-search", "খোঁজ",
       "রিপোর নাম লিখুন (<code>bartowski/Qwen3-…-GGUF</code>) বা যেকোনো শব্দ। শুধু GGUF রিপোজিটরি দেখানো হয়।"],
      ["#hfRepoCol", "রিপোজিটরি",
       "একটি রিপোজিটরি বেছে নিন — তারা, ডাউনলোড ও বেঞ্চমার্ক ব্যাজ বাছাইয়ে সাহায্য করে। ★ প্রিয়গুলি সবসময় উপরে থাকে।"],
      ["#hfFileCol", "ফাইল ও কোয়ান্ট",
       "রিপোর সব GGUF তাদের আকারসহ। আপনার VRAM-এ ধরে এমন কোয়ান্টাইজেশন বেছে নিন (বোর্ডের এডিটর আঁটবে কিনা অনুমান দেখায়) এবং ডাউনলোড চাপুন; বহু-খণ্ড ফাইল নিজে নিজেই সামলানো হয়। ফাইল রাখা হয় <code>&lt;মডেল&gt;/&lt;লেখক&gt;/&lt;কোয়ান্ট&gt;/file.gguf</code> আকারে — হাতে মডেল যোগ করলেও একই কাঠামো রাখুন।"],
      [".hf-token-row", "HF টোকেন",
       "শুধু gated বা প্রাইভেট রিপোর জন্য দরকার। কন্ট্রোলারে সংরক্ষিত, ব্রাউজারে কখনও নয়।"],
    ],
  },
  pt: {
    btn: "Como usar esta página",
    label: "Tour",
    langPick: "Idioma",
    next: "Avançar →", back: "← Voltar", done: "Concluir", skip: "Fechar",
    steps: [
      [null, "Navegador de modelos HuggingFace",
       "Pesquise modelos <b>GGUF</b> no HuggingFace e baixe-os direto para o diretório de modelos do controlador — ficam disponíveis para todas as células de servidor llama.<br><br>Navegue com <b>→</b>/<b>←</b>, feche com <b>Esc</b>."],
      [".hf-search", "Busca",
       "Digite o nome de um repositório (<code>bartowski/Qwen3-…-GGUF</code>) ou palavras livres. Só repositórios GGUF são exibidos."],
      ["#hfRepoCol", "Repositórios",
       "Escolha um repositório — estrelas, downloads e selos de benchmark ajudam na escolha. Os favoritos ★ ficam no topo."],
      ["#hfFileCol", "Arquivos e quantizações",
       "Todos os GGUF do repositório com seus tamanhos. Escolha uma quantização que caiba na sua VRAM (o editor do quadro estima se cabe) e clique em baixar; arquivos multipartes são tratados automaticamente. Os arquivos ficam como <code>&lt;modelo&gt;/&lt;autor&gt;/&lt;quant&gt;/file.gguf</code> — mantenha a mesma estrutura ao adicionar modelos à mão."],
      [".hf-token-row", "Token HF",
       "Necessário só para repositórios gated ou privados. Guardado no controlador, nunca no navegador."],
    ],
  },
  ja: {
    btn: "このページの使い方",
    label: "ツアー",
    langPick: "言語",
    next: "次へ →", back: "← 戻る", done: "完了", skip: "閉じる",
    steps: [
      [null, "HuggingFace モデルブラウザ",
       "HuggingFace で <b>GGUF</b> モデルを検索し、コントローラのモデルディレクトリへ直接ダウンロード — すべての llama サーバーセルで使えるようになります。<br><br><b>→</b>/<b>←</b> で移動、<b>Esc</b> で閉じます。"],
      [".hf-search", "検索",
       "リポジトリ名（<code>bartowski/Qwen3-…-GGUF</code>）か自由な語句を入力。GGUF リポジトリだけが表示されます。"],
      ["#hfRepoCol", "リポジトリ",
       "リポジトリを選択 — スター数、ダウンロード数、ベンチマークバッジが選定の助けになります。★ お気に入りは常に上部に。"],
      ["#hfFileCol", "ファイルと量子化",
       "リポジトリ内の全 GGUF とサイズ。VRAM に収まる量子化を選び（ボードのエディタが収まるか推定します）、ダウンロードを押すだけ。分割ファイルは自動処理。ファイルは <code>&lt;モデル&gt;/&lt;作者&gt;/&lt;量子化&gt;/file.gguf</code> の形で保存 — 手動でモデルを置くときも同じ構成で。"],
      [".hf-token-row", "HF トークン",
       "gated・プライベートリポジトリにのみ必要。コントローラに保存され、ブラウザには残りません。"],
    ],
  },
  de: {
    btn: "So benutzt du diese Seite",
    label: "Tour",
    langPick: "Sprache",
    next: "Weiter →", back: "← Zurück", done: "Fertig", skip: "Schließen",
    steps: [
      [null, "HuggingFace-Modellbrowser",
       "Suche auf HuggingFace nach <b>GGUF</b>-Modellen und lade sie direkt ins Modellverzeichnis des Controllers — sie stehen sofort jeder llama-Serverzelle zur Verfügung.<br><br>Navigieren mit <b>→</b>/<b>←</b>, schließen mit <b>Esc</b>."],
      [".hf-search", "Suche",
       "Repo-Namen eingeben (<code>bartowski/Qwen3-…-GGUF</code>) oder freie Begriffe. Es werden nur GGUF-Repositories angezeigt."],
      ["#hfRepoCol", "Repositories",
       "Wähle ein Repository — Sterne, Downloads und Benchmark-Badges helfen bei der Wahl. ★-Favoriten bleiben oben."],
      ["#hfFileCol", "Dateien & Quantisierungen",
       "Alle GGUF des Repos mit Größe. Wähle eine Quantisierung, die in deinen VRAM passt (der Editor auf dem Board schätzt, ob es passt), und starte den Download; mehrteilige Dateien werden automatisch behandelt. Dateien landen als <code>&lt;Modell&gt;/&lt;Autor&gt;/&lt;Quant&gt;/file.gguf</code> — nutze dieselbe Struktur, wenn du Modelle von Hand ablegst."],
      [".hf-token-row", "HF-Token",
       "Nur für gated oder private Repos nötig. Liegt auf dem Controller, nie im Browser."],
    ],
  },
  id: {
    btn: "Cara memakai halaman ini",
    label: "Tur",
    langPick: "Bahasa",
    next: "Lanjut →", back: "← Kembali", done: "Selesai", skip: "Tutup",
    steps: [
      [null, "Peramban model HuggingFace",
       "Cari model <b>GGUF</b> di HuggingFace dan unduh langsung ke direktori model controller — langsung tersedia untuk semua sel server llama.<br><br>Navigasi dengan <b>→</b>/<b>←</b>, tutup dengan <b>Esc</b>."],
      [".hf-search", "Pencarian",
       "Ketik nama repo (<code>bartowski/Qwen3-…-GGUF</code>) atau kata bebas. Hanya repositori GGUF yang ditampilkan."],
      ["#hfRepoCol", "Repositori",
       "Pilih repositori — bintang, unduhan, dan lencana benchmark membantu memilih. Favorit ★ selalu di atas."],
      ["#hfFileCol", "Berkas & kuantisasi",
       "Semua GGUF dalam repo beserta ukurannya. Pilih kuantisasi yang muat di VRAM Anda (editor papan menampilkan perkiraan muat) lalu tekan unduh; berkas multi-bagian ditangani otomatis. Berkas tersimpan sebagai <code>&lt;model&gt;/&lt;penulis&gt;/&lt;kuant&gt;/file.gguf</code> — pakai struktur yang sama saat menaruh model secara manual."],
      [".hf-token-row", "Token HF",
       "Hanya perlu untuk repo gated atau privat. Disimpan di controller, tidak pernah di peramban."],
    ],
  },
  ur: {
    btn: "یہ صفحہ کیسے استعمال کریں",
    label: "ٹور",
    langPick: "زبان",
    next: "اگلا ←", back: "→ پیچھے", done: "مکمل", skip: "بند کریں",
    steps: [
      [null, "HuggingFace ماڈل براؤزر",
       "HuggingFace پر <b>GGUF</b> ماڈل تلاش کریں اور سیدھا کنٹرولر کی ماڈل ڈائریکٹری میں ڈاؤن لوڈ کریں — وہ ہر llama سرور سیل کو دستیاب ہو جاتے ہیں۔<br><br><b>→</b>/<b>←</b> سے چلیں، <b>Esc</b> سے بند کریں۔"],
      [".hf-search", "تلاش",
       "ریپو کا نام لکھیں (<code>bartowski/Qwen3-…-GGUF</code>) یا کوئی بھی الفاظ۔ صرف GGUF ریپوزٹریاں دکھائی جاتی ہیں۔"],
      ["#hfRepoCol", "ریپوزٹریاں",
       "کوئی ریپوزٹری چنیں — ستارے، ڈاؤن لوڈ اور بینچ مارک بیجز انتخاب میں مدد دیتے ہیں۔ ★ پسندیدہ ہمیشہ اوپر رہتے ہیں۔"],
      ["#hfFileCol", "فائلیں اور کوانٹ",
       "ریپو کی تمام GGUF فائلیں مع سائز۔ اپنی VRAM میں سمانے والی کوانٹائزیشن چنیں (بورڈ کا ایڈیٹر اندازہ دکھاتا ہے) اور ڈاؤن لوڈ دبائیں؛ کثیر حصہ فائلیں خود سنبھل جاتی ہیں۔ فائلیں <code>&lt;ماڈل&gt;/&lt;مصنف&gt;/&lt;کوانٹ&gt;/file.gguf</code> کی صورت رکھی جاتی ہیں — ہاتھ سے ماڈل رکھتے وقت بھی یہی ساخت رکھیں۔"],
      [".hf-token-row", "HF ٹوکن",
       "صرف gated یا نجی ریپوز کے لیے درکار۔ کنٹرولر پر محفوظ، براؤزر میں کبھی نہیں۔"],
    ],
  },
  tr: {
    btn: "Bu sayfa nasıl kullanılır",
    label: "Tur",
    langPick: "Dil",
    next: "İleri →", back: "← Geri", done: "Bitti", skip: "Kapat",
    steps: [
      [null, "HuggingFace model tarayıcısı",
       "HuggingFace'te <b>GGUF</b> modelleri arayın ve doğrudan denetleyicinin model dizinine indirin — tüm llama sunucu hücrelerine açılırlar.<br><br><b>→</b>/<b>←</b> ile gezinin, <b>Esc</b> ile kapatın."],
      [".hf-search", "Arama",
       "Depo adı yazın (<code>bartowski/Qwen3-…-GGUF</code>) ya da serbest sözcükler. Yalnızca GGUF depoları gösterilir."],
      ["#hfRepoCol", "Depolar",
       "Bir depo seçin — yıldızlar, indirmeler ve benchmark rozetleri seçime yardım eder. ★ favoriler hep üstte."],
      ["#hfFileCol", "Dosyalar ve kuantlar",
       "Depodaki tüm GGUF'lar boyutlarıyla. VRAM'inize sığan bir kuantizasyon seçin (panodaki düzenleyici sığar mı tahmin eder) ve indir'e basın; çok parçalı dosyalar kendiliğinden halledilir. Dosyalar <code>&lt;model&gt;/&lt;yazar&gt;/&lt;kuant&gt;/file.gguf</code> düzeninde durur — elle model eklerken de aynı yapıyı koruyun."],
      [".hf-token-row", "HF belirteci",
       "Yalnızca gated veya özel depolar için gerekir. Denetleyicide saklanır, asla tarayıcıda değil."],
    ],
  },
  ko: {
    btn: "이 페이지 사용법",
    label: "투어",
    langPick: "언어",
    next: "다음 →", back: "← 이전", done: "완료", skip: "닫기",
    steps: [
      [null, "HuggingFace 모델 브라우저",
       "HuggingFace에서 <b>GGUF</b> 모델을 검색해 컨트롤러의 모델 디렉터리로 바로 내려받으세요 — 모든 llama 서버 셀에서 쓸 수 있게 됩니다.<br><br><b>→</b>/<b>←</b>로 이동, <b>Esc</b>로 닫기."],
      [".hf-search", "검색",
       "저장소 이름(<code>bartowski/Qwen3-…-GGUF</code>)이나 자유 검색어를 입력하세요. GGUF 저장소만 표시됩니다."],
      ["#hfRepoCol", "저장소",
       "저장소를 고르세요 — 별, 다운로드 수, 벤치마크 배지가 선택을 돕습니다. ★ 즐겨찾기는 항상 맨 위에."],
      ["#hfFileCol", "파일과 양자화",
       "저장소의 모든 GGUF와 크기. VRAM에 맞는 양자화를 고르고(보드의 편집기가 들어갈지 추정해 줍니다) 다운로드를 누르세요; 분할 파일은 자동 처리됩니다. 파일은 <code>&lt;모델&gt;/&lt;작성자&gt;/&lt;양자화&gt;/file.gguf</code> 구조로 저장됩니다 — 직접 모델을 넣을 때도 같은 구조를 지키세요."],
      [".hf-token-row", "HF 토큰",
       "gated·비공개 저장소에만 필요합니다. 컨트롤러에 저장되며 브라우저에는 남지 않습니다."],
    ],
  },
  vi: {
    btn: "Cách dùng trang này",
    label: "Tour",
    langPick: "Ngôn ngữ",
    next: "Tiếp →", back: "← Lùi", done: "Xong", skip: "Đóng",
    steps: [
      [null, "Trình duyệt mô hình HuggingFace",
       "Tìm mô hình <b>GGUF</b> trên HuggingFace và tải thẳng vào thư mục mô hình của bộ điều khiển — chúng lập tức sẵn sàng cho mọi ô máy chủ llama.<br><br>Di chuyển bằng <b>→</b>/<b>←</b>, đóng bằng <b>Esc</b>."],
      [".hf-search", "Tìm kiếm",
       "Gõ tên kho (<code>bartowski/Qwen3-…-GGUF</code>) hoặc từ khóa tự do. Chỉ hiển thị các kho GGUF."],
      ["#hfRepoCol", "Kho mô hình",
       "Chọn một kho — sao, lượt tải và huy hiệu benchmark giúp bạn quyết định. Mục ★ yêu thích luôn ở trên cùng."],
      ["#hfFileCol", "Tệp & lượng tử hóa",
       "Mọi GGUF trong kho kèm kích thước. Chọn mức lượng tử hóa vừa với VRAM của bạn (trình soạn trên bảng ước tính có vừa không) rồi bấm tải; tệp nhiều phần được xử lý tự động. Tệp nằm theo dạng <code>&lt;mô hình&gt;/&lt;tác giả&gt;/&lt;quant&gt;/file.gguf</code> — thêm mô hình thủ công cũng giữ đúng cấu trúc này."],
      [".hf-token-row", "Token HF",
       "Chỉ cần cho kho gated hoặc riêng tư. Lưu trên bộ điều khiển, không bao giờ ở trình duyệt."],
    ],
  },
  it: {
    btn: "Come usare questa pagina",
    label: "Tour",
    langPick: "Lingua",
    next: "Avanti →", back: "← Indietro", done: "Fatto", skip: "Chiudi",
    steps: [
      [null, "Browser dei modelli HuggingFace",
       "Cerca modelli <b>GGUF</b> su HuggingFace e scaricali direttamente nella directory dei modelli del controller — diventano disponibili a ogni cella server llama.<br><br>Naviga con <b>→</b>/<b>←</b>, chiudi con <b>Esc</b>."],
      [".hf-search", "Ricerca",
       "Digita il nome di un repo (<code>bartowski/Qwen3-…-GGUF</code>) o parole libere. Vengono mostrati solo repository GGUF."],
      ["#hfRepoCol", "Repository",
       "Scegli un repository — stelle, download e badge dei benchmark aiutano nella scelta. I preferiti ★ restano in cima."],
      ["#hfFileCol", "File e quantizzazioni",
       "Tutti i GGUF del repo con le dimensioni. Scegli una quantizzazione che stia nella tua VRAM (l'editor della board stima se ci sta) e premi download; i file multi-parte sono gestiti da soli. I file finiscono come <code>&lt;modello&gt;/&lt;autore&gt;/&lt;quant&gt;/file.gguf</code> — mantieni la stessa struttura quando aggiungi modelli a mano."],
      [".hf-token-row", "Token HF",
       "Serve solo per repo gated o privati. Conservato sul controller, mai nel browser."],
    ],
  },
  te: {
    btn: "ఈ పేజీని ఎలా వాడాలి",
    label: "టూర్",
    langPick: "భాష",
    next: "తర్వాత →", back: "← వెనుకకు", done: "పూర్తయింది", skip: "మూసివేయి",
    steps: [
      [null, "HuggingFace మోడల్ బ్రౌజర్",
       "HuggingFace లో <b>GGUF</b> మోడళ్లను వెతికి నేరుగా కంట్రోలర్ మోడల్ డైరెక్టరీలోకి దించుకోండి — అవి ప్రతి llama సర్వర్ సెల్‌కు అందుబాటులోకి వస్తాయి.<br><br><b>→</b>/<b>←</b> తో కదలండి, <b>Esc</b> తో మూసేయండి."],
      [".hf-search", "వెతుకులాట",
       "రిపో పేరు టైప్ చేయండి (<code>bartowski/Qwen3-…-GGUF</code>) లేదా ఏవైనా పదాలు. GGUF రిపోజిటరీలు మాత్రమే కనిపిస్తాయి."],
      ["#hfRepoCol", "రిపోజిటరీలు",
       "ఒక రిపోజిటరీ ఎంచుకోండి — నక్షత్రాలు, డౌన్‌లోడ్‌లు, బెంచ్‌మార్క్ బ్యాడ్జీలు ఎంపికకు సాయపడతాయి. ★ ఇష్టమైనవి ఎప్పుడూ పైనే."],
      ["#hfFileCol", "ఫైళ్లు & క్వాంట్‌లు",
       "రిపోలోని అన్ని GGUF లు వాటి పరిమాణాలతో. మీ VRAM లో పట్టే క్వాంటైజేషన్ ఎంచుకుని (బోర్డు ఎడిటర్ పడుతుందో లేదో అంచనా చూపుతుంది) డౌన్‌లోడ్ నొక్కండి; బహుళ-భాగ ఫైళ్లు వాటంతటవే సర్దుకుంటాయి. ఫైళ్లు <code>&lt;మోడల్&gt;/&lt;రచయిత&gt;/&lt;క్వాంట్&gt;/file.gguf</code> గా పడతాయి — చేతితో మోడళ్లు పెట్టేటప్పుడూ ఇదే అమరిక పాటించండి."],
      [".hf-token-row", "HF టోకెన్",
       "gated లేదా ప్రైవేటు రిపోలకు మాత్రమే అవసరం. కంట్రోలర్‌పై నిల్వ, బ్రౌజర్‌లో ఎప్పటికీ కాదు."],
    ],
  },
  mr: {
    btn: "हे पान कसे वापरावे",
    label: "टूर",
    langPick: "भाषा",
    next: "पुढे →", back: "← मागे", done: "झाले", skip: "बंद करा",
    steps: [
      [null, "HuggingFace मॉडेल ब्राउझर",
       "HuggingFace वर <b>GGUF</b> मॉडेल शोधा आणि थेट कंट्रोलरच्या मॉडेल डिरेक्टरीत उतरवा — ती प्रत्येक llama सर्व्हर सेलला उपलब्ध होतात.<br><br><b>→</b>/<b>←</b> ने फिरा, <b>Esc</b> ने बंद करा."],
      [".hf-search", "शोध",
       "रेपोचे नाव लिहा (<code>bartowski/Qwen3-…-GGUF</code>) किंवा कोणतेही शब्द. फक्त GGUF रिपॉझिटरी दाखवल्या जातात."],
      ["#hfRepoCol", "रिपॉझिटरी",
       "एक रिपॉझिटरी निवडा — तारे, डाउनलोड व बेंचमार्क बिल्ले निवडीस मदत करतात. ★ आवडते नेहमी वर राहतात."],
      ["#hfFileCol", "फायली व क्वांट",
       "रेपोतील सर्व GGUF त्यांच्या आकारासह. तुमच्या VRAM मध्ये मावणारे क्वांटायझेशन निवडा (फलकावरील एडिटर मावेल का याचा अंदाज दाखवतो) आणि डाउनलोड दाबा; बहु-भाग फायली आपोआप हाताळल्या जातात. फायली <code>&lt;मॉडेल&gt;/&lt;लेखक&gt;/&lt;क्वांट&gt;/file.gguf</code> अशा ठेवल्या जातात — हाताने मॉडेल ठेवतानाही हीच रचना पाळा."],
      [".hf-token-row", "HF टोकन",
       "फक्त gated वा खासगी रेपोंसाठी लागते. कंट्रोलरवर साठवले जाते, ब्राउझरमध्ये कधीही नाही."],
    ],
  },
  ta: {
    btn: "இந்தப் பக்கத்தை எப்படி பயன்படுத்துவது",
    label: "சுற்று",
    langPick: "மொழி",
    next: "அடுத்து →", back: "← பின்", done: "முடிந்தது", skip: "மூடு",
    steps: [
      [null, "HuggingFace மாதிரி உலாவி",
       "HuggingFace இல் <b>GGUF</b> மாதிரிகளைத் தேடி நேரடியாக கட்டுப்படுத்தியின் மாதிரி அடைவில் பதிவிறக்குங்கள் — அவை எல்லா llama சேவையக செல்களுக்கும் கிடைக்கும்.<br><br><b>→</b>/<b>←</b> மூலம் நகருங்கள், <b>Esc</b> மூலம் மூடுங்கள்."],
      [".hf-search", "தேடல்",
       "ரெப்போ பெயரை உள்ளிடுங்கள் (<code>bartowski/Qwen3-…-GGUF</code>) அல்லது எந்த சொற்களும். GGUF களஞ்சியங்கள் மட்டுமே காட்டப்படும்."],
      ["#hfRepoCol", "களஞ்சியங்கள்",
       "ஒரு களஞ்சியத்தைத் தேர்வு செய்யுங்கள் — நட்சத்திரங்கள், பதிவிறக்கங்கள், பெஞ்ச்மார்க் பேட்ஜ்கள் தேர்வுக்கு உதவும். ★ பிடித்தவை எப்போதும் மேலே."],
      ["#hfFileCol", "கோப்புகள் & குவாண்ட்கள்",
       "களஞ்சியத்தின் எல்லா GGUF களும் அளவுகளுடன். உங்கள் VRAM இல் பொருந்தும் குவாண்டைசேஷனைத் தேர்ந்து (பலகையின் திருத்தி பொருந்துமா என மதிப்பிடும்) பதிவிறக்கத்தை அழுத்துங்கள்; பல-பகுதி கோப்புகள் தானாக கையாளப்படும். கோப்புகள் <code>&lt;மாதிரி&gt;/&lt;ஆசிரியர்&gt;/&lt;குவாண்ட்&gt;/file.gguf</code> ஆக வைக்கப்படும் — கைமுறையாக மாதிரி சேர்க்கும்போதும் இதே அமைப்பைப் பின்பற்றுங்கள்."],
      [".hf-token-row", "HF டோக்கன்",
       "gated அல்லது தனியார் களஞ்சியங்களுக்கு மட்டுமே தேவை. கட்டுப்படுத்தியில் சேமிக்கப்படும், உலாவியில் ஒருபோதும் இல்லை."],
    ],
  },
};

// Mirrors LANGS in i18n-data.js (kept inline so this page stays independent of
// the big dictionary); scripts/check_tour_i18n.py enforces the mirror.
const HF_LANGS = [
  ["en", "☕ English"], ["zh", "🐼 中文"], ["hi", "🪷 हिन्दी"], ["es", "🥘 Español"],
  ["fr", "🥐 Français"], ["ar", "🕌 العربية"], ["bn", "🐅 বাংলা"], ["pt", "⚽ Português"],
  ["ru", "🪆 Русский"], ["ja", "🗻 日本語"], ["de", "🥨 Deutsch"], ["id", "🦎 Bahasa Indonesia"],
  ["ur", "🌙 اردو"], ["tr", "🧿 Türkçe"], ["ko", "🥋 한국어"], ["vi", "🛵 Tiếng Việt"],
  ["it", "🍕 Italiano"], ["te", "🪔 తెలుగు"], ["mr", "🥭 मराठी"], ["ta", "🐘 தமிழ்"],
];

function hfTourStrings() {
  const lang = localStorage.getItem("llamacppAdminLang") || "en";
  return HF_TOUR[lang] || HF_TOUR.en;
}

function hfTourBtnLabel() {
  const el = document.getElementById("obBtnLabel");
  if (el) el.textContent = hfTourStrings().label;
}

// Every app language is offered; the choice is written to the shared app
// language key, so the main pages pick it up too.
function hfLangPicker(body, api) {
  const s = hfTourStrings();
  const cur = localStorage.getItem("llamacppAdminLang") || "en";
  const wrap = document.createElement("div");
  wrap.className = "ob-langs";
  wrap.innerHTML = `<div class="ob-langs-head">${s.langPick}</div><div class="ob-langs-grid">`
    + HF_LANGS.map(([code, label]) =>
      `<button type="button" class="ob-lang${code === cur ? " selected" : ""}" data-ob-lang="${code}">${label}</button>`).join("")
    + `</div>`;
  wrap.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-ob-lang]");
    if (!btn) return;
    localStorage.setItem("llamacppAdminLang", btn.dataset.obLang);
    hfTourBtnLabel();
    api.rerender();
  });
  body.appendChild(wrap);
}

function hfStartTour() {
  createTour({
    steps: () => hfTourStrings().steps.map(([anchor, title, body], i) => ({
      anchor, title, body, center: !anchor,
      onRender: !anchor && i === 0 ? hfLangPicker : undefined,
    })),
    labels: () => {
      const s = hfTourStrings();
      return { next: s.next, back: s.back, done: s.done, skip: s.skip };
    },
  }).start();
}

hfTourBtnLabel();
initTourButtons({ title: () => hfTourStrings().btn, onClick: hfStartTour });
autoStartOnce("hf", () => !document.getElementById("appLoader"), hfStartTour);
