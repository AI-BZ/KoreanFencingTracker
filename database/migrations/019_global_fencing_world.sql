-- ============================================================================
-- Migration 019: Global Fencing World Reference Data
-- Created: 2026-05-24
-- Updated: 2026-05-25 (추가 브랜드 80+, 데이터 플랫폼 65개)
-- Description: 전 세계 펜싱 연맹, 장비 브랜드, 관련 조직, 데이터 플랫폼
--   - fie_confederations: 5개 대륙 연합
--   - fie_national_federations: 162개 국가 연맹
--   - fencing_equipment_brands: 147 장비 브랜드/리테일러 (30개국+)
--   - fencing_world_organizations: 65 관련 조직 (FIE 위원회, 코치협회, 지역협회 등)
--   - fencing_data_platforms: 65 데이터/분석/결과 플랫폼
--
-- Supabase 마이그레이션 적용 이력:
--   1. global_fencing_world_tables_and_confederations
--   2. global_fencing_federations_europe_asia
--   3. global_fencing_federations_americas_africa_oceania
--   4. global_fencing_equipment_brands
--   5. global_fencing_world_organizations
--   6. global_fencing_world_organizations_additional
--   7. global_fencing_equipment_brands_additional
--   8. additional_equipment_brands_manufacturers
--   9. additional_equipment_brands_retailers_asia_europe
--   10. additional_equipment_brands_retailers_americas_oceania_eastern
--   11. create_fencing_data_platforms_table
--   12. insert_data_platforms_official_bodies
--   13. insert_data_platforms_independent_analytics_ai
--   14. insert_data_platforms_tournament_software_scoring
-- ============================================================================

-- ============================================================================
-- TABLE 1: fie_confederations (대륙 펜싱 연합)
-- ============================================================================
CREATE TABLE IF NOT EXISTS fie_confederations (
    id SERIAL PRIMARY KEY,
    code VARCHAR(5) NOT NULL UNIQUE,
    name_en VARCHAR(200) NOT NULL,
    name_fr VARCHAR(200),
    abbreviation VARCHAR(10) NOT NULL,
    website VARCHAR(200),
    headquarters VARCHAR(200),
    founded_year INTEGER,
    member_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO fie_confederations (code, name_en, name_fr, abbreviation, website, headquarters, founded_year, member_count)
VALUES
('EUR', 'European Fencing Confederation', 'Confédération Européenne d''Escrime', 'EFC/CEE', 'https://www.fencing-efc.eu', 'Brussels, Belgium', 1991, 47),
('AME', 'Pan American Fencing Confederation', 'Confédération Panaméricaine d''Escrime', 'CPE/PAFC', 'http://www.cpe-fie.org', 'Mexico City, Mexico', 1951, 33),
('AFR', 'African Fencing Confederation', 'Confédération Africaine d''Escrime', 'CAE', 'https://www.cae-fencing.org', 'Dakar, Senegal', 1989, 31),
('ASI', 'Fencing Confederation of Asia', 'Confédération Asiatique d''Escrime', 'FCA', 'https://asian-fencing.com', 'Kuwait City, Kuwait', 1988, 40),
('OCE', 'Oceania Fencing Confederation', 'Confédération d''Escrime d''Océanie', 'OFC', 'https://www.oceaniafencing.org', 'Sydney, Australia', 2002, 6)
ON CONFLICT (code) DO NOTHING;


-- ============================================================================
-- TABLE 2: fie_national_federations (국가 펜싱 연맹)
-- ============================================================================
CREATE TABLE IF NOT EXISTS fie_national_federations (
    id SERIAL PRIMARY KEY,
    country_name_en VARCHAR(100) NOT NULL,
    country_name_native VARCHAR(200),
    fie_code VARCHAR(5) NOT NULL UNIQUE,
    iso_alpha3 VARCHAR(3),
    federation_name_en VARCHAR(300),
    federation_name_native VARCHAR(300),
    federation_abbreviation VARCHAR(20),
    website VARCHAR(300),
    email VARCHAR(200),
    confederation_code VARCHAR(5) NOT NULL REFERENCES fie_confederations(code),
    membership_status VARCHAR(20) DEFAULT 'full',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- EUROPE (47)
INSERT INTO fie_national_federations (fie_code, iso_alpha3, country_name_en, country_name_native, federation_name_en, federation_name_native, federation_abbreviation, website, email, confederation_code, membership_status)
VALUES
('ALB', 'ALB', 'Albania', 'Shqipëria', 'Albanian Fencing Federation', 'Federata Shqiptare e Skermës', 'FSHSK', NULL, NULL, 'EUR', 'full'),
('ARM', 'ARM', 'Armenia', 'Hayastan', 'Armenian Fencing Federation', NULL, NULL, NULL, NULL, 'EUR', 'full'),
('AUT', 'AUT', 'Austria', 'Österreich', 'Austrian Fencing Federation', 'Österreichischer Fechtverband', 'OeFV', 'http://www.oefv.com', 'office@oefv.com', 'EUR', 'full'),
('AZE', 'AZE', 'Azerbaijan', 'Azərbaycan', 'Azerbaijan Fencing Federation', 'Azərbaycan Qılıncoynatma Federasiyası', NULL, NULL, NULL, 'EUR', 'full'),
('BLR', 'BLR', 'Belarus', 'Беларусь', 'Belarusian Fencing Federation', 'Беларуская федэрацыя фехтавання', 'BFF', NULL, NULL, 'EUR', 'suspended'),
('BEL', 'BEL', 'Belgium', 'België / Belgique', 'Royal Belgian Fencing Federation', 'Fédération Royale Belge des Cercles d''Escrime', 'FRBCE', 'http://www.fencing-belgium.be', 'info@fencing-belgium.be', 'EUR', 'full'),
('BUL', 'BGR', 'Bulgaria', 'България', 'Bulgarian Fencing Federation', 'Българска федерация по фехтовка', 'BFF', NULL, NULL, 'EUR', 'full'),
('CRO', 'HRV', 'Croatia', 'Hrvatska', 'Croatian Fencing Federation', 'Hrvatski mačevalački savez', 'HMS', NULL, NULL, 'EUR', 'full'),
('CYP', 'CYP', 'Cyprus', 'Κύπρος', 'Cyprus Fencing Federation', 'Κυπριακή Ομοσπονδία Ξιφασκίας', NULL, NULL, NULL, 'EUR', 'full'),
('CZE', 'CZE', 'Czechia', 'Česko', 'Czech Fencing Federation', 'Český svaz šermu', 'CSS', NULL, NULL, 'EUR', 'full'),
('DEN', 'DNK', 'Denmark', 'Danmark', 'Danish Fencing Federation', 'Dansk Fægte Forbund', 'DFF', 'http://www.faegtning.dk', 'dff@faegtning.dk', 'EUR', 'full'),
('EST', 'EST', 'Estonia', 'Eesti', 'Estonian Fencing Federation', 'Eesti Vehklemisliit', 'EVL', NULL, NULL, 'EUR', 'full'),
('FIN', 'FIN', 'Finland', 'Suomi', 'Finnish Fencing Federation', 'Suomen Miekkailuliitto', 'SML', NULL, NULL, 'EUR', 'full'),
('FRA', 'FRA', 'France', 'France', 'French Fencing Federation', 'Fédération Française d''Escrime', 'FFE', 'http://www.escrime-ffe.fr', 'contact@ffescrime.fr', 'EUR', 'full'),
('GEO', 'GEO', 'Georgia', 'საქართველო', 'Georgian Fencing Federation', 'საქართველოს ფარიკაობის ფედერაცია', NULL, NULL, NULL, 'EUR', 'full'),
('GER', 'DEU', 'Germany', 'Deutschland', 'German Fencing Federation', 'Deutscher Fechter-Bund', 'DFeB', 'http://www.fechten.org', 'info@fechten.org', 'EUR', 'full'),
('GBR', 'GBR', 'Great Britain', 'Great Britain', 'British Fencing', 'British Fencing Association', 'BF', 'http://www.britishfencing.com', 'headoffice@britishfencing.com', 'EUR', 'full'),
('GRE', 'GRC', 'Greece', 'Ελλάδα', 'Hellenic Fencing Federation', 'Ελληνική Ομοσπονδία Ξιφασκίας', 'EOX', 'http://www.fencing.org.gr', 'fencing@fencing.org.gr', 'EUR', 'full'),
('HUN', 'HUN', 'Hungary', 'Magyarország', 'Hungarian Fencing Federation', 'Magyar Vívó Szövetség', 'MVSz', 'http://www.hunfencing.hu', 'benedek.soproniszabo@hunfencing.hu', 'EUR', 'full'),
('ISL', 'ISL', 'Iceland', 'Ísland', 'Icelandic Fencing Federation', 'Skylmingasamband Íslands', NULL, NULL, NULL, 'EUR', 'full'),
('IRL', 'IRL', 'Ireland', 'Éire', 'Fencing Ireland', 'Fencing Ireland', 'FI', NULL, NULL, 'EUR', 'full'),
('ISR', 'ISR', 'Israel', 'ישראל', 'Israel Fencing Association', 'איגוד הסיוף בישראל', 'IFA', 'http://www.fencing.org.il', 'office@fencing.org.il', 'EUR', 'full'),
('ITA', 'ITA', 'Italy', 'Italia', 'Italian Fencing Federation', 'Federazione Italiana Scherma', 'FIS', 'http://www.federscherma.it', 'internazionale@federscherma.it', 'EUR', 'full'),
('LAT', 'LVA', 'Latvia', 'Latvija', 'Latvian Fencing Federation', 'Latvijas Paukošanas Federācija', 'LPF', NULL, NULL, 'EUR', 'full'),
('LIE', 'LIE', 'Liechtenstein', 'Liechtenstein', 'Liechtenstein Fencing Federation', 'Liechtensteiner Fechtverband', NULL, NULL, NULL, 'EUR', 'full'),
('LTU', 'LTU', 'Lithuania', 'Lietuva', 'Lithuanian Fencing Federation', 'Lietuvos fechtavimo federacija', 'LFF', NULL, NULL, 'EUR', 'full'),
('LUX', 'LUX', 'Luxembourg', 'Lëtzebuerg', 'Luxembourg Fencing Federation', 'Fédération Luxembourgeoise d''Escrime', 'FLE', NULL, NULL, 'EUR', 'full'),
('MLT', 'MLT', 'Malta', 'Malta', 'Malta Fencing Association', 'Malta Fencing Association', 'MFA', NULL, NULL, 'EUR', 'full'),
('MON', 'MCO', 'Monaco', 'Monaco', 'Fencing Federation of Monaco', 'Fédération Monégasque d''Escrime', 'FME', NULL, NULL, 'EUR', 'full'),
('MNE', 'MNE', 'Montenegro', 'Crna Gora', 'Fencing Federation of Montenegro', 'Mačevalački savez Crne Gore', NULL, NULL, NULL, 'EUR', 'full'),
('NED', 'NLD', 'Netherlands', 'Nederland', 'Royal Netherlands Fencing Federation', 'Koninklijke Nederlandse Algemene Schermbond', 'KNAS', 'http://www.knas.nl', 'info@knas.nl', 'EUR', 'full'),
('MKD', 'MKD', 'North Macedonia', 'Северна Македонија', 'Fencing Federation of North Macedonia', 'Федерација на мечувалство на Македонија', NULL, NULL, NULL, 'EUR', 'full'),
('NOR', 'NOR', 'Norway', 'Norge', 'Norwegian Fencing Federation', 'Norges Fekteforbund', 'NFF', 'http://www.fekting.no', 'claes.bendiksen@nif.idrett.no', 'EUR', 'full'),
('POL', 'POL', 'Poland', 'Polska', 'Polish Fencing Federation', 'Polski Związek Szermierczy', 'PZSzerm', 'http://www.pzszerm.pl', 'pzszerm@pzszerm.pl', 'EUR', 'full'),
('POR', 'PRT', 'Portugal', 'Portugal', 'Portuguese Fencing Federation', 'Federação Portuguesa de Esgrima', 'FPE', NULL, NULL, 'EUR', 'full'),
('MDA', 'MDA', 'Moldova', 'Moldova', 'Fencing Federation of Moldova', 'Federația de Scrimă din Moldova', NULL, NULL, NULL, 'EUR', 'full'),
('ROU', 'ROU', 'Romania', 'România', 'Romanian Fencing Federation', 'Federația Română de Scrimă', 'FRS', 'http://www.frscrima.ro', 'office@frscrima.ro', 'EUR', 'full'),
('RUS', 'RUS', 'Russia', 'Россия', 'Russian Fencing Federation', 'Федерация фехтования России', 'FFR', 'http://www.rusfencing.ru', 'info@rusfencing.ru', 'EUR', 'suspended'),
('SMR', 'SMR', 'San Marino', 'San Marino', 'San Marino Fencing Federation', 'Federazione Sammarinese Scherma', 'FSS', NULL, NULL, 'EUR', 'full'),
('SRB', 'SRB', 'Serbia', 'Србија', 'Fencing Federation of Serbia', 'Мачевалачки савез Србије', 'MSS', NULL, NULL, 'EUR', 'full'),
('SVK', 'SVK', 'Slovakia', 'Slovensko', 'Slovak Fencing Federation', 'Slovenský šermiársky zväz', 'SSZ', NULL, NULL, 'EUR', 'full'),
('SLO', 'SVN', 'Slovenia', 'Slovenija', 'Fencing Federation of Slovenia', 'Mečevalska zveza Slovenije', 'MZS', NULL, NULL, 'EUR', 'full'),
('ESP', 'ESP', 'Spain', 'España', 'Royal Spanish Fencing Federation', 'Real Federación Española de Esgrima', 'RFEE', 'http://www.esgrima.es', 'rfee@esgrima.es', 'EUR', 'full'),
('SWE', 'SWE', 'Sweden', 'Sverige', 'Swedish Fencing Federation', 'Svenska Fäktförbundet', 'SFF', 'http://www.fencing.se', 'info@fencing.se', 'EUR', 'full'),
('SUI', 'CHE', 'Switzerland', 'Schweiz / Suisse', 'Swiss Fencing Federation', 'Fédération Suisse d''Escrime', 'FSE', 'http://www.swiss-fencing.ch', 'info@swiss-fencing.ch', 'EUR', 'full'),
('TUR', 'TUR', 'Turkiye', 'Türkiye', 'Turkish Fencing Federation', 'Türkiye Eskrim Federasyonu', 'TEF', 'http://www.eskrim.org.tr', 'tef@eskrim.org.tr', 'EUR', 'full'),
('UKR', 'UKR', 'Ukraine', 'Україна', 'Ukrainian Fencing Federation', 'Національна федерація фехтування України', 'NFFU', 'http://www.nffu.org.ua', 'ukr-fencing@ukr.net', 'EUR', 'full')
ON CONFLICT (fie_code) DO NOTHING;

-- ASIA (41)
INSERT INTO fie_national_federations (fie_code, iso_alpha3, country_name_en, country_name_native, federation_name_en, federation_name_native, federation_abbreviation, website, email, confederation_code, membership_status)
VALUES
('AFG', 'AFG', 'Afghanistan', 'افغانستان', 'Fencing Federation of Afghanistan', 'فدراسیون شمشیرزنی افغانستان', NULL, NULL, 'fencing.afg@gmail.com', 'ASI', 'full'),
('BRN', 'BHR', 'Bahrain', 'البحرين', 'Bahrain Fencing Federation', 'الاتحاد البحريني للمبارزة', NULL, NULL, 'bahrainfencing@gmail.com', 'ASI', 'full'),
('BAN', 'BGD', 'Bangladesh', 'বাংলাদেশ', 'Bangladesh Fencing Federation', 'বাংলাদেশ ফেন্সিং ফেডারেশন', 'BFF', 'http://www.fencingbangladesh.org', 'bangladeshfencing1171@gmail.com', 'ASI', 'full'),
('BRU', 'BRN', 'Brunei Darussalam', 'بروناي', 'Brunei Darussalam Fencing Federation', NULL, 'BDFF', 'http://www.bruneifencing.org', 'bdff.fencing@gmail.com', 'ASI', 'full'),
('CAM', 'KHM', 'Cambodia', 'កម្ពុជា', 'Cambodia Fencing Federation', 'សហព័ន្ធកាំបិត កម្ពុជា', 'CFF', 'http://www.camfencing.org', 'info@camfencing.org', 'ASI', 'full'),
('CHN', 'CHN', 'China', '中国', 'Chinese Fencing Association', '中国击剑协会', 'CFA', 'http://fencing.sport.org.cn', 'fencing@sports.cn', 'ASI', 'full'),
('TPE', 'TWN', 'Chinese Taipei', '中華台北', 'Chinese Taipei Fencing Association', '中華民國擊劍協會', 'CTFA', NULL, 'taipei.fencing@msa.hinet.net', 'ASI', 'full'),
('HKG', 'HKG', 'Hong Kong, China', '香港', 'Fencing Association of Hong Kong, China', '中國香港劍擊總會', 'HKFA', 'http://www.hkfa.org.hk', 'info@hkfa.org.hk', 'ASI', 'full'),
('IND', 'IND', 'India', 'भारत', 'Fencing Association of India', NULL, 'FAI', 'http://www.fencingindia.org', 'comm@fencingindia.org', 'ASI', 'full'),
('INA', 'IDN', 'Indonesia', 'Indonesia', 'Indonesian Fencing Federation', 'Ikatan Anggar Seluruh Indonesia', 'IKASI', 'http://www.ikasi.org', 'ikasiindonesia@gmail.com', 'ASI', 'full'),
('IRI', 'IRN', 'Iran', 'ایران', 'Iran Fencing Federation', 'فدراسیون شمشیربازی ایران', NULL, NULL, 'fencingiranfed@gmail.com', 'ASI', 'full'),
('IRQ', 'IRQ', 'Iraq', 'العراق', 'Iraq Fencing Federation', 'الاتحاد العراقي للمبارزة', NULL, NULL, 'Fencing_iraq@yahoo.com', 'ASI', 'full'),
('JPN', 'JPN', 'Japan', '日本', 'Japan Fencing Association', '日本フェンシング協会', 'JFA', 'http://www.fencing-jpn.jp', 'info@fencing-jpn.jp', 'ASI', 'full'),
('JOR', 'JOR', 'Jordan', 'الأردن', 'Jordan Fencing Federation', 'الاتحاد الأردني للمبارزة', NULL, 'http://www.fencingjordan.com', 'jofenc@hotmail.com', 'ASI', 'full'),
('KAZ', 'KAZ', 'Kazakhstan', 'Қазақстан', 'Kazakhstan Fencing Federation', 'Қазақстан семсерлесу федерациясы', NULL, 'http://www.kazfencing.com', 'office@kazfencing.com', 'ASI', 'full'),
('KOR', 'KOR', 'Korea', '대한민국', 'Korea Fencing Federation', '대한펜싱협회', 'KFF', 'http://fencing.sports.or.kr', 'kffseoul@hotmail.com', 'ASI', 'full'),
('PRK', 'PRK', 'North Korea', '조선민주주의인민공화국', 'DPR Korea Fencing Association', '조선민주주의인민공화국 펜싱 협회', NULL, NULL, NULL, 'ASI', 'full'),
('KUW', 'KWT', 'Kuwait', 'الكويت', 'Kuwait Fencing Amateur Association', 'الاتحاد الكويتي للمبارزة', NULL, 'http://www.q8-fencing.com', 'info@fencingkw.com', 'ASI', 'full'),
('KGZ', 'KGZ', 'Kyrgyzstan', 'Кыргызстан', 'Kyrgyz Fencing Federation', 'Кыргыз фехтование федерациясы', NULL, NULL, 'kgz.fencing@gmail.com', 'ASI', 'full'),
('LBN', 'LBN', 'Lebanon', 'لبنان', 'Lebanon Fencing Federation', 'الاتحاد اللبناني للمبارزة', NULL, NULL, 'fencinglebanon@yahoo.com', 'ASI', 'full'),
('MAC', 'MAC', 'Macao, China', '澳門', 'Macao Fencing Association', '澳門劍擊總會', NULL, NULL, 'fencingmo@yahoo.com', 'ASI', 'full'),
('MAS', 'MYS', 'Malaysia', 'Malaysia', 'Malaysian Fencing Federation', 'Persekutuan Anggar Malaysia', 'MFF', NULL, 'mffmalaysia@hotmail.com', 'ASI', 'full'),
('MGL', 'MNG', 'Mongolia', 'Монгол', 'Mongolia Fencing Federation', 'Монголын илдний спортын холбоо', NULL, NULL, 'mongolia@fencing.mn', 'ASI', 'full'),
('MYA', 'MMR', 'Myanmar', 'မြန်မာ', 'Myanmar Fencing Federation', NULL, NULL, NULL, 'fencingmyanmar@gmail.com', 'ASI', 'full'),
('NEP', 'NPL', 'Nepal', 'नेपाल', 'Nepal Fencing Association', 'नेपाल फेन्सिङ एसोसिएसन', 'NFA', NULL, 'nepalfencing@gmail.com', 'ASI', 'full'),
('OMA', 'OMN', 'Oman', 'عُمان', 'Oman Fencing Committee', 'لجنة المبارزة العمانية', NULL, NULL, NULL, 'ASI', 'full'),
('PAK', 'PAK', 'Pakistan', 'پاکستان', 'Pakistan Fencing Federation', NULL, 'PFF', 'http://www.fencing.pk', 'pakistanfencingfederation1@gmail.com', 'ASI', 'full'),
('PLE', 'PSE', 'Palestine', 'فلسطين', 'Palestine Fencing Federation', 'الاتحاد الفلسطيني للمبارزة', NULL, NULL, 'ffpal@yahoo.com', 'ASI', 'full'),
('PHI', 'PHL', 'Philippines', 'Pilipinas', 'Philippine Fencing Association', NULL, 'PFA', NULL, 'philfencing@gmail.com', 'ASI', 'full'),
('QAT', 'QAT', 'Qatar', 'قطر', 'Qatar Fencing Federation', 'الاتحاد القطري للمبارزة', 'QFF', 'http://www.qatarfencing.qa', 'qff@olympic.qa', 'ASI', 'full'),
('KSA', 'SAU', 'Saudi Arabia', 'المملكة العربية السعودية', 'Saudi Arabia Fencing Federation', 'الاتحاد السعودي للمبارزة', NULL, 'http://www.fencing.sa', 'info@fencing.sa', 'ASI', 'full'),
('SGP', 'SGP', 'Singapore', 'Singapore', 'Fencing Singapore', NULL, 'FS', 'http://www.fencingsingapore.org.sg', 'fsgm@fencingsingapore.org.sg', 'ASI', 'full'),
('SRI', 'LKA', 'Sri Lanka', 'ශ්‍රී ලංකාව', 'Sri Lanka Fencing Federation', NULL, 'SLFF', NULL, 'fencing.srilanka@gmail.com', 'ASI', 'full'),
('SYR', 'SYR', 'Syrian Arab Republic', 'سوريا', 'Syrian Fencing Federation', 'الاتحاد السوري للمبارزة', NULL, NULL, 'fencing.syr@gmail.com', 'ASI', 'full'),
('TJK', 'TJK', 'Tajikistan', 'Тоҷикистон', 'Tajikistan Fencing Federation', NULL, NULL, NULL, NULL, 'ASI', 'full'),
('THA', 'THA', 'Thailand', 'ประเทศไทย', 'Thailand Fencing Association', 'สมาคมกีฬาฟันดาบแห่งประเทศไทย', 'TFA', 'http://www.thaifencing.org', 'fencing.tha@gmail.com', 'ASI', 'full'),
('TKM', 'TKM', 'Turkmenistan', 'Türkmenistan', 'Turkmenistan Fencing Federation', NULL, NULL, NULL, NULL, 'ASI', 'full'),
('UAE', 'ARE', 'United Arab Emirates', 'الإمارات', 'UAE Fencing Federation', 'اتحاد الإمارات للمبارزة', NULL, NULL, NULL, 'ASI', 'full'),
('UZB', 'UZB', 'Uzbekistan', 'Oʻzbekiston', 'Uzbekistan Fencing Federation', NULL, NULL, NULL, NULL, 'ASI', 'full'),
('VIE', 'VNM', 'Vietnam', 'Việt Nam', 'Vietnam Fencing Federation', 'Liên đoàn Đấu kiếm Việt Nam', NULL, NULL, NULL, 'ASI', 'full'),
('YEM', 'YEM', 'Yemen', 'اليمن', 'Yemen Fencing Federation', 'الاتحاد اليمني للمبارزة', NULL, NULL, NULL, 'ASI', 'full')
ON CONFLICT (fie_code) DO NOTHING;

-- AMERICAS (34)
INSERT INTO fie_national_federations (fie_code, iso_alpha3, country_name_en, country_name_native, federation_name_en, federation_name_native, federation_abbreviation, website, email, confederation_code, membership_status)
VALUES
('ANT', 'ATG', 'Antigua and Barbuda', NULL, 'Antigua and Barbuda Fencing Association', NULL, NULL, NULL, NULL, 'AME', 'full'),
('ARG', 'ARG', 'Argentina', 'Argentina', 'Argentine Fencing Federation', 'Federación Argentina de Esgrima', 'FAE', 'http://www.esgrima-fae.com.ar', 'presidencia@faesgrima.org', 'AME', 'full'),
('ARU', 'ABW', 'Aruba', 'Aruba', 'Aruba Fencing Federation', 'Aruba Fencing Bond', NULL, NULL, NULL, 'AME', 'full'),
('BAH', 'BHS', 'Bahamas', 'Bahamas', 'Bahamas Fencing Federation', NULL, NULL, NULL, NULL, 'AME', 'full'),
('BAR', 'BRB', 'Barbados', 'Barbados', 'Barbados Fencing Association', NULL, NULL, NULL, NULL, 'AME', 'full'),
('BIZ', 'BLZ', 'Belize', 'Belize', 'Belize Fencing Federation', NULL, NULL, NULL, NULL, 'AME', 'full'),
('BER', 'BMU', 'Bermuda', 'Bermuda', 'Bermuda Fencing Federation', NULL, NULL, NULL, NULL, 'AME', 'full'),
('BOL', 'BOL', 'Bolivia', 'Bolivia', 'Bolivian Fencing Federation', 'Federación Boliviana de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
('BRA', 'BRA', 'Brazil', 'Brasil', 'Brazilian Fencing Confederation', 'Confederação Brasileira de Esgrima', 'CBE', 'http://www.cbesgrima.org.br', 'contato@cbesgrima.org.br', 'AME', 'full'),
('CAN', 'CAN', 'Canada', 'Canada', 'Canadian Fencing Federation', 'Fédération Canadienne d''Escrime', 'CFF', 'http://www.fencing.ca', 'president@fencing.ca', 'AME', 'full'),
('CHI', 'CHL', 'Chile', 'Chile', 'Chilean Fencing Federation', 'Federación Chilena de Esgrima', 'FECHILE', 'http://www.esgrima.cl', 'esgrimachi@gmail.com', 'AME', 'full'),
('COL', 'COL', 'Colombia', 'Colombia', 'Colombian Fencing Federation', 'Federación Colombiana de Esgrima', 'FCE', 'http://www.colombiaesgrima.es', 'fcesgrimacol@gmail.com', 'AME', 'full'),
('CRC', 'CRI', 'Costa Rica', 'Costa Rica', 'Costa Rica Fencing Federation', 'Federación Costarricense de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
('CUB', 'CUB', 'Cuba', 'Cuba', 'Cuban Fencing Federation', 'Federación Cubana de Esgrima', NULL, 'http://www.inder.co.cu', 'federacioncubanadeesgrima@gmail.com', 'AME', 'full'),
('DMA', 'DMA', 'Dominica', 'Dominica', 'Dominica Fencing Association', NULL, NULL, NULL, NULL, 'AME', 'full'),
('DOM', 'DOM', 'Dominican Republic', 'República Dominicana', 'Dominican Fencing Federation', 'Federación Dominicana de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
('ECU', 'ECU', 'Ecuador', 'Ecuador', 'Ecuadorian Fencing Federation', 'Federación Ecuatoriana de Esgrima', 'FEE', NULL, NULL, 'AME', 'full'),
('ESA', 'SLV', 'El Salvador', 'El Salvador', 'Salvadoran Fencing Federation', 'Federación Salvadoreña de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
('GUA', 'GTM', 'Guatemala', 'Guatemala', 'Guatemalan Fencing Federation', 'Asociación Nacional de Esgrima de Guatemala', NULL, NULL, NULL, 'AME', 'full'),
('GUY', 'GUY', 'Guyana', 'Guyana', 'Guyana Fencing Association', NULL, NULL, NULL, NULL, 'AME', 'full'),
('HAI', 'HTI', 'Haiti', 'Haïti', 'Haitian Fencing Federation', 'Fédération Haïtienne d''Escrime', NULL, NULL, NULL, 'AME', 'full'),
('HON', 'HND', 'Honduras', 'Honduras', 'Honduran Fencing Federation', 'Federación Hondureña de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
('JAM', 'JAM', 'Jamaica', 'Jamaica', 'Jamaica Fencing Association', NULL, NULL, NULL, NULL, 'AME', 'full'),
('MEX', 'MEX', 'Mexico', 'México', 'Mexican Fencing Federation', 'Federación Mexicana de Esgrima', 'FME', 'http://www.femexesgrima.net', 'fme.esgrima@gmail.com', 'AME', 'full'),
('NCA', 'NIC', 'Nicaragua', 'Nicaragua', 'Nicaraguan Fencing Federation', 'Federación Nicaragüense de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
('PAN', 'PAN', 'Panama', 'Panamá', 'Panamanian Fencing Federation', 'Federación Panameña de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
('PAR', 'PRY', 'Paraguay', 'Paraguay', 'Paraguayan Fencing Federation', 'Federación Paraguaya de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
('PER', 'PER', 'Peru', 'Perú', 'Peruvian Fencing Federation', 'Federación Deportiva Nacional de Esgrima', 'FDNPE', NULL, 'presidencia@fdnpe.pe', 'AME', 'full'),
('PUR', 'PRI', 'Puerto Rico', 'Puerto Rico', 'Puerto Rico Fencing Federation', 'Federación Puertorriqueña de Esgrima', NULL, NULL, NULL, 'AME', 'full'),
('TTO', 'TTO', 'Trinidad and Tobago', 'Trinidad and Tobago', 'Trinidad and Tobago Fencing Association', NULL, 'TTFA', NULL, NULL, 'AME', 'full'),
('USA', 'USA', 'United States of America', NULL, 'USA Fencing', 'United States Fencing Association', 'USFA', 'http://www.USFencing.org', 'international@usfencing.org', 'AME', 'full'),
('URU', 'URY', 'Uruguay', 'Uruguay', 'Uruguayan Fencing Federation', 'Federación de Esgrima del Uruguay', NULL, NULL, NULL, 'AME', 'full'),
('VEN', 'VEN', 'Venezuela', 'Venezuela', 'Venezuelan Fencing Federation', 'Federación Venezolana de Esgrima', 'FVE', NULL, 'marin.f.ven@gmail.com', 'AME', 'full'),
('ISV', 'VIR', 'Virgin Islands', NULL, 'Virgin Islands Fencing Association', NULL, NULL, NULL, NULL, 'AME', 'full')
ON CONFLICT (fie_code) DO NOTHING;

-- AFRICA (34)
INSERT INTO fie_national_federations (fie_code, iso_alpha3, country_name_en, country_name_native, federation_name_en, federation_name_native, federation_abbreviation, website, email, confederation_code, membership_status)
VALUES
('ALG', 'DZA', 'Algeria', 'الجزائر', 'Algerian Fencing Federation', 'Fédération Algérienne d''Escrime', 'FAE', NULL, 'faescrime@gmail.com', 'AFR', 'full'),
('ANG', 'AGO', 'Angola', 'Angola', 'Angolan Fencing Federation', 'Federação Angolana de Esgrima', NULL, NULL, NULL, 'AFR', 'full'),
('BEN', 'BEN', 'Benin', 'Bénin', 'Benin Fencing Association', 'Association Béninoise d''Escrime', 'ABE', NULL, NULL, 'AFR', 'full'),
('BOT', 'BWA', 'Botswana', 'Botswana', 'Botswana Amateur Fencing Association', NULL, 'BAFA', NULL, NULL, 'AFR', 'full'),
('BUR', 'BFA', 'Burkina Faso', 'Burkina Faso', 'Burkina Faso Fencing Federation', 'Fédération Burkinabè d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
('CMR', 'CMR', 'Cameroon', 'Cameroun', 'Cameroon Fencing Federation', 'Fédération Camerounaise d''Escrime', 'FECAES', NULL, NULL, 'AFR', 'full'),
('CPV', 'CPV', 'Cape Verde', 'Cabo Verde', 'Cape Verde Fencing Federation', 'Federação Caboverdiana de Esgrima', NULL, NULL, NULL, 'AFR', 'full'),
('CGO', 'COG', 'Congo', 'Congo', 'Congo Fencing Federation', 'Fédération Congolaise d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
('CIV', 'CIV', 'Cote d''Ivoire', 'Côte d''Ivoire', 'Cote d''Ivoire Fencing Federation', 'Fédération Ivoirienne d''Escrime', 'FIE-CI', NULL, NULL, 'AFR', 'full'),
('COD', 'COD', 'Democratic Republic of Congo', 'République démocratique du Congo', 'DR Congo Fencing Federation', 'Fédération d''Escrime de la RD Congo', NULL, NULL, NULL, 'AFR', 'full'),
('EGY', 'EGY', 'Egypt', 'مصر', 'Egyptian Fencing Federation', 'الاتحاد المصري للسلاح', 'EFF', 'http://www.fencingegypt.org', 'admin@fencingegypt.org', 'AFR', 'full'),
('GEQ', 'GNQ', 'Equatorial Guinea', 'Guinea Ecuatorial', 'Equatorial Guinea Fencing Federation', 'Federación Ecuatoguineana de Esgrima', NULL, NULL, NULL, 'AFR', 'full'),
('GAB', 'GAB', 'Gabon', 'Gabon', 'Gabonese Fencing Federation', 'Fédération Gabonaise d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
('GHA', 'GHA', 'Ghana', 'Ghana', 'Ghana Fencing Association', NULL, 'GFA', NULL, NULL, 'AFR', 'full'),
('GUI', 'GIN', 'Guinea', 'Guinée', 'Guinea Fencing Federation', 'Fédération Guinéenne d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
('KEN', 'KEN', 'Kenya', 'Kenya', 'Kenya Fencing Federation', NULL, NULL, NULL, NULL, 'AFR', 'full'),
('LBA', 'LBY', 'Libya', 'ليبيا', 'Libyan Fencing Federation', 'الاتحاد الليبي للمبارزة', NULL, NULL, NULL, 'AFR', 'full'),
('MAD', 'MDG', 'Madagascar', 'Madagasikara', 'Madagascar Fencing Federation', 'Fédération Malgache d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
('MLI', 'MLI', 'Mali', 'Mali', 'Mali Fencing Federation', 'Fédération Malienne d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
('MTN', 'MRT', 'Mauritania', 'موريتانيا', 'Mauritanian Fencing Federation', 'Fédération de Mauritanie d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
('MRI', 'MUS', 'Mauritius', 'Maurice', 'Mauritius Fencing Federation', 'Fédération d''Escrime de Maurice', NULL, NULL, NULL, 'AFR', 'full'),
('MAR', 'MAR', 'Morocco', 'المغرب', 'Royal Moroccan Fencing Federation', 'Fédération Royale Marocaine d''Escrime', 'FRME', 'http://www.marocescrime.com', 'frme2010@gmail.com', 'AFR', 'full'),
('NAM', 'NAM', 'Namibia', 'Namibia', 'Namibia Fencing Federation', NULL, NULL, NULL, NULL, 'AFR', 'full'),
('NIG', 'NER', 'Niger', 'Niger', 'Niger Fencing Federation', 'Fédération Nigérienne d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
('NGR', 'NGA', 'Nigeria', 'Nigeria', 'Fencing Federation of Nigeria', NULL, 'FFN', NULL, 'info@nigerianfencing.com', 'AFR', 'full'),
('RWA', 'RWA', 'Rwanda', 'Rwanda', 'Rwanda Fencing Federation', 'Fédération Rwandaise d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
('SEN', 'SEN', 'Senegal', 'Sénégal', 'Senegalese Fencing Federation', 'Fédération Sénégalaise d''Escrime', 'FSE', NULL, 'fsescrimesenegal2018@gmail.com', 'AFR', 'full'),
('SLE', 'SLE', 'Sierra Leone', 'Sierra Leone', 'Sierra Leone Fencing Association', NULL, NULL, NULL, NULL, 'AFR', 'full'),
('SOM', 'SOM', 'Somalia', 'Soomaaliya', 'Somalia Fencing Federation', NULL, NULL, NULL, NULL, 'AFR', 'full'),
('RSA', 'ZAF', 'South Africa', 'South Africa', 'Fencing Federation of South Africa', NULL, 'FFSA', 'http://www.safencer.co.za', 'louise@safefencing.co.za', 'AFR', 'full'),
('SUD', 'SDN', 'Sudan', 'السودان', 'Sudan Fencing Federation', 'الاتحاد السوداني للمبارزة', NULL, NULL, NULL, 'AFR', 'full'),
('TOG', 'TGO', 'Togo', 'Togo', 'Togolese Fencing Federation', 'Fédération Togolaise d''Escrime', NULL, NULL, NULL, 'AFR', 'full'),
('TUN', 'TUN', 'Tunisia', 'تونس', 'Tunisian Fencing Federation', 'Fédération Tunisienne d''Escrime', 'FTE', NULL, 'contact@ftescrime.com', 'AFR', 'full'),
('UGA', 'UGA', 'Uganda', 'Uganda', 'Uganda Fencing Federation', NULL, 'UFF', NULL, NULL, 'AFR', 'full')
ON CONFLICT (fie_code) DO NOTHING;

-- OCEANIA (6)
INSERT INTO fie_national_federations (fie_code, iso_alpha3, country_name_en, country_name_native, federation_name_en, federation_name_native, federation_abbreviation, website, email, confederation_code, membership_status)
VALUES
('AUS', 'AUS', 'Australia', 'Australia', 'Australian Fencing Federation', NULL, 'AFF', 'http://www.ausfencing.org', 'president@fencing.org.au', 'OCE', 'full'),
('GUM', 'GUM', 'Guam', 'Guåhan', 'Guam Fencing Federation', NULL, NULL, NULL, NULL, 'OCE', 'full'),
('NZL', 'NZL', 'New Zealand', 'Aotearoa', 'Fencing New Zealand', NULL, 'FNZ', 'http://www.fencing.org.nz', 'secretary@fencing.org.nz', 'OCE', 'full'),
('SAM', 'WSM', 'Samoa', 'Sāmoa', 'Samoa Fencing Association', NULL, NULL, NULL, NULL, 'OCE', 'full'),
('ASA', 'ASM', 'American Samoa', 'Amerika Sāmoa', 'American Samoa Fencing Association', NULL, NULL, NULL, NULL, 'OCE', 'associate'),
('PNG', 'PNG', 'Papua New Guinea', 'Papua Niugini', 'Papua New Guinea Fencing Federation', NULL, NULL, NULL, NULL, 'OCE', 'associate')
ON CONFLICT (fie_code) DO NOTHING;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_fie_fed_fie_code ON fie_national_federations(fie_code);
CREATE INDEX IF NOT EXISTS idx_fie_fed_iso ON fie_national_federations(iso_alpha3);
CREATE INDEX IF NOT EXISTS idx_fie_fed_conf ON fie_national_federations(confederation_code);

-- Summary view
CREATE OR REPLACE VIEW fie_federations_summary AS
SELECT
    c.abbreviation AS confederation,
    c.name_en AS confederation_name,
    COUNT(f.id) AS total_members,
    COUNT(CASE WHEN f.membership_status = 'full' THEN 1 END) AS full_members,
    COUNT(CASE WHEN f.membership_status = 'suspended' THEN 1 END) AS suspended,
    COUNT(CASE WHEN f.membership_status = 'associate' THEN 1 END) AS associate
FROM fie_confederations c
LEFT JOIN fie_national_federations f ON f.confederation_code = c.code
GROUP BY c.abbreviation, c.name_en
ORDER BY total_members DESC;


-- ============================================================================
-- TABLE 3: fencing_equipment_brands (펜싱 장비 브랜드)
-- ============================================================================
CREATE TABLE IF NOT EXISTS fencing_equipment_brands (
    id SERIAL PRIMARY KEY,
    brand_name VARCHAR(200) NOT NULL,
    company_legal_name VARCHAR(300),
    country_code CHAR(3) NOT NULL,
    country_name VARCHAR(100) NOT NULL,
    city VARCHAR(200),
    website_url VARCHAR(500),
    founded_year INTEGER,
    product_categories TEXT[],
    is_fie_registered BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    brand_type VARCHAR(50) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO fencing_equipment_brands (brand_name, company_legal_name, country_code, country_name, city, website_url, founded_year, product_categories, is_fie_registered, is_active, brand_type, description)
VALUES
-- Germany
('Allstar', 'allstar Fecht-Center GmbH & Co. KG', 'DEU', 'Germany', 'Kusterdingen', 'https://allstar.de', 1964, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','scoring','piste','electrical'], TRUE, TRUE, 'manufacturer', 'Founded 1964. World''s largest fencing equipment manufacturer. Parent company of Uhlmann.'),
('Uhlmann', 'Uhlmann Fechtsport GmbH & Co. KG', 'DEU', 'Germany', 'Laupheim', 'https://uhlmann-fechtsport.com', 1933, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','scoring','piste','electrical'], TRUE, TRUE, 'manufacturer', 'Founded 1933. Now part of Allstar group. Supplies 80+ countries.'),
('ARTOS Fencing', 'ARTOS Fencing GmbH & Co. KG', 'DEU', 'Germany', 'Schkeuditz', 'https://artos-fencing.com', 1994, ARRAY['clothing','masks','gloves','bags','accessories','piste','scoring','electrical'], TRUE, TRUE, 'manufacturer', 'Founded 1994. Known for FIE-patented aluminium pistes.'),
('FWF Fechtwelt', 'FWF Fechtwelt GmbH', 'DEU', 'Germany', 'Mietingen', 'https://fechtwelt.de', 2005, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'], TRUE, TRUE, 'manufacturer', 'Founded 2005. Made in Germany, FIE standards.'),
('Adidas Fencing', 'Adidas AG', 'DEU', 'Germany', 'Herzogenaurach', 'https://www.adidas.com', NULL, ARRAY['shoes','clothing'], FALSE, TRUE, 'manufacturer', 'Major sportswear brand with fencing shoes and apparel.'),
-- UK
('Leon Paul', 'Leon Paul Equipment Co. Ltd', 'GBR', 'United Kingdom', 'London', 'https://www.leonpaul.com', 1921, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','scoring','electrical'], TRUE, TRUE, 'manufacturer', 'Founded 1921. Family-run 100+ years. Only fencing company run by Olympic fencers.'),
('Excalibur Sports', 'Excalibur Sports Ltd.', 'GBR', 'United Kingdom', 'Hereford', 'https://excalibursports.co.uk', 2017, ARRAY['weapons','clothing','masks','gloves','bags','accessories','scoring','piste'], TRUE, TRUE, 'both', 'Founded 2017 by international-level fencers.'),
('EnPointe', 'EnPointe', 'GBR', 'United Kingdom', NULL, 'https://enpointefencing.com', NULL, ARRAY['scoring','electrical'], FALSE, TRUE, 'manufacturer', 'Wireless fencing scoring system.'),
-- France
('Prieur', 'Prieur Sports', 'FRA', 'France', 'Genlis', 'https://www.prieur-sports.com', 1788, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'], TRUE, TRUE, 'manufacturer', 'Founded 1788 - oldest fencing brand in the world.'),
('Blaise Freres', 'Blaise Freres S.A.S.', 'FRA', 'France', 'Le Chambon-Feugerolles', 'https://blaise-freres.fr', 1885, ARRAY['weapons'], TRUE, TRUE, 'manufacturer', 'Historic French blade forge since 1885.'),
('Engarde', 'Engarde / ST37', 'FRA', 'France', NULL, 'https://www.engarde-escrime.com', NULL, ARRAY['software'], FALSE, TRUE, 'software', 'Tournament management software. FIE standard.'),
-- Italy
('Carmimari', 'Nuova Carmimari S.r.l.', 'ITA', 'Italy', 'Monza', 'https://carmimari.com', 1938, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'], TRUE, TRUE, 'manufacturer', 'Founded 1938. 100% made in Italy.'),
('Negrini', 'L. Negrini & Figli', 'ITA', 'Italy', NULL, 'https://negrini.com', 1897, ARRAY['weapons','clothing','masks','bags','accessories'], TRUE, TRUE, 'manufacturer', 'Family-run since 1897. Made in Italy.'),
('Favero', 'Favero Electronics S.r.l.', 'ITA', 'Italy', 'Arcade (Treviso)', 'https://www.favero.com', 1978, ARRAY['scoring','electrical','training'], FALSE, TRUE, 'manufacturer', 'Founded 1978. Premier scoring machine manufacturer. FIE certified.'),
-- Hungary
('PBT', 'PBT Hungary Ltd.', 'HUN', 'Hungary', 'Budapest', 'https://shop.pbtfencing.com', 1991, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'], TRUE, TRUE, 'manufacturer', 'Founded 1991. Made in Hungary. Also HEMA line.'),
-- Ukraine
('StM', 'StM Group of Companies', 'UKR', 'Ukraine', 'Kharkiv', 'https://stm-fencing.com', 1988, ARRAY['weapons','clothing','masks','gloves','bags','accessories','scoring','electrical'], TRUE, TRUE, 'manufacturer', 'Founded 1988. Full range. Supplies FIE World Cups and Olympics.'),
('Unic Fencing', 'Unic Fencing Plus LLC', 'UKR', 'Ukraine', 'Kharkiv', 'https://unicfencing.com', 2022, ARRAY['weapons','accessories','bags','piste'], TRUE, TRUE, 'manufacturer', 'Founded 2022. Blades, accessories, pistes.'),
-- USA
('Absolute Fencing Gear', 'Absolute Fencing Gear Inc.', 'USA', 'United States', 'Bridgewater, NJ', 'https://www.absolutefencinggear.com', 2004, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','scoring','piste','electrical'], TRUE, TRUE, 'both', 'Founded 2004. Official Supplier for FIE and UIPM.'),
('Blue Gauntlet', 'Blue Gauntlet Fencing Gear Inc.', 'USA', 'United States', 'Saddle Brook, NJ', 'https://www.blue-gauntlet.com', 1995, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','scoring','electrical','training'], TRUE, TRUE, 'both', 'Founded 1995 by six-time Chinese national epee champion.'),
('Radical Fencing', 'Radical Fencing', 'USA', 'United States', 'New York, NY', 'https://radicalfencing.com', NULL, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','scoring','training'], FALSE, TRUE, 'both', 'NYC-based. Designed and made in the U.S.'),
('Blade Fencing Equipment', 'Blade Fencing Equipment Inc.', 'USA', 'United States', 'New York, NY', 'https://blade-fencing-nyc.com', 1983, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], FALSE, TRUE, 'retailer', 'Founded 1983. First to import Russian/Ukrainian steel blades to US.'),
('American Fencers Supply', 'American Fencers Supply Co. Inc.', 'USA', 'United States', 'San Francisco, CA', 'http://www.amfence.com', 1965, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], FALSE, TRUE, 'retailer', 'Established 1965. Oldest US fencing equipment supplier.'),
('Fencing Time', 'Fencing Time LLC', 'USA', 'United States', 'Kirkland, WA', 'https://www.fencingtime.com', NULL, ARRAY['software'], TRUE, TRUE, 'software', 'FIE-registered tournament management software.'),
('Nike Fencing', 'Nike Inc.', 'USA', 'United States', 'Beaverton, OR', 'https://www.nike.com', NULL, ARRAY['shoes'], FALSE, TRUE, 'manufacturer', 'Nike Ballestra fencing shoes (since 2008 Olympics).'),
-- Russia
('LM Group / Lammet', 'LM Group', 'RUS', 'Russia', 'Moscow', 'https://lammet.ru', NULL, ARRAY['weapons','clothing','accessories'], TRUE, TRUE, 'manufacturer', 'Oldest Russian fencing equipment company.'),
('Vniti', 'Vniti', 'RUS', 'Russia', NULL, NULL, NULL, ARRAY['weapons'], FALSE, TRUE, 'manufacturer', 'Russian blade foundry. Cold forging.'),
-- China
('OK Fencing / BOPAC', 'BOPAC Sports Co., Ltd.', 'CHN', 'China', 'Zhangjiagang, Jiangsu', 'https://www.okfencing.com', 2000, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','piste','training','scoring'], TRUE, TRUE, 'manufacturer', 'FIE Certified. Supplies 50+ countries.'),
('Shanghai Jianli', 'Shanghai Jianli Sport Equipment Co., Ltd.', 'CHN', 'China', 'Shanghai', 'http://www.jianlisport.com.cn', 1992, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'], TRUE, TRUE, 'manufacturer', 'Established 1992. Biggest Chinese domestic producer.'),
('LEONARK', 'LEONARK', 'CHN', 'China', NULL, 'https://www.leonark.com', 2018, ARRAY['weapons','clothing','masks','gloves','bags','accessories','training'], FALSE, TRUE, 'manufacturer', 'Founded 2018. Major Amazon presence. Also HEMA gear.'),
('Beyond Fencing Gear', 'Beyond Fencing Gear Ltd.', 'CHN', 'China', 'Nanjing', 'https://chinafencingfactory.com', 2010, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], TRUE, TRUE, 'manufacturer', 'Founded 2010 by former fencing athlete.'),
('Jiangsu Mingjian', 'Jiangsu Mingjian Sports Goods Co., Ltd.', 'CHN', 'China', 'Danyang, Jiangsu', 'http://en.fencingchina.net', NULL, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'], FALSE, TRUE, 'manufacturer', 'EU CE certified. Leading Chinese manufacturer.'),
-- Japan
('Tokyo Fencing', 'Tokyo Fencing Co., Ltd.', 'JPN', 'Japan', 'Tokyo', 'https://tf-fencing.co.jp', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], TRUE, TRUE, 'manufacturer', 'Only FIE-registered Japanese manufacturer.'),
-- South Korea (retailers)
('Fencing Korea', 'Fencing Korea', 'KOR', 'South Korea', 'Seoul', 'https://www.fencingkorea.com', NULL, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'], FALSE, TRUE, 'retailer', 'Korean fencing equipment mall.'),
('Fencing Warehouse', 'Fencing Warehouse', 'KOR', 'South Korea', 'Seoul', 'https://fencingwarehouse.co.kr', NULL, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'], FALSE, TRUE, 'retailer', 'Seoul Gangnam-gu fencing retailer.'),
('Fencing Season', 'Fencing Season', 'KOR', 'South Korea', NULL, 'https://fencingseason.kr', NULL, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'], FALSE, TRUE, 'retailer', 'Korean retailer. Reasonable prices.'),
('Fencing Label', 'Fencing Label', 'KOR', 'South Korea', NULL, 'https://fencinglabel.com', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], FALSE, TRUE, 'both', 'Korean fencing equipment brand.'),
-- Turkey
('Klotho / Maia Fencing', 'Klotho Tekstil San. ve Tic. Ltd. Sti.', 'TUR', 'Turkey', 'Istanbul', 'https://klothomaiafencing.com', NULL, ARRAY['clothing','masks','gloves'], TRUE, TRUE, 'manufacturer', 'FIE-registered textiles manufacturer.'),
('Green Apple Fencing', 'RANA Kilit Ltd.', 'TUR', 'Turkey', 'Istanbul', 'https://greenapplefencing.com', NULL, ARRAY['piste'], TRUE, TRUE, 'manufacturer', 'FIE-registered aluminium piste manufacturer.'),
-- Israel
('4F for Fencing', 'SP D. Rigin', 'ISR', 'Israel', 'Ashqelon', 'https://4fencing.store', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], TRUE, TRUE, 'both', 'FIE-registered equipment supplier.'),
-- Czech Republic
('5M Fencing', '5 M spol. s r.o.', 'CZE', 'Czech Republic', 'Prague', 'https://www.5mfencing.com', 1991, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], FALSE, TRUE, 'both', 'Founded 1991. Allstar representative for Czech Republic.'),
-- Hong Kong
('Purplerise', 'Purplerise', 'HKG', 'Hong Kong', 'Wanchai', 'https://purplerise.com', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], TRUE, TRUE, 'both', 'FIE-registered HK supplier.')
ON CONFLICT DO NOTHING;

-- Additional brands (26)
INSERT INTO fencing_equipment_brands (brand_name, company_legal_name, country_code, country_name, city, website_url, founded_year, product_categories, is_fie_registered, is_active, brand_type, description)
VALUES
('KABCOM', 'KABCOM', 'FRA', 'France', 'Aurec sur Loire', 'https://kabcom.fr', NULL, ARRAY['weapons','accessories','electrical'], TRUE, TRUE, 'manufacturer', 'French FIE-registered manufacturer.'),
('Planete Escrime', 'Planete Escrime', 'FRA', 'France', 'Paris', 'https://www.planeteescrime.com', NULL, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','piste'], FALSE, TRUE, 'retailer', 'Paris-based retailer.'),
('Escrime Diffusion', 'Escrime Diffusion', 'FRA', 'France', NULL, 'https://escrime-diffusion.fr', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], FALSE, TRUE, 'retailer', 'French fencing equipment retailer.'),
('Malterre', 'Malterre', 'FRA', 'France', 'Moreuil', 'https://www.malterrefencing.com', NULL, ARRAY['piste','accessories'], FALSE, TRUE, 'manufacturer', 'Conductive textile fencing pistes approved for all competitions.'),
('Targett Fencing', 'Targett Fencing', 'FRA', 'France', NULL, 'https://targettfencing.com', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], FALSE, TRUE, 'retailer', 'Online fencing equipment retailer.'),
('Triplette Competition Arms', 'Triplette Competition Arms', 'USA', 'United States', 'Elkin, NC', 'https://www.triplette.com', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], FALSE, TRUE, 'both', 'Manufacturer and distributor based in Elkin, NC.'),
('Morehouse Fencing Gear', 'Morehouse Fencing Gear', 'USA', 'United States', 'New York, NY', 'https://morehousefencinggear.com', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], FALSE, TRUE, 'both', 'Founded by Olympic Silver Medalist Tim Morehouse.'),
('The Fencing Post', 'The Fencing Post', 'USA', 'United States', 'California', 'https://thefencingpost.com', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories','scoring'], FALSE, TRUE, 'retailer', 'California-based retailer carrying major brands.'),
('American Fencing Gear', 'American Fencing Gear', 'USA', 'United States', NULL, 'https://americanfencinggear.com', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], FALSE, TRUE, 'both', 'High-quality manufactured fencing gear for all levels.'),
('Alliance Fencing Equipment', 'Alliance Fencing Equipment LLC', 'USA', 'United States', 'San Francisco, CA', 'https://www.alliancefencingequipment.com', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories','scoring'], FALSE, TRUE, 'retailer', 'San Francisco-based retailer. Ships worldwide.'),
('Vinco Sports', 'Vinco Sports Inc.', 'USA', 'United States', 'Montvale, NJ', 'https://vincosports.com', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], TRUE, TRUE, 'both', 'FIE-registered fencing equipment supplier.'),
('Zivkovic Modern Fencing', 'Zivkovic Modern Fencing Equipment', 'USA', 'United States', 'Wellesley, MA', NULL, NULL, ARRAY['weapons','clothing','masks','accessories'], FALSE, TRUE, 'retailer', 'Massachusetts-based fencing equipment supplier.'),
('FenceSmart', 'FenceSmart', 'USA', 'United States', 'New Jersey', NULL, NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], FALSE, TRUE, 'retailer', 'New Jersey-based fencing equipment vendor.'),
('Virtual Scoring Machine (VSM)', 'Second Intention Software and Design', 'USA', 'United States', NULL, 'https://www.virtualscoringmachine.com', NULL, ARRAY['scoring','software'], FALSE, TRUE, 'manufacturer', 'Compact alternative to traditional scoring machines.'),
('WSFENCING / Ally Sports', 'Nanjing Lanzi Sports Equipment Co., Limited', 'CHN', 'China', 'Nanjing, Jiangsu', 'https://www.wsfencing.com', NULL, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'], TRUE, TRUE, 'manufacturer', 'FIE-registered manufacturer in Nanjing.'),
('Shanghai Olympik', 'Shanghai Olympik Sports Co., Ltd.', 'CHN', 'China', 'Shanghai', 'http://www.czhe-fencing.com', NULL, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'], TRUE, TRUE, 'manufacturer', 'High quality equipment. Based in Baoshan District, Shanghai.'),
('Guan Da', 'Wuxi City Guan Da Sport Goods Co., Ltd.', 'CHN', 'China', 'Wuxi, Jiangsu', 'https://gfencing.com', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], TRUE, TRUE, 'manufacturer', 'FIE-registered manufacturer in Wuxi, Jiangsu.'),
('Danyang Sports Article', 'Danyang Sports Article Co., Ltd.', 'CHN', 'China', 'Danyang, Jiangsu', 'https://fencingsets.com', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], TRUE, TRUE, 'manufacturer', 'FIE-registered manufacturer in Danyang, Jiangsu.'),
('Wuxi Husheng', 'Wuxi Husheng Sports Goods Plant', 'CHN', 'China', 'Wuxi, Jiangsu', 'http://en.jiangfencing.com', NULL, ARRAY['weapons','clothing','masks','gloves','bags','accessories'], TRUE, TRUE, 'manufacturer', 'Shore of Taihu Lake. Manufacturing, sales, and service.'),
('KOOV Tech', 'KOOV Tech', 'HKG', 'Hong Kong', 'Kowloon', 'https://koovbroadcasting.com', NULL, ARRAY['broadcasting'], TRUE, TRUE, 'manufacturer', 'FIE-registered fencing broadcasting and video replay systems.'),
('Hi-Tec / Leon Paul Razor', 'Hi-Tec Sports', 'GBR', 'United Kingdom', NULL, NULL, NULL, ARRAY['shoes'], FALSE, TRUE, 'manufacturer', 'Fencing shoes through collaboration with Leon Paul.'),
('Allstar-Uhlmann UK', 'Allstar Uhlmann UK', 'GBR', 'United Kingdom', NULL, 'https://allstaruhlmann.com', NULL, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories','scoring'], FALSE, TRUE, 'retailer', 'Official UK supplier of Allstar and Uhlmann equipment.'),
('WOLF Training Dummy', 'WOLF Fencing', 'ISR', 'Israel', NULL, 'https://rethinkfencing.com', NULL, ARRAY['training'], FALSE, TRUE, 'manufacturer', 'Dynamic mobile fencing training dummy.'),
('MAC Armour', 'MAC Armour CZ', 'CZE', 'Czech Republic', 'Libouchec', 'https://www.mac-armour.cz', NULL, ARRAY['training','clothing'], FALSE, TRUE, 'manufacturer', 'HEMA protective equipment based on original armor construction.'),
('Fechtsport Kindermann / INNOFENCE', 'Fechtsport Kindermann', 'DEU', 'Germany', 'Teltow', 'https://fechtsport-kindermann.de', NULL, ARRAY['weapons','clothing','masks','gloves','shoes','bags','accessories'], FALSE, TRUE, 'retailer', 'Allstar-Uhlmann representation near Berlin.'),
('Calibur', 'Calibur', 'GBR', 'United Kingdom', NULL, 'https://calibur.ai', 2020, ARRAY['scoring','electrical'], FALSE, TRUE, 'manufacturer', 'Wireless fencing scoring system since 2020.')
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_feb_country ON fencing_equipment_brands(country_code);
CREATE INDEX IF NOT EXISTS idx_feb_fie ON fencing_equipment_brands(is_fie_registered);
CREATE INDEX IF NOT EXISTS idx_feb_type ON fencing_equipment_brands(brand_type);
CREATE INDEX IF NOT EXISTS idx_feb_name ON fencing_equipment_brands(brand_name);


-- ============================================================================
-- TABLE 4: fencing_world_organizations (펜싱 관련 조직)
-- ============================================================================
CREATE TABLE IF NOT EXISTS fencing_world_organizations (
    id SERIAL PRIMARY KEY,
    name_en VARCHAR(200) NOT NULL,
    name_native VARCHAR(200),
    abbreviation VARCHAR(20),
    org_type VARCHAR(50) NOT NULL,
    country VARCHAR(100) NOT NULL,
    website VARCHAR(300),
    parent_organization VARCHAR(200),
    founded_year INTEGER,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO fencing_world_organizations (name_en, name_native, abbreviation, org_type, country, website, parent_organization, founded_year, description)
VALUES
-- International Bodies
('Fédération Internationale d''Escrime', 'Fédération Internationale d''Escrime', 'FIE', 'international_body', 'International', 'https://fie.org', 'IOC-recognized', 1913, 'International governing body of Olympic fencing. 155+ member federations. HQ in Lausanne, Switzerland.'),
('FIE Athletes Commission', NULL, 'FIE-ATH', 'fie_commission', 'International', 'https://fie.org/fie/structure/council/Ath', 'FIE', NULL, 'Athletes'' representation within FIE governance.'),
('FIE Refereeing Commission', NULL, 'FIE-REF', 'fie_commission', 'International', 'https://fie.org/fie/structure/council/CA', 'FIE', NULL, 'Oversees international referee certification and training.'),
('FIE SEMI Commission', NULL, 'FIE-SEMI', 'fie_commission', 'International', 'https://fie.org/fie/structure/council/SEMI', 'FIE', NULL, 'Technical commission for equipment homologation and approval.'),
('FIE Coaches Council', NULL, 'FIE-COA', 'fie_commission', 'International', 'https://fie.org/fie/structure/council/Coache', 'FIE', NULL, 'Advisory body for coaching standards.'),
('FIE Veterans Council', NULL, 'FIE-VET', 'fie_commission', 'International', 'https://fie.org/fie/structure/council/Vet', 'FIE', NULL, 'Oversees veterans fencing programs and World Championships.'),
('FIE Medical Commission', NULL, 'FIE-MED', 'fie_commission', 'International', 'https://fie.org/fie/structure/council', 'FIE', NULL, 'Medical services and anti-doping.'),
('FIE Rules Commission', NULL, 'FIE-RUL', 'fie_commission', 'International', 'https://fie.org/fie/structure/council', 'FIE', NULL, 'Develops and maintains competition rules.'),

-- Multi-sport bodies with fencing
('World Abilitysport', NULL, 'WAS', 'para_sports_body', 'International', 'https://worldabilitysport.org', 'IPC-recognized', 2005, 'Governs wheelchair fencing (Paralympic). Formerly IWAS.'),
('World Para Fencing', NULL, 'WPF', 'para_sports_body', 'International', 'https://parafencing.org', 'World Abilitysport', NULL, 'Wheelchair fencing competitions. Paralympic sport since 1960.'),
('International University Sports Federation', 'FISU', 'FISU', 'multi_sport_body', 'International', 'https://www.fisu.net', 'IOC-recognized', 1949, 'World University Games. Fencing included since 1949.'),
('International School Sport Federation', 'ISF', 'ISF', 'multi_sport_body', 'International', 'https://www.isfsports.org', NULL, 1972, 'School sports ages 13-18. Fencing in Gymnasiade.'),
('Union Internationale de Pentathlon Moderne', NULL, 'UIPM', 'multi_sport_body', 'International', 'https://www.uipmworld.org', 'IOC-recognized', 1948, 'Modern pentathlon - fencing/épée is core component.'),

-- Coaches associations
('Académie d''Armes Internationale', 'Académie d''Armes Internationale', 'AAI', 'coaches_association', 'International', 'https://www.aai.world', NULL, NULL, 'World organization of fencing masters. 20+ member national academies.'),
('United States Fencing Coaches Association', NULL, 'USFCA', 'coaches_association', 'United States', 'https://usfca.org', 'AAI member', 1941, 'US fencing coaches education and certification.'),
('British Academy of Fencing', NULL, 'BAF', 'coaches_association', 'United Kingdom', 'https://baf-fencing.com', 'AAI founding member', 1949, 'UK coaching membership. Provost to Professor titles.'),
('Irish Academy of Arms', NULL, 'IAA', 'coaches_association', 'Ireland', 'https://www.irishacademyofarms.org', 'AAI member', 1952, 'Irish national fencing coaching academy.'),
('Accademia Nazionale di Scherma', 'Accademia Nazionale di Scherma', 'ANS', 'coaches_association', 'Italy', NULL, 'AAI member', 1861, 'Italy''s premier fencing academy. Naples. Only Master of Sword conferring institution.'),

-- Veterans fencing
('European Veterans Fencing', NULL, 'EVF', 'veterans_org', 'International', 'https://www.veteransfencing.eu', 'EFC', 1991, 'European Veterans Championships and EVF Circuit ranking.'),
('British Veterans Fencing', NULL, 'BVF', 'veterans_org', 'United Kingdom', 'https://veterans-fencing.co.uk', 'British Fencing', NULL, 'UK veterans fencing competitions.'),

-- HEMA organizations
('International Federation of HEMA', NULL, 'IFHEMA', 'hema_org', 'International', 'https://www.ifhema.org', NULL, 2013, 'Federation of national HEMA organizations.'),
('HEMA Alliance', NULL, NULL, 'hema_org', 'International', 'https://www.hemaalliance.com', NULL, 2010, 'US-based federation of HEMA schools.'),

-- National sub-organizations
('England Fencing', NULL, 'EF', 'national_sub_org', 'England', 'https://englandfencing.co.uk', 'British Fencing', 2002, 'Governing body for fencing in England. 9 regional subdivisions.'),
('Scottish Fencing', NULL, 'SF', 'national_sub_org', 'Scotland', 'https://www.scottish-fencing.com', 'British Fencing', NULL, 'National governing body for fencing in Scotland.'),
('Ontario Fencing Association', NULL, 'OFA', 'regional_association', 'Canada', 'https://fencingontario.ca', 'CFF', NULL, 'Provincial governing body for fencing in Ontario.'),
('Korean Regional Fencing Associations', '시도 펜싱협회', NULL, 'regional_association', 'South Korea', 'https://fencing.sports.or.kr', 'KFF', NULL, '17 metropolitan/provincial associations covering all Korean regions.'),
('Seoul Metropolitan Fencing Association', '서울특별시 펜싱협회', 'SFA', 'regional_association', 'South Korea', NULL, 'KFF', NULL, 'Seoul metropolitan area fencing association.'),

-- Collegiate fencing (US)
('National Intercollegiate Women''s Fencing Association', NULL, 'NIWFA', 'collegiate_org', 'United States', 'http://www.niwfa.com', NULL, 1929, 'Women''s collegiate fencing.'),
('Intercollegiate Fencing Association', NULL, 'IFA', 'collegiate_org', 'United States', NULL, 'ECAC', 1894, 'Oldest US collegiate fencing conference.'),
('United States Association of Collegiate Fencing Clubs', NULL, 'USACFC', 'collegiate_org', 'United States', 'https://www.usacfc.org', 'USA Fencing', 2003, 'Collegiate club fencing. 50+ teams.'),

-- Notable historic clubs
('Fencers Club', NULL, NULL, 'historic_club', 'United States', NULL, NULL, 1883, 'Oldest fencing club in Western Hemisphere. NYC.'),
('Peter Westbrook Foundation', NULL, 'PWF', 'foundation', 'United States', 'https://www.peterwestbrook.org', NULL, 1991, 'Youth fencing. 12 PWF athletes earned 17 Olympic berths.'),
('Tim Morehouse Fencing Club', NULL, 'TMFC', 'historic_club', 'United States', 'https://www.timmorehousefencing.com', NULL, 2016, 'Founded by Olympic silver medalist. 5 fencers to 2024 Olympics.')
ON CONFLICT DO NOTHING;

-- Additional FIE Commissions & Councils
INSERT INTO fencing_world_organizations (name_en, name_native, abbreviation, org_type, country, website, parent_organization, founded_year, description)
VALUES
('FIE Legal Commission', 'Commission Juridique FIE', 'FIE-LEG', 'fie_commission', 'International', 'https://fie.org/fie/structure/council', 'FIE', NULL, 'Provides legal guidance and handles dispute resolution within the FIE framework.'),
('FIE Promotion, Communication and Marketing Commission', 'Commission Promotion, Communication et Marketing FIE', 'FIE-PCM', 'fie_commission', 'International', 'https://fie.org/fie/structure/council', 'FIE', NULL, 'Handles promotion, communications, and marketing strategy for international fencing.'),
('FIE Ethics Committee', 'Comité d''Éthique FIE', 'FIE-ETH', 'fie_commission', 'International', 'https://fie.org/fie/structure/council', 'FIE', NULL, 'Handles ethical matters and code of conduct for the FIE.'),
('FIE Disciplinary Panel', 'Commission de Discipline FIE', 'FIE-DIS', 'fie_commission', 'International', 'https://fie.org/fie/structure/council', 'FIE', NULL, 'Adjudicates disciplinary cases involving FIE members and national federations.'),
('FIE Women and Fencing Council', 'Conseil Femmes et Escrime FIE', 'FIE-WFC', 'fie_commission', 'International', 'https://fie.org/fie/structure/council', 'FIE', NULL, 'Promotes gender equity and women''s participation in international fencing.'),
('International Masters Games Association', NULL, 'IMGA', 'multi_sport_body', 'International', 'https://www.imga.ch', 'IOC-recognized', 1985, 'Organizes World Masters Games with fencing included; open to 25-35+ athletes of all abilities.'),
('Historical European Martial Arts Coalition', NULL, 'HEMAC', 'hema_org', 'International', 'https://www.hemac.org', NULL, 2001, 'Non-hierarchical coalition for research and practice of traditional European fighting arts from historical sources.'),
('USA Fencing Referees Commission', NULL, NULL, 'coaches_association', 'United States', 'https://www.usafencing.org/referees-commission', 'USA Fencing', NULL, 'Oversees referee certification, training, and assignment for USA Fencing competitions.'),
('USA Fencing Divisions', NULL, NULL, 'regional_association', 'United States', 'https://www.usafencing.org/divisions', 'USA Fencing', NULL, 'Primary geographic structure of USA Fencing; divisions defined by state/county lines.'),
('Welsh Fencing', NULL, 'WF', 'national_sub_org', 'Wales', NULL, 'British Fencing', NULL, 'Governing body for fencing in Wales.'),
('Northern Ireland Fencing', NULL, 'NIF', 'national_sub_org', 'Northern Ireland', NULL, 'British Fencing', NULL, 'Governing body for fencing in Northern Ireland.'),
('Guernsey Fencing', NULL, NULL, 'national_sub_org', 'Guernsey', NULL, 'British Fencing', NULL, 'Affiliated home nation association for fencing in Guernsey.'),
('Jersey Fencing', NULL, NULL, 'national_sub_org', 'Jersey', NULL, 'British Fencing', NULL, 'Affiliated home nation association for fencing in Jersey.'),
('Foundation for Scottish Fencing', NULL, 'FSF', 'foundation', 'Scotland', 'https://foundationforscottishfencing.org', NULL, 2008, 'Scottish charity supporting and encouraging youth fencing in Scotland.'),
('South East Region Fencing', NULL, NULL, 'regional_association', 'England', NULL, 'England Fencing', NULL, 'One of 9 England Fencing regional subdivisions.'),
('Southern Region Fencing', NULL, NULL, 'regional_association', 'England', NULL, 'England Fencing', NULL, 'One of 9 England Fencing regional subdivisions.'),
('South West Region Fencing', NULL, NULL, 'regional_association', 'England', NULL, 'England Fencing', NULL, 'One of 9 England Fencing regional subdivisions.'),
('London Region Fencing', NULL, NULL, 'regional_association', 'England', NULL, 'England Fencing', NULL, 'One of 9 England Fencing regional subdivisions.'),
('Eastern Region Fencing', NULL, NULL, 'regional_association', 'England', NULL, 'England Fencing', NULL, 'One of 9 England Fencing regional subdivisions.'),
('East Midlands Fencing', NULL, NULL, 'regional_association', 'England', NULL, 'England Fencing', NULL, 'One of 9 England Fencing regional subdivisions.'),
('West Midlands Region Fencing', NULL, NULL, 'regional_association', 'England', NULL, 'England Fencing', NULL, 'One of 9 England Fencing regional subdivisions.'),
('Yorkshire Fencing', NULL, NULL, 'regional_association', 'England', NULL, 'England Fencing', NULL, 'One of 9 England Fencing regional subdivisions.'),
('North East Region Fencing', NULL, NULL, 'regional_association', 'England', NULL, 'England Fencing', NULL, 'One of 9 England Fencing regional subdivisions.'),
('North West Region Fencing', NULL, NULL, 'regional_association', 'England', NULL, 'England Fencing', NULL, 'One of 9 England Fencing regional subdivisions.'),
('French Fencing Federation Regional Leagues', 'Ligues Régionales d''Escrime', NULL, 'regional_association', 'France', 'https://www.ffescrime.fr', 'FFE', NULL, '18 regional committees managing qualifying events, training, and regional development.'),
('Ligue d''Escrime Région Sud', 'Ligue d''Escrime Région Sud', NULL, 'regional_association', 'France', 'https://www.escrime-regionsud.fr', 'FFE', NULL, 'Regional fencing league for the South of France.'),
('Ligue Ile de France d''Escrime', 'Ligue Ile de France d''Escrime', 'LIFE', 'regional_association', 'France', 'https://escrime-iledefrance.fr', 'FFE', NULL, 'Regional fencing league for the Ile-de-France (Paris) region.'),
('Fédération d''escrime du Québec', 'Fédération d''escrime du Québec', NULL, 'regional_association', 'Canada', NULL, 'CFF', NULL, 'Provincial fencing federation for Quebec.'),
('ACT Fencing Association', NULL, 'ACTFA', 'regional_association', 'Australia', 'https://www.actfa.org.au', 'AFF', NULL, 'State sporting association for fencing in the Australian Capital Territory.'),
('FencingWA', NULL, NULL, 'regional_association', 'Australia', 'https://www.fencingwa.com', 'AFF', NULL, 'State sporting association for fencing in Western Australia.'),
('Circolo della Spada Mangiarotti', 'Circolo della Spada Mangiarotti', NULL, 'historic_club', 'Italy', NULL, NULL, NULL, 'Historic Milan fencing club connected to the legendary Mangiarotti fencing family.'),
('PUC Escrime', 'PUC Escrime', NULL, 'historic_club', 'France', 'http://puc-escrime.fr', NULL, NULL, 'Historic Paris University Club fencing section.')
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_fwo_type ON fencing_world_organizations(org_type);
CREATE INDEX IF NOT EXISTS idx_fwo_country ON fencing_world_organizations(country);
CREATE INDEX IF NOT EXISTS idx_fwo_abbrev ON fencing_world_organizations(abbreviation);
