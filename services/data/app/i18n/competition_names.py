"""
Competition name translations for all supported languages.

Uses pattern-based decomposition: competition names are split into
ordinal prefix ("제N회" or "YYYY") + base name, then translated
using base name mappings and language-specific ordinal formatters.

Supported languages: ko (base), en, fr, it, ja, zh, tr
"""

import re


# =============================================================================
# Ordinal formatters per language
# =============================================================================

def _ordinal_en(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return {1: f"{n}st", 2: f"{n}nd", 3: f"{n}rd"}.get(n % 10, f"{n}th")


_ORDINAL = {
    'en': _ordinal_en,
    'fr': lambda n: f"{n}{'er' if n == 1 else 'e'}",
    'it': lambda n: f"{n}°",
    'ja': lambda n: f"第{n}回",
    'zh': lambda n: f"第{n}届",
    'tr': lambda n: f"{n}.",
}


# =============================================================================
# Base competition name translations (Korean base → {lang: translated})
# =============================================================================
# NOTE: The Korean key is the base name AFTER stripping "제N회 " or "YYYY ".
# Variants (spacing, dot separators) are normalized before lookup.

_BASE_TRANSLATIONS = {
    # --- Selection page short labels (선발 포인트 테이블 약칭) ---
    "중고연맹회장배": {
        "en": "Jr. Federation President's Cup",
        "fr": "Coupe du Président Fédération Jr.",
        "it": "Coppa Presidente Fed. Jr.",
        "ja": "中高連盟会長杯",
        "zh": "中高联盟会长杯",
        "tr": "Jr. Federasyon Başkan Kupası",
    },
    "회장배종별": {
        "en": "President's Cup by Category",
        "fr": "Coupe du Président par Catégorie",
        "it": "Coppa Presidente per Categoria",
        "ja": "会長杯種別",
        "zh": "会长杯分类",
        "tr": "Başkan Kupası Kategorilere Göre",
    },
    "문체부장관기": {
        "en": "Minister of Culture Cup",
        "fr": "Coupe du Ministre de la Culture",
        "it": "Coppa Ministro della Cultura",
        "ja": "文体部長官旗",
        "zh": "文体部长官旗",
        "tr": "Kültür Bakanı Kupası",
    },
    "전국종별": {
        "en": "National by Category",
        "fr": "National par Catégorie",
        "it": "Nazionale per Categoria",
        "ja": "全国種別",
        "zh": "全国分类",
        "tr": "Ulusal Kategorilere Göre",
    },
    "중고연맹종별": {
        "en": "Jr. Federation by Category",
        "fr": "Fédération Jr. par Catégorie",
        "it": "Fed. Jr. per Categoria",
        "ja": "中高連盟種別",
        "zh": "中高联盟分类",
        "tr": "Jr. Federasyon Kategorilere Göre",
    },
    "대통령배": {
        "en": "Presidential Cup",
        "fr": "Coupe Présidentielle",
        "it": "Coppa Presidenziale",
        "ja": "大統領杯",
        "zh": "总统杯",
        "tr": "Cumhurbaşkanlığı Kupası",
    },
    "김창환배": {
        "en": "Kim Chang-hwan Cup",
        "fr": "Coupe Kim Chang-hwan",
        "it": "Coppa Kim Chang-hwan",
        "ja": "キム・チャンファン杯",
        "zh": "金昌焕杯",
        "tr": "Kim Chang-hwan Kupası",
    },
    "종목별오픈": {
        "en": "Open by Event",
        "fr": "Open par Épreuve",
        "it": "Open per Specialità",
        "ja": "種目別オープン",
        "zh": "项目公开赛",
        "tr": "Branş Açık Turnuvası",
    },
    "국대선발": {
        "en": "National Team Selection",
        "fr": "Sélection Équipe Nationale",
        "it": "Selezione Squadra Nazionale",
        "ja": "国家代表選抜",
        "zh": "国家队选拔",
        "tr": "Milli Takım Seçimi",
    },

    # --- KFF President's Cup ---
    "회장배전국남녀종별펜싱선수권대회": {
        "en": "KFF President's Cup National Fencing Championships by Category",
        "fr": "Coupe du Président de la KFF - Championnats Nationaux d'Escrime par Catégorie",
        "it": "Coppa del Presidente KFF - Campionati Nazionali di Scherma per Categoria",
        "ja": "会長杯全国男女種別フェンシング選手権大会",
        "zh": "会长杯全国男女分类击剑锦标赛",
        "tr": "KFF Başkan Kupası Ulusal Eskrim Şampiyonası (Kategorilere Göre)",
    },
    "회장배전국남·녀종별펜싱선수권대회": {
        "en": "KFF President's Cup National Fencing Championships by Category",
        "fr": "Coupe du Président de la KFF - Championnats Nationaux d'Escrime par Catégorie",
        "it": "Coppa del Presidente KFF - Campionati Nazionali di Scherma per Categoria",
        "ja": "会長杯全国男女種別フェンシング選手権大会",
        "zh": "会长杯全国男女分类击剑锦标赛",
        "tr": "KFF Başkan Kupası Ulusal Eskrim Şampiyonası (Kategorilere Göre)",
    },
    # Typo in original data: 펭신 → 펜싱
    "회장배전국남·녀종별펭신선수권대회": {
        "en": "KFF President's Cup National Fencing Championships by Category",
        "fr": "Coupe du Président de la KFF - Championnats Nationaux d'Escrime par Catégorie",
        "it": "Coppa del Presidente KFF - Campionati Nazionali di Scherma per Categoria",
        "ja": "会長杯全国男女種別フェンシング選手権大会",
        "zh": "会长杯全国男女分类击剑锦标赛",
        "tr": "KFF Başkan Kupası Ulusal Eskrim Şampiyonası (Kategorilere Göre)",
    },

    # --- Presidential Cup ---
    "대통령배전국남녀펜싱선수권대회 겸 국가대표선수 선발대회": {
        "en": "Presidential Cup National Fencing Championships & National Team Selection",
        "fr": "Coupe Présidentielle - Championnats Nationaux d'Escrime & Sélection Équipe Nationale",
        "it": "Coppa Presidenziale - Campionati Nazionali di Scherma & Selezione Squadra Nazionale",
        "ja": "大統領杯全国男女フェンシング選手権大会 兼 国家代表選手選抜大会",
        "zh": "总统杯全国男女击剑锦标赛暨国家代表选手选拔赛",
        "tr": "Cumhurbaşkanlığı Kupası Ulusal Eskrim Şampiyonası & Milli Takım Seçimi",
    },
    "대통령배전국남·녀펜싱선수권대회 겸 국가대표선수 선발대회": {
        "en": "Presidential Cup National Fencing Championships & National Team Selection",
        "fr": "Coupe Présidentielle - Championnats Nationaux d'Escrime & Sélection Équipe Nationale",
        "it": "Coppa Presidenziale - Campionati Nazionali di Scherma & Selezione Squadra Nazionale",
        "ja": "大統領杯全国男女フェンシング選手権大会 兼 国家代表選手選抜大会",
        "zh": "总统杯全国男女击剑锦标赛暨国家代表选手选拔赛",
        "tr": "Cumhurbaşkanlığı Kupası Ulusal Eskrim Şampiyonası & Milli Takım Seçimi",
    },
    "대통령배 전국남·녀펜싱선수권대회 겸 국가대표 선수 선발대회": {
        "en": "Presidential Cup National Fencing Championships & National Team Selection",
        "fr": "Coupe Présidentielle - Championnats Nationaux d'Escrime & Sélection Équipe Nationale",
        "it": "Coppa Presidenziale - Campionati Nazionali di Scherma & Selezione Squadra Nazionale",
        "ja": "大統領杯全国男女フェンシング選手権大会 兼 国家代表選手選抜大会",
        "zh": "总统杯全国男女击剑锦标赛暨国家代表选手选拔赛",
        "tr": "Cumhurbaşkanlığı Kupası Ulusal Eskrim Şampiyonası & Milli Takım Seçimi",
    },
    "대통령배전국남녀펜싱선수권대회": {
        "en": "Presidential Cup National Fencing Championships",
        "fr": "Coupe Présidentielle - Championnats Nationaux d'Escrime",
        "it": "Coppa Presidenziale - Campionati Nazionali di Scherma",
        "ja": "大統領杯全国男女フェンシング選手権大会",
        "zh": "总统杯全国男女击剑锦标赛",
        "tr": "Cumhurbaşkanlığı Kupası Ulusal Eskrim Şampiyonası",
    },
    "대통령배전국종별펜싱선수권대회": {
        "en": "Presidential Cup National Fencing Championships by Category",
        "fr": "Coupe Présidentielle - Championnats Nationaux d'Escrime par Catégorie",
        "it": "Coppa Presidenziale - Campionati Nazionali di Scherma per Categoria",
        "ja": "大統領杯全国種別フェンシング選手権大会",
        "zh": "总统杯全国分类击剑锦标赛",
        "tr": "Cumhurbaşkanlığı Kupası Ulusal Eskrim Şampiyonası (Kategorilere Göre)",
    },
    "대통령배전국남녀종별펜싱선수권대회": {
        "en": "Presidential Cup National Fencing Championships by Category",
        "fr": "Coupe Présidentielle - Championnats Nationaux d'Escrime par Catégorie",
        "it": "Coppa Presidenziale - Campionati Nazionali di Scherma per Categoria",
        "ja": "大統領杯全国男女種別フェンシング選手権大会",
        "zh": "总统杯全国男女分类击剑锦标赛",
        "tr": "Cumhurbaşkanlığı Kupası Ulusal Eskrim Şampiyonası (Kategorilere Göre)",
    },
    "대통령배 전국종별펜싱선수권대회": {
        "en": "Presidential Cup National Fencing Championships by Category",
        "fr": "Coupe Présidentielle - Championnats Nationaux d'Escrime par Catégorie",
        "it": "Coppa Presidenziale - Campionati Nazionali di Scherma per Categoria",
        "ja": "大統領杯全国種別フェンシング選手権大会",
        "zh": "总统杯全国分类击剑锦标赛",
        "tr": "Cumhurbaşkanlığı Kupası Ulusal Eskrim Şampiyonası (Kategorilere Göre)",
    },

    # --- Kim Chang-hwan Cup ---
    "김창환배전국남녀펜싱선수권대회 겸 국가대표선수 선발대회": {
        "en": "Kim Chang-hwan Cup National Fencing Championships & National Team Selection",
        "fr": "Coupe Kim Chang-hwan - Championnats Nationaux d'Escrime & Sélection Équipe Nationale",
        "it": "Coppa Kim Chang-hwan - Campionati Nazionali di Scherma & Selezione Squadra Nazionale",
        "ja": "金昌煥杯全国男女フェンシング選手権大会 兼 国家代表選手選抜大会",
        "zh": "金昌焕杯全国男女击剑锦标赛暨国家代表选手选拔赛",
        "tr": "Kim Chang-hwan Kupası Ulusal Eskrim Şampiyonası & Milli Takım Seçimi",
    },
    "김창환배전국남·녀펜싱선수권대회 겸 국가대표선수 선발대회": {
        "en": "Kim Chang-hwan Cup National Fencing Championships & National Team Selection",
        "fr": "Coupe Kim Chang-hwan - Championnats Nationaux d'Escrime & Sélection Équipe Nationale",
        "it": "Coppa Kim Chang-hwan - Campionati Nazionali di Scherma & Selezione Squadra Nazionale",
        "ja": "金昌煥杯全国男女フェンシング選手権大会 兼 国家代表選手選抜大会",
        "zh": "金昌焕杯全国男女击剑锦标赛暨国家代表选手选拔赛",
        "tr": "Kim Chang-hwan Kupası Ulusal Eskrim Şampiyonası & Milli Takım Seçimi",
    },
    "김창환배 전국남녀펜싱선수권대회": {
        "en": "Kim Chang-hwan Cup National Fencing Championships",
        "fr": "Coupe Kim Chang-hwan - Championnats Nationaux d'Escrime",
        "it": "Coppa Kim Chang-hwan - Campionati Nazionali di Scherma",
        "ja": "金昌煥杯全国男女フェンシング選手権大会",
        "zh": "金昌焕杯全国男女击剑锦标赛",
        "tr": "Kim Chang-hwan Kupası Ulusal Eskrim Şampiyonası",
    },

    # --- National Fencing Championships by Category ---
    "전국남녀종별펜싱선수권대회": {
        "en": "National Fencing Championships by Category",
        "fr": "Championnats Nationaux d'Escrime par Catégorie",
        "it": "Campionati Nazionali di Scherma per Categoria",
        "ja": "全国男女種別フェンシング選手権大会",
        "zh": "全国男女分类击剑锦标赛",
        "tr": "Ulusal Eskrim Şampiyonası (Kategorilere Göre)",
    },
    "전국남녀종별펜싱선수권대회(고등부)": {
        "en": "National Fencing Championships by Category (High School Division)",
        "fr": "Championnats Nationaux d'Escrime par Catégorie (Division Lycée)",
        "it": "Campionati Nazionali di Scherma per Categoria (Divisione Liceo)",
        "ja": "全国男女種別フェンシング選手権大会（高等部）",
        "zh": "全国男女分类击剑锦标赛（高中组）",
        "tr": "Ulusal Eskrim Şampiyonası (Lise Bölümü)",
    },
    "전국남녀종별펜싱선수권대회(초·중·대·일반부 개최)": {
        "en": "National Fencing Championships by Category (Elementary/Middle/University/Senior Divisions)",
        "fr": "Championnats Nationaux d'Escrime par Catégorie (Divisions Primaire/Collège/Université/Senior)",
        "it": "Campionati Nazionali di Scherma per Categoria (Divisioni Elementare/Media/Università/Senior)",
        "ja": "全国男女種別フェンシング選手権大会（小・中・大・一般部開催）",
        "zh": "全国男女分类击剑锦标赛（小学·初中·大学·一般组）",
        "tr": "Ulusal Eskrim Şampiyonası (İlk/Orta/Üniversite/Büyükler Bölümleri)",
    },

    # --- National Sports Festivals ---
    "전국체육대회": {
        "en": "National Sports Festival",
        "fr": "Festival National des Sports",
        "it": "Festival Nazionale dello Sport",
        "ja": "全国体育大会",
        "zh": "全国体育大会",
        "tr": "Ulusal Spor Festivali",
    },
    "전국소년체육대회": {
        "en": "National Youth Sports Festival",
        "fr": "Festival National des Sports de la Jeunesse",
        "it": "Festival Nazionale dello Sport Giovanile",
        "ja": "全国少年体育大会",
        "zh": "全国少年体育大会",
        "tr": "Ulusal Gençlik Spor Festivali",
    },

    # --- Ministry of Culture Cup ---
    "문화체육관광부장관기전국남녀중고펜싱선수권대회": {
        "en": "Minister of Culture Cup National Middle & High School Fencing Championships",
        "fr": "Coupe du Ministre de la Culture - Championnats Nationaux d'Escrime Collège & Lycée",
        "it": "Coppa del Ministro della Cultura - Campionati Nazionali di Scherma Scuole Medie & Superiori",
        "ja": "文化体育観光部長官旗全国男女中高フェンシング選手権大会",
        "zh": "文化体育观光部部长旗全国男女中高击剑锦标赛",
        "tr": "Kültür Bakanı Kupası Ulusal Ortaokul & Lise Eskrim Şampiyonası",
    },
    "문화체육관광부장관기전국체육고등학교체육대회": {
        "en": "Minister of Culture Cup National Sports High School Athletics",
        "fr": "Coupe du Ministre de la Culture - Compétitions des Lycées Sportifs Nationaux",
        "it": "Coppa del Ministro della Cultura - Gare delle Scuole Sportive Nazionali",
        "ja": "文化体育観光部長官旗全国体育高等学校体育大会",
        "zh": "文化体育观光部部长旗全国体育高中体育大会",
        "tr": "Kültür Bakanı Kupası Ulusal Spor Liseleri Atletizm Müsabakaları",
    },

    # --- KMHFF (Korean Middle & High School Fencing Federation) ---
    "한국중고펜싱연맹회장배전국남녀중고펜싱선수권대회": {
        "en": "KMHFF President's Cup National Middle & High School Fencing Championships",
        "fr": "Coupe du Président KMHFF - Championnats Nationaux d'Escrime Collège & Lycée",
        "it": "Coppa del Presidente KMHFF - Campionati Nazionali di Scherma Scuole Medie & Superiori",
        "ja": "韓国中高フェンシング連盟会長杯全国男女中高フェンシング選手権大会",
        "zh": "韩国中高击剑联盟会长杯全国男女中高击剑锦标赛",
        "tr": "KMHFF Başkan Kupası Ulusal Ortaokul & Lise Eskrim Şampiyonası",
    },
    # 대한중고펜싱연맹 == 한국중고펜싱연맹 (same federation, both spellings appear
    # in KFA source data) — keep the English/abbreviation identical.
    "대한중고펜싱연맹회장배전국중고펜싱선수권대회": {
        "en": "KMHFF President's Cup National Middle & High School Fencing Championships",
        "fr": "Coupe du Président KMHFF - Championnats Nationaux d'Escrime Collège & Lycée",
        "it": "Coppa del Presidente KMHFF - Campionati Nazionali di Scherma Scuole Medie & Superiori",
        "ja": "大韓中高フェンシング連盟会長杯全国中高フェンシング選手権大会",
        "zh": "大韩中高击剑联盟会长杯全国中高击剑锦标赛",
        "tr": "KMHFF Başkan Kupası Ulusal Ortaokul & Lise Eskrim Şampiyonası",
    },
    "대한중고펜싱연맹회장배전국남녀중고펜싱선수권대회": {
        "en": "KMHFF President's Cup National Middle & High School Fencing Championships",
        "fr": "Coupe du Président KMHFF - Championnats Nationaux d'Escrime Collège & Lycée",
        "it": "Coppa del Presidente KMHFF - Campionati Nazionali di Scherma Scuole Medie & Superiori",
        "ja": "大韓中高フェンシング連盟会長杯全国男女中高フェンシング選手権大会",
        "zh": "大韩中高击剑联盟会长杯全国男女中高击剑锦标赛",
        "tr": "KMHFF Başkan Kupası Ulusal Ortaokul & Lise Eskrim Şampiyonası",
    },
    "대한중고펜싱연맹전국남녀종별펜싱선수권대회": {
        "en": "KMHFF National Fencing Championships by Category",
        "fr": "Championnats Nationaux d'Escrime par Catégorie de la KMHFF",
        "it": "Campionati Nazionali di Scherma per Categoria della KMHFF",
        "ja": "大韓中高フェンシング連盟全国男女種別フェンシング選手権大会",
        "zh": "大韩中高击剑联盟全国男女分类击剑锦标赛",
        "tr": "KMHFF Ulusal Eskrim Şampiyonası (Kategorilere Göre)",
    },
    "한국중고펜싱연맹전국남녀종별펜싱선수권대회": {
        "en": "KMHFF National Fencing Championships by Category",
        "fr": "Championnats Nationaux d'Escrime par Catégorie de la KMHFF",
        "it": "Campionati Nazionali di Scherma per Categoria della KMHFF",
        "ja": "韓国中高フェンシング連盟全国男女種別フェンシング選手権大会",
        "zh": "韩国中高击剑联盟全国男女分类击剑锦标赛",
        "tr": "KMHFF Ulusal Eskrim Şampiyonası (Kategorilere Göre)",
    },

    # --- KPFF (Korean Professional Fencing Federation) ---
    "한국실업펜싱연맹회장배전국남녀펜싱선수권대회": {
        "en": "KPFF President's Cup National Fencing Championships",
        "fr": "Coupe du Président KPFF - Championnats Nationaux d'Escrime",
        "it": "Coppa del Presidente KPFF - Campionati Nazionali di Scherma",
        "ja": "韓国実業フェンシング連盟会長杯全国男女フェンシング選手権大会",
        "zh": "韩国实业击剑联盟会长杯全国男女击剑锦标赛",
        "tr": "KPFF Başkan Kupası Ulusal Eskrim Şampiyonası",
    },
    "한국실업종별펜싱선수권대회": {
        "en": "Korean Professional Fencing Championships by Category",
        "fr": "Championnats Professionnels Coréens d'Escrime par Catégorie",
        "it": "Campionati Professionali Coreani di Scherma per Categoria",
        "ja": "韓国実業種別フェンシング選手権大会",
        "zh": "韩国实业分类击剑锦标赛",
        "tr": "Kore Profesyonel Eskrim Şampiyonası (Kategorilere Göre)",
    },

    # --- University Championships ---
    "전국남녀대학펜싱선수권대회": {
        "en": "National University Fencing Championships",
        "fr": "Championnats Nationaux Universitaires d'Escrime",
        "it": "Campionati Nazionali Universitari di Scherma",
        "ja": "全国男女大学フェンシング選手権大会",
        "zh": "全国男女大学击剑锦标赛",
        "tr": "Ulusal Üniversite Eskrim Şampiyonası",
    },
    "한국대학펜싱연맹회장기전국남녀펜싱선수권대회": {
        "en": "KUFA President's Trophy National University Fencing Championships",
        "fr": "Trophée du Président KUFA - Championnats Nationaux Universitaires d'Escrime",
        "it": "Trofeo del Presidente KUFA - Campionati Nazionali Universitari di Scherma",
        "ja": "韓国大学フェンシング連盟会長旗全国男女フェンシング選手権大会",
        "zh": "韩国大学击剑联盟会长旗全国男女击剑锦标赛",
        "tr": "KUFA Başkan Kupası Ulusal Üniversite Eskrim Şampiyonası",
    },
    "한국대학펜싱연맹회장기 전국남녀대학펜싱선수권대회": {
        "en": "KUFA President's Trophy National University Fencing Championships",
        "fr": "Trophée du Président KUFA - Championnats Nationaux Universitaires d'Escrime",
        "it": "Trofeo del Presidente KUFA - Campionati Nazionali Universitari di Scherma",
        "ja": "韓国大学フェンシング連盟会長旗全国男女大学フェンシング選手権大会",
        "zh": "韩国大学击剑联盟会长旗全国男女大学击剑锦标赛",
        "tr": "KUFA Başkan Kupası Ulusal Üniversite Eskrim Şampiyonası",
    },
    "한국대학연맹회장기전국남녀펜싱선수권대회": {
        "en": "KUFA President's Trophy National Fencing Championships",
        "fr": "Trophée du Président KUFA - Championnats Nationaux d'Escrime",
        "it": "Trofeo del Presidente KUFA - Campionati Nazionali di Scherma",
        "ja": "韓国大学連盟会長旗全国男女フェンシング選手権大会",
        "zh": "韩国大学联盟会长旗全国男女击剑锦标赛",
        "tr": "KUFA Başkan Kupası Ulusal Eskrim Şampiyonası",
    },

    # --- National Team Selection ---
    "펜싱 국가대표선수 선발대회": {
        "en": "Fencing National Team Selection",
        "fr": "Sélection de l'Équipe Nationale d'Escrime",
        "it": "Selezione della Squadra Nazionale di Scherma",
        "ja": "フェンシング国家代表選手選抜大会",
        "zh": "击剑国家代表选手选拔赛",
        "tr": "Eskrim Milli Takım Seçmesi",
    },
    "펜싱 국가대표선수 선발전": {
        "en": "Fencing National Team Selection",
        "fr": "Sélection de l'Équipe Nationale d'Escrime",
        "it": "Selezione della Squadra Nazionale di Scherma",
        "ja": "フェンシング国家代表選手選抜戦",
        "zh": "击剑国家代表选手选拔赛",
        "tr": "Eskrim Milli Takım Seçmesi",
    },
    "대한펜싱협회 유소년 국가대표선수 선발전": {
        "en": "KFF Youth National Team Selection",
        "fr": "Sélection de l'Équipe Nationale Jeunes de la KFF",
        "it": "Selezione Squadra Nazionale Giovanile della KFF",
        "ja": "大韓フェンシング協会ユース国家代表選手選抜戦",
        "zh": "大韩击剑协会青少年国家代表选手选拔赛",
        "tr": "KFF Gençlik Milli Takım Seçmesi",
    },
    "대한펜싱협회 유소년 국가대표선수 선발전(여자 플러레)": {
        "en": "KFF Youth National Team Selection (Women's Foil)",
        "fr": "Sélection de l'Équipe Nationale Jeunes de la KFF (Fleuret Dames)",
        "it": "Selezione Squadra Nazionale Giovanile della KFF (Fioretto Femminile)",
        "ja": "大韓フェンシング協会ユース国家代表選手選抜戦（女子フルーレ）",
        "zh": "大韩击剑协会青少年国家代表选手选拔赛（女子花剑）",
        "tr": "KFF Gençlik Milli Takım Seçmesi (Kadın Flöre)",
    },
    "대한펜싱협회 청소년, 유소년 국가대표선수 선발전": {
        "en": "KFF Junior & Youth National Team Selection",
        "fr": "Sélection Équipe Nationale Juniors & Jeunes de la KFF",
        "it": "Selezione Squadra Nazionale Juniores & Giovanile della KFF",
        "ja": "大韓フェンシング協会青少年・ユース国家代表選手選抜戦",
        "zh": "大韩击剑协会青少年及青年国家代表选手选拔赛",
        "tr": "KFF Genç & Gençlik Milli Takım Seçmesi",
    },

    # --- National Open Championships + National Team Selection ---
    "전국남·녀종목별오픈펜싱선수권대회 겸 국가대표선수 선발대회": {
        "en": "National Open Fencing Championships & National Team Selection",
        "fr": "Championnats Nationaux Open d'Escrime & Sélection Équipe Nationale",
        "it": "Campionati Nazionali Open di Scherma & Selezione Squadra Nazionale",
        "ja": "全国男女種目別オープンフェンシング選手権大会 兼 国家代表選手選抜大会",
        "zh": "全国男女分项公开击剑锦标赛暨国家代表选手选拔赛",
        "tr": "Ulusal Açık Eskrim Şampiyonası & Milli Takım Seçimi",
    },
    "전국남녀종목별오픈펜싱선수권대회 겸 국가대표 선수 선발대회": {
        "en": "National Open Fencing Championships & National Team Selection",
        "fr": "Championnats Nationaux Open d'Escrime & Sélection Équipe Nationale",
        "it": "Campionati Nazionali Open di Scherma & Selezione Squadra Nazionale",
        "ja": "全国男女種目別オープンフェンシング選手権大会 兼 国家代表選手選抜大会",
        "zh": "全国男女分项公开击剑锦标赛暨国家代表选手选拔赛",
        "tr": "Ulusal Açık Eskrim Şampiyonası & Milli Takım Seçimi",
    },
    "전국남녀종목별오픈펜싱선수권대회": {
        "en": "National Open Fencing Championships",
        "fr": "Championnats Nationaux Open d'Escrime",
        "it": "Campionati Nazionali Open di Scherma",
        "ja": "全国男女種目別オープンフェンシング選手権大会",
        "zh": "全国男女分项公开击剑锦标赛",
        "tr": "Ulusal Açık Eskrim Şampiyonası",
    },

    # --- FILA Cup ---
    "FILA배 전국생활체육 동호인·클럽펜싱선수권대회": {
        "en": "FILA Cup National Recreational Club Fencing Championships",
        "fr": "Coupe FILA - Championnats Nationaux d'Escrime de Loisir & Club",
        "it": "Coppa FILA - Campionati Nazionali di Scherma Ricreativa & Club",
        "ja": "FILA杯全国生活体育同好人・クラブフェンシング選手権大会",
        "zh": "FILA杯全国全民健身业余·俱乐部击剑锦标赛",
        "tr": "FILA Kupası Ulusal Rekreasyonel Kulüp Eskrim Şampiyonası",
    },

    # --- KFF President's Cup Club Championships ---
    "대한펜싱협회장배 전국 클럽·동호인 펜싱선수권대회": {
        "en": "KFF President's Cup National Club & Amateur Fencing Championships",
        "fr": "Coupe du Président de la KFF - Championnats Nationaux d'Escrime Club & Amateur",
        "it": "Coppa del Presidente KFF - Campionati Nazionali di Scherma Club & Amatoriali",
        "ja": "大韓フェンシング協会長杯全国クラブ・同好人フェンシング選手権大会",
        "zh": "大韩击剑协会会长杯全国俱乐部·业余击剑锦标赛",
        "tr": "KFF Başkan Kupası Ulusal Kulüp & Amatör Eskrim Şampiyonası",
    },
    "대한펜싱협회장배 전국남녀클럽동호인펜싱선수권대회": {
        "en": "KFF President's Cup National Club & Amateur Fencing Championships",
        "fr": "Coupe du Président de la KFF - Championnats Nationaux d'Escrime Club & Amateur",
        "it": "Coppa del Presidente KFF - Campionati Nazionali di Scherma Club & Amatoriali",
        "ja": "大韓フェンシング協会長杯全国男女クラブ同好人フェンシング選手権大会",
        "zh": "大韩击剑协会会长杯全国男女俱乐部业余击剑锦标赛",
        "tr": "KFF Başkan Kupası Ulusal Kulüp & Amatör Eskrim Şampiyonası",
    },
    "대한펜싱협회장배 전국클럽·동호인펜싱선수권대회": {
        "en": "KFF President's Cup National Club & Amateur Fencing Championships",
        "fr": "Coupe du Président de la KFF - Championnats Nationaux d'Escrime Club & Amateur",
        "it": "Coppa del Presidente KFF - Campionati Nazionali di Scherma Club & Amatoriali",
        "ja": "大韓フェンシング協会長杯全国クラブ・同好人フェンシング選手権大会",
        "zh": "大韩击剑协会会长杯全国俱乐部·业余击剑锦标赛",
        "tr": "KFF Başkan Kupası Ulusal Kulüp & Amatör Eskrim Şampiyonası",
    },
    # Unicode variant with ‧ (middle dot) instead of ·
    "대한펜싱협회장배 전국클럽‧동호인펜싱선수권대회": {
        "en": "KFF President's Cup National Club & Amateur Fencing Championships",
        "fr": "Coupe du Président de la KFF - Championnats Nationaux d'Escrime Club & Amateur",
        "it": "Coppa del Presidente KFF - Campionati Nazionali di Scherma Club & Amatoriali",
        "ja": "大韓フェンシング協会長杯全国クラブ・同好人フェンシング選手権大会",
        "zh": "大韩击剑协会会长杯全国俱乐部·业余击剑锦标赛",
        "tr": "KFF Başkan Kupası Ulusal Kulüp & Amatör Eskrim Şampiyonası",
    },

    # --- Recreational Fencing ---
    "생활체육(클럽, 동호인) 전국펜싱대회": {
        "en": "Recreational (Club & Amateur) National Fencing Competition",
        "fr": "Compétition Nationale d'Escrime de Loisir (Club & Amateur)",
        "it": "Competizione Nazionale di Scherma Ricreativa (Club & Amatoriale)",
        "ja": "生活体育（クラブ・同好人）全国フェンシング大会",
        "zh": "全民健身（俱乐部·业余）全国击剑大会",
        "tr": "Rekreasyonel (Kulüp & Amatör) Ulusal Eskrim Müsabakası",
    },
    "생활체육(클럽·동호인) 전국펜싱대회": {
        "en": "Recreational (Club & Amateur) National Fencing Competition",
        "fr": "Compétition Nationale d'Escrime de Loisir (Club & Amateur)",
        "it": "Competizione Nazionale di Scherma Ricreativa (Club & Amatoriale)",
        "ja": "生活体育（クラブ・同好人）全国フェンシング大会",
        "zh": "全民健身（俱乐部·业余）全国击剑大会",
        "tr": "Rekreasyonel (Kulüp & Amatör) Ulusal Eskrim Müsabakası",
    },

    # --- Club Korea Open ---
    "펜싱 클럽 코리아 오픈대회": {
        "en": "Fencing Club Korea Open",
        "fr": "Open de Corée d'Escrime de Club",
        "it": "Open di Corea di Scherma per Club",
        "ja": "フェンシングクラブコリアオープン大会",
        "zh": "击剑俱乐部韩国公开赛",
        "tr": "Eskrim Kulüp Kore Açık Turnuvası",
    },
    # Extra space variant
    "펜싱 클럽 코리아  오픈대회": {
        "en": "Fencing Club Korea Open",
        "fr": "Open de Corée d'Escrime de Club",
        "it": "Open di Corea di Scherma per Club",
        "ja": "フェンシングクラブコリアオープン大会",
        "zh": "击剑俱乐部韩国公开赛",
        "tr": "Eskrim Kulüp Kore Açık Turnuvası",
    },
    "펜싱클럽 코리아 오픈대회": {
        "en": "Fencing Club Korea Open",
        "fr": "Open de Corée d'Escrime de Club",
        "it": "Open di Corea di Scherma per Club",
        "ja": "フェンシングクラブコリアオープン大会",
        "zh": "击剑俱乐部韩国公开赛",
        "tr": "Eskrim Kulüp Kore Açık Turnuvası",
    },

    # --- Korea Iksan International ---
    "코리아 익산 인터내셔널 펜싱선수권대회(U17,U20)": {
        "en": "Korea Iksan International Fencing Championships (U17, U20)",
        "fr": "Championnats Internationaux d'Escrime de Korea Iksan (U17, U20)",
        "it": "Campionati Internazionali di Scherma Korea Iksan (U17, U20)",
        "ja": "コリア益山インターナショナルフェンシング選手権大会（U17, U20）",
        "zh": "韩国益山国际击剑锦标赛（U17, U20）",
        "tr": "Kore Iksan Uluslararası Eskrim Şampiyonası (U17, U20)",
    },
    "코리아 익산 인터내셔널 펜싱선수권대회(U13,U11,U9)": {
        "en": "Korea Iksan International Fencing Championships (U13, U11, U9)",
        "fr": "Championnats Internationaux d'Escrime de Korea Iksan (U13, U11, U9)",
        "it": "Campionati Internazionali di Scherma Korea Iksan (U13, U11, U9)",
        "ja": "コリア益山インターナショナルフェンシング選手権大会（U13, U11, U9）",
        "zh": "韩国益山国际击剑锦标赛（U13, U11, U9）",
        "tr": "Kore Iksan Uluslararası Eskrim Şampiyonası (U13, U11, U9)",
    },

    # --- Summer Universiade ---
    "하계유니버시아드대회 파견선수 선발전": {
        "en": "Summer Universiade Delegation Selection",
        "fr": "Sélection de la Délégation pour l'Universiade d'Été",
        "it": "Selezione della Delegazione per l'Universiade Estiva",
        "ja": "夏季ユニバーシアード大会派遣選手選抜戦",
        "zh": "夏季大学生运动会派遣选手选拔赛",
        "tr": "Yaz Üniversiad Delegasyonu Seçmesi",
    },
    "하계유니버시아드대회 파견선수 선발전(1차)": {
        "en": "Summer Universiade Delegation Selection (1st Round)",
        "fr": "Sélection Délégation Universiade d'Été (1er Tour)",
        "it": "Selezione Delegazione Universiade Estiva (1° Turno)",
        "ja": "夏季ユニバーシアード大会派遣選手選抜戦（1次）",
        "zh": "夏季大学生运动会派遣选手选拔赛（第1轮）",
        "tr": "Yaz Üniversiad Delegasyonu Seçmesi (1. Tur)",
    },
    "하계유니버시아드대회 파견선수 선발전(2차)": {
        "en": "Summer Universiade Delegation Selection (2nd Round)",
        "fr": "Sélection Délégation Universiade d'Été (2e Tour)",
        "it": "Selezione Delegazione Universiade Estiva (2° Turno)",
        "ja": "夏季ユニバーシアード大会派遣選手選抜戦（2次）",
        "zh": "夏季大学生运动会派遣选手选拔赛（第2轮）",
        "tr": "Yaz Üniversiad Delegasyonu Seçmesi (2. Tur)",
    },
}


# =============================================================================
# Regex patterns for decomposing competition names
# =============================================================================

# "제N회 BASE" pattern
_RE_JE_N_HOE = re.compile(r'^제(\d+)회\s*(.+)$')
# "YYYY BASE" pattern (with optional 제N회 embedded after year)
_RE_YEAR_PREFIX = re.compile(r'^(\d{4})\s+(.+)$')
# "YYYY 제N회 BASE" compound pattern
_RE_YEAR_JE_N = re.compile(r'^(\d{4})\s+제(\d+)회\s*(.+)$')
# Test prefix
_RE_TEST_PREFIX = re.compile(r'^테스트_(.+)$')


def _format_ordinal_prefix(n: int, lang: str) -> str:
    """Format the ordinal prefix for the given language."""
    formatter = _ORDINAL.get(lang)
    if formatter:
        return formatter(n)
    return f"{n}"


def translate_competition_name(name_ko: str, lang: str) -> str:
    """Translate a Korean competition name to the target language.

    Decomposition strategy:
    1. Check for "테스트_" prefix → strip and translate rest
    2. Check for "YYYY 제N회 BASE" → year + ordinal + translated base
    3. Check for "YYYY BASE" → year + translated base
    4. Check for "제N회 BASE" → ordinal + translated base
    5. Exact match in _BASE_TRANSLATIONS
    6. Fallback: return Korean original

    Args:
        name_ko: Korean competition name
        lang: Target language code (en, fr, it, ja, zh, tr)

    Returns:
        Translated competition name, or Korean original if no translation found
    """
    if lang == 'ko' or not name_ko:
        return name_ko

    # Strip test prefix
    m_test = _RE_TEST_PREFIX.match(name_ko)
    if m_test:
        inner = m_test.group(1)
        translated = translate_competition_name(inner, lang)
        return f"[TEST] {translated}" if translated != inner else name_ko

    # Try "YYYY 제N회 BASE"
    m = _RE_YEAR_JE_N.match(name_ko)
    if m:
        year, n, base = m.group(1), int(m.group(2)), m.group(3)
        entry = _BASE_TRANSLATIONS.get(base)
        if entry and lang in entry:
            ordinal = _format_ordinal_prefix(n, lang)
            translated_base = entry[lang]
            if lang in ('ja', 'zh'):
                return f"{year} {ordinal} {translated_base}"
            else:
                return f"{year} {ordinal} {translated_base}"
        # Fall through to other patterns

    # Try "YYYY BASE"
    m = _RE_YEAR_PREFIX.match(name_ko)
    if m:
        year, base = m.group(1), m.group(2)
        # Check if base itself starts with 제N회
        m_inner = _RE_JE_N_HOE.match(base)
        if m_inner:
            n, inner_base = int(m_inner.group(1)), m_inner.group(2)
            entry = _BASE_TRANSLATIONS.get(inner_base)
            if entry and lang in entry:
                ordinal = _format_ordinal_prefix(n, lang)
                translated_base = entry[lang]
                if lang in ('ja', 'zh'):
                    return f"{year} {ordinal} {translated_base}"
                else:
                    return f"{year} {ordinal} {translated_base}"
        # Base without ordinal
        entry = _BASE_TRANSLATIONS.get(base)
        if entry and lang in entry:
            return f"{year} {entry[lang]}"

    # Try "제N회 BASE"
    m = _RE_JE_N_HOE.match(name_ko)
    if m:
        n, base = int(m.group(1)), m.group(2)
        entry = _BASE_TRANSLATIONS.get(base)
        if entry and lang in entry:
            ordinal = _format_ordinal_prefix(n, lang)
            translated_base = entry[lang]
            if lang in ('ja', 'zh'):
                return f"{ordinal} {translated_base}"
            else:
                return f"{ordinal} {translated_base}"

    # Exact match (for base names without prefix)
    entry = _BASE_TRANSLATIONS.get(name_ko)
    if entry and lang in entry:
        return entry[lang]

    # Fallback: return Korean original
    return name_ko


def get_js_competition_names(lang: str, competition_names: list) -> dict:
    """Return a dict of {korean_name: translated_name} for JS use.

    Args:
        lang: Target language code
        competition_names: List of Korean competition names to translate

    Returns:
        Dict mapping Korean names to translated names (only translated entries)
    """
    if lang == 'ko':
        return {}
    result = {}
    for name in competition_names:
        translated = translate_competition_name(name, lang)
        if translated != name:
            result[name] = translated
    return result


# =============================================
# Venue names
# =============================================
# Korean venue names follow "<proper noun><facility type>". No official English
# name was published for the venues in this data set, so the proper noun is
# romanized (Revised Romanization) and the facility type is translated, which is
# the convention Korean venues use in English (Jamsil Gymnasium, Jangchung
# Gymnasium). Add an entry to _VENUE_OFFICIAL when an official name does exist:
# that always wins over the generated form.

# The generated form cannot find word boundaries inside a compound proper noun
# (양구 + 청춘 romanizes as one run), so venues present in the data are listed
# here with the spacing spelled out. Replace an entry the moment an official
# English name turns up.
_VENUE_OFFICIAL: dict = {
    "양구청춘체육관": {
        "en": "Yanggu Cheongchun Gymnasium",
        "fr": "Gymnase Yanggu Cheongchun",
        "it": "Palazzetto Yanggu Cheongchun",
        "tr": "Yanggu Cheongchun Spor Salonu",
    },
}

# Longest suffix first: 문화체육관 must match before 체육관.
_VENUE_FACILITY_SUFFIXES = [
    ("국민체육센터", {"en": "Sports Center", "fr": "Centre sportif", "it": "Centro sportivo",
                 "ja": "国民体育センター", "zh": "国民体育中心", "tr": "Spor Merkezi"}),
    ("실내체육관", {"en": "Indoor Gymnasium", "fr": "Gymnase couvert", "it": "Palazzetto coperto",
                "ja": "屋内体育館", "zh": "室内体育馆", "tr": "Kapalı Spor Salonu"}),
    ("문화체육관", {"en": "Culture & Sports Center", "fr": "Centre culturel et sportif",
                "it": "Centro culturale e sportivo", "ja": "文化体育館", "zh": "文化体育馆",
                "tr": "Kültür ve Spor Merkezi"}),
    ("체육공원", {"en": "Sports Park", "fr": "Parc sportif", "it": "Parco sportivo",
               "ja": "体育公園", "zh": "体育公园", "tr": "Spor Parkı"}),
    ("체육관", {"en": "Gymnasium", "fr": "Gymnase", "it": "Palazzetto dello sport",
              "ja": "体育館", "zh": "体育馆", "tr": "Spor Salonu"}),
    ("경기장", {"en": "Stadium", "fr": "Stade", "it": "Stadio",
              "ja": "競技場", "zh": "体育场", "tr": "Stadyum"}),
]


def _romanize_korean(text: str) -> str:
    """Revised Romanization, capitalized as a proper noun."""
    try:
        from app.international_data import romanize_syllable
    except ImportError:
        return text
    out = "".join(romanize_syllable(c) if "가" <= c <= "힣" else c for c in text)
    return out.capitalize() if out else text


def translate_venue_name(venue_ko: str, lang: str) -> str:
    """Localize a Korean venue name.

    Order: official name, then romanized proper noun plus translated facility
    type, then the Korean original. CJK locales keep the Korean text, which
    their readers can parse.
    """
    if not venue_ko or lang == "ko":
        return venue_ko

    # Some records hold several venues separated by a slash.
    if "/" in venue_ko:
        return " / ".join(translate_venue_name(p.strip(), lang) for p in venue_ko.split("/") if p.strip())

    official = _VENUE_OFFICIAL.get(venue_ko)
    if official and lang in official:
        return official[lang]

    if lang in ("ja", "zh"):
        return venue_ko

    for suffix, labels in _VENUE_FACILITY_SUFFIXES:
        if venue_ko.endswith(suffix):
            stem = venue_ko[: -len(suffix)].strip()
            facility = labels.get(lang, labels["en"])
            return f"{_romanize_korean(stem)} {facility}".strip() if stem else facility

    # No facility suffix: a bare place name such as 익산.
    return _romanize_korean(venue_ko)
